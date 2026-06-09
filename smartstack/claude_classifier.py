"""
claude_classifier.py — Groq-powered PDF classification for SmartStack.

Sends extracted PDF text to the Groq API and parses a structured JSON
response containing the document category, topic, and a short summary.
Includes retry logic for transient API failures.
"""

import json
import logging
import time
from typing import Optional

from groq import Groq, APIError, APIConnectionError, RateLimitError

from config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    MAX_TOKENS,
    RETRY_COUNT,
)

logger = logging.getLogger(__name__)

_EXPECTED_KEYS = {"category", "topic", "summary"}
_VALID_CATEGORIES = {"Study", "College Admin", "Personal/Fun"}

_SYSTEM_PROMPT = """\
You are a document classifier. The user will provide extracted text from a PDF.
Your task is to classify the document and return ONLY valid JSON — no prose,
no markdown fences, no explanation — in exactly this shape:

{
  "category": "Study | College Admin | Personal/Fun",
  "topic": "one-line topic (max 15 words)",
  "summary": "three-line summary separated by newlines"
}

Rules:
- "category" MUST be exactly one of: Study, College Admin, Personal/Fun
- "topic" must be a single line, 15 words or fewer
- "summary" must be exactly three lines separated by \\n
- Return ONLY the JSON object, nothing else
"""


def classify_document(
    text: str,
    filename: str = "unknown.pdf",
) -> dict:
    """
    Classify a document using Groq and return structured metadata.

    Sends *text* to the configured Groq model and parses the JSON response.
    Retries up to ``RETRY_COUNT`` times on transient failures using
    exponential back-off (2 s, 4 s, 8 s …).

    Args:
        text:     Extracted text from the PDF (pre-truncated to token budget).
        filename: Original filename — used only for logging.

    Returns:
        Dict with keys ``category``, ``topic``, and ``summary``.

    Raises:
        RuntimeError: When all retry attempts are exhausted.
    """
    client = Groq(api_key=GROQ_API_KEY)

    user_message = (
        f"Please classify the following document extracted from '{filename}':\n\n"
        f"{text}"
    )

    last_error: Optional[Exception] = None

    for attempt in range(1, RETRY_COUNT + 1):
        logger.info(
            "Classifying '%s' — attempt %d/%d.", filename, attempt, RETRY_COUNT
        )
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
            raw_content = response.choices[0].message.content.strip()
            logger.debug("Raw Groq response for '%s': %s", filename, raw_content)

            parsed = _parse_and_validate(raw_content, filename)
            logger.info("Classified '%s' as '%s'.", filename, parsed["category"])
            return parsed

        except RateLimitError as exc:
            last_error = exc
            wait = 2 ** attempt
            logger.warning(
                "Rate limit on attempt %d for '%s' — retrying in %ds.", attempt, filename, wait
            )
            if attempt < RETRY_COUNT:
                time.sleep(wait)

        except (APIError, APIConnectionError) as exc:
            last_error = exc
            wait = 2 ** attempt
            logger.warning(
                "API error on attempt %d for '%s': %s — retrying in %ds.",
                attempt, filename, exc, wait,
            )
            if attempt < RETRY_COUNT:
                time.sleep(wait)

        except ValueError as val_exc:
            last_error = val_exc
            wait = 2 ** attempt
            logger.warning(
                "JSON validation failed on attempt %d for '%s': %s — retrying in %ds.",
                attempt, filename, val_exc, wait,
            )
            if attempt < RETRY_COUNT:
                time.sleep(wait)

    raise RuntimeError(
        f"Classification failed for '{filename}' after {RETRY_COUNT} attempts. "
        f"Last error: {last_error}"
    )


def _parse_and_validate(raw: str, filename: str) -> dict:
    """
    Parse *raw* as JSON and validate it matches the expected schema.

    Args:
        raw:      Raw string returned by Groq.
        filename: Used in error messages for context.

    Returns:
        Validated dict with keys ``category``, ``topic``, ``summary``.

    Raises:
        ValueError: If JSON is malformed or the schema is incorrect.
    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        inner = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(inner).strip()

    try:
        data: dict = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Groq returned invalid JSON for '{filename}': {exc}\nRaw: {cleaned!r}"
        ) from exc

    missing = _EXPECTED_KEYS - data.keys()
    if missing:
        raise ValueError(
            f"Groq response missing keys {missing} for '{filename}'. "
            f"Got: {list(data.keys())}"
        )

    category = data.get("category", "")
    if category not in _VALID_CATEGORIES:
        fixed = _normalise_category(category)
        if fixed:
            logger.warning(
                "Normalised category '%s' → '%s' for '%s'.", category, fixed, filename
            )
            data["category"] = fixed
        else:
            raise ValueError(
                f"Invalid category '{category}' for '{filename}'. "
                f"Expected one of: {_VALID_CATEGORIES}"
            )

    return {
        "category": data["category"],
        "topic": str(data["topic"]).strip(),
        "summary": str(data["summary"]).strip(),
    }


def _normalise_category(raw_category: str) -> Optional[str]:
    """
    Attempt to map a non-standard category string to one of the valid values.

    Args:
        raw_category: Category string returned by Groq.

    Returns:
        A valid category string, or ``None`` if no mapping is found.
    """
    mapping = {
        "study": "Study",
        "studies": "Study",
        "academic": "Study",
        "college admin": "College Admin",
        "college administration": "College Admin",
        "admin": "College Admin",
        "administration": "College Admin",
        "personal": "Personal/Fun",
        "fun": "Personal/Fun",
        "personal/fun": "Personal/Fun",
        "personal fun": "Personal/Fun",
        "leisure": "Personal/Fun",
    }
    return mapping.get(raw_category.lower().strip())
