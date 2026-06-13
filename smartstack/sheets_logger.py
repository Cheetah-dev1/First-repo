"""
sheets_logger.py — Google Sheets integration for SmartStack.

Responsibilities:
- Authenticate with Google Sheets via OAuth2 (with token refresh).
- Open (or create) the SmartStack Log spreadsheet for the active account.
- Append one row per processed file — never overwrite existing data.
- Expose functions to read and update logged rows.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError

from config import (
    SHEETS_SCOPES,
    SHEETS_TOKEN_PATH,
    OAUTH_CLIENT_SECRET_PATH,
    SHEET_NAME,
    SHEET_COLUMNS,
)

logger = logging.getLogger(__name__)

# Per-account spreadsheet ID cache — keyed by account email (or "default")
_cached_spreadsheet_id: dict[str, str] = {}


def _active_email() -> str:
    """Return the active account email, or 'default' as a fallback key."""
    try:
        from drive_manager import get_active_account_email
        return get_active_account_email() or "default"
    except Exception:
        return "default"


def _active_sheets_token_path() -> str:
    """Return the Sheets token path for the active account."""
    try:
        from drive_manager import get_active_sheets_token_path
        return get_active_sheets_token_path()
    except Exception:
        return SHEETS_TOKEN_PATH


def _get_sheets_service() -> Resource:
    """
    Authenticate and return an authorised Google Sheets API service object
    for the currently active account.
    """
    token_path = _active_sheets_token_path()

    creds: Optional[Credentials] = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SHEETS_SCOPES)
        logger.debug("Loaded Sheets credentials from %s.", token_path)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Sheets token expired — refreshing.")
            creds.refresh(Request())
        else:
            logger.info("Sheets OAuth flow starting — browser window will open.")
            flow = InstalledAppFlow.from_client_secrets_file(
                OAUTH_CLIENT_SECRET_PATH, SHEETS_SCOPES
            )
            creds = flow.run_local_server(port=0)

        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())
        logger.info("Sheets credentials saved to %s.", token_path)

    return build("sheets", "v4", credentials=creds)


def _get_or_create_spreadsheet(service: Resource) -> str:
    """
    Return the spreadsheet ID for the active account's SmartStack Log,
    creating it if it doesn't exist yet.
    """
    global _cached_spreadsheet_id
    key = _active_email()
    if _cached_spreadsheet_id.get(key):
        return _cached_spreadsheet_id[key]

    from drive_manager import get_drive_service
    drive_svc = get_drive_service()

    try:
        from settings_manager import load_settings
        sheet_name = load_settings()["sheets"]["sheet_name"]
    except Exception:
        sheet_name = SHEET_NAME

    query = (
        f"name = '{sheet_name}' "
        f"and mimeType = 'application/vnd.google-apps.spreadsheet' "
        f"and trashed = false"
    )
    results = (
        drive_svc.files()
        .list(q=query, spaces="drive", fields="files(id, name)")
        .execute()
    )
    files = results.get("files", [])

    if files:
        spreadsheet_id: str = files[0]["id"]
        logger.info("Found existing spreadsheet '%s' (id=%s).", sheet_name, spreadsheet_id)
        _cached_spreadsheet_id[key] = spreadsheet_id
        return spreadsheet_id

    spreadsheet_body = {
        "properties": {"title": sheet_name},
        "sheets": [
            {
                "properties": {"title": "Log"},
                "data": [
                    {
                        "startRow": 0,
                        "startColumn": 0,
                        "rowData": [
                            {
                                "values": [
                                    {"userEnteredValue": {"stringValue": col}}
                                    for col in SHEET_COLUMNS
                                ]
                            }
                        ],
                    }
                ],
            }
        ],
    }
    created = (
        service.spreadsheets()
        .create(body=spreadsheet_body, fields="spreadsheetId")
        .execute()
    )
    spreadsheet_id = created["spreadsheetId"]
    logger.info("Created new spreadsheet '%s' (id=%s).", sheet_name, spreadsheet_id)
    _cached_spreadsheet_id[key] = spreadsheet_id
    return spreadsheet_id


def log_processed_file(
    filename: str,
    category: str,
    topic: str,
    summary: str,
) -> None:
    """Append a single row to the active account's SmartStack Log spreadsheet."""
    service = _get_sheets_service()
    spreadsheet_id = _get_or_create_spreadsheet(service)

    date_processed = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    row_values = [filename, category, topic, summary, date_processed]

    try:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="Log!A:E",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row_values]},
        ).execute()
        logger.info("Logged '%s' to sheet.", filename)
    except HttpError as exc:
        logger.error("Failed to log '%s' to sheet: %s", filename, exc)
        raise


def fetch_all_logs() -> list[dict]:
    """
    Return all logged rows from the active account's SmartStack Log as a
    list of dicts keyed by column name.
    """
    service = _get_sheets_service()
    spreadsheet_id = _get_or_create_spreadsheet(service)

    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range="Log!A:E")
            .execute()
        )
    except HttpError as exc:
        logger.error("Failed to read sheet: %s", exc)
        raise

    rows = result.get("values", [])
    if not rows:
        logger.info("Sheet is empty — no logs found.")
        return []

    header = rows[0]
    data_rows = rows[1:]

    logs: list[dict] = []
    for row in data_rows:
        padded = row + [""] * (len(header) - len(row))
        logs.append(dict(zip(header, padded)))

    logger.info("Fetched %d log entries from sheet.", len(logs))
    return logs


def update_row_category(filename: str, new_category: str) -> bool:
    """
    Find the row for *filename* in the Sheet and update its Category column.
    Returns True if updated, False if not found.
    """
    service = _get_sheets_service()
    spreadsheet_id = _get_or_create_spreadsheet(service)

    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="Log!A:A")
        .execute()
    )
    rows = result.get("values", [])

    row_index: Optional[int] = None
    for i, row in enumerate(rows):
        if row and row[0] == filename:
            row_index = i + 1  # Sheets API is 1-based
            break

    if row_index is None:
        logger.warning("'%s' not found in sheet — cannot update category.", filename)
        return False

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"Log!B{row_index}",
        valueInputOption="RAW",
        body={"values": [[new_category]]},
    ).execute()

    logger.info("Updated category for '%s' → '%s' in sheet.", filename, new_category)
    return True
