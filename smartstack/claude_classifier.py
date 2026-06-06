"""
claude_classifier.py — Claude-powered PDF classification for SmartStack.

Sends extracted PDF text to the Claude API and parses a structured JSON
response containing the document category, topic, and a short summary.
Includes retry logic for transient API failures.
"""

import json
import logging
import time
from typing import Optional

import anthropic

from config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    CLAUDE_MAX_TOKENS,
    CLAUDE_RETRY_COUNT,
)

logger = logging.getLogger(__name__)

# The exact JSON shape we expect Claude to return.
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
    Classify a document using Claude and return structured metadata.

    Sends *text* to the configured Claude model and parses the JSON response.
    Retries up to ``CLAUDE_RETRY_COUNT`` times on transient failures, using
    exponential back-off (2 s, 4 s, 8 s …).

    Args:
        text:     Extracted text from the PDF (pre-truncated to token budget).
        filename: Original filename — used only for logging.

    Returns:
        Dict with keys ``category``, ``topic``, and ``summary``.

    Raises:
        RuntimeError: When all retry attempts are exhausted or the API
                      consistently returns malformed JSON.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    user_message = (
        f"Please classify the following document extracted from '{filename}':\n\n"
        f"{text}"
    )

    last_error: Optional[Exception] = None

    for attempt in range(1, CLAUDE_RETRY_COUNT + 1):
        logger.info(
            "Classifying '%s' — attempt %d/%d.", filename, attempt, CLAUDE_RETRY_COUNT
        )
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            raw_content = response.content[0].text.strip()
            logger.debug("Raw Claude response for '%s': %s", filename, raw_content)

            parsed = _parse_and_validate(raw_content, filename)
            logger.info(
                "Classified '%s' as '%s'.", filename, parsed["category"]
            )
            return parsed

        except (anthropic.APIError, anthropic.APIConnectionError) as api_exc:
            last_error = api_exc
            wait = 2 ** attempt  # 2, 4, 8 seconds …
            logger.warning(
                "API error on attempt %d for '%s': %s — retrying in %ds.",
                attempt,
                filename,
                api_exc,
                wait,
            )
            if attempt < CLAUDE_RETRY_COUNT:
                time.sleep(wait)

        except ValueError as val_exc:
            last_error = val_exc
            wait = 2 ** attempt
            logger.warning(
                "JSON validation failed on attempt %d for '%s': %s — retrying in %ds.",
                attempt,
                filename,
                val_exc,
                wait,
            )
            if attempt < CLAUDE_RETRY_COUNT:
                time.sleep(wait)

    raise RuntimeError(
        f"Classification failed for '{filename}' after {CLAUDE_RETRY_COUNT} attempts. "
        f"Last error: {last_error}"
    )


def _parse_and_validate(raw: str, filename: str) -> dict:
    """
    Parse *raw* as JSON and validate it matches the expected schema.

    Args:
        raw:      Raw string returned by Claude.
        filename: Used in error messages for context.

    Returns:
        Validated dict with keys ``category``, ``topic``, ``summary``.

    Raises:
        ValueError: If JSON is malformed or the schema is incorrect.
    """
    # Strip accidental markdown code fences if Claude slips one in
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove first and last fence lines
        inner = [
            l for l in lines if not l.strip().startswith("```")
        ]
        cleaned = "\n".join(inner).strip()

    try:
        data: dict = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Claude returned invalid JSON for '{filename}': {exc}\nRaw: {cleaned!r}"
        ) from exc

    missing = _EXPECTED_KEYS - data.keys()
    if missing:
        raise ValueError(
            f"Claude response missing keys {missing} for '{filename}'. "
            f"Got: {list(data.keys())}"
        )

    category = data.get("category", "")
    if category not in _VALID_CATEGORIES:
        # Attempt a fuzzy fix for common Claude deviations
        fixed = _normalise_category(category)
        if fixed:
            logger.warning(
                "Normalised category '%s' → '%s' for '%s'.",
                category,
                fixed,
                filename,
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
        raw_category: Category string returned by Claude.

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
