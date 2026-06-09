"""
sheets_logger.py — Google Sheets integration for SmartStack.

Responsibilities:
- Authenticate with Google Sheets via OAuth2 (with token refresh).
- Open (or create) the SmartStack Log spreadsheet.
- Append one row per processed file — never overwrite existing data.
- Expose a function to read all logged rows for the query engine.
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

# Cache the spreadsheet ID in memory across calls within the same session
_cached_spreadsheet_id: Optional[str] = None


def _get_sheets_service() -> Resource:
    """
    Authenticate and return an authorised Google Sheets API service object.

    Token is cached to disk and refreshed automatically when expired.
    On first run the user is directed to a browser-based OAuth consent screen.

    Returns:
        An authorised ``googleapiclient.discovery.Resource`` for Sheets v4.
    """
    creds: Optional[Credentials] = None

    if os.path.exists(SHEETS_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(
            SHEETS_TOKEN_PATH, SHEETS_SCOPES
        )
        logger.debug("Loaded Sheets credentials from token cache.")

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

        os.makedirs(os.path.dirname(SHEETS_TOKEN_PATH), exist_ok=True)
        with open(SHEETS_TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())
        logger.info("Sheets credentials saved to %s", SHEETS_TOKEN_PATH)

    service: Resource = build("sheets", "v4", credentials=creds)
    return service


def _get_or_create_spreadsheet(service: Resource) -> str:
    """
    Return the spreadsheet ID of the SmartStack Log, creating it if absent.

    The function first searches Drive for an existing spreadsheet with the
    configured ``SHEET_NAME``.  If found, its ID is returned.  Otherwise a
    new spreadsheet is created with a header row.

    Args:
        service: Authorised Sheets API service.

    Returns:
        Spreadsheet ID string.
    """
    global _cached_spreadsheet_id
    if _cached_spreadsheet_id:
        return _cached_spreadsheet_id

    # Use the Drive service to search for the spreadsheet by name
    from googleapiclient.discovery import build as _build
    from google.oauth2.credentials import Credentials as _Creds

    # Re-use sheets credentials but via Drive API to search
    drive_creds = Credentials.from_authorized_user_file(
        SHEETS_TOKEN_PATH, SHEETS_SCOPES
    )
    drive_svc = _build("drive", "v3", credentials=drive_creds)

    query = (
        f"name = '{SHEET_NAME}' "
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
        logger.info("Found existing spreadsheet '%s' (id=%s).", SHEET_NAME, spreadsheet_id)
        _cached_spreadsheet_id = spreadsheet_id
        return spreadsheet_id

    # Create a new spreadsheet
    spreadsheet_body = {
        "properties": {"title": SHEET_NAME},
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
    logger.info(
        "Created new spreadsheet '%s' (id=%s).", SHEET_NAME, spreadsheet_id
    )
    _cached_spreadsheet_id = spreadsheet_id
    return spreadsheet_id


def log_processed_file(
    filename: str,
    category: str,
    topic: str,
    summary: str,
) -> None:
    """
    Append a single row to the SmartStack Log spreadsheet.

    The row includes the filename, Claude's classification, topic, summary,
    and a UTC timestamp.  Existing rows are never modified.

    Args:
        filename: Original PDF filename.
        category: Claude-assigned category (Study / College Admin / Personal/Fun).
        topic:    One-line topic returned by Claude.
        summary:  Three-line summary returned by Claude.
    """
    service = _get_sheets_service()
    spreadsheet_id = _get_or_create_spreadsheet(service)

    date_processed = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    row_values = [filename, category, topic, summary, date_processed]

    body = {"values": [row_values]}

    try:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="Log!A:E",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()
        logger.info("Logged '%s' to sheet.", filename)
    except HttpError as exc:
        logger.error("Failed to log '%s' to sheet: %s", filename, exc)
        raise


def fetch_all_logs() -> list[dict]:
    """
    Return all logged rows from the SmartStack Log spreadsheet as a list of
    dicts keyed by column name.

    The header row is used as keys; it is not included in the returned list.
    Returns an empty list if the sheet exists but has no data rows.

    Returns:
        List of dicts, each representing one processed file.
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
        # Pad short rows in case trailing empty cells were omitted by the API
        padded = row + [""] * (len(header) - len(row))
        logs.append(dict(zip(header, padded)))

    logger.info("Fetched %d log entries from sheet.", len(logs))
    return logs


def update_row_category(filename: str, new_category: str) -> bool:
    """
    Find the row for *filename* in the Sheet and update its Category column.

    Scans column A (Filename) for a matching entry and overwrites column B
    (Category) with *new_category*.  Only the first matching row is updated.

    Args:
        filename:     Filename to search for in column A.
        new_category: New category value to write into column B.

    Returns:
        ``True`` if a matching row was found and updated, ``False`` otherwise.

    Raises:
        HttpError: Propagated from the Sheets API.
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
            row_index = i + 1  # Sheets API uses 1-based row numbers
            break

    if row_index is None:
        logger.warning("'%s' not found in sheet — cannot update category.", filename)
        return False

    # Column B is the Category column (index 2 in A1 notation)
    cell_range = f"Log!B{row_index}"
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=cell_range,
        valueInputOption="RAW",
        body={"values": [[new_category]]},
    ).execute()

    logger.info("Updated category for '%s' → '%s' in sheet.", filename, new_category)
    return True
