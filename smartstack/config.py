"""
config.py — Central configuration for SmartStack.

Loads all environment variables via python-dotenv and exposes
typed constants consumed by every other module.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Google OAuth scopes
# ---------------------------------------------------------------------------
DRIVE_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/drive",
]
SHEETS_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# ---------------------------------------------------------------------------
# Credential paths
# ---------------------------------------------------------------------------
CREDENTIALS_DIR: str = os.path.join(os.path.dirname(__file__), "credentials")
DRIVE_TOKEN_PATH: str = os.path.join(CREDENTIALS_DIR, "drive_token.json")
SHEETS_TOKEN_PATH: str = os.path.join(CREDENTIALS_DIR, "sheets_token.json")
OAUTH_CLIENT_SECRET_PATH: str = os.path.join(
    CREDENTIALS_DIR,
    os.getenv("OAUTH_CLIENT_SECRET_FILE", "client_secret.json"),
)

# ---------------------------------------------------------------------------
# Gemini API
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "1024"))
RETRY_COUNT: int = int(os.getenv("RETRY_COUNT", "3"))

# ---------------------------------------------------------------------------
# Google Drive folder names
# ---------------------------------------------------------------------------
FOLDER_STUDY: str = os.getenv("FOLDER_STUDY", "Study")
FOLDER_COLLEGE_ADMIN: str = os.getenv("FOLDER_COLLEGE_ADMIN", "College Admin")
FOLDER_PERSONAL_FUN: str = os.getenv("FOLDER_PERSONAL_FUN", "Personal/Fun")

CATEGORY_FOLDERS: dict[str, str] = {
    "Study": FOLDER_STUDY,
    "College Admin": FOLDER_COLLEGE_ADMIN,
    "Personal/Fun": FOLDER_PERSONAL_FUN,
}

# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------
SHEET_NAME: str = os.getenv("SHEET_NAME", "SmartStack Log")
SHEET_COLUMNS: list[str] = [
    "Filename",
    "Category",
    "Topic",
    "Summary",
    "Date Processed",
]

# ---------------------------------------------------------------------------
# PDF processing
# ---------------------------------------------------------------------------
MAX_WORDS: int = int(os.getenv("MAX_WORDS", "3000"))


def validate_config() -> None:
    """Raise ValueError if mandatory environment variables are missing."""
    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is not set. "
            "Add it to your .env file — get a free key at "
            "https://aistudio.google.com/apikey"
        )
    if not os.path.isfile(OAUTH_CLIENT_SECRET_PATH):
        raise ValueError(
            f"OAuth client secret not found at: {OAUTH_CLIENT_SECRET_PATH}\n"
            "Download it from Google Cloud Console and place it in the "
            "'credentials/' directory."
        )
    logger.info("Configuration validated successfully.")
