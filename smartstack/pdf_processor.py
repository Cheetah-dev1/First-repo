"""
pdf_processor.py — Multi-format file text extraction for SmartStack.

Supports: PDF, DOCX, DOC, XLSX, XLS, PPTX, PPT, and images (JPG/PNG/etc).
Falls back to a friendly message for unreadable or unsupported files.
"""

import io
import logging
import os

import pdfplumber
import pandas as pd
from PIL import Image

from config import MAX_WORDS

logger = logging.getLogger(__name__)

_UNREADABLE = (
    "[This file appears to be unreadable or image-based and could not be "
    "extracted automatically. Convert it to a text-selectable format and try again.]"
)
_NO_TEXT = "[No readable text could be extracted from this file.]"


def extract_text_from_bytes(file_bytes: bytes, filename: str = "unknown") -> str:
    """
    Extract and return plain text from a file supplied as raw bytes.

    Dispatches to a format-specific extractor based on the file extension.
    Text is truncated to ``MAX_WORDS`` words. Returns a friendly placeholder
    when the file is unreadable rather than raising an exception.

    Supported formats:
        PDF, DOCX, DOC, XLSX, XLS, PPTX, PPT,
        JPG, JPEG, PNG, BMP, TIFF, GIF, WEBP

    Args:
        file_bytes: Raw bytes of the file.
        filename:   Original filename including extension.

    Returns:
        Extracted text (possibly truncated) or a friendly error placeholder.
    """
    ext = os.path.splitext(filename)[1].lower()
    logger.info("Extracting text from '%s' (ext=%s, %d bytes).", filename, ext, len(file_bytes))

    try:
        if ext == ".pdf":
            return _extract_pdf(file_bytes, filename)
        elif ext in (".docx", ".doc"):
            return _extract_docx(file_bytes, filename)
        elif ext in (".xlsx", ".xls"):
            return _extract_xlsx(file_bytes, filename)
        elif ext in (".pptx", ".ppt"):
            return _extract_pptx(file_bytes, filename)
        elif ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif", ".webp"):
            return _extract_image(file_bytes, filename)
        else:
            logger.warning("Unsupported extension '%s' for '%s'.", ext, filename)
            return f"[Unsupported file type: {ext}]"
    except Exception as exc:  # noqa: BLE001
        logger.error("Extraction failed for '%s': %s", filename, exc)
        return _UNREADABLE


def _extract_pdf(file_bytes: bytes, filename: str) -> str:
    """Extract text from a PDF using pdfplumber."""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        pages_text: list[str] = []
        for page_num, page in enumerate(pdf.pages, start=1):
            try:
                pages_text.append(page.extract_text() or "")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Page %d of '%s' failed: %s", page_num, filename, exc)
                pages_text.append("")

    full_text = "\n".join(pages_text).strip()
    if not full_text:
        logger.warning("'%s' yielded no text (likely scanned).", filename)
        return _UNREADABLE
    return _truncate_to_words(full_text, MAX_WORDS)


def _extract_docx(file_bytes: bytes, filename: str) -> str:
    """Extract text from a Word document (.docx / .doc)."""
    import docx  # python-docx
    doc = docx.Document(io.BytesIO(file_bytes))
    parts: list[str] = []

    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())

    # Also pull text from tables
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                parts.append(row_text)

    full_text = "\n".join(parts)
    if not full_text.strip():
        return _NO_TEXT
    return _truncate_to_words(full_text, MAX_WORDS)


def _extract_xlsx(file_bytes: bytes, filename: str) -> str:
    """Extract text from an Excel spreadsheet (.xlsx / .xls)."""
    engine = "openpyxl" if filename.lower().endswith(".xlsx") else "xlrd"
    try:
        sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, engine=engine)
    except Exception:
        # Fallback: try openpyxl regardless
        sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, engine="openpyxl")

    parts: list[str] = []
    for sheet_name, df in sheets.items():
        parts.append(f"Sheet: {sheet_name}")
        # Convert each row to readable text
        for _, row in df.iterrows():
            row_text = " | ".join(str(v) for v in row.values if pd.notna(v) and str(v).strip())
            if row_text:
                parts.append(row_text)

    full_text = "\n".join(parts)
    if not full_text.strip():
        return _NO_TEXT
    return _truncate_to_words(full_text, MAX_WORDS)


def _extract_pptx(file_bytes: bytes, filename: str) -> str:
    """Extract text from a PowerPoint presentation (.pptx / .ppt)."""
    from pptx import Presentation  # python-pptx

    prs = Presentation(io.BytesIO(file_bytes))
    parts: list[str] = []

    for slide_num, slide in enumerate(prs.slides, start=1):
        slide_texts: list[str] = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                slide_texts.append(shape.text.strip())
        if slide_texts:
            parts.append(f"[Slide {slide_num}]")
            parts.extend(slide_texts)

    full_text = "\n".join(parts)
    if not full_text.strip():
        return _NO_TEXT
    return _truncate_to_words(full_text, MAX_WORDS)


def _extract_image(file_bytes: bytes, filename: str) -> str:
    """
    Extract text from an image using Tesseract OCR via pytesseract.

    Falls back gracefully if Tesseract is not installed on the system.
    """
    try:
        import pytesseract
        image = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(image).strip()
        if text:
            logger.info("OCR extracted %d chars from '%s'.", len(text), filename)
            return _truncate_to_words(text, MAX_WORDS)
        return _NO_TEXT
    except ImportError:
        logger.warning("pytesseract not installed — returning image placeholder.")
        return (
            "[Image file detected. Install Tesseract OCR and pytesseract "
            "to extract text from images automatically.]"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR failed for '%s': %s", filename, exc)
        return _NO_TEXT


def _truncate_to_words(text: str, max_words: int) -> str:
    """Return *text* truncated to at most *max_words* words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])
