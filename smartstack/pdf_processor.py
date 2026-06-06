"""
pdf_processor.py — PDF text extraction for SmartStack.

Uses pdfplumber to extract readable text from PDF bytes.
Scanned / image-only PDFs are detected and a friendly message is returned
rather than crashing the pipeline.
"""

import io
import logging

import pdfplumber

from config import MAX_WORDS

logger = logging.getLogger(__name__)

_UNREADABLE_PLACEHOLDER = (
    "[This PDF appears to be scanned or image-based and could not be read "
    "automatically. Please convert it to a text-selectable PDF and try again.]"
)


def extract_text_from_bytes(pdf_bytes: bytes, filename: str = "unknown.pdf") -> str:
    """
    Extract and return plain text from a PDF supplied as raw bytes.

    Text is truncated to the first ``MAX_WORDS`` words so that it fits within
    the Claude API token budget.  If the PDF is scanned/image-based (no
    extractable text on any page), a human-friendly placeholder string is
    returned instead of raising an exception.

    Args:
        pdf_bytes: Raw bytes of the PDF file.
        filename:  Original filename — used only for log messages.

    Returns:
        Extracted text (possibly truncated) or a friendly error placeholder.
    """
    logger.info("Extracting text from '%s' (%d bytes).", filename, len(pdf_bytes))

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text: list[str] = []
            for page_num, page in enumerate(pdf.pages, start=1):
                try:
                    page_text = page.extract_text() or ""
                    pages_text.append(page_text)
                    logger.debug(
                        "Page %d: extracted %d chars.", page_num, len(page_text)
                    )
                except Exception as page_exc:  # noqa: BLE001
                    logger.warning(
                        "Could not extract text from page %d of '%s': %s",
                        page_num,
                        filename,
                        page_exc,
                    )
                    pages_text.append("")

            full_text = "\n".join(pages_text).strip()

    except Exception as exc:  # noqa: BLE001
        logger.error("pdfplumber failed to open '%s': %s", filename, exc)
        return _UNREADABLE_PLACEHOLDER

    if not full_text:
        logger.warning("'%s' yielded no extractable text (likely scanned).", filename)
        return _UNREADABLE_PLACEHOLDER

    truncated = _truncate_to_words(full_text, MAX_WORDS)
    logger.info(
        "'%s' — extracted %d words (truncated to %d).",
        filename,
        len(full_text.split()),
        len(truncated.split()),
    )
    return truncated


def _truncate_to_words(text: str, max_words: int) -> str:
    """
    Return *text* truncated to at most *max_words* words.

    Args:
        text:      The source string.
        max_words: Maximum number of whitespace-separated tokens to keep.

    Returns:
        Truncated string.  The original string is returned unchanged when it
        contains fewer than *max_words* words.
    """
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])
