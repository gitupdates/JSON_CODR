import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from web_app.designer.assets import AssetError, AssetService, MAX_ASSET_BYTES
from web_app.designer.store import DesignerStore


def image_bytes(image_format):
    output = io.BytesIO()
    Image.new("RGB", (4, 3), (30, 80, 120)).save(output, format=image_format)
    return output.getvalue()


class DesignerAssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.store = DesignerStore(self.root)
        self.project = self.store.create_project("blank", "Asset test")
        self.assets = AssetService(self.store)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_imports_and_hashes_png_jpeg_sanitized_svg_and_open_font_bytes(self):
        cases = (
            (image_bytes("PNG"), "cover.png", "image/png", "image/png"),
            (image_bytes("JPEG"), "cover.jpg", "image/jpeg", "image/jpeg"),
            (
                b'<svg xmlns="http://www.w3.org/2000/svg" onload="run()">'
                b'<script>run()</script><rect width="8" height="8" fill="#123456"/>'
                b'<image href="https://invalid.example/pixel.png"/></svg>',
                "mark.svg", "image/svg+xml", "image/svg+xml",
            ),
            (b"wOFF" + bytes(range(32)), "open.woff", "font/woff", "font/woff"),
        )
        for data, filename, media_type, expected_type in cases:
            with self.subTest(filename=filename):
                result = self.assets.import_file(
                    self.project.project_id,
                    io.BytesIO(data),
                    filename,
                    media_type,
                    source_label="User supplied",
                    license_note="CC0",
                )
                path = self.store.projects_root / self.project.project_id / result.relative_path
                stored = path.read_bytes()
                self.assertEqual(result.media_type, expected_type)
                self.assertTrue(result.content_digest.startswith("sha256:"))
                self.assertEqual(result.content_digest, f"sha256:{__import__('hashlib').sha256(stored).hexdigest()}")
                self.assertEqual((result.source_label, result.license_note), ("User supplied", "CC0"))
                self.assertTrue(path.is_file())
                if media_type == "image/svg+xml":
                    self.assertNotIn(b"<script", stored.lower())
                    self.assertNotIn(b"onload", stored.lower())
                    self.assertNotIn(b"https://", stored.lower())

    def test_raster_import_reencodes_image_and_discards_exif_metadata(self):
        source = io.BytesIO()
        image = Image.new("RGB", (4, 3), (1, 2, 3))
        image.save(source, format="JPEG", exif=b"Exif\x00\x00private-location")

        result = self.assets.import_file(
            self.project.project_id,
            io.BytesIO(source.getvalue()),
            "photo.jpg",
            "image/jpeg",
        )
        stored = (self.store.projects_root / self.project.project_id / result.relative_path).read_bytes()

        self.assertNotIn(b"private-location", stored)
        self.assertEqual(Image.open(io.BytesIO(stored)).size, (4, 3))

    def test_rejects_mime_mismatch_malformed_active_svg_and_oversized_stream(self):
        with self.assertRaisesRegex(AssetError, "MIME"):
            self.assets.import_file(
                self.project.project_id, io.BytesIO(image_bytes("JPEG")), "bad.png", "image/png",
            )
        with self.assertRaisesRegex(AssetError, "SVG"):
            self.assets.import_file(
                self.project.project_id,
                io.BytesIO(b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///secret">]><svg/>'),
                "bad.svg",
                "image/svg+xml",
            )
        with self.assertRaisesRegex(AssetError, "font"):
            self.assets.import_file(
                self.project.project_id, io.BytesIO(b"not-a-font"), "bad.woff", "font/woff",
            )
        limited = AssetService(self.store, max_asset_bytes=64)
        with self.assertRaisesRegex(AssetError, "size limit"):
            limited.import_file(
                self.project.project_id, io.BytesIO(image_bytes("PNG")), "large.png", "image/png",
            )

    def test_names_and_project_ids_cannot_escape_managed_asset_root(self):
        asset = self.assets.import_file(
            self.project.project_id,
            io.BytesIO(image_bytes("PNG")),
            r"..\..\outside.png",
            "image/png",
        )
        asset_path = self.store.projects_root / self.project.project_id / asset.relative_path

        self.assertEqual(Path(asset.relative_path).parts[0], "assets")
        self.assertEqual(asset_path.resolve().parent, (self.store.projects_root / self.project.project_id / "assets").resolve())
        with self.assertRaises((ValueError, KeyError)):
            self.assets.import_file("../escape", io.BytesIO(image_bytes("PNG")), "x.png", "image/png")

    def test_supported_asset_limit_is_bounded(self):
        self.assertGreater(MAX_ASSET_BYTES, 0)
        self.assertLessEqual(MAX_ASSET_BYTES, 16 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
