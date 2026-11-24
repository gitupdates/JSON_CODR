import base64
import hashlib
import io
import json
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from web_app.designer.assets import AssetService
from web_app.designer.capture_adapters import (
    CapturePolicyError,
    PlaywrightCaptureAdapter,
    available_capture_adapters,
    sanitize_capture_envelope,
)
from web_app.designer.references import (
    ReferenceImportError,
    ReferenceImporter,
)
from web_app.designer.contracts import DesignDocument
from web_app.designer.store import DesignerStore


def extract_payload():
    return {
        "schema_version": 1,
        "viewport": {"width": 1280, "height": 800},
        "pages": [{
            "name": "Operations",
            "route": "/",
            "headings": ["Operations"],
            "labels": ["Search", "Refresh"],
            "controls": [{"type": "searchbox", "label": "Search"}],
            "elements": [{
                "tag": "main",
                "role": "main",
                "name": "Operations",
                "classes": ["dashboard"],
                "bounds": {"x": 0, "y": 0, "width": 1280, "height": 800},
            }],
            "grid_columns": [1, 2, 4],
        }],
        "class_frequencies": {"dashboard": 1, "card": 4},
        "framework_hints": ["React"],
        "resources": [{"type": "stylesheet", "path": "/static/site.css", "media_type": "text/css", "size": 512}],
    }


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (4, 3), (30, 80, 120)).save(output, format="PNG")
    return output.getvalue()


def make_archive(entries, *, version=1, review=None, checksum_override=None, symlink=None):
    files = dict(entries)
    if review is not None:
        files["REVIEW.txt"] = review.encode("utf-8")
    manifest_files = {
        name: f"sha256:{hashlib.sha256(data).hexdigest()}"
        for name, data in files.items()
    }
    if checksum_override:
        manifest_files[checksum_override] = "sha256:" + ("0" * 64)
    manifest = json.dumps({
        "format": "json-codr-ui-reference",
        "schema_version": version,
        "files": manifest_files,
    }, sort_keys=True).encode("utf-8")
    checksum_text = "".join(
        f"{digest.removeprefix('sha256:')}  {name}\n"
        for name, digest in sorted(manifest_files.items())
    ).encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("MANIFEST.json", manifest)
        archive.writestr("MANIFEST.sha256", checksum_text)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "target")
    return output.getvalue()


class DesignerReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.store = DesignerStore(self.root)
        self.project = self.store.create_project("blank", "Reference test")
        self.assets = AssetService(self.store)
        self.references = ReferenceImporter(self.store, self.assets)
        self.provenance = {
            "source_label": "User-owned operations console",
            "license_note": "User-owned",
            "authorization_attested": True,
        }

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_import_extract_preserves_safe_structure_and_provenance(self):
        record = self.references.import_extract(
            self.project.project_id, extract_payload(), **self.provenance,
        )
        imported = self.references.get_reference(self.project.project_id, record.reference_id)

        self.assertEqual(record.kind, "extract")
        self.assertEqual(record.source_label, self.provenance["source_label"])
        self.assertEqual(record.license_note, self.provenance["license_note"])
        self.assertEqual(imported["extract"]["pages"][0]["headings"], ["Operations"])
        self.assertEqual(imported["extract"]["pages"][0]["controls"][0]["label"], "Search")
        serialized = json.dumps(imported).lower()
        for forbidden in ("input_value", "table_cells", "cookie", "storage", "hostname", "query_string"):
            self.assertNotIn(forbidden, serialized)

    def test_saved_design_keeps_reference_provenance(self):
        record = self.references.import_extract(
            self.project.project_id, extract_payload(), **self.provenance,
        )
        current = self.store.get_project(self.project.project_id)
        payload = current.model_dump(mode="json", exclude={"canonical_digest"})
        payload["references"] = [record.model_dump(mode="json")]
        draft = DesignDocument.model_validate(payload)

        revision = self.store.save_revision(
            self.project.project_id, draft, current.canonical_digest,
        )

        self.assertEqual(revision.document.references[0].reference_id, record.reference_id)
        self.assertEqual(revision.document.references[0].source_label, self.provenance["source_label"])
        self.assertEqual(revision.document.references[0].license_note, self.provenance["license_note"])

    def test_extract_rejects_malformed_private_data_hostnames_and_queries(self):
        invalid_payloads = []
        malformed = extract_payload()
        malformed["viewport"]["width"] = -1
        invalid_payloads.append(malformed)
        private = extract_payload()
        private["cookies"] = [{"name": "session"}]
        invalid_payloads.append(private)
        host = extract_payload()
        host["pages"][0]["route"] = "https://private.example/dashboard"
        invalid_payloads.append(host)
        hostname_text = extract_payload()
        hostname_text["pages"][0]["headings"] = ["private.example"]
        invalid_payloads.append(hostname_text)
        query = extract_payload()
        query["pages"][0]["route"] = "/dashboard?access_token=secret"
        invalid_payloads.append(query)
        for candidate in invalid_payloads:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ReferenceImportError):
                    self.references.import_extract(
                        self.project.project_id, candidate, **self.provenance,
                    )

    def test_import_image_requires_authorized_license_provenance(self):
        image = png_bytes()
        with self.assertRaises(CapturePolicyError):
            self.references.import_image(
                self.project.project_id,
                io.BytesIO(image),
                "reference.png",
                "image/png",
                source_label="Unknown site",
                license_note="",
                authorization_attested=False,
            )
        record = self.references.import_image(
            self.project.project_id,
            io.BytesIO(image),
            "reference.png",
            "image/png",
            **self.provenance,
        )
        self.assertEqual(record.kind, "screenshot")
        self.assertTrue(record.content_digest.startswith("sha256:"))

    def test_import_capture_stores_bounded_screenshot_as_managed_asset(self):
        image = png_bytes()
        envelope = {
            "schema_version": 1,
            "pages": [{
                "route": "/",
                "screenshots": [{
                    "path": "screenshots/001.png",
                    "media_type": "image/png",
                    "size": len(image),
                    "digest": f"sha256:{hashlib.sha256(image).hexdigest()}",
                    "content_base64": base64.b64encode(image).decode("ascii"),
                }],
            }],
        }
        record = self.references.import_capture(
            self.project.project_id, envelope, **self.provenance,
        )
        stored = self.references.get_reference(self.project.project_id, record.reference_id)
        screenshot = stored["capture"]["pages"][0]["screenshots"][0]
        asset = stored["screenshot_assets"][0]

        self.assertNotIn("content_base64", screenshot)
        self.assertEqual(screenshot["asset"]["asset_id"], asset["asset_id"])
        stored_image = self.assets.read_asset(self.project.project_id, asset["relative_path"])
        self.assertEqual(Image.open(io.BytesIO(stored_image)).getpixel((0, 0)), Image.open(io.BytesIO(image)).getpixel((0, 0)))

    def test_archive_verifies_manifest_and_requires_review_acknowledgement(self):
        entries = {
            "REPORT.md": b"Capture report",
            "DIFF.md": b"Sanitization diff",
            "ui-extract.json": json.dumps(extract_payload()).encode("utf-8"),
        }
        archive = make_archive(entries, review="Unresolved sanitizer finding")
        with self.assertRaisesRegex(ReferenceImportError, "acknowledgement"):
            self.references.import_archive(
                self.project.project_id, io.BytesIO(archive), **self.provenance,
            )
        record = self.references.import_archive(
            self.project.project_id,
            io.BytesIO(archive),
            **self.provenance,
            acknowledge_review=True,
        )
        self.assertEqual(record.kind, "archive")
        self.assertEqual(self.references.get_reference(self.project.project_id, record.reference_id)["report"], "Capture report")

    def test_archive_rejects_bad_digests_unsupported_versions_traversal_and_symlinks(self):
        base = {"REPORT.md": b"Report", "DIFF.md": b"Diff", "ui-extract.json": json.dumps(extract_payload()).encode()}
        bad_digest = make_archive(base, checksum_override="REPORT.md")
        unsupported = make_archive(base, version=99)
        traversal = make_archive({**base, "../outside.txt": b"no"})
        symlink = make_archive(base, symlink="assets/link.png")
        for archive in (bad_digest, unsupported, traversal, symlink):
            with self.subTest(archive=archive[:16]):
                with self.assertRaises(ReferenceImportError):
                    self.references.import_archive(
                        self.project.project_id, io.BytesIO(archive), **self.provenance,
                    )

    def test_archive_bounds_uncompressed_entries_and_total_size(self):
        limited = ReferenceImporter(self.store, self.assets, max_entry_bytes=256, max_archive_bytes=512)
        bomb = make_archive({
            "REPORT.md": b"R" * 1024,
            "DIFF.md": b"Diff",
            "ui-extract.json": json.dumps(extract_payload()).encode(),
        })
        with self.assertRaisesRegex(ReferenceImportError, "size limit"):
            limited.import_archive(
                self.project.project_id, io.BytesIO(bomb), **self.provenance,
            )

    def test_archive_builder_outputs_importable_versioned_archive(self):
        source = self.root / "archive-source"
        source.mkdir()
        (source / "REPORT.md").write_text("Capture report", encoding="utf-8")
        (source / "DIFF.md").write_text("Sanitization diff", encoding="utf-8")
        (source / "ui-extract.json").write_text(json.dumps(extract_payload()), encoding="utf-8")
        output = self.root / "built-reference.zip"
        tool = Path(__file__).parent / "tools" / "make_ui_reference_archive.py"
        subprocess.run(
            [sys.executable, str(tool), str(source), str(output)],
            check=True,
            capture_output=True,
            text=True,
        )
        with output.open("rb") as stream:
            record = self.references.import_archive(
                self.project.project_id, stream, **self.provenance,
            )
        self.assertEqual(record.kind, "archive")
        self.assertEqual(self.references.get_reference(self.project.project_id, record.reference_id)["report"], "Capture report")

    def test_preview_removes_scripts_forms_event_handlers_and_remote_resources(self):
        entries = {
            "REPORT.md": b"Report",
            "DIFF.md": b"Diff",
            "ui-extract.json": json.dumps(extract_payload()).encode(),
            "index.html": (
                b'<main onload="bad()"><script>steal()</script><h1>Safe title</h1>'
                b'<form><input value="private"></form><img src="https://evil.example/x" onerror="bad()"></main>'
            ),
            "styles.css": b'@import "https://evil.example/a.css"; .safe { color: #123456; }',
        }
        record = self.references.import_archive(
            self.project.project_id, io.BytesIO(make_archive(entries)), **self.provenance,
        )
        preview = self.references.reference_preview(self.project.project_id, record.reference_id)
        markup = preview["html"].lower()

        for forbidden in ("<script", "<form", "private", "onload", "onerror", "https://evil.example", "@import"):
            self.assertNotIn(forbidden, markup)
        self.assertEqual(preview["sandbox"], "")
        self.assertIn("default-src 'none'", preview["content_security_policy"])

    def test_playwright_adapter_is_authorized_bounded_and_excludes_private_capture_fields(self):
        captured_request = {}
        screenshot = png_bytes()

        def capture_runner(request):
            captured_request.update(request)
            return {
                "schema_version": 1,
                "pages": [{
                    "route": "/",
                    "viewport": {"width": 1280, "height": 800},
                    "dom": {"tag": "main", "role": "main", "name": "Overview", "children": []},
                    "accessibility": [{"role": "main", "name": "Overview"}],
                    "stylesheets": [{
                        "path": "/site.css",
                        "body": ".card { color: #123456; background: url(https://evil.example/a); }",
                    }],
                    "inline_styles": [{"tag": "section", "declarations": "color: #123456; background: url(https://evil.example/x)"}],
                    "computed_styles": [{"tag": "main", "properties": {"color": "rgb(1, 2, 3)", "display": "grid"}}],
                    "css_variables": {"--brand": "#123456", "--external": "url(https://evil.example/x)"},
                    "tokens": {"colors": ["#123456"], "spacing": [8, 16]},
                    "images": [{"path": "/logo.svg", "alt": "Brand mark"}],
                    "backgrounds": [{"path": "/surface.png"}, {"unresolved": True}],
                    "svgs": [{"label": "Brand mark", "bounds": {"x": 0, "y": 0, "width": 32, "height": 32}}],
                    "fonts": [{"family": "Open Sans", "weight": "400", "style": "normal"}],
                    "resources": [{"kind": "image", "path": "/logo.svg", "media_type": "image/svg+xml"}],
                    "screenshots": [{
                        "path": "screenshots/001.png",
                        "media_type": "image/png",
                        "size": len(screenshot),
                        "digest": f"sha256:{hashlib.sha256(screenshot).hexdigest()}",
                        "content_base64": base64.b64encode(screenshot).decode("ascii"),
                    }],
                    "unresolved_resources": [{"path": "/cross-origin.css", "reason": "blocked"}],
                    "selector_usage": [".card"],
                }],
                "framework_hints": ["React"],
                "excluded_field_counts": {"input_values": 1, "cookies": 0},
            }

        adapter = PlaywrightCaptureAdapter(runner=capture_runner)
        request = {
            "url": "https://owned.example/path?private=secret",
            "authorization_attested": True,
            "source_label": "Owned application",
            "license_note": "User-owned",
            "allowed_origins": ["https://owned.example"],
            "routes": ["/"],
            "viewports": [{"width": 1280, "height": 800}],
        }
        result = adapter.capture(request)

        self.assertNotIn("private=secret", json.dumps(result))
        self.assertNotIn("owned.example", json.dumps(result))
        page = result["pages"][0]
        self.assertNotIn("evil.example", json.dumps(result))
        self.assertEqual(page["stylesheets"][0]["body"], ".card { color: #123456; background: none; }")
        self.assertEqual(page["inline_styles"][0]["declarations"], "color: #123456; background: none")
        self.assertEqual(page["accessibility"][0]["name"], "Overview")
        self.assertEqual(page["tokens"]["spacing"], [8, 16])
        self.assertEqual(page["selector_usage"], [".card"])
        self.assertEqual(page["screenshots"][0]["media_type"], "image/png")
        self.assertEqual(result["framework_hints"], ["React"])
        self.assertEqual(result["excluded_field_counts"]["input_values"], 1)
        self.assertEqual(captured_request["url"], "https://owned.example/path")
        self.assertNotIn("authorization_attested", result)
        descriptors = available_capture_adapters()
        self.assertEqual(PlaywrightCaptureAdapter.describe()["version"], "1")
        self.assertIn("playwright", [item["id"] for item in descriptors])
        self.assertTrue(all(item["status"] == "descriptor-only" for item in descriptors if item["id"] != "playwright"))
        with self.assertRaises(CapturePolicyError):
            adapter.capture({**request, "authorization_attested": False})

    def test_envelope_sanitizer_rejects_private_fields_and_oversized_resources(self):
        unsafe = {
            "schema_version": 1,
            "pages": [],
            "cookies": [{"name": "session"}],
        }
        with self.assertRaises(CapturePolicyError):
            sanitize_capture_envelope(unsafe)
        oversized = {
            "schema_version": 1,
            "pages": [{"route": "/", "resources": [{"path": "/x.css", "body": "x" * (5 * 1024 * 1024 + 1)}]}],
        }
        with self.assertRaises(CapturePolicyError):
            sanitize_capture_envelope(oversized)

    def test_node_capture_sanitizer_removes_remote_css_and_rejects_private_fields(self):
        module_uri = (Path(__file__).parent / "tools" / "playwright_ui_capture.mjs").resolve().as_uri()
        envelope = {
            "schema_version": 1,
            "pages": [{
                "route": "/",
                "stylesheets": [{
                    "path": "/site.css",
                    "body": ".card { background: url(https://evil.example/x); color: #123456; }",
                }],
            }],
        }
        program = f"""
import {{ sanitizeEnvelope }} from {json.dumps(module_uri)};
const clean = sanitizeEnvelope({json.dumps(envelope)});
let rejectedPrivate = false;
try {{ sanitizeEnvelope({{ schema_version: 1, pages: [], cookies: [{{ name: "session" }}] }}); }}
catch {{ rejectedPrivate = true; }}
process.stdout.write(JSON.stringify({{ clean, rejectedPrivate }}));
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", program],
            check=True,
            capture_output=True,
            text=True,
        )
        output = json.loads(result.stdout)
        serialized = json.dumps(output["clean"])

        self.assertTrue(output["rejectedPrivate"])
        self.assertNotIn("evil.example", serialized)
        self.assertEqual(
            output["clean"]["pages"][0]["stylesheets"][0]["body"],
            ".card { background: none; color: #123456; }",
        )


if __name__ == "__main__":
    unittest.main()
