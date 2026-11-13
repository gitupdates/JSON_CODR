import re
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field


class ExtractionResult(BaseModel):
    text: str
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


class ExtractionService:
    _AUTO_OCR = object()

    def __init__(
        self,
        max_characters: int = 100_000,
        ocr: Callable | None | object = _AUTO_OCR,
    ) -> None:
        self.max_characters = max_characters
        self.ocr = self._detect_ocr() if ocr is self._AUTO_OCR else ocr

    def extract(self, source: Path, detected_type: str) -> ExtractionResult:
        if detected_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return self._extract_docx(source)
        if detected_type == "application/pdf":
            return self._extract_pdf(source)
        if detected_type.startswith("image/"):
            return self._extract_image(source)
        if detected_type == "application/rtf":
            return self._extract_rtf(source)
        payload = source.read_bytes()
        if b"\x00" in payload:
            raise ValueError("Binary content is not valid text")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Text must be UTF-8") from error
        truncated = len(text) > self.max_characters
        return ExtractionResult(
            text=text[: self.max_characters],
            truncated=truncated,
            warnings=["Extracted text was truncated"] if truncated else [],
        )

    @staticmethod
    def _detect_ocr():
        try:
            import pytesseract

            standard_windows_path = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            if standard_windows_path.is_file():
                pytesseract.pytesseract.tesseract_cmd = str(standard_windows_path)

            pytesseract.get_tesseract_version()
            return pytesseract.image_to_string
        except Exception:
            return None

    def _bounded(self, text: str, warnings: list[str] | None = None) -> ExtractionResult:
        truncated = len(text) > self.max_characters
        result_warnings = list(warnings or [])
        if truncated:
            result_warnings.append("Extracted text was truncated")
        return ExtractionResult(
            text=text[: self.max_characters],
            truncated=truncated,
            warnings=result_warnings,
        )

    def _extract_pdf(self, source: Path) -> ExtractionResult:
        from pypdf import PdfReader

        try:
            reader = PdfReader(source)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported")
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("Malformed PDF") from error
        text = "\n\n".join(page for page in pages if page)
        warnings = [] if text else ["PDF contains no extractable text; OCR is required"]
        return self._bounded(text, warnings)

    def _extract_image(self, source: Path) -> ExtractionResult:
        from PIL import Image

        try:
            with Image.open(source) as opened:
                opened.seek(0)
                image = opened.convert("RGB")
                image.load()
        except Exception as error:
            raise ValueError("Malformed image") from error
        if self.ocr is None:
            return self._bounded("", ["OCR unavailable"])
        try:
            return self._bounded(str(self.ocr(image)).strip())
        except Exception as error:
            raise ValueError("Image OCR failed") from error

    def _extract_rtf(self, source: Path) -> ExtractionResult:
        raw = source.read_text(encoding="utf-8")
        text = re.sub(r"\\'[0-9a-fA-F]{2}", "", raw)
        text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
        text = text.replace("{", "").replace("}", "").strip()
        return self._bounded(text)

    def _extract_docx(self, source: Path) -> ExtractionResult:
        from docx import Document

        document = Document(source)
        sections = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            sections.extend(
                " | ".join(cell.text.strip() for cell in row.cells)
                for row in table.rows
            )
        text = "\n".join(sections)
        truncated = len(text) > self.max_characters
        return ExtractionResult(
            text=text[: self.max_characters],
            truncated=truncated,
            warnings=["Extracted text was truncated"] if truncated else [],
        )
