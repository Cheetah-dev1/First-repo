"""
query_engine.py — Natural-language Q&A against logged document summaries.

Fetches all rows from the SmartStack Log spreadsheet, constructs a context
block, and asks Gemini to answer the user's question based solely on that
context.
"""

import logging
import time
from typing import Optional

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    MAX_TOKENS,
    RETRY_COUNT,
)
from sheets_logger import fetch_all_logs

logger = logging.getLogger(__name__)

_NO_DATA_RESPONSE = (
    "No study material has been logged yet. "
    "Please go to the 'Organise My Drive' page, scan your Drive, and process "
    "some PDFs before asking questions."
)

_SYSTEM_PROMPT = """\
You are a helpful study assistant. The user has processed several documents
and you have been given summaries of each one. Answer the user's question
based ONLY on the summaries provided. If the answer cannot be found in the
summaries, say so clearly and politely — do not invent information.
Keep your answer concise, helpful, and well-structured.
"""


def answer_question(question: str) -> str:
    """
    Answer *question* using document summaries stored in the Google Sheet.

    The function:
    1. Fetches all logged summaries from the sheet.
    2. Constructs a context block from those summaries.
    3. Sends the context + question to Gemini.
    4. Returns Gemini's answer as a plain string.

    Retries up to ``RETRY_COUNT`` times on transient API failures.

    Args:
        question: The user's natural-language question.

    Returns:
        Gemini's answer string, or a friendly "no data" message if the
        sheet is empty.

    Raises:
        RuntimeError: When all retry attempts are exhausted.
    """
    logs = fetch_all_logs()

    if not logs:
        logger.info("No logs in sheet — returning no-data message.")
        return _NO_DATA_RESPONSE

    context = _build_context(logs)
    logger.info(
        "Sending question to Gemini with context from %d document(s).", len(logs)
    )

    user_message = (
        f"Here are summaries of all processed documents:\n\n"
        f"{context}\n\n"
        f"---\n\n"
        f"My question: {question}"
    )

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=_SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            max_output_tokens=MAX_TOKENS,
        ),
    )

    last_error: Optional[Exception] = None

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            response = model.generate_content(user_message)
            answer: str = response.text.strip()
            logger.info("Received answer (%d chars).", len(answer))
            return answer

        except (
            google_exceptions.ServiceUnavailable,
            google_exceptions.InternalServerError,
            google_exceptions.ResourceExhausted,
            google_exceptions.GoogleAPIError,
        ) as exc:
            last_error = exc
            wait = 2 ** attempt
            logger.warning(
                "API error on attempt %d: %s — retrying in %ds.", attempt, exc, wait
            )
            if attempt < RETRY_COUNT:
                time.sleep(wait)

    raise RuntimeError(
        f"Query engine failed after {RETRY_COUNT} attempts. "
        f"Last error: {last_error}"
    )


def _build_context(logs: list[dict]) -> str:
    """
    Format a list of log dicts into a numbered context block for Gemini.

    Args:
        logs: List of dicts from ``fetch_all_logs()``, each containing
              at minimum ``Filename``, ``Category``, ``Topic``, ``Summary``.

    Returns:
        A formatted multi-line string ready for inclusion in a Gemini prompt.
    """
    sections: list[str] = []
    for i, entry in enumerate(logs, start=1):
        section = (
            f"[Document {i}]\n"
            f"Filename : {entry.get('Filename', 'Unknown')}\n"
            f"Category : {entry.get('Category', 'Unknown')}\n"
            f"Topic    : {entry.get('Topic', 'Unknown')}\n"
            f"Summary  :\n{entry.get('Summary', 'No summary available.')}\n"
        )
        sections.append(section)
    return "\n".join(sections)
