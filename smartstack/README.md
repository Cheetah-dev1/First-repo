# SmartStack

SmartStack is an AI-powered Google Drive organiser built with Streamlit. It
scans your Drive root for loose files, classifies them using Groq's Llama
models, moves each file into the correct subfolder, logs everything to a
Google Sheet, and lets you ask natural-language questions about your study
material. A fourth catch-all **Miscellaneous** folder handles anything that
doesn't fit the other categories.

---

## Features

| Feature | Detail |
|---|---|
| **Drive scan** | Finds every loose file sitting directly in your Drive root |
| **Multi-format support** | PDF, Word (DOCX/DOC), Excel (XLSX/XLS), PowerPoint (PPTX/PPT), images (JPG/PNG/BMP/TIFF/GIF/WEBP), and videos |
| **AI classification** | Groq Llama 3.3 70B classifies each file into Study / College Admin / Personal/Fun / Miscellaneous |
| **Image understanding** | Groq vision model (Llama 3.2 11B) reads and describes image content — no Tesseract required |
| **Video support** | Videos are classified by filename alone (no download needed) |
| **Auto-folder creation** | Creates destination subfolders in Drive if they don't exist |
| **Audit log** | Every processed file is appended to a Google Sheet |
| **Q&A engine** | Ask questions; Groq answers from your logged summaries |
| **Reclassify** | Change any file's category — Drive and the Sheet are both updated |
| **Profile display** | Your Gmail profile picture and name appear in the sidebar |

---

## Tech Stack

- **Python 3.13**
- **Streamlit** — UI
- **Google Drive API v3** — scanning and moving files
- **Google Sheets API v4** — logging processed files
- **Groq API** — Llama 3.3 70B Versatile (text) + Llama 3.2 11B Vision (images)
- **pdfplumber** — PDF text extraction
- **python-docx** — Word document extraction
- **openpyxl / xlrd / pandas** — Excel extraction
- **python-pptx** — PowerPoint extraction
- **Pillow** — image format conversion for vision model

---

## Prerequisites

- Python 3.13 (or 3.10+)
- A Google account with Google Drive and Sheets enabled
- A free [Groq API key](https://console.groq.com) — no card required
- A Google Cloud project with the Drive and Sheets APIs enabled

---

## Setup

### 1. Clone the repository

```bash
git clone -b claude/smartstack-production-M78y0 <repo-url>
cd first-repo/smartstack
```

### 2. Create a virtual environment

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Google Cloud

#### 4a. Enable APIs

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (or select an existing one).
3. Go to **APIs & Services → Library**.
4. Enable **Google Drive API**.
5. Enable **Google Sheets API**.

#### 4b. Create OAuth 2.0 credentials

1. Go to **APIs & Services → Credentials**.
2. Click **Create Credentials → OAuth client ID**.
3. Application type: **Desktop app**.
4. Give it a name (e.g. `SmartStack`) and click **Create**.
5. Click **Download JSON**, rename the file to `client_secret.json`.
6. Move it into the `credentials/` directory inside this project.

> **Windows tip:** If the file downloads as `client_secret.json.json`, enable
> "Show file name extensions" in File Explorer and remove the extra `.json`.

#### 4c. Configure OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen**.
2. Choose **External** and fill in the required fields.
3. Under **Test users**, add your Google account email.
4. Save and continue (no need to add scopes manually — they're requested at runtime).

### 5. Set up environment variables

```bash
# Windows
copy .env.example .env

# macOS/Linux
cp .env.example .env
```

Open `.env` (use Notepad on Windows) and fill in your values:

```dotenv
GROQ_API_KEY=gsk_...          # from https://console.groq.com
OAUTH_CLIENT_SECRET_FILE=client_secret.json
```

All other variables have sensible defaults — see `.env.example` for the full
reference.

### 6. Run the app

```bash
streamlit run app.py
```

On first run a browser window will open for Google OAuth. Grant access to
Drive and Sheets. Tokens are cached in `credentials/` — you won't be
prompted again unless you delete them.

---

## Project Structure

```
smartstack/
│
├── app.py                  # Streamlit UI (3 pages)
├── drive_manager.py        # Google Drive: scan, download, move, user info
├── pdf_processor.py        # Multi-format text extraction
├── claude_classifier.py    # Groq Llama classification
├── sheets_logger.py        # Google Sheets: log, fetch, update
├── query_engine.py         # Natural-language Q&A
├── config.py               # Environment variables & constants
│
├── requirements.txt        # Pinned dependencies
├── .env.example            # Environment variable reference
├── .gitignore              # Excludes .env and credentials/*.json
│
└── credentials/
    ├── .gitkeep            # Keeps the directory in version control
    ├── client_secret.json  # YOUR file — not committed
    ├── drive_token.json    # Auto-generated — not committed
    └── sheets_token.json   # Auto-generated — not committed
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | *(required)* | Groq secret key — free at console.groq.com |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq text model ID |
| `MAX_TOKENS` | `1024` | Max response tokens |
| `RETRY_COUNT` | `3` | API retry attempts |
| `OAUTH_CLIENT_SECRET_FILE` | `client_secret.json` | Filename inside `credentials/` |
| `FOLDER_STUDY` | `Study` | Drive subfolder for study material |
| `FOLDER_COLLEGE_ADMIN` | `College Admin` | Drive subfolder for admin docs |
| `FOLDER_PERSONAL_FUN` | `Personal/Fun` | Drive subfolder for personal content |
| `FOLDER_MISCELLANEOUS` | `Miscellaneous` | Drive subfolder for everything else |
| `SHEET_NAME` | `SmartStack Log` | Google Sheet name |
| `MAX_WORDS` | `3000` | Max words extracted per file |

---

## How It Works

### Page 1 — Organise My Drive

1. Click **Scan My Drive** → Drive API lists all supported files in your root.
2. For each file:
   - **Videos** — classified by filename only (no download).
   - **Images** — sent to Groq vision model for description + text extraction.
   - **Everything else** — bytes downloaded, text extracted by format-specific parser.
3. Groq Llama classifies the text into `{category, topic, summary}`.
4. File is moved to the matching Drive subfolder (auto-created if absent).
5. A row is appended to the Google Sheet.
6. Results are displayed in a colour-coded table.

### Page 2 — Ask a Question

1. Type any question about your study material.
2. All logged summaries are fetched from the Sheet.
3. Summaries + question are sent to Groq Llama.
4. The answer is displayed in a styled box.

### Page 3 — Reclassify Files

1. All logged files are listed with their current category.
2. Pick a new category from the dropdown and click **Reclassify**.
3. SmartStack moves the file in Drive **and** updates the Sheet row.

---

## Security Notes

- Credentials and tokens are stored locally in `credentials/` and excluded
  from version control by `.gitignore`.
- API keys are loaded from environment variables — never hardcoded.
- OAuth tokens are refreshed automatically.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `GROQ_API_KEY is not set` | Add your key to `.env` |
| `OAuth client secret not found` | Copy `client_secret.json` to `credentials/` |
| `403 access_denied` | Add your email as a test user in the OAuth consent screen |
| `403 insufficientPermissions` | Delete token files and re-authenticate (see below) |
| Profile picture not showing | Delete `credentials/drive_token.json` and re-authenticate |
| Image unreadable | Check your Groq key has vision access |
| Sheet not found | Auto-created on first log — check your Google Drive |

---

## Resetting OAuth

Delete the cached tokens to force re-authorisation:

```bash
# Windows
del credentials\drive_token.json
del credentials\sheets_token.json

# macOS/Linux
rm credentials/drive_token.json credentials/sheets_token.json
```

Run the app again and complete the browser consent flow.

> **Note:** If the profile picture doesn't appear after updating, delete
> `drive_token.json` and re-authenticate — the new profile scopes require
> a fresh token.
