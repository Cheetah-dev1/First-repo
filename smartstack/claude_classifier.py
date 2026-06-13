"""
claude_classifier.py — LiteLLM-powered document classification for SmartStack.
"""

import json
import logging
import os
import time
from typing import Optional

import litellm
litellm.set_verbose = False  # suppress LiteLLM's own logging

from config import MAX_TOKENS, RETRY_COUNT
from settings_manager import (
    load_settings,
    get_text_model_kwargs,
    track_tokens,
    save_settings,
)

logger = logging.getLogger(__name__)

_EXPECTED_KEYS = {"category", "topic", "summary"}
_VALID_CATEGORIES = {"Study", "College Admin", "Personal/Fun", "Miscellaneous"}

_BASE_SYSTEM_PROMPT = """\
You are a document classifier. The user will provide extracted text from a file.
Your task is to classify the document and return ONLY valid JSON — no prose,
no markdown fences, no explanation — in exactly this shape:

{
  "category": "Study | College Admin | Personal/Fun | Miscellaneous",
  "topic": "one-line topic (max 15 words)",
  "summary": "three-line summary separated by newlines"
}

Rules:
- "category" MUST be exactly one of: Study, College Admin, Personal/Fun, Miscellaneous
- Use Miscellaneous for signatures, photos, ID scans, forms with no clear academic or admin purpose
- "topic" must be a single line, 15 words or fewer
- "summary" must be exactly three lines separated by \\n
- Return ONLY the JSON object, nothing else
"""


def _build_system_prompt() -> str:
    try:
        directives = load_settings().get("directives", "").strip()
        if directives:
            return (
                _BASE_SYSTEM_PROMPT
                + "\nAdditional rules set by the user — follow these closely:\n"
                + directives + "\n"
            )
    except Exception:
        pass
    return _BASE_SYSTEM_PROMPT


def classify_document(text: str, filename: str = "unknown") -> dict:
    settings = load_settings()
    model_kwargs = get_text_model_kwargs(settings)
    user_message = (
        f"Please classify the following document extracted from '{filename}':\n\n{text}"
    )
    system_prompt = _build_system_prompt()
    last_error: Optional[Exception] = None

    for attempt in range(1, RETRY_COUNT + 1):
        logger.info("Classifying '%s' — attempt %d/%d.", filename, attempt, RETRY_COUNT)
        try:
            response = litellm.completion(
                **model_kwargs,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )
            raw = response.choices[0].message.content.strip()
            if hasattr(response, "usage") and response.usage:
                settings = track_tokens(settings, response.usage.total_tokens or 0)
                save_settings(settings)
            parsed = _parse_and_validate(raw, filename)
            logger.info("Classified '%s' as '%s'.", filename, parsed["category"])
            return parsed

        except Exception as exc:
            last_error = exc
            wait = 2 ** attempt
            logger.warning(
                "Attempt %d for '%s' failed: %s — retrying in %ds.",
                attempt, filename, exc, wait,
            )
            if attempt < RETRY_COUNT:
                time.sleep(wait)

    raise RuntimeError(
        f"Classification failed for '{filename}' after {RETRY_COUNT} attempts. "
        f"Last error: {last_error}"
    )


def suggest_reclassification(filename: str, current_category: str, rules: str) -> Optional[str]:
    settings = load_settings()
    model_kwargs = get_text_model_kwargs(settings)
    prompt = (
        f"The user has defined these classification rules:\n{rules}\n\n"
        f'A file named "{filename}" is currently in "{current_category}".\n'
        "Based on the rules, should it move to a different category?\n"
        "Valid categories: Study, College Admin, Personal/Fun, Miscellaneous\n\n"
        "Return ONLY valid JSON:\n"
        '{"reclassify": true or false, "new_category": "the correct category"}\n\n'
        "Only set reclassify to true if a rule clearly applies AND the category differs."
    )
    try:
        response = litellm.completion(
            **model_kwargs,
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        if hasattr(response, "usage") and response.usage:
            settings = track_tokens(settings, response.usage.total_tokens or 0)
            save_settings(settings)
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(raw[start:end])
            if data.get("reclassify"):
                new_cat = data.get("new_category", "")
                if new_cat in _VALID_CATEGORIES and new_cat != current_category:
                    return new_cat
    except Exception as exc:
        logger.debug("suggest_reclassification failed for '%s': %s", filename, exc)
    return None


def _parse_and_validate(raw: str, filename: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(l for l in lines if not l.strip().startswith("```")).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start != -1 and end > start:
        cleaned = cleaned[start:end]
    try:
        data: dict = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for '{filename}': {exc}\nRaw: {cleaned!r}") from exc

    missing = _EXPECTED_KEYS - data.keys()
    if missing:
        raise ValueError(f"Response missing keys {missing} for '{filename}'.")

    category = data.get("category", "")
    if category not in _VALID_CATEGORIES:
        fixed = _normalise_category(category)
        if fixed:
            logger.warning("Normalised '%s' → '%s' for '%s'.", category, fixed, filename)
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
    mapping = {
        "study": "Study", "studies": "Study", "academic": "Study",
        "college admin": "College Admin", "college administration": "College Admin",
        "admin": "College Admin", "administration": "College Admin",
        "personal": "Personal/Fun", "fun": "Personal/Fun",
        "personal/fun": "Personal/Fun", "personal fun": "Personal/Fun",
        "leisure": "Personal/Fun",
        "miscellaneous": "Miscellaneous", "misc": "Miscellaneous", "other": "Miscellaneous",
    }
    return mapping.get(raw_category.lower().strip())
