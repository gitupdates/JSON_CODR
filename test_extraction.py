import tempfile
import unittest
import zipfile
from pathlib import Path

from docx import Document
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from web_app.extraction import ExtractionService


class ExtractionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_extracts_supported_text_and_code_without_rendering_markup(self):
        for suffix, content in ((".txt", "hello"), (".py", "print('<b>x</b>')"), (".json", '{"x": 1}')):
            with self.subTest(suffix=suffix):
                source = self.root / f"input{suffix}"
                source.write_text(content, encoding="utf-8")
                result = ExtractionService().extract(source, "text/plain")
                self.assertEqual(result.text, content)
                self.assertFalse(result.truncated)

    def test_truncates_text_at_100000_characters_with_warning(self):
        source = self.root / "large.txt"
        source.write_text("x" * 100_001, encoding="utf-8")
        result = ExtractionService().extract(source, "text/plain")
        self.assertEqual(len(result.text), 100_000)
        self.assertTrue(result.truncated)
        self.assertIn("truncated", result.warnings[0].lower())

    def test_rejects_binary_content_claiming_to_be_text(self):
        source = self.root / "bad.txt"
        source.write_bytes(b"\x00\x01\x02")
        with self.assertRaises(ValueError):
            ExtractionService().extract(source, "text/plain")

    def test_extracts_formatted_docx_paragraphs_and_tables(self):
        source = self.root / "review.docx"
        document = Document()
        document.add_heading("Review target", level=1)
        document.add_paragraph("Comment on this requirement.")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Owner"
        table.cell(0, 1).text = "JSON_CODR"
        document.save(source)

        result = ExtractionService().extract(
            source,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        self.assertIn("Review target", result.text)
        self.assertIn("Comment on this requirement.", result.text)
        self.assertIn("Owner | JSON_CODR", result.text)

    def test_extracts_pdf_text(self):
        source = self.root / "review.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 72 200 Td (PDF review text) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        with source.open("wb") as destination:
            writer.write(destination)

        result = ExtractionService().extract(source, "application/pdf")

        self.assertIn("PDF review text", result.text)

    def test_decodes_common_images_and_uses_local_ocr(self):
        for suffix, image_format in (
            (".png", "PNG"),
            (".jpg", "JPEG"),
            (".webp", "WEBP"),
            (".gif", "GIF"),
            (".bmp", "BMP"),
        ):
            with self.subTest(suffix=suffix):
                source = self.root / f"screen{suffix}"
                Image.new("RGB", (20, 10), "white").save(source, format=image_format)
                result = ExtractionService(ocr=lambda image: f"OCR {image.width}x{image.height}").extract(
                    source, f"image/{image_format.lower()}"
                )
                self.assertEqual(result.text, "OCR 20x10")

    def test_image_without_local_ocr_stays_reviewable_with_warning(self):
        source = self.root / "screen.png"
        Image.new("RGB", (10, 10), "white").save(source)
        result = ExtractionService(ocr=None).extract(source, "image/png")
        self.assertEqual(result.text, "")
        self.assertIn("OCR unavailable", result.warnings)

    def test_detects_standard_windows_tesseract_install(self):
        executable = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        if not executable.exists():
            self.skipTest("Standard Windows Tesseract install is unavailable")
        self.assertIsNotNone(ExtractionService().ocr)

    def test_extracts_basic_rtf_as_text(self):
        source = self.root / "notes.rtf"
        source.write_text(r"{\rtf1\ansi Review \b this\b0 document.}", encoding="utf-8")
        result = ExtractionService().extract(source, "application/rtf")
        self.assertIn("Review", result.text)
        self.assertIn("this", result.text)
        self.assertNotIn("\\b", result.text)

    def test_extracts_supported_files_from_zip_without_writing_entries(self):
        source = self.root / "project.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("src/main.py", "print('review me')")
            archive.writestr("docs/notes.md", "# Review notes")
            archive.writestr("assets/binary.exe", b"\x00\x01")

        result = ExtractionService().extract(source, "application/zip")

        self.assertIn("FILE: src/main.py", result.text)
        self.assertIn("print('review me')", result.text)
        self.assertIn("FILE: docs/notes.md", result.text)
        self.assertNotIn("binary.exe\n\x00", result.text)

    def test_rejects_zip_traversal_and_uncompressed_size_over_limit(self):
        traversal = self.root / "traversal.zip"
        with zipfile.ZipFile(traversal, "w") as archive:
            archive.writestr("../outside.txt", "escape")
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            ExtractionService().extract(traversal, "application/zip")

        oversized = self.root / "oversized.zip"
        with zipfile.ZipFile(oversized, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("large.txt", "x" * 101)
        with self.assertRaisesRegex(ValueError, "uncompressed size"):
            ExtractionService(max_archive_bytes=100).extract(oversized, "application/zip")

    def test_extracts_supported_files_from_7z(self):
        import py7zr

        source = Path(self.temporary_directory.name) / "context.7z"
        note = Path(self.temporary_directory.name) / "note.md"
        note.write_text("seven zip context", encoding="utf-8")
        with py7zr.SevenZipFile(source, "w") as archive:
            archive.write(note, "docs/note.md")

        result = ExtractionService().extract(source, "application/x-7z-compressed")

        self.assertIn("FILE: docs/note.md", result.text)
        self.assertIn("seven zip context", result.text)


if __name__ == "__main__":
    unittest.main()
