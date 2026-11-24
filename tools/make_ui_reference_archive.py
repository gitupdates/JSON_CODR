from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web_app.designer.capture_adapters import sanitize_capture_envelope
from web_app.designer.references import (
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_ENTRY_BYTES,
    ReferenceImporter,
)


_ALLOWED_ROOT_FILES = {
    "REPORT.md", "DIFF.md", "REVIEW.txt", "ui-extract.json", "capture-envelope.json",
    "index.html", "styles.css",
}
_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".woff", ".woff2", ".ttf", ".otf"}


def _extract_from_capture(capture: dict[str, object]) -> dict[str, object]:
    pages = capture.get("pages", [])
    safe_pages = []
    class_frequencies: dict[str, int] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        dom_elements = []

        def flatten(node: object) -> None:
            if not isinstance(node, dict) or len(dom_elements) >= 4096:
                return
            classes = node.get("classes", [])
            bounds = node.get("bounds", {})
            dom_elements.append({
                "tag": node.get("tag", "div"),
                "role": node.get("role", ""),
                "name": node.get("name", ""),
                "classes": classes,
                "bounds": bounds,
            })
            if isinstance(classes, list):
                for class_name in classes:
                    if isinstance(class_name, str):
                        class_frequencies[class_name] = min(1_000_000, class_frequencies.get(class_name, 0) + 1)
            for child in node.get("children", []) if isinstance(node.get("children", []), list) else []:
                flatten(child)

        flatten(page.get("dom"))
        viewport = page.get("viewport", {"width": 1280, "height": 800})
        safe_pages.append({
            "name": str(page.get("page_title", ""))[:256],
            "route": page.get("route", "/"),
            "headings": page.get("headings", [])[:128] if isinstance(page.get("headings", []), list) else [],
            "labels": page.get("labels", [])[:512] if isinstance(page.get("labels", []), list) else [],
            "controls": page.get("controls", [])[:512] if isinstance(page.get("controls", []), list) else [],
            "elements": dom_elements,
            "grid_columns": page.get("grid_columns", [])[:24] if isinstance(page.get("grid_columns", []), list) else [],
            "viewport": viewport,
        })
    first_viewport = safe_pages[0].pop("viewport", {"width": 1280, "height": 800}) if safe_pages else {"width": 1280, "height": 800}
    for page in safe_pages[1:]:
        page.pop("viewport", None)
    safe_resources = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        for resource in page.get("resources", []) if isinstance(page.get("resources", []), list) else []:
            if not isinstance(resource, dict):
                continue
            safe_resources.append({
                key: resource[key] for key in ("type", "path", "media_type", "size") if key in resource
            })
            if len(safe_resources) >= 1000:
                break
    return {
        "schema_version": 1,
        "viewport": first_viewport,
        "pages": safe_pages,
        "class_frequencies": class_frequencies,
        "framework_hints": capture.get("framework_hints", [])[:32],
        "resources": safe_resources[:1000],
    }


def collect_files(source: Path) -> dict[str, bytes]:
    if not source.is_dir():
        raise ValueError("input must be a directory")
    files: dict[str, bytes] = {}
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"symbolic links are not allowed: {path.name}")
        if not path.is_file():
            continue
        name = path.relative_to(source).as_posix()
        parts = PurePosixPath(name).parts
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError(f"unsafe input path: {name}")
        if name not in _ALLOWED_ROOT_FILES and not (
            name.startswith("assets/") and len(parts) == 2 and PurePosixPath(name).suffix.lower() in _ASSET_EXTENSIONS
        ):
            raise ValueError(f"unsupported archive input: {name}")
        if path.stat().st_size > MAX_ARCHIVE_ENTRY_BYTES:
            raise ValueError(f"input file exceeds size limit: {name}")
        files[name] = path.read_bytes()
    capture = files.get("capture-envelope.json")
    if capture is not None:
        safe_capture = sanitize_capture_envelope(json.loads(capture.decode("utf-8")))
        files["capture-envelope.json"] = json.dumps(
            safe_capture, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        files.setdefault("ui-extract.json", json.dumps(
            _extract_from_capture(safe_capture), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8"))
    if not {"REPORT.md", "DIFF.md", "ui-extract.json"}.issubset(files):
        raise ValueError("input must contain REPORT.md, DIFF.md, and ui-extract.json (or capture-envelope.json)")
    files["ui-extract.json"] = json.dumps(
        ReferenceImporter._sanitize_extract(json.loads(files["ui-extract.json"].decode("utf-8"))),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    total = sum(len(content) for content in files.values())
    if total > MAX_ARCHIVE_BYTES - 1024:
        raise ValueError("archive inputs exceed total size limit")
    return files


def build_archive(files: dict[str, bytes], output: Path) -> None:
    manifest_files = {
        name: f"sha256:{hashlib.sha256(content).hexdigest()}"
        for name, content in sorted(files.items())
    }
    manifest = json.dumps({
        "format": "json-codr-ui-reference",
        "schema_version": 1,
        "files": manifest_files,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    checksums = "".join(
        f"{digest.removeprefix('sha256:')}  {name}\n"
        for name, digest in sorted(manifest_files.items())
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
        archive.writestr("MANIFEST.json", manifest)
        archive.writestr("MANIFEST.sha256", checksums)
    if output.stat().st_size > MAX_ARCHIVE_BYTES:
        output.unlink()
        raise ValueError("generated archive exceeds size limit")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a bounded, checksummed JSON_CODR UI reference archive.")
    parser.add_argument("input_directory", type=Path)
    parser.add_argument("output_archive", type=Path)
    args = parser.parse_args()
    try:
        build_archive(collect_files(args.input_directory), args.output_archive)
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
