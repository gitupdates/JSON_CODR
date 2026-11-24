from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import os
import re
import stat
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from uuid import uuid4

from web_app.designer.assets import AssetError, AssetService
from web_app.designer.capture_adapters import CapturePolicyError, sanitize_capture_envelope
from web_app.designer.contracts import ReferenceRecord
from web_app.designer.store import DesignerStore


MAX_EXTRACT_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_ENTRY_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 512
_FORBIDDEN_KEYS = re.compile(
    r"(?:cookie|header|storage|input.?value|form.?value|auth|credential|token|"
    r"source.?map|script|(?:xhr|fetch|api).?(?:body|payload)|table.?cell|"
    r"hostname|(?:^|_)(?:host|url|href|src|origin|query)(?:$|_))",
    re.IGNORECASE,
)
_HOST_OR_URL_TEXT = re.compile(
    r"(?:https?://|www\.)|(?:^|[\s(])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?=[:/\s)]|$)",
    re.IGNORECASE,
)
_KNOWN_FRAMEWORK_HINTS = {
    "react", "next.js", "angular", "vue", "svelte", "tailwind", "bootstrap", "material ui",
}
_ROUTE = re.compile(r"^(?:/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*|[A-Za-z0-9._~!$&'()*+,;=:@%-]+)$")
_SAFE_HTML_TAGS = {
    "main", "section", "article", "header", "footer", "nav", "aside", "div", "span",
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tr", "th", "td", "strong", "em", "b", "i", "small",
    "blockquote", "pre", "code", "br", "hr", "img", "a", "label",
}
_VOID_HTML_TAGS = {"br", "hr", "img"}
_DROP_HTML_TAGS = {"script", "style", "form", "iframe", "object", "embed", "svg", "template", "input", "button"}
_SAFE_HTML_ATTRIBUTES = {"class", "id", "title", "alt", "role", "aria-label", "colspan", "rowspan"}
_SAFE_CSS_PROPERTIES = {
    "align-items", "background-color", "border", "border-color", "border-radius", "border-style",
    "border-width", "box-shadow", "color", "display", "flex", "flex-direction", "font-family",
    "font-size", "font-weight", "gap", "grid-template-columns", "height", "justify-content",
    "line-height", "margin", "max-width", "min-height", "opacity", "padding", "text-align",
    "text-decoration", "width",
}
_SAFE_CSS_VALUE = re.compile(r"^[A-Za-z0-9\s#.,%()+/'\"_-]{1,256}$")


class ReferenceImportError(ValueError):
    """Raised when a UI reference is malformed or unsafe."""


class _SanitizingHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.suppressed: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.suppressed:
            if tag in _DROP_HTML_TAGS:
                self.suppressed.append(tag)
            return
        if tag in _DROP_HTML_TAGS:
            if tag not in _VOID_HTML_TAGS:
                self.suppressed.append(tag)
            return
        if tag not in _SAFE_HTML_TAGS:
            return
        safe_attrs: list[tuple[str, str]] = []
        for key, value in attrs:
            key = key.lower()
            if key not in _SAFE_HTML_ATTRIBUTES or value is None:
                continue
            if key == "class" and not re.fullmatch(r"[A-Za-z0-9 _-]{0,256}", value):
                continue
            if key == "id" and not re.fullmatch(r"[A-Za-z0-9_-]{0,128}", value):
                continue
            safe_attrs.append((key, value[:512]))
        rendered_attrs = "".join(f' {key}="{html.escape(value, quote=True)}"' for key, value in safe_attrs)
        self.output.append(f"<{tag}{rendered_attrs}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_HTML_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.suppressed:
            if tag == self.suppressed[-1]:
                self.suppressed.pop()
            return
        if tag in _SAFE_HTML_TAGS and tag not in _VOID_HTML_TAGS:
            self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            self.output.append(html.escape(data[:4096]))


class ReferenceImporter:
    """Imports bounded, inert references under each Designer project's managed root."""

    def __init__(
        self,
        store: DesignerStore,
        assets: AssetService,
        *,
        max_archive_bytes: int = MAX_ARCHIVE_BYTES,
        max_entry_bytes: int = MAX_ARCHIVE_ENTRY_BYTES,
    ) -> None:
        if max_archive_bytes <= 0 or max_archive_bytes > MAX_ARCHIVE_BYTES:
            raise ValueError(f"max_archive_bytes must be between 1 and {MAX_ARCHIVE_BYTES}")
        if max_entry_bytes <= 0 or max_entry_bytes > MAX_ARCHIVE_ENTRY_BYTES:
            raise ValueError(f"max_entry_bytes must be between 1 and {MAX_ARCHIVE_ENTRY_BYTES}")
        self.store = store
        self.assets = assets
        self.max_archive_bytes = max_archive_bytes
        self.max_entry_bytes = max_entry_bytes

    def import_image(
        self,
        project_id: str,
        stream,
        filename: str,
        media_type: str,
        *,
        source_label: str,
        license_note: str,
        authorization_attested: bool,
    ) -> ReferenceRecord:
        self._require_provenance(source_label, license_note, authorization_attested)
        if media_type not in {"image/png", "image/jpeg", "image/svg+xml"}:
            raise ReferenceImportError("reference screenshots must be PNG, JPEG, or SVG images")
        try:
            asset = self.assets.import_file(
                project_id, stream, filename, media_type,
                source_label=source_label, license_note=license_note,
            )
        except AssetError as exc:
            raise ReferenceImportError(str(exc)) from exc
        return self._save_reference(project_id, "screenshot", {
            "asset": asset.__dict__,
        }, source_label, license_note)

    def import_extract(
        self,
        project_id: str,
        extract: object,
        *,
        source_label: str,
        license_note: str,
        authorization_attested: bool,
    ) -> ReferenceRecord:
        self._require_provenance(source_label, license_note, authorization_attested)
        safe_extract = self._sanitize_extract(extract)
        return self._save_reference(project_id, "extract", {
            "extract": safe_extract,
        }, source_label, license_note)

    def import_capture(
        self,
        project_id: str,
        envelope: object,
        *,
        source_label: str,
        license_note: str,
        authorization_attested: bool,
        adapter: str = "Playwright",
        adapter_version: str = "1",
    ) -> ReferenceRecord:
        self._require_provenance(source_label, license_note, authorization_attested)
        if adapter != "Playwright" or not isinstance(adapter_version, str) or len(adapter_version) > 32:
            raise ReferenceImportError("unsupported capture adapter provenance")
        try:
            safe_capture = sanitize_capture_envelope(envelope)
        except CapturePolicyError as exc:
            raise ReferenceImportError(str(exc)) from exc
        screenshot_assets = self._materialize_capture_screenshots(
            project_id, safe_capture, source_label, license_note,
        )
        return self._save_reference(project_id, "playwright", {
            "capture": safe_capture,
            "screenshot_assets": screenshot_assets,
            "capture_provenance": {
                "adapter": adapter,
                "adapter_version": adapter_version,
                "authorization_attested": True,
                "source_type": "authorized-browser-capture",
                "sanitizer_version": 1,
            },
        }, source_label, license_note)

    def import_archive(
        self,
        project_id: str,
        stream,
        *,
        source_label: str,
        license_note: str,
        authorization_attested: bool,
        acknowledge_review: bool = False,
    ) -> ReferenceRecord:
        self._require_provenance(source_label, license_note, authorization_attested)
        archive_bytes = self._read_limited(stream, self.max_archive_bytes, "archive")
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                files = self._read_archive_entries(archive)
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            raise ReferenceImportError("invalid or unreadable reference archive") from exc

        manifest_bytes = files.pop("MANIFEST.json", None)
        checksum_bytes = files.pop("MANIFEST.sha256", None)
        if manifest_bytes is None or checksum_bytes is None:
            raise ReferenceImportError("archive manifest and checksum are required")
        self._verify_manifest(manifest_bytes, checksum_bytes, files)
        review = files.get("REVIEW.txt")
        if review is not None and not acknowledge_review:
            raise ReferenceImportError("archive has REVIEW.txt findings; explicit acknowledgement is required")
        for required in ("REPORT.md", "DIFF.md", "ui-extract.json"):
            if required not in files:
                raise ReferenceImportError(f"archive is missing {required}")
        try:
            extract = self._sanitize_extract(json.loads(files["ui-extract.json"].decode("utf-8")))
            report = files["REPORT.md"].decode("utf-8")
            diff = files["DIFF.md"].decode("utf-8")
            review_text = review.decode("utf-8") if review is not None else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReferenceImportError("archive contains invalid UTF-8 or JSON") from exc
        if len(report) > 256_000 or len(diff) > 256_000 or (review_text is not None and len(review_text) > 256_000):
            raise ReferenceImportError("archive report exceeds size limit")

        html_source = files.get("index.html", b"").decode("utf-8", errors="replace")
        css_source = files.get("styles.css", b"").decode("utf-8", errors="replace")
        preview = self._sanitize_preview(html_source, css_source)
        imported_assets = self._import_archive_assets(project_id, files, source_label, license_note)
        payload = {
            "extract": extract,
            "report": report,
            "diff": diff,
            "review": review_text,
            "preview": preview,
            "assets": imported_assets,
        }
        capture_bytes = files.get("capture-envelope.json")
        if capture_bytes is not None:
            try:
                payload["capture"] = sanitize_capture_envelope(json.loads(capture_bytes.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError, CapturePolicyError) as exc:
                raise ReferenceImportError("archive capture envelope is invalid or unsafe") from exc
            payload["screenshot_assets"] = self._materialize_capture_screenshots(
                project_id, payload["capture"], source_label, license_note,
            )
        return self._save_reference(project_id, "archive", payload, source_label, license_note)

    def get_reference(self, project_id: str, reference_id: str) -> dict[str, object]:
        path = self._reference_path(project_id, reference_id)
        if not path.is_file():
            raise KeyError(reference_id)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReferenceImportError("stored reference is invalid") from exc
        if record.get("record", {}).get("reference_id") != reference_id:
            raise ReferenceImportError("stored reference identifier does not match its path")
        return record

    def reference_preview(self, project_id: str, reference_id: str) -> dict[str, str]:
        reference = self.get_reference(project_id, reference_id)
        preview = reference.get("preview")
        if not isinstance(preview, dict):
            preview = reference.get("archive", {}).get("preview") if isinstance(reference.get("archive"), dict) else None
        if not isinstance(preview, dict):
            preview = {"html": "<main></main>", "css": ""}
        html_document = (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;">'
            f"<style>{preview.get('css', '')}</style></head><body>{preview.get('html', '')}</body></html>"
        )
        return {
            "html": html_document,
            "sandbox": "",
            "content_security_policy": "default-src 'none'; style-src 'unsafe-inline'",
        }

    def _save_reference(
        self,
        project_id: str,
        kind: str,
        payload: dict[str, object],
        source_label: str,
        license_note: str,
    ) -> ReferenceRecord:
        self.store._project_dir(project_id, must_exist=True)
        reference_id = f"reference-{uuid4().hex}"
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        record = ReferenceRecord(
            reference_id=reference_id,
            kind=kind,
            content_digest=f"sha256:{hashlib.sha256(serialized).hexdigest()}",
            source_label=source_label.strip(),
            license_note=license_note.strip(),
        )
        reference_root = self.store.projects_root / project_id / "references"
        reference_root.mkdir(exist_ok=True)
        if reference_root.resolve().parent != (self.store.projects_root / project_id).resolve():
            raise ReferenceImportError("reference directory escapes the managed project root")
        self._atomic_json(reference_root / f"{reference_id}.json", {"record": record.model_dump(mode="json"), **payload})
        return record

    def _reference_path(self, project_id: str, reference_id: str) -> Path:
        if not re.fullmatch(r"reference-[0-9a-f]{32}", reference_id):
            raise ValueError("invalid reference identifier")
        project_root = self.store._project_dir(project_id, must_exist=True)
        reference_root = project_root / "references"
        if reference_root.exists() and reference_root.resolve().parent != project_root.resolve():
            raise ValueError("reference directory escapes managed project root")
        path = reference_root / f"{reference_id}.json"
        if path.resolve().parent != reference_root.resolve():
            raise ValueError("reference path escapes managed project root")
        return path

    @staticmethod
    def _require_provenance(source_label: str, license_note: str, authorization_attested: bool) -> None:
        if not isinstance(authorization_attested, bool) or not authorization_attested:
            raise CapturePolicyError("explicit authorization attestation is required")
        if not isinstance(source_label, str) or not source_label.strip() or len(source_label) > 256:
            raise CapturePolicyError("a bounded source label is required")
        if not isinstance(license_note, str) or not license_note.strip() or len(license_note) > 512:
            raise CapturePolicyError("a license or reuse note is required")
        if source_label.startswith(("/", "\\\\")) or re.match(r"^[A-Za-z]:[\\/]", source_label):
            raise CapturePolicyError("source labels cannot contain local paths")

    @staticmethod
    def _sanitize_extract(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ReferenceImportError("UI extract must be an object")
        allowed_root = {"schema_version", "viewport", "pages", "class_frequencies", "framework_hints", "resources"}
        if set(value) - allowed_root or _contains_forbidden_key(value):
            raise ReferenceImportError("UI extract contains unsupported or private fields")
        if value.get("schema_version") != 1:
            raise ReferenceImportError("unsupported UI extract schema version")
        viewport = value.get("viewport")
        pages = value.get("pages")
        if not isinstance(viewport, dict) or set(viewport) != {"width", "height"}:
            raise ReferenceImportError("invalid extract viewport")
        safe_viewport = {
            "width": _bounded_dimension(viewport["width"]),
            "height": _bounded_dimension(viewport["height"]),
        }
        if not isinstance(pages, list) or not 1 <= len(pages) <= 100:
            raise ReferenceImportError("extract must contain between 1 and 100 pages")
        safe_pages = [_sanitize_page(page) for page in pages]
        class_frequencies = value.get("class_frequencies", {})
        if not isinstance(class_frequencies, dict) or len(class_frequencies) > 2048:
            raise ReferenceImportError("invalid class frequency map")
        safe_frequencies: dict[str, int] = {}
        for key, count in class_frequencies.items():
            if not isinstance(key, str) or len(key) > 128 or not isinstance(count, int) or not 0 <= count <= 1_000_000:
                raise ReferenceImportError("invalid class frequency entry")
            safe_frequencies[key] = count
        frameworks = value.get("framework_hints", [])
        if not isinstance(frameworks, list) or len(frameworks) > 32:
            raise ReferenceImportError("invalid framework hints")
        safe_frameworks = [_bounded_text(item, 64) for item in frameworks]
        resources = value.get("resources", [])
        if not isinstance(resources, list) or len(resources) > 1000:
            raise ReferenceImportError("invalid resource inventory")
        safe_resources = [_sanitize_resource(item) for item in resources]
        result: dict[str, object] = {
            "schema_version": 1,
            "viewport": safe_viewport,
            "pages": safe_pages,
            "class_frequencies": safe_frequencies,
            "framework_hints": safe_frameworks,
            "resources": safe_resources,
        }
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_EXTRACT_BYTES:
            raise ReferenceImportError("UI extract exceeds size limit")
        return result

    def _read_archive_entries(self, archive: zipfile.ZipFile) -> dict[str, bytes]:
        infos = archive.infolist()
        if not 1 <= len(infos) <= MAX_ARCHIVE_ENTRIES:
            raise ReferenceImportError("archive entry count exceeds size limit")
        files: dict[str, bytes] = {}
        total_size = 0
        for info in infos:
            name = info.filename
            path = PurePosixPath(name)
            mode = info.external_attr >> 16
            if (
                not name or "\\" in name or path.is_absolute() or ":" in name
                or any(part in {"", ".", ".."} for part in path.parts)
                or stat.S_ISLNK(mode) or info.flag_bits & 0x1
            ):
                raise ReferenceImportError("archive contains an unsafe path, symlink, or encrypted entry")
            if info.is_dir():
                continue
            if name in files:
                raise ReferenceImportError("archive contains duplicate entries")
            if info.file_size > self.max_entry_bytes or info.file_size < 0:
                raise ReferenceImportError("archive entry exceeds size limit")
            total_size += info.file_size
            if total_size > self.max_archive_bytes:
                raise ReferenceImportError("archive exceeds total uncompressed size limit")
            if not _allowed_archive_path(name):
                raise ReferenceImportError(f"archive contains unsupported file: {name}")
            with archive.open(info) as entry:
                content = entry.read(self.max_entry_bytes + 1)
            if len(content) != info.file_size or len(content) > self.max_entry_bytes:
                raise ReferenceImportError("archive entry size does not match its directory record")
            files[name] = content
        return files

    @staticmethod
    def _verify_manifest(manifest_bytes: bytes, checksum_bytes: bytes, files: dict[str, bytes]) -> None:
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            checksum_lines = checksum_bytes.decode("utf-8").splitlines()
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReferenceImportError("archive manifest is invalid") from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("format") != "json-codr-ui-reference"
            or manifest.get("schema_version") != 1
            or not isinstance(manifest.get("files"), dict)
        ):
            raise ReferenceImportError("unsupported archive manifest")
        expected = manifest["files"]
        if set(expected) != set(files):
            raise ReferenceImportError("archive manifest entries do not match archive files")
        checksum_map: dict[str, str] = {}
        for line in checksum_lines:
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match or match.group(2) in checksum_map:
                raise ReferenceImportError("archive checksum file is malformed")
            checksum_map[match.group(2)] = match.group(1)
        if set(checksum_map) != set(files):
            raise ReferenceImportError("archive checksum entries do not match archive files")
        for name, content in files.items():
            digest = hashlib.sha256(content).hexdigest()
            if expected.get(name) != f"sha256:{digest}" or checksum_map.get(name) != digest:
                raise ReferenceImportError(f"archive checksum mismatch for {name}")

    def _import_archive_assets(
        self,
        project_id: str,
        files: dict[str, bytes],
        source_label: str,
        license_note: str,
    ) -> list[dict[str, object]]:
        imported: list[dict[str, object]] = []
        for name, content in files.items():
            if not name.startswith("assets/"):
                continue
            media_type = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".svg": "image/svg+xml", ".woff": "font/woff", ".woff2": "font/woff2",
                ".ttf": "font/ttf", ".otf": "font/otf",
            }[Path(name).suffix.lower()]
            try:
                asset = self.assets.import_file(
                    project_id, io.BytesIO(content), Path(name).name, media_type,
                    source_label=source_label, license_note=license_note,
                )
            except AssetError as exc:
                raise ReferenceImportError(f"invalid archive asset {Path(name).name}: {exc}") from exc
            imported.append(asset.__dict__)
        return imported

    def _materialize_capture_screenshots(
        self,
        project_id: str,
        capture: dict[str, object],
        source_label: str,
        license_note: str,
    ) -> list[dict[str, object]]:
        imported: list[dict[str, object]] = []
        pages = capture.get("pages", [])
        if not isinstance(pages, list):
            raise ReferenceImportError("capture pages are malformed")
        for page in pages:
            if not isinstance(page, dict):
                raise ReferenceImportError("capture page is malformed")
            screenshots = page.get("screenshots", [])
            if not isinstance(screenshots, list):
                raise ReferenceImportError("capture screenshot inventory is malformed")
            for screenshot in screenshots:
                if screenshot.get("omitted") == "size_limit":
                    continue
                encoded = screenshot.pop("content_base64", None)
                if encoded is None:
                    continue
                media_type = screenshot["media_type"]
                try:
                    content = base64.b64decode(encoded, validate=True)
                    asset = self.assets.import_file(
                        project_id,
                        io.BytesIO(content),
                        Path(screenshot["path"]).name,
                        media_type,
                        source_label=source_label,
                        license_note=license_note,
                    )
                except (ValueError, AssetError) as exc:
                    raise ReferenceImportError("captured screenshot could not be stored safely") from exc
                screenshot["asset"] = asset.__dict__
                imported.append(asset.__dict__)
        return imported

    @staticmethod
    def _sanitize_preview(html_source: str, css_source: str) -> dict[str, str]:
        parser = _SanitizingHTMLParser()
        parser.feed(html_source[:1_000_000])
        parser.close()
        return {"html": "".join(parser.output)[:1_000_000], "css": _sanitize_css(css_source[:1_000_000])}

    @staticmethod
    def _read_limited(stream, limit: int, label: str) -> bytes:
        if not hasattr(stream, "read"):
            raise ReferenceImportError(f"{label} input must be a readable stream")
        content = stream.read(limit + 1)
        if not isinstance(content, bytes):
            raise ReferenceImportError(f"{label} stream must yield bytes")
        if len(content) > limit:
            raise ReferenceImportError(f"{label} exceeds size limit")
        return content

    @staticmethod
    def _atomic_json(target: Path, value: object) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(_FORBIDDEN_KEYS.search(str(key)) or _contains_forbidden_key(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_key(child) for child in value)
    return False


def _bounded_dimension(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10000:
        raise ReferenceImportError("viewport dimensions must be integers between 1 and 10000")
    return value


def _sanitize_page(value: object) -> dict[str, object]:
    allowed = {"name", "route", "headings", "labels", "controls", "elements", "grid_columns"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ReferenceImportError("extract page has unsupported fields")
    name = _bounded_text(value.get("name", ""), 256)
    route = value.get("route", "/")
    if not isinstance(route, str) or len(route) > 512 or "?" in route or "#" in route or not _ROUTE.fullmatch(route):
        raise ReferenceImportError("extract routes must be local paths without query strings")
    headings = _text_list(value.get("headings", []), 128, 256)
    labels = _text_list(value.get("labels", []), 512, 256)
    controls = value.get("controls", [])
    if not isinstance(controls, list) or len(controls) > 512:
        raise ReferenceImportError("invalid extract control list")
    safe_controls: list[dict[str, str]] = []
    for control in controls:
        if not isinstance(control, dict) or set(control) - {"type", "label"}:
            raise ReferenceImportError("extract controls may contain only type and label")
        safe_controls.append({
            "type": _bounded_text(control.get("type", "control"), 64),
            "label": _bounded_text(control.get("label", ""), 256),
        })
    elements = value.get("elements", [])
    if not isinstance(elements, list) or len(elements) > 4096:
        raise ReferenceImportError("invalid extract element list")
    safe_elements: list[dict[str, object]] = []
    for element in elements:
        if not isinstance(element, dict) or set(element) - {"tag", "role", "name", "classes", "bounds"}:
            raise ReferenceImportError("extract elements contain unsupported fields")
        classes = _text_list(element.get("classes", []), 64, 128)
        bounds = element.get("bounds", {})
        if not isinstance(bounds, dict) or set(bounds) - {"x", "y", "width", "height"}:
            raise ReferenceImportError("invalid element bounds")
        safe_bounds: dict[str, int | float] = {}
        for key in ("x", "y", "width", "height"):
            number = bounds.get(key, 0)
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not 0 <= number <= 10000:
                raise ReferenceImportError("element bounds must be finite values between 0 and 10000")
            safe_bounds[key] = number
        safe_elements.append({
            "tag": _bounded_text(element.get("tag", "div"), 64),
            "role": _bounded_text(element.get("role", ""), 64),
            "name": _bounded_text(element.get("name", ""), 256),
            "classes": classes,
            "bounds": safe_bounds,
        })
    grid_columns = value.get("grid_columns", [])
    if not isinstance(grid_columns, list) or len(grid_columns) > 24 or any(
        isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 24 for item in grid_columns
    ):
        raise ReferenceImportError("invalid grid column hints")
    return {
        "name": name,
        "route": route,
        "headings": headings,
        "labels": labels,
        "controls": safe_controls,
        "elements": safe_elements,
        "grid_columns": list(grid_columns),
    }


def _sanitize_resource(value: object) -> dict[str, object]:
    allowed = {"type", "path", "media_type", "size"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ReferenceImportError("resource metadata contains unsupported fields")
    path = value.get("path", "")
    if not isinstance(path, str) or len(path) > 1024 or "?" in path or "#" in path or "://" in path or path.startswith("//"):
        raise ReferenceImportError("resource paths must be local and query-free")
    size = value.get("size", 0)
    if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_ARCHIVE_ENTRY_BYTES:
        raise ReferenceImportError("invalid resource size")
    return {
        "type": _bounded_text(value.get("type", "unknown"), 32),
        "path": path,
        "media_type": _bounded_text(value.get("media_type", ""), 128),
        "size": size,
    }


def _text_list(value: object, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, list) or len(value) > max_items:
        raise ReferenceImportError("invalid text list in UI extract")
    return [_bounded_text(item, max_length) for item in value]


def _bounded_text(value: object, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit or any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        raise ReferenceImportError("extract text field is invalid or too long")
    if _HOST_OR_URL_TEXT.search(value) and value.casefold() not in _KNOWN_FRAMEWORK_HINTS:
        raise ReferenceImportError("extract text cannot contain hostnames or URLs")
    return value


def _allowed_archive_path(name: str) -> bool:
    if name in {
        "MANIFEST.json", "MANIFEST.sha256", "REPORT.md", "DIFF.md", "REVIEW.txt",
        "ui-extract.json", "capture-envelope.json", "index.html", "styles.css",
    }:
        return True
    if name.startswith("assets/") and len(PurePosixPath(name).parts) == 2:
        return PurePosixPath(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".svg", ".woff", ".woff2", ".ttf", ".otf"}
    return False


def _sanitize_css(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    output: list[str] = []
    for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", source):
        selector = selector.strip()
        if not selector or len(selector) > 512 or not re.fullmatch(r"[A-Za-z0-9_#., >+~:\-\[\]=\"'()*\s]+", selector):
            continue
        safe_declarations: list[str] = []
        for declaration in declarations.split(";"):
            if ":" not in declaration:
                continue
            name, value = (part.strip() for part in declaration.split(":", 1))
            if (
                name.lower() not in _SAFE_CSS_PROPERTIES
                or not _SAFE_CSS_VALUE.fullmatch(value)
                or re.search(r"url|expression|import|javascript|data:|https?:|@|\\", value, re.IGNORECASE)
            ):
                continue
            safe_declarations.append(f"{name.lower()}: {value}")
        if safe_declarations:
            output.append(f"{selector} {{ {'; '.join(safe_declarations)}; }}")
    return "\n".join(output)
