"""
drive_manager.py — Google Drive integration for SmartStack.

Responsibilities:
- Authenticate with Google Drive via OAuth2 (with token refresh).
- Scan the root of the user's Drive for loose files (PDF, Word, Excel,
  PowerPoint, and images) with no parent other than the Drive root.
- Auto-create destination subfolders (Study, College Admin, Personal/Fun,
  Miscellaneous).
- Move classified files into the correct subfolder.
"""

import logging
import os
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError

from config import (
    DRIVE_SCOPES,
    DRIVE_TOKEN_PATH,
    OAUTH_CLIENT_SECRET_PATH,
    CATEGORY_FOLDERS,
)

logger = logging.getLogger(__name__)

# MIME type constants
_MIME_FOLDER = "application/vnd.google-apps.folder"

# All file types SmartStack can process
_SUPPORTED_MIME_TYPES: list[str] = [
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
    # Video — classified by filename only, never downloaded
    "video/mp4",
    "video/x-msvideo",     # avi
    "video/quicktime",     # mov
    "video/x-matroska",   # mkv
    "video/x-ms-wmv",     # wmv
    "video/webm",
    "video/x-flv",
]


def _get_drive_service() -> Resource:
    """
    Authenticate and return an authorised Google Drive API service object.

    Token is cached to disk and refreshed automatically when expired.
    On first run the user is directed to a browser-based OAuth consent screen.

    Returns:
        An authorised ``googleapiclient.discovery.Resource`` for the Drive v3 API.
    """
    creds: Optional[Credentials] = None

    if os.path.exists(DRIVE_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(DRIVE_TOKEN_PATH, DRIVE_SCOPES)
        logger.debug("Loaded Drive credentials from token cache.")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Drive token expired — refreshing.")
            creds.refresh(Request())
        else:
            logger.info("Drive OAuth flow starting — browser window will open.")
            flow = InstalledAppFlow.from_client_secrets_file(
                OAUTH_CLIENT_SECRET_PATH, DRIVE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        os.makedirs(os.path.dirname(DRIVE_TOKEN_PATH), exist_ok=True)
        with open(DRIVE_TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())
        logger.info("Drive credentials saved to %s", DRIVE_TOKEN_PATH)

    service: Resource = build("drive", "v3", credentials=creds)
    return service


def _get_root_folder_id(service: Resource) -> str:
    """
    Return the file ID of the user's 'My Drive' root folder.

    Args:
        service: Authorised Drive API service.

    Returns:
        The root folder file ID string.
    """
    root = service.files().get(fileId="root", fields="id").execute()
    root_id: str = root["id"]
    logger.debug("Drive root folder ID: %s", root_id)
    return root_id


def _get_or_create_folder(service: Resource, name: str, parent_id: str) -> str:
    """
    Return the file ID of a named subfolder inside *parent_id*, creating it
    if it does not already exist.

    Args:
        service:   Authorised Drive API service.
        name:      The desired folder name.
        parent_id: File ID of the parent folder.

    Returns:
        File ID of the (possibly newly created) subfolder.
    """
    # Search for an existing folder with this name under the parent
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
        folder_id: str = files[0]["id"]
        logger.debug("Folder '%s' already exists (id=%s).", name, folder_id)
        return folder_id

    # Create the folder
    metadata = {
        "name": name,
        "mimeType": _MIME_FOLDER,
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    folder_id = folder["id"]
    logger.info("Created Drive folder '%s' (id=%s).", name, folder_id)
    return folder_id


def scan_root_for_files() -> list[dict]:
    """
    Return a list of supported files sitting directly in the Drive root.

    Supported types: PDF, DOCX, DOC, XLSX, XLS, PPTX, PPT, and common images.
    Files already inside a subfolder are not returned.

    Each item in the returned list is a dict with keys:
        ``id``   — Drive file ID
        ``name`` — filename including extension

    Returns:
        List of dicts describing loose supported files in the Drive root.
    """
    service = _get_drive_service()
    root_id = _get_root_folder_id(service)

    mime_conditions = " or ".join(
        f"mimeType = '{m}'" for m in _SUPPORTED_MIME_TYPES
    )
    query = f"({mime_conditions}) and '{root_id}' in parents and trashed = false"

    files: list[dict] = []
    page_token: Optional[str] = None

    while True:
        response = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name)",
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


# Keep old name as alias so nothing breaks if called elsewhere
scan_root_for_pdfs = scan_root_for_files


def move_pdf_to_category(file_id: str, category: str) -> None:
    """
    Move a Drive file into the subfolder matching *category*.

    The destination subfolder is auto-created under Drive root if absent.
    The file is simultaneously removed from the root so it no longer appears
    as a loose file.

    Args:
        file_id:  Drive file ID of the PDF to move.
        category: One of ``"Study"``, ``"College Admin"``, ``"Personal/Fun"``.

    Raises:
        ValueError: If *category* is not a recognised value.
        HttpError:  Propagated from the Drive API on network/permission errors.
    """
    folder_name = CATEGORY_FOLDERS.get(category)
    if folder_name is None:
        raise ValueError(
            f"Unknown category '{category}'. "
            f"Expected one of: {list(CATEGORY_FOLDERS.keys())}"
        )

    service = _get_drive_service()
    root_id = _get_root_folder_id(service)

    dest_folder_id = _get_or_create_folder(service, folder_name, root_id)

    # Fetch current parents so we can remove the file from root
    file_meta = service.files().get(fileId=file_id, fields="parents").execute()
    current_parents = ",".join(file_meta.get("parents", []))

    try:
        service.files().update(
            fileId=file_id,
            addParents=dest_folder_id,
            removeParents=current_parents,
            fields="id, parents",
        ).execute()
        logger.info(
            "Moved file %s → folder '%s' (id=%s).",
            file_id,
            folder_name,
            dest_folder_id,
        )
    except HttpError as exc:
        logger.error("Failed to move file %s: %s", file_id, exc)
        raise


def download_pdf_content(file_id: str) -> bytes:
    """
    Download the raw bytes of a Drive PDF file.

    Args:
        file_id: Drive file ID.

    Returns:
        Raw PDF bytes.

    Raises:
        HttpError: Propagated from the Drive API.
    """
    service = _get_drive_service()
    request = service.files().get_media(fileId=file_id)
    content: bytes = request.execute()
    logger.debug("Downloaded %d bytes for file id=%s.", len(content), file_id)
    return content


def find_file_by_name(filename: str) -> Optional[str]:
    """
    Search Google Drive for a PDF with the given filename and return its file ID.

    Searches across all folders (not just root) so it works after a file has
    already been moved into a category subfolder.

    Args:
        filename: Exact filename to search for (including .pdf extension).

    Returns:
        Drive file ID string if found, or ``None`` if not found.
    """
    service = _get_drive_service()
    # Escape single quotes in filename for the query string
    safe_name = filename.replace("'", "\\'")
    query = (
        f"name = '{safe_name}' "
        f"and mimeType = '{_MIME_PDF}' "
        f"and trashed = false"
    )
    results = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id, name)")
        .execute()
    )
    files = results.get("files", [])
    if files:
        logger.info("Found file '%s' with id=%s.", filename, files[0]["id"])
        return files[0]["id"]
    logger.warning("File '%s' not found in Drive.", filename)
    return None


def reclassify_file(filename: str, new_category: str) -> None:
    """
    Find a PDF by name anywhere in Drive and move it to a new category folder.

    Args:
        filename:     Exact filename of the PDF to reclassify.
        new_category: Target category — one of ``"Study"``, ``"College Admin"``,
                      ``"Personal/Fun"``.

    Raises:
        FileNotFoundError: If the file cannot be found in Drive.
        ValueError:        If *new_category* is not a recognised value.
        HttpError:         Propagated from the Drive API.
    """
    file_id = find_file_by_name(filename)
    if file_id is None:
        raise FileNotFoundError(
            f"Could not find '{filename}' in Google Drive. "
            "It may have been deleted or renamed manually."
        )
    move_pdf_to_category(file_id, new_category)
    logger.info("Reclassified '%s' → '%s'.", filename, new_category)
