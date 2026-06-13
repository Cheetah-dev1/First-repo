"""
pdf_processor.py — Multi-format file text extraction for SmartStack.

Supports: PDF, DOCX, DOC, XLSX, XLS, PPTX, PPT, and images (JPG/PNG/etc).
Falls back to a friendly message for unreadable or unsupported files.
"""

import io
import logging
import os
import base64

import litellm
litellm.set_verbose = False

import pdfplumber
import pandas as pd
from PIL import Image

from config import MAX_WORDS
from settings_manager import load_settings, get_vision_model_kwargs, track_tokens, save_settings

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
    settings = load_settings()
    max_pages = settings["processing"]["max_pages"]
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        pages = pdf.pages[:max_pages]
        pages_text: list[str] = []
        for page_num, page in enumerate(pages, start=1):
            try:
                pages_text.append(page.extract_text() or "")
            except Exception as exc:
                logger.warning("Page %d of '%s' failed: %s", page_num, filename, exc)
                pages_text.append("")
    full_text = "\n".join(pages_text).strip()
    if not full_text:
        logger.info("'%s' yielded no text — attempting vision OCR.", filename)
        return _extract_scanned_pdf(file_bytes, filename)
    return _truncate_to_words(full_text, MAX_WORDS)


def _extract_scanned_pdf(file_bytes: bytes, filename: str) -> str:
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF not installed — cannot OCR '%s'.", filename)
        return _UNREADABLE

    settings = load_settings()
    model_kwargs = get_vision_model_kwargs(settings)
    max_pages = min(settings["processing"]["max_pages"], len(fitz.open(stream=file_bytes, filetype="pdf")))

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    num_pages = min(len(doc), max_pages, 5)  # cap at 5 for API cost sanity
    parts: list[str] = []

    for i in range(num_pages):
        page = doc[i]
        pix = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72))
        img_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
        try:
            response = litellm.completion(
                **model_kwargs,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        {"type": "text",
                         "text": (
                             f"This is page {i + 1} of a scanned document called '{filename}'. "
                             "Transcribe every piece of visible text exactly. "
                             "If it's a form or table, describe all fields and values."
                         )},
                    ],
                }],
            )
            page_text = response.choices[0].message.content.strip()
            if hasattr(response, "usage") and response.usage:
                settings = track_tokens(settings, response.usage.total_tokens or 0)
                save_settings(settings)
            if page_text:
                parts.append(f"[Page {i + 1}]\n{page_text}")
        except Exception as exc:
            logger.warning("Vision OCR failed page %d of '%s': %s", i + 1, filename, exc)

    doc.close()
    if not parts:
        return _UNREADABLE
    return _truncate_to_words("\n\n".join(parts), MAX_WORDS)


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
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".bmp", ".tiff", ".tif"):
        img = Image.open(io.BytesIO(file_bytes))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        file_bytes = buf.getvalue()
        media_type = "image/png"
    elif ext in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    elif ext == ".webp":
        media_type = "image/webp"
    elif ext == ".gif":
        media_type = "image/gif"
    else:
        media_type = "image/png"

    image_b64 = base64.b64encode(file_bytes).decode("utf-8")
    settings = load_settings()
    model_kwargs = get_vision_model_kwargs(settings)

    response = litellm.completion(
        **model_kwargs,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
                {"type": "text",
                 "text": (
                     "Describe this image in detail. "
                     "If it contains text, transcribe it fully. "
                     "If it is a document or form, describe its contents."
                 )},
            ],
        }],
    )
    text = response.choices[0].message.content.strip()
    if hasattr(response, "usage") and response.usage:
        settings = track_tokens(settings, response.usage.total_tokens or 0)
        save_settings(settings)
    logger.info("Vision model described '%s' (%d chars).", filename, len(text))
    return _truncate_to_words(text, MAX_WORDS) if text else _NO_TEXT


def _truncate_to_words(text: str, max_words: int) -> str:
    """Return *text* truncated to at most *max_words* words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])
