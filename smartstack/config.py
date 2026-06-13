"""
config.py — Central configuration for SmartStack.

Loads all environment variables via python-dotenv and exposes
typed constants consumed by every other module.
"""

import os
import logging
from dotenv import load_dotenv

# Explicitly load .env from the same directory as this file so it always
# wins regardless of where streamlit is launched from.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Google OAuth scopes
# ---------------------------------------------------------------------------
DRIVE_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/drive",
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
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
ACCOUNTS_DIR: str = os.path.join(CREDENTIALS_DIR, "accounts")
ACTIVE_ACCOUNT_FILE: str = os.path.join(CREDENTIALS_DIR, "active_account.txt")
DIRECTIVES_PATH: str = os.path.join(os.path.dirname(__file__), "directives.txt")
OAUTH_CLIENT_SECRET_PATH: str = os.path.join(
    CREDENTIALS_DIR,
    os.getenv("OAUTH_CLIENT_SECRET_FILE", "client_secret.json"),
)

# ---------------------------------------------------------------------------
# Groq API
# ---------------------------------------------------------------------------
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "1024"))
RETRY_COUNT: int = int(os.getenv("RETRY_COUNT", "3"))

# ---------------------------------------------------------------------------
# Google Drive folder names
# ---------------------------------------------------------------------------
FOLDER_STUDY: str = os.getenv("FOLDER_STUDY", "Study")
FOLDER_COLLEGE_ADMIN: str = os.getenv("FOLDER_COLLEGE_ADMIN", "College Admin")
FOLDER_PERSONAL_FUN: str = os.getenv("FOLDER_PERSONAL_FUN", "Personal/Fun")
FOLDER_MISCELLANEOUS: str = os.getenv("FOLDER_MISCELLANEOUS", "Miscellaneous")

CATEGORY_FOLDERS: dict[str, str] = {
    "Study": FOLDER_STUDY,
    "College Admin": FOLDER_COLLEGE_ADMIN,
    "Personal/Fun": FOLDER_PERSONAL_FUN,
    "Miscellaneous": FOLDER_MISCELLANEOUS,
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
    if not GROQ_API_KEY:
        raise ValueError(
            "GROQ_API_KEY is not set. "
            "Get a free key at https://console.groq.com"
        )
    if not os.path.isfile(OAUTH_CLIENT_SECRET_PATH):
        raise ValueError(
            f"OAuth client secret not found at: {OAUTH_CLIENT_SECRET_PATH}\n"
            "Download it from Google Cloud Console and place it in the "
            "'credentials/' directory."
        )
    logger.info("Configuration validated successfully.")
