from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


MAX_CAPTURE_BYTES = 20 * 1024 * 1024
MAX_CAPTURE_RESOURCE_BYTES = 5 * 1024 * 1024
MAX_CAPTURE_SCREENSHOT_BYTES = 512 * 1024
MAX_CAPTURE_SCREENSHOT_TOTAL_BYTES = 5 * 1024 * 1024
MAX_CAPTURE_PAGES = 100
_FORBIDDEN_CAPTURE_KEYS = re.compile(
    r"(?:cookie|header|storage|input.?value|form.?value|auth|credential|token|"
    r"source.?map|script.?body|(?:xhr|fetch|api).?(?:body|payload)|table.?cell|"
    r"hostname|(?:^|_)host(?:$|_)|(?:^|_)(?:url|href|src|origin|query)(?:$|_))",
    re.IGNORECASE,
)
_RESOURCE_URL = re.compile(r"url\(\s*(['\"]?)(?:https?:|data:|file:|javascript:|//).*?\1\s*\)", re.IGNORECASE)
_IMPORT_RULE = re.compile(r"@import\b[^;]*(?:;|$)", re.IGNORECASE)
_HOSTNAME_VALUE = re.compile(
    r"(?:https?://|www\.)|(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}",
    re.IGNORECASE,
)
_KNOWN_FRAMEWORK_HINTS = {
    "react", "next.js", "angular", "vue", "svelte", "tailwind", "bootstrap", "material ui",
}
_SAFE_TOKEN_GROUPS = {"colors", "spacing", "typography", "radius", "border", "shadow", "font_families"}


class CapturePolicyError(ValueError):
    """Raised when capture authorization or privacy requirements are not met."""


@dataclass(frozen=True)
class CaptureAdapterDescriptor:
    id: str
    name: str
    version: str
    status: str
    description: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "description": self.description,
        }


_ADAPTERS = (
    CaptureAdapterDescriptor(
        "playwright", "Playwright", "1", "available",
        "Bounded, user-authorized browser capture; requires a separately installed Playwright runtime and browser.",
    ),
    CaptureAdapterDescriptor("puppeteer", "Puppeteer", "planned", "descriptor-only", "Future Chromium capture adapter."),
    CaptureAdapterDescriptor("storybook", "Storybook", "planned", "descriptor-only", "Future component catalog adapter."),
    CaptureAdapterDescriptor("screenshot-to-code", "Screenshot-to-Code", "planned", "descriptor-only", "Future reviewed draft-generation adapter."),
    CaptureAdapterDescriptor("react-devtools", "React DevTools", "planned", "descriptor-only", "Future authorized metadata enrichment."),
    CaptureAdapterDescriptor("flauinspect", "FlaUInspect", "planned", "descriptor-only", "Future Windows desktop metadata adapter."),
    CaptureAdapterDescriptor("pyqtinspect", "PyQtInspect-Open", "planned", "descriptor-only", "Future Qt desktop metadata adapter."),
    CaptureAdapterDescriptor("applitools", "Applitools Eyes", "planned", "descriptor-only", "Future user-configured visual comparison connector."),
)


def available_capture_adapters() -> list[dict[str, str]]:
    return [descriptor.as_dict() for descriptor in _ADAPTERS]


class PlaywrightCaptureAdapter:
    """Captures a sanitized envelope without persisting browser credentials or state."""

    name = "Playwright"
    version = "1"

    def __init__(self, *, runner=None) -> None:
        self._runner = runner

    @classmethod
    def describe(cls) -> dict[str, str]:
        return _ADAPTERS[0].as_dict()

    def capture(self, request: object) -> dict[str, object]:
        normalized = _validate_request(request)
        if self._runner is not None:
            envelope = self._runner(normalized)
        else:
            envelope = self._run_playwright(normalized)
        safe = sanitize_capture_envelope(envelope)
        safe["adapter"] = self.name
        safe["adapter_version"] = self.version
        return safe

    @staticmethod
    def _run_playwright(request: dict[str, object]) -> dict[str, object]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright capture is optional; install Playwright and its browser only after approval."
            ) from exc

        script_path = Path(__file__).resolve().parents[2] / "web" / "designer_capture.js"
        capture_script = script_path.read_text(encoding="utf-8")
        base_url = request["url"]
        allowed_origins = set(request["allowed_origins"])
        routes = request["routes"]
        viewports = request["viewports"]
        pages: list[dict[str, object]] = []
        stylesheet_contents: dict[str, str] = {}
        resource_inventory: dict[str, dict[str, object]] = {}

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(service_workers="block")
                page = context.new_page()
                stylesheet_bytes_total = 0
                unresolved_resources: list[dict[str, str]] = []

                def route_request(route) -> None:
                    parsed = urlsplit(route.request.url)
                    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
                    if origin not in allowed_origins or route.request.resource_type in {
                        "xhr", "fetch", "websocket", "eventsource", "media", "manifest",
                    }:
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/*", route_request)

                def on_response(response) -> None:
                    nonlocal stylesheet_bytes_total
                    parsed = urlsplit(response.url)
                    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
                    if origin not in allowed_origins:
                        return
                    resource_type = response.request.resource_type
                    if resource_type not in {"stylesheet", "image", "font"}:
                        return
                    relative = parsed.path or "/"
                    if resource_type == "stylesheet" and len(stylesheet_contents) < 512:
                        content_length = response.headers.get("content-length", "")
                        if content_length.isdigit() and int(content_length) <= MAX_CAPTURE_RESOURCE_BYTES:
                            try:
                                body = response.body()
                            except Exception:
                                unresolved_resources.append({"path": relative, "reason": "unreadable"})
                                return
                            if len(body) <= MAX_CAPTURE_RESOURCE_BYTES and stylesheet_bytes_total + len(body) <= MAX_CAPTURE_BYTES:
                                try:
                                    stylesheet_contents[relative] = body.decode("utf-8")
                                    stylesheet_bytes_total += len(body)
                                except UnicodeDecodeError:
                                    unresolved_resources.append({"path": relative, "reason": "invalid-encoding"})
                                    return
                            else:
                                unresolved_resources.append({"path": relative, "reason": "size-limit"})
                        else:
                            unresolved_resources.append({"path": relative, "reason": "size-unknown-or-limit"})
                    if relative not in resource_inventory and len(resource_inventory) >= 2048:
                        return
                    content_length = response.headers.get("content-length", "")
                    resource_inventory[relative] = {
                        "type": resource_type,
                        "path": relative,
                        "media_type": response.headers.get("content-type", "").split(";", 1)[0][:128],
                        "size": min(int(content_length), MAX_CAPTURE_RESOURCE_BYTES) if content_length.isdigit() else 0,
                    }

                page.on("response", on_response)
                screenshot_bytes_total = 0
                for route_path in routes:
                    for viewport in viewports:
                        page.set_viewport_size(viewport)
                        target = _url_for_route(base_url, route_path)
                        page.goto(target, wait_until="domcontentloaded", timeout=30_000)
                        capture = page.evaluate(capture_script)
                        page.add_style_tag(content=(
                            "input,textarea,select,[contenteditable=true] {"
                            " color: transparent !important; text-shadow: none !important;"
                            " background-image: none !important; caret-color: transparent !important;"
                            "}"
                        ))
                        screenshot_path = f"screenshots/{len(pages) + 1:03d}.jpg"
                        image = page.screenshot(type="jpeg", quality=60, full_page=False)
                        if (
                            len(image) <= MAX_CAPTURE_SCREENSHOT_BYTES
                            and screenshot_bytes_total + len(image) <= MAX_CAPTURE_SCREENSHOT_TOTAL_BYTES
                        ):
                            screenshot_bytes_total += len(image)
                            capture["screenshots"] = [{
                                "path": screenshot_path,
                                "media_type": "image/jpeg",
                                "size": len(image),
                                "digest": f"sha256:{hashlib.sha256(image).hexdigest()}",
                                "content_base64": base64.b64encode(image).decode("ascii"),
                            }]
                        else:
                            capture["screenshots"] = [{"path": screenshot_path, "omitted": "size_limit"}]
                        capture["route"] = route_path
                        capture["viewport"] = viewport
                        capture["stylesheets"] = [
                            {"path": path, "body": body}
                            for path, body in sorted(stylesheet_contents.items())
                        ]
                        capture["resources"] = list(resource_inventory.values())
                        capture["unresolved_resources"] = unresolved_resources[:2048]
                        pages.append(capture)
                        if len(pages) >= MAX_CAPTURE_PAGES:
                            break
                    if len(pages) >= MAX_CAPTURE_PAGES:
                        break
                context.close()
            finally:
                browser.close()
        return {
            "schema_version": 1,
            "pages": pages,
            "framework_hints": [],
        }


def sanitize_capture_envelope(envelope: object) -> dict[str, object]:
    if not isinstance(envelope, dict) or envelope.get("schema_version") != 1:
        raise CapturePolicyError("unsupported or malformed capture envelope")
    if _contains_private_field(envelope):
        raise CapturePolicyError("capture envelope contains prohibited private data fields")
    pages = envelope.get("pages")
    if not isinstance(pages, list) or len(pages) > MAX_CAPTURE_PAGES:
        raise CapturePolicyError("capture envelope page count exceeds limit")
    safe = _sanitize_value(envelope)
    if not isinstance(safe, dict):
        raise CapturePolicyError("capture envelope must be an object")
    safe_pages = safe.get("pages")
    if not isinstance(safe_pages, list):
        raise CapturePolicyError("capture envelope pages must be a list")
    _validate_capture_paths(safe)
    screenshot_total = 0
    for page in safe_pages:
        if not isinstance(page, dict):
            raise CapturePolicyError("capture page must be an object")
        route = page.get("route", "/")
        if not isinstance(route, str) or not route.startswith("/") or "?" in route or "#" in route or "://" in route:
            raise CapturePolicyError("capture page route must be local and query-free")
        page["route"] = route[:512]
        viewport = page.get("viewport")
        if viewport is not None:
            if not isinstance(viewport, dict) or set(viewport) != {"width", "height"}:
                raise CapturePolicyError("capture page viewport is malformed")
            for value in viewport.values():
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4096:
                    raise CapturePolicyError("capture viewport dimensions are out of range")
            if viewport["width"] * viewport["height"] > 8_388_608:
                raise CapturePolicyError("capture viewport pixel area exceeds limit")
        resources = page.get("resources", [])
        if not isinstance(resources, list) or len(resources) > 2048:
            raise CapturePolicyError("capture resource inventory exceeds limit")
        for resource in resources:
            if not isinstance(resource, dict):
                raise CapturePolicyError("capture resource entry must be an object")
            path = resource.get("path", "")
            if (
                not isinstance(path, str) or "://" in path or "?" in path or "#" in path
                or path.startswith("//") or "\\" in path or _looks_like_remote_path(path)
            ):
                raise CapturePolicyError("captured resource paths must be local and query-free")
            size = resource.get("size", 0)
            if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_CAPTURE_RESOURCE_BYTES:
                raise CapturePolicyError("captured resource size is invalid or exceeds limit")
        for field, limit in {
            "accessibility": 4096,
            "computed_styles": 1000,
            "images": 512,
            "backgrounds": 512,
            "svgs": 128,
            "fonts": 256,
            "selector_usage": 2048,
            "unresolved_resources": 2048,
        }.items():
            inventory = page.get(field, [])
            if not isinstance(inventory, list) or len(inventory) > limit:
                raise CapturePolicyError(f"capture {field} inventory exceeds limit")
        for field in ("stylesheets", "inline_styles"):
            styles = page.get(field, [])
            if not isinstance(styles, list) or len(styles) > 512:
                raise CapturePolicyError("capture stylesheet count exceeds limit")
            for stylesheet in styles:
                if not isinstance(stylesheet, dict):
                    raise CapturePolicyError("capture stylesheet must be an object")
                path = stylesheet.get("path", "")
                if path and (
                    not isinstance(path, str) or "://" in path or "?" in path or "#" in path
                    or path.startswith("//") or "\\" in path or _looks_like_remote_path(path)
                ):
                    raise CapturePolicyError("capture stylesheet paths must be local and query-free")
                content_key = "body" if "body" in stylesheet else "declarations"
                body = stylesheet.get(content_key, "")
                if not isinstance(body, str) or len(body.encode("utf-8")) > MAX_CAPTURE_RESOURCE_BYTES:
                    raise CapturePolicyError("captured stylesheet exceeds size limit")
                stylesheet[content_key] = _sanitize_capture_css(body)
        screenshots = page.get("screenshots", [])
        if not isinstance(screenshots, list) or len(screenshots) > 16:
            raise CapturePolicyError("capture screenshot count exceeds limit")
        for screenshot in screenshots:
            if not isinstance(screenshot, dict) or set(screenshot) - {
                "path", "media_type", "size", "content_base64", "digest", "omitted",
            }:
                raise CapturePolicyError("capture screenshot metadata is malformed")
            path = screenshot.get("path", "")
            if not isinstance(path, str) or not path.startswith("screenshots/") or "://" in path or "?" in path:
                raise CapturePolicyError("screenshot path must be a managed relative path")
            if screenshot.get("omitted") == "size_limit":
                if "content_base64" in screenshot:
                    raise CapturePolicyError("omitted screenshot cannot include image data")
                continue
            if screenshot.get("media_type") not in {"image/jpeg", "image/png"}:
                raise CapturePolicyError("capture screenshots must be JPEG or PNG")
            encoded = screenshot.get("content_base64")
            size = screenshot.get("size")
            digest = screenshot.get("digest")
            if not isinstance(encoded, str) or len(encoded) > MAX_CAPTURE_SCREENSHOT_BYTES * 4 // 3 + 8:
                raise CapturePolicyError("capture screenshot exceeds size limit")
            try:
                image_bytes = base64.b64decode(encoded, validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                raise CapturePolicyError("capture screenshot encoding is invalid") from exc
            if (
                len(image_bytes) > MAX_CAPTURE_SCREENSHOT_BYTES
                or isinstance(size, bool) or not isinstance(size, int) or len(image_bytes) != size
                or digest != f"sha256:{hashlib.sha256(image_bytes).hexdigest()}"
            ):
                raise CapturePolicyError("capture screenshot size or checksum is invalid")
            screenshot_total += len(image_bytes)
            if screenshot_total > MAX_CAPTURE_SCREENSHOT_TOTAL_BYTES:
                raise CapturePolicyError("capture screenshots exceed total size limit")
    encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_CAPTURE_BYTES:
        raise CapturePolicyError("capture envelope exceeds total size limit")
    return safe


def _validate_request(value: object) -> dict[str, object]:
    required = {
        "url", "authorization_attested", "source_label", "license_note",
        "allowed_origins", "routes", "viewports",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise CapturePolicyError("capture request has missing or unsupported fields")
    if value["authorization_attested"] is not True:
        raise CapturePolicyError("explicit authorization attestation is required")
    if not isinstance(value["source_label"], str) or not value["source_label"].strip() or len(value["source_label"]) > 256:
        raise CapturePolicyError("a bounded source label is required")
    if not isinstance(value["license_note"], str) or not value["license_note"].strip() or len(value["license_note"]) > 512:
        raise CapturePolicyError("a license or reuse note is required")
    url = value["url"]
    if not isinstance(url, str) or len(url) > 4096:
        raise CapturePolicyError("capture URL is invalid")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise CapturePolicyError("capture URL must be an HTTP(S) address without embedded credentials")
    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    allowed = value["allowed_origins"]
    if not isinstance(allowed, list) or not 1 <= len(allowed) <= 32 or origin not in allowed:
        raise CapturePolicyError("capture origin must be explicitly allow-listed")
    if any(not isinstance(item, str) or _origin(item) != item for item in allowed):
        raise CapturePolicyError("allowed origins must be canonical HTTP(S) origins")
    routes = value["routes"]
    if not isinstance(routes, list) or not 1 <= len(routes) <= MAX_CAPTURE_PAGES:
        raise CapturePolicyError("capture route count exceeds limit")
    if any(not isinstance(route, str) or not route.startswith("/") or "?" in route or "#" in route or "://" in route for route in routes):
        raise CapturePolicyError("capture routes must be local paths without query strings")
    viewports = value["viewports"]
    if not isinstance(viewports, list) or not 1 <= len(viewports) <= 12 or len(viewports) * len(routes) > MAX_CAPTURE_PAGES:
        raise CapturePolicyError("capture viewport count exceeds limit")
    safe_viewports: list[dict[str, int]] = []
    for viewport in viewports:
        if not isinstance(viewport, dict) or set(viewport) != {"width", "height"}:
            raise CapturePolicyError("capture viewport is malformed")
        width, height = viewport["width"], viewport["height"]
        if any(isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 4096 for item in (width, height)):
            raise CapturePolicyError("capture viewport dimensions are out of range")
        if width * height > 8_388_608:
            raise CapturePolicyError("capture viewport pixel area exceeds limit")
        safe_viewports.append({"width": width, "height": height})
    clean_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))
    return {
        "url": clean_url,
        "authorization_attested": True,
        "source_label": value["source_label"].strip(),
        "license_note": value["license_note"].strip(),
        "allowed_origins": list(allowed),
        "routes": list(routes),
        "viewports": safe_viewports,
    }


def _origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _url_for_route(base_url: str, route: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, route, "", ""))


def _contains_private_field(value: object) -> bool:
    return _contains_private_field_at_depth(value, 0)


def _contains_private_field_at_depth(value: object, depth: int) -> bool:
    if depth > 32:
        return True
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "excluded_field_counts":
                if not isinstance(child, dict) or any(
                    not isinstance(count, int) or count < 0 for count in child.values()
                ):
                    return True
                continue
            if key == "tokens":
                if not _is_safe_token_map(child) or _contains_private_field_at_depth(child, depth + 1):
                    return True
                continue
            if _FORBIDDEN_CAPTURE_KEYS.search(str(key)) or _contains_private_field_at_depth(child, depth + 1):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_private_field_at_depth(child, depth + 1) for child in value)
    return False


def _sanitize_value(
    value: object,
    depth: int = 0,
    *,
    css_context: bool = False,
    key_context: str = "",
) -> object:
    if depth > 32:
        raise CapturePolicyError("capture envelope nesting exceeds limit")
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise CapturePolicyError("capture envelope contains an invalid key")
            if key == "excluded_field_counts":
                if not isinstance(child, dict) or any(
                    not isinstance(count, int) or isinstance(count, bool) or count < 0
                    for count in child.values()
                ):
                    raise CapturePolicyError("excluded-field counts must be non-negative integers")
                sanitized[key] = {
                    str(count_name)[:64]: count for count_name, count in child.items()
                    if isinstance(count_name, str)
                }
                continue
            if key == "tokens":
                if not _is_safe_token_map(child):
                    raise CapturePolicyError("capture design-token candidates are malformed")
                sanitized[key] = _sanitize_value(child, depth + 1, key_context="tokens")
                continue
            if _FORBIDDEN_CAPTURE_KEYS.search(key):
                raise CapturePolicyError("capture envelope contains prohibited private data fields")
            sanitized[key] = _sanitize_value(
                child,
                depth + 1,
                css_context=(
                    css_context
                    or key == "css_variables"
                    or (key in {"body", "declarations"} and key_context in {"stylesheets", "inline_styles"})
                ),
                key_context=key,
            )
        return sanitized
    if isinstance(value, list):
        if len(value) > 10000:
            raise CapturePolicyError("capture envelope collection exceeds limit")
        return [
            _sanitize_value(child, depth + 1, css_context=css_context, key_context=key_context)
            for child in value
        ]
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_CAPTURE_RESOURCE_BYTES:
            raise CapturePolicyError("capture string exceeds size limit")
        text = value[:MAX_CAPTURE_RESOURCE_BYTES]
        if css_context:
            return _sanitize_capture_css(text)
        if (
            key_context != "path"
            and not (key_context == "framework_hints" and text.casefold() in _KNOWN_FRAMEWORK_HINTS)
            and _HOSTNAME_VALUE.search(text)
        ):
            raise CapturePolicyError("capture text cannot contain hostnames or URLs")
        return text
    if isinstance(value, float) and not math.isfinite(value):
        raise CapturePolicyError("capture envelope contains a non-finite number")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise CapturePolicyError("capture envelope contains an unsupported value")


def _sanitize_capture_css(source: str) -> str:
    source = _IMPORT_RULE.sub("", source)
    source = _RESOURCE_URL.sub("none", source)
    source = re.sub(r"url\s*\([^)]*\)", "none", source, flags=re.IGNORECASE)
    source = re.sub(r"(?:https?:)?//[^\s;,)]+", "none", source, flags=re.IGNORECASE)
    source = re.sub(r"data:[^\s;,)]+", "none", source, flags=re.IGNORECASE)
    source = _HOSTNAME_VALUE.sub("none", source)
    source = re.sub(r"(?:javascript|vbscript|file):", "", source, flags=re.IGNORECASE)
    return source


def _looks_like_remote_path(value: str) -> bool:
    if value.rsplit(".", 1)[-1].lower() in {"css", "png", "jpg", "jpeg", "svg", "woff", "woff2", "ttf", "otf"}:
        return value.lower().startswith("www.")
    return bool(re.match(r"^(?:www\.)|^(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/|$)", value, re.IGNORECASE))


def _validate_capture_paths(value: object, key_context: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "path":
                if (
                    not isinstance(child, str)
                    or not child
                    or "://" in child
                    or "?" in child
                    or "#" in child
                    or "\\" in child
                    or child.startswith("//")
                    or any(part in {".", ".."} for part in child.split("/"))
                    or (
                        not child.startswith("/")
                        and not child.startswith(("assets/", "screenshots/"))
                        and child.rsplit(".", 1)[-1].lower() not in {
                            "css", "png", "jpg", "jpeg", "svg", "woff", "woff2", "ttf", "otf",
                        }
                    )
                    or (not child.startswith("/") and _looks_like_remote_path(child))
                ):
                    raise CapturePolicyError("capture paths must be local, query-free relative paths")
            _validate_capture_paths(child, str(key))
    elif isinstance(value, list):
        for child in value:
            _validate_capture_paths(child, key_context)


def _is_safe_token_map(value: object) -> bool:
    if not isinstance(value, dict) or set(value) - _SAFE_TOKEN_GROUPS or len(value) > len(_SAFE_TOKEN_GROUPS):
        return False

    def safe_value(item: object, depth: int = 0) -> bool:
        if depth > 8:
            return False
        if isinstance(item, dict):
            return len(item) <= 128 and all(
                isinstance(key, str) and len(key) <= 64
                and not _FORBIDDEN_CAPTURE_KEYS.search(key)
                and safe_value(child, depth + 1)
                for key, child in item.items()
            )
        if isinstance(item, list):
            return len(item) <= 256 and all(safe_value(child, depth + 1) for child in item)
        if isinstance(item, str):
            return len(item) <= 256
        return item is None or isinstance(item, (bool, int, float))

    return all(safe_value(item) for item in value.values())
