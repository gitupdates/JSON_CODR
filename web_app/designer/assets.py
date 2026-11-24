from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

from PIL import Image, ImageOps, UnidentifiedImageError

from web_app.designer.store import DesignerStore


MAX_ASSET_BYTES = 10 * 1024 * 1024
_MAX_IMAGE_PIXELS = 20_000_000
_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/svg+xml": ".svg",
    "font/woff": ".woff",
    "font/woff2": ".woff2",
    "font/ttf": ".ttf",
    "font/otf": ".otf",
}
_ACTIVE_SVG_ELEMENTS = {
    "script", "foreignobject", "iframe", "object", "embed", "audio", "video",
    "animate", "animatemotion", "animatetransform", "set",
}
_SAFE_SVG_ELEMENTS = {
    "svg", "g", "defs", "symbol", "use", "path", "rect", "circle", "ellipse",
    "line", "polyline", "polygon", "text", "tspan", "title", "desc", "clipPath",
    "mask", "linearGradient", "radialGradient", "stop", "pattern", "marker",
}
_SAFE_SVG_ATTRIBUTES = {
    "id", "viewBox", "width", "height", "x", "y", "x1", "x2", "y1", "y2",
    "cx", "cy", "r", "rx", "ry", "d", "points", "fill", "fill-rule",
    "fill-opacity", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
    "stroke-dasharray", "stroke-dashoffset", "stroke-opacity", "opacity",
    "transform", "preserveAspectRatio", "offset", "stop-color", "stop-opacity",
    "gradientUnits", "gradientTransform", "patternUnits", "patternTransform",
    "clip-path", "mask", "role", "aria-label", "focusable", "font-size",
    "font-family", "font-weight", "text-anchor", "dominant-baseline",
}
_URL_FUNCTION = re.compile(r"url\s*\(", re.IGNORECASE)


class AssetError(ValueError):
    """Raised when an asset is invalid or unsafe to import."""


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    relative_path: str
    media_type: str
    content_digest: str
    size: int
    source_label: str
    license_note: str


class AssetService:
    """Validates and stores inert asset copies under a managed project root."""

    def __init__(self, store: DesignerStore, *, max_asset_bytes: int = MAX_ASSET_BYTES) -> None:
        if max_asset_bytes <= 0 or max_asset_bytes > MAX_ASSET_BYTES:
            raise ValueError(f"max_asset_bytes must be between 1 and {MAX_ASSET_BYTES}")
        self.store = store
        self.max_asset_bytes = max_asset_bytes

    def import_file(
        self,
        project_id: str,
        stream,
        filename: str,
        media_type: str,
        *,
        source_label: str = "User supplied",
        license_note: str = "",
    ) -> AssetRecord:
        if media_type not in _MIME_EXTENSIONS:
            raise AssetError("unsupported asset MIME type")
        if not isinstance(filename, str) or not filename.strip():
            raise AssetError("asset filename is required")
        if not isinstance(source_label, str) or len(source_label) > 256:
            raise AssetError("invalid asset source label")
        if not isinstance(license_note, str) or len(license_note) > 512:
            raise AssetError("invalid asset license note")
        content = self._read_limited(stream)

        if media_type in ("image/png", "image/jpeg"):
            content = self._sanitize_raster(content, media_type)
        elif media_type == "image/svg+xml":
            content = self._sanitize_svg(content)
        else:
            self._validate_font(content, media_type)
        if len(content) > self.max_asset_bytes:
            raise AssetError("asset exceeds size limit after sanitization")

        project_root = self.store._project_dir(project_id, must_exist=True)
        assets_dir = project_root / "assets"
        assets_dir.mkdir(exist_ok=True)
        if assets_dir.resolve().parent != project_root.resolve():
            raise AssetError("asset directory escapes the managed project root")
        asset_id = f"asset-{uuid4().hex}"
        relative_path = f"assets/{asset_id}{_MIME_EXTENSIONS[media_type]}"
        target = assets_dir / f"{asset_id}{_MIME_EXTENSIONS[media_type]}"
        self._atomic_write(target, content)
        return AssetRecord(
            asset_id=asset_id,
            relative_path=relative_path,
            media_type=media_type,
            content_digest=f"sha256:{hashlib.sha256(content).hexdigest()}",
            size=len(content),
            source_label=source_label.strip() or "User supplied",
            license_note=license_note.strip(),
        )

    def read_asset(self, project_id: str, relative_path: str) -> bytes:
        if not isinstance(relative_path, str) or not re.fullmatch(
            r"assets/asset-[0-9a-f]{32}\.(?:png|jpg|svg|woff|woff2|ttf|otf)", relative_path,
        ):
            raise AssetError("invalid managed asset identifier")
        project_root = self.store._project_dir(project_id, must_exist=True)
        assets_dir = project_root / "assets"
        if assets_dir.resolve().parent != project_root.resolve():
            raise AssetError("asset directory escapes the managed project root")
        target = project_root / relative_path
        if target.resolve().parent != assets_dir.resolve() or not target.is_file():
            raise AssetError("managed asset does not exist")
        content = target.read_bytes()
        if len(content) > self.max_asset_bytes:
            raise AssetError("stored asset exceeds size limit")
        return content

    def _read_limited(self, stream) -> bytes:
        if not hasattr(stream, "read"):
            raise AssetError("asset input must be a readable stream")
        content = stream.read(self.max_asset_bytes + 1)
        if not isinstance(content, bytes):
            raise AssetError("asset stream must yield bytes")
        if len(content) > self.max_asset_bytes:
            raise AssetError("asset exceeds size limit")
        return content

    @staticmethod
    def _sanitize_raster(content: bytes, media_type: str) -> bytes:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as source:
                    expected_format = "PNG" if media_type == "image/png" else "JPEG"
                    if source.format != expected_format:
                        raise AssetError("asset content does not match declared MIME type")
                    if source.width * source.height > _MAX_IMAGE_PIXELS:
                        raise AssetError("image exceeds pixel size limit")
                    source.load()
                    image = ImageOps.exif_transpose(source)
                    if expected_format == "JPEG":
                        image = image.convert("RGB")
                    elif image.mode not in ("RGB", "RGBA"):
                        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                    output = io.BytesIO()
                    image.save(output, format=expected_format, optimize=False)
                    return output.getvalue()
        except AssetError:
            raise
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise AssetError("malformed image or image exceeds safe limits") from exc

    @classmethod
    def _sanitize_svg(cls, content: bytes) -> bytes:
        try:
            text = content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise AssetError("malformed SVG document encoding") from exc
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.IGNORECASE):
            raise AssetError("SVG document types and entities are not allowed")
        try:
            root = ElementTree.fromstring(text)
        except (ElementTree.ParseError, UnicodeDecodeError) as exc:
            raise AssetError("malformed SVG document") from exc
        if cls._local_name(root.tag).lower() != "svg":
            raise AssetError("SVG root element is required")
        cls._sanitize_svg_element(root)
        return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)

    @classmethod
    def _sanitize_svg_element(cls, element) -> None:
        for child in list(element):
            local = cls._local_name(child.tag)
            if local.lower() in _ACTIVE_SVG_ELEMENTS or local not in _SAFE_SVG_ELEMENTS:
                element.remove(child)
            else:
                cls._sanitize_svg_element(child)
        for attribute in list(element.attrib):
            local = cls._local_name(attribute)
            value = element.attrib[attribute]
            if (
                local.lower().startswith("on")
                or local not in _SAFE_SVG_ATTRIBUTES
                or _URL_FUNCTION.search(value)
                or re.search(r"(?:javascript|vbscript|data|https?|file):", value, re.IGNORECASE)
            ):
                del element.attrib[attribute]

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    @staticmethod
    def _validate_font(content: bytes, media_type: str) -> None:
        signatures = {
            "font/woff": (b"wOFF",),
            "font/woff2": (b"wOF2",),
            "font/ttf": (b"\x00\x01\x00\x00", b"true"),
            "font/otf": (b"OTTO",),
        }
        if len(content) < 12 or not content.startswith(signatures[media_type]):
            raise AssetError("malformed font content")

    @staticmethod
    def _atomic_write(target: Path, content: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
