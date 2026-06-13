"""
query_engine.py — Natural-language Q&A against logged document summaries.

Fetches all rows from the SmartStack Log spreadsheet, constructs a context
block, and asks the AI to answer the user's question based solely on that context.
"""

import logging
import time
from typing import Optional

import litellm
litellm.set_verbose = False

from config import MAX_TOKENS, RETRY_COUNT
from settings_manager import load_settings, get_text_model_kwargs, track_tokens, save_settings
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
    3. Sends the context + question to the configured AI model.
    4. Returns the answer as a plain string.

    Retries up to ``RETRY_COUNT`` times on transient API failures.

    Args:
        question: The user's natural-language question.

    Returns:
        The answer string, or a friendly "no data" message if the
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
        "Sending question to AI with context from %d document(s).", len(logs)
    )

    user_message = (
        f"Here are summaries of all processed documents:\n\n"
        f"{context}\n\n"
        f"---\n\n"
        f"My question: {question}"
    )

    settings = load_settings()
    model_kwargs = get_text_model_kwargs(settings)
    last_error: Optional[Exception] = None

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            response = litellm.completion(
                **model_kwargs,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
            answer: str = response.choices[0].message.content.strip()
            if hasattr(response, "usage") and response.usage:
                settings = track_tokens(settings, response.usage.total_tokens or 0)
                save_settings(settings)
            logger.info("Received answer (%d chars).", len(answer))
            return answer

        except Exception as exc:
            last_error = exc
            wait = 2 ** attempt
            logger.warning("Attempt %d failed: %s — retrying in %ds.", attempt, exc, wait)
            if attempt < RETRY_COUNT:
                time.sleep(wait)

    raise RuntimeError(
        f"Query engine failed after {RETRY_COUNT} attempts. "
        f"Last error: {last_error}"
    )


def _build_context(logs: list[dict]) -> str:
    """
    Format a list of log dicts into a numbered context block for the AI.

    Args:
        logs: List of dicts from ``fetch_all_logs()``, each containing
              at minimum ``Filename``, ``Category``, ``Topic``, ``Summary``.

    Returns:
        A formatted multi-line string ready for inclusion in a prompt.
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
