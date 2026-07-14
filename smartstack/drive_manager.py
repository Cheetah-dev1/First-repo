"""
drive_manager.py — Google Drive integration + multi-account management.

Responsibilities:
- Manage multiple Google accounts (add, switch, delete, migrate legacy tokens).
- Authenticate with Google Drive via OAuth2 (with token refresh).
- Scan the Drive root for loose files (PDF, Word, Excel, PowerPoint, images, video).
- Auto-create destination subfolders and move classified files into them.
"""

import logging
import os
import shutil
from typing import Optional

import requests as _requests

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError

from config import (
    DRIVE_SCOPES,
    DRIVE_TOKEN_PATH,
    SHEETS_TOKEN_PATH,
    OAUTH_CLIENT_SECRET_PATH,
    CATEGORY_FOLDERS,
    ACCOUNTS_DIR,
    ACTIVE_ACCOUNT_FILE,
)

logger = logging.getLogger(__name__)

_MIME_FOLDER = "application/vnd.google-apps.folder"

# Google-native formats that require export instead of direct download
GOOGLE_EXPORT_MAP: dict[str, dict] = {
    "application/vnd.google-apps.document": {
        "export_mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "extension": ".docx",
    },
    "application/vnd.google-apps.spreadsheet": {
        "export_mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "extension": ".xlsx",
    },
    "application/vnd.google-apps.presentation": {
        "export_mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "extension": ".pptx",
    },
}

_SUPPORTED_MIME_TYPES: list[str] = [
    # Google native
    "application/vnd.google-apps.document",      # Google Docs
    "application/vnd.google-apps.spreadsheet",   # Google Sheets
    "application/vnd.google-apps.presentation",  # Google Slides
    # Office formats
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "application/msword",                                                         # doc
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",         # xlsx
    "application/vnd.ms-excel",                                                   # xls
    "application/vnd.openxmlformats-officedocument.presentationml.presentation", # pptx
    "application/vnd.ms-powerpoint",                                              # ppt
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/webp",
    "video/mp4",
    "video/x-msvideo",   # avi
    "video/quicktime",   # mov
    "video/x-matroska",  # mkv
    "video/x-ms-wmv",   # wmv
    "video/webm",
    "video/x-flv",
]


# ===========================================================================
# Account management
# ===========================================================================

def get_active_account_email() -> Optional[str]:
    """Return the email of the currently active account, or None."""
    if os.path.exists(ACTIVE_ACCOUNT_FILE):
        email = open(ACTIVE_ACCOUNT_FILE).read().strip()
        return email or None
    return None


def set_active_account(email: Optional[str]) -> None:
    """Set the active account email. Pass None to clear."""
    os.makedirs(os.path.dirname(ACTIVE_ACCOUNT_FILE), exist_ok=True)
    with open(ACTIVE_ACCOUNT_FILE, "w") as f:
        f.write(email or "")
    logger.info("Active account set to: %s", email)


def _account_dir(email: str) -> str:
    return os.path.join(ACCOUNTS_DIR, email)


def _drive_token_path(email: str) -> str:
    return os.path.join(_account_dir(email), "drive_token.json")


def _sheets_token_path(email: str) -> str:
    return os.path.join(_account_dir(email), "sheets_token.json")


def get_active_sheets_token_path() -> str:
    """Return the Sheets token path for the active account (or legacy fallback)."""
    email = get_active_account_email()
    return _sheets_token_path(email) if email else SHEETS_TOKEN_PATH


def get_all_account_emails() -> list[str]:
    """Return sorted list of emails for all locally stored accounts."""
    if not os.path.isdir(ACCOUNTS_DIR):
        return []
    return sorted(
        e for e in os.listdir(ACCOUNTS_DIR)
        if os.path.isfile(_drive_token_path(e))
    )


def add_new_account() -> str:
    """
    Run an OAuth consent flow for a new Google account, store its token,
    and return the new account's email.
    """
    logger.info("Starting OAuth flow for a new account.")
    flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CLIENT_SECRET_PATH, DRIVE_SCOPES)
    creds = flow.run_local_server(port=0)

    resp = _requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=5,
    )
    resp.raise_for_status()
    email: str = resp.json()["email"]

    os.makedirs(_account_dir(email), exist_ok=True)
    with open(_drive_token_path(email), "w") as f:
        f.write(creds.to_json())
    logger.info("Stored credentials for new account: %s", email)
    return email


def delete_account(email: str) -> None:
    """Remove all locally stored credentials for *email*."""
    account_dir = _account_dir(email)
    if os.path.isdir(account_dir):
        shutil.rmtree(account_dir)
        logger.info("Removed credentials for %s.", email)
    if get_active_account_email() == email:
        set_active_account(None)


def _try_migrate_legacy_tokens() -> None:
    """
    If pre-multi-account flat token files exist, migrate them into the
    accounts/ directory structure. Runs at most once and fails gracefully.
    """
    if os.path.isdir(ACCOUNTS_DIR) and os.listdir(ACCOUNTS_DIR):
        return  # already migrated
    if not os.path.exists(DRIVE_TOKEN_PATH):
        return  # nothing to migrate
    try:
        creds = Credentials.from_authorized_user_file(DRIVE_TOKEN_PATH, DRIVE_SCOPES)
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        resp = _requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=5,
        )
        if resp.status_code != 200:
            return
        email = resp.json().get("email")
        if not email:
            return
        os.makedirs(_account_dir(email), exist_ok=True)
        shutil.copy2(DRIVE_TOKEN_PATH, _drive_token_path(email))
        if os.path.exists(SHEETS_TOKEN_PATH):
            shutil.copy2(SHEETS_TOKEN_PATH, _sheets_token_path(email))
        set_active_account(email)
        logger.info("Migrated legacy tokens → accounts/%s/", email)
    except Exception as exc:
        logger.debug("Legacy token migration skipped: %s", exc)


_try_migrate_legacy_tokens()


# ===========================================================================
# Auth helpers
# ===========================================================================

def _get_drive_credentials() -> Credentials:
    """Return valid Drive credentials for the active account, re-authing if needed."""
    email = get_active_account_email()
    token_path = _drive_token_path(email) if email else DRIVE_TOKEN_PATH

    creds: Optional[Credentials] = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, DRIVE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CLIENT_SECRET_PATH, DRIVE_SCOPES)
            creds = flow.run_local_server(port=0)
            # Discover email so we store in the right place
            try:
                resp = _requests.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {creds.token}"},
                    timeout=5,
                )
                if resp.status_code == 200:
                    email = resp.json().get("email")
                    if email:
                        token_path = _drive_token_path(email)
                        set_active_account(email)
            except Exception:
                pass
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds


def _get_drive_service() -> Resource:
    return build("drive", "v3", credentials=_get_drive_credentials())


get_drive_service = _get_drive_service


# ===========================================================================
# User info
# ===========================================================================

def get_user_info(email: Optional[str] = None) -> Optional[dict]:
    """
    Return name / email / picture for *email* (or the active account if None).
    Returns None on any error.
    """
    try:
        target = email or get_active_account_email()
        if not target:
            return None
        token_path = _drive_token_path(target)
        if not os.path.exists(token_path):
            return None
        creds = Credentials.from_authorized_user_file(token_path, DRIVE_SCOPES)
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        resp = _requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "name": data.get("name", ""),
                "email": data.get("email", target),
                "picture": data.get("picture", ""),
            }
        return None
    except Exception as exc:
        logger.debug("Could not fetch user info for %s: %s", email, exc)
        return None


# ===========================================================================
# Drive operations
# ===========================================================================

def _get_root_folder_id(service: Resource) -> str:
    root = service.files().get(fileId="root", fields="id").execute()
    return root["id"]


def _get_or_create_folder(service: Resource, name: str, parent_id: str) -> str:
    query = (
        f"name = '{name}' "
        f"and mimeType = '{_MIME_FOLDER}' "
        f"and '{parent_id}' in parents "
        f"and trashed = false"
    )
    results = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id, name)")
        .execute()
    )
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    metadata = {"name": name, "mimeType": _MIME_FOLDER, "parents": [parent_id]}
    folder = service.files().create(body=metadata, fields="id").execute()
    folder_id: str = folder["id"]
    logger.info("Created Drive folder '%s' (id=%s).", name, folder_id)
    return folder_id


def scan_root_for_files() -> list[dict]:
    """Return supported files sitting directly in the Drive root."""
    service = _get_drive_service()
    root_id = _get_root_folder_id(service)
    mime_conditions = " or ".join(f"mimeType = '{m}'" for m in _SUPPORTED_MIME_TYPES)
    query = f"({mime_conditions}) and '{root_id}' in parents and trashed = false"

    files: list[dict] = []
    page_token: Optional[str] = None
    while True:
        response = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                pageToken=page_token,
            )
            .execute()
        )
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    logger.info("Found %d loose file(s) in Drive root.", len(files))
    return files


scan_root_for_pdfs = scan_root_for_files

_MIME_FRIENDLY: dict[str, str] = {
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
    "application/msword": "Word",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
    "application/vnd.ms-excel": "Excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
    "application/vnd.ms-powerpoint": "PowerPoint",
    "application/vnd.google-apps.document": "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "application/vnd.google-apps.presentation": "Google Slides",
    "image/jpeg": "Image", "image/png": "Image", "image/gif": "Image",
    "image/webp": "Image", "image/bmp": "Image", "image/tiff": "Image",
}


def list_drive_contents() -> dict:
    """
    Return a dict with:
      "loose":      list of files in Drive root (unorganised)
      "organised":  dict of {category_name: [files]} for each category folder
    Each file is {name, type, modified}.
    """
    service  = _get_drive_service()
    root_id  = _get_root_folder_id(service)

    try:
        from settings_manager import load_settings, get_category_folders
        category_folders = get_category_folders(load_settings())
    except Exception:
        category_folders = CATEGORY_FOLDERS

    def _list_in(parent_id: str) -> list[dict]:
        results, page_token = [], None
        while True:
            resp = service.files().list(
                q=f"'{parent_id}' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'",
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                pageToken=page_token,
            ).execute()
            for f in resp.get("files", []):
                mod = (f.get("modifiedTime") or "")[:10]
                results.append({
                    "name":     f["name"],
                    "type":     _MIME_FRIENDLY.get(f.get("mimeType", ""), "File"),
                    "modified": mod,
                })
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return results

    loose = []
    for f in scan_root_for_files():
        mod = (f.get("modifiedTime") or "")[:10]
        loose.append({
            "name":     f["name"],
            "type":     _MIME_FRIENDLY.get(f.get("mimeType", ""), "File"),
            "modified": mod,
        })

    organised: dict[str, list] = {}
    for category, folder_name in category_folders.items():
        try:
            folder_id = _find_or_create_folder(service, folder_name, root_id)
            organised[category] = _list_in(folder_id)
        except Exception as exc:
            logger.warning("Could not list folder '%s': %s", folder_name, exc)
            organised[category] = []

    return {"loose": loose, "organised": organised}


def move_pdf_to_category(file_id: str, category: str) -> None:
    """Move a Drive file into the subfolder matching *category*."""
    try:
        from settings_manager import load_settings, get_category_folders
        category_folders = get_category_folders(load_settings())
    except Exception:
        category_folders = CATEGORY_FOLDERS
    folder_name = category_folders.get(category)
    if folder_name is None:
        raise ValueError(
            f"Unknown category '{category}'. "
            f"Expected one of: {list(category_folders.keys())}"
        )
    service = _get_drive_service()
    root_id = _get_root_folder_id(service)
    dest_folder_id = _get_or_create_folder(service, folder_name, root_id)
    file_meta = service.files().get(fileId=file_id, fields="parents").execute()
    current_parents = ",".join(file_meta.get("parents", []))
    try:
        service.files().update(
            fileId=file_id,
            addParents=dest_folder_id,
            removeParents=current_parents,
            fields="id, parents",
        ).execute()
        logger.info("Moved file %s → folder '%s'.", file_id, folder_name)
    except HttpError as exc:
        logger.error("Failed to move file %s: %s", file_id, exc)
        raise


def download_pdf_content(file_id: str, mime_type: str = "") -> bytes:
    """
    Download a Drive file's bytes, exporting Google-native formats first.
    Pass *mime_type* (from the scan result) to skip an extra API call.
    """
    service = _get_drive_service()
    if not mime_type:
        mime_type = service.files().get(fileId=file_id, fields="mimeType").execute().get("mimeType", "")
    if mime_type in GOOGLE_EXPORT_MAP:
        export_mime = GOOGLE_EXPORT_MAP[mime_type]["export_mime"]
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        logger.debug("Exporting Google-native file %s as %s.", file_id, export_mime)
    else:
        request = service.files().get_media(fileId=file_id)
    content: bytes = request.execute()
    logger.debug("Downloaded %d bytes for file id=%s.", len(content), file_id)
    return content


def find_file_by_name(filename: str) -> Optional[str]:
    """Search Drive for a file by exact name (any type) and return its ID."""
    service = _get_drive_service()
    safe_name = filename.replace("'", "\\'")
    query = f"name = '{safe_name}' and trashed = false"
    results = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id, name)")
        .execute()
    )
    files = results.get("files", [])
    if files:
        logger.info("Found '%s' with id=%s.", filename, files[0]["id"])
        return files[0]["id"]
    logger.warning("File '%s' not found in Drive.", filename)
    return None


def reclassify_file(filename: str, new_category: str) -> None:
    """Find a file anywhere in Drive and move it to a new category folder."""
    file_id = find_file_by_name(filename)
    if file_id is None:
        raise FileNotFoundError(
            f"Could not find '{filename}' in Google Drive. "
            "It may have been deleted or renamed manually."
        )
    move_pdf_to_category(file_id, new_category)
    logger.info("Reclassified '%s' → '%s'.", filename, new_category)
