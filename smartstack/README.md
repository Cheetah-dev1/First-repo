# SmartStack

SmartStack is a Streamlit application that automatically organises loose PDFs
sitting in your Google Drive root. It uses Claude to classify each document,
moves it to the correct subfolder (Study, College Admin, or Personal/Fun),
logs everything to a Google Sheet, and lets you ask natural-language questions
about your study material.

---

## Features

| Feature | Detail |
|---|---|
| **Drive scan** | Finds every PDF sitting directly in your Drive root |
| **AI classification** | Classifies documents into Study / College Admin / Personal/Fun |
| **Auto-folder creation** | Creates destination subfolders if they don't exist |
| **PDF text extraction** | Uses pdfplumber; handles scanned PDFs gracefully |
| **Audit log** | Every processed file is appended to a Google Sheet |
| **Q&A engine** | Ask questions; Claude answers from your logged summaries |

---

## Tech Stack

- **Python 3.12**
- **Streamlit** — UI
- **Google Drive API v3** — scanning and moving files
- **Google Sheets API v4** — logging processed files
- **Anthropic SDK** — Claude `claude-sonnet-4-20250514`
- **pdfplumber** — PDF text extraction
- **pandas** — results table

---

## Prerequisites

- Python 3.12+
- A Google account with Google Drive enabled
- An [Anthropic API key](https://console.anthropic.com/settings/keys)
- A Google Cloud project with the Drive and Sheets APIs enabled

---

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd smartstack
```

### 2. Create a virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
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
4. Give it a name (e.g. `SmartStack`).
5. Click **Create**, then **Download JSON**.
6. Rename the downloaded file to `client_secret.json`.
7. Move it into the `credentials/` directory inside this project.

#### 4c. Configure OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen**.
2. Choose **External** (or Internal if using Google Workspace).
3. Fill in the required fields (App name, support email).
4. Under **Scopes**, add:
   - `https://www.googleapis.com/auth/drive`
   - `https://www.googleapis.com/auth/spreadsheets`
5. Under **Test users**, add your Google account email.
6. Save and continue.

### 5. Set up environment variables

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...
OAUTH_CLIENT_SECRET_FILE=client_secret.json
```

All other variables have sensible defaults — see `.env.example` for the full
reference.

### 6. Run the app

```bash
streamlit run app.py
```

The first time you use either page, a browser window will open asking you to
authorise SmartStack to access your Google Drive and Google Sheets. OAuth
tokens are cached in `credentials/` so you won't be prompted again.

---

## Project Structure

```
smartstack/
│
├── app.py                  # Streamlit UI (two pages)
├── drive_manager.py        # Google Drive: scan, download, move
├── pdf_processor.py        # pdfplumber text extraction
├── claude_classifier.py    # Claude JSON classification
├── sheets_logger.py        # Google Sheets: log & fetch
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
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic secret key |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Claude model ID |
| `CLAUDE_MAX_TOKENS` | `1024` | Max response tokens |
| `CLAUDE_RETRY_COUNT` | `3` | API retry attempts |
| `OAUTH_CLIENT_SECRET_FILE` | `client_secret.json` | Filename inside `credentials/` |
| `FOLDER_STUDY` | `Study` | Drive subfolder for study material |
| `FOLDER_COLLEGE_ADMIN` | `College Admin` | Drive subfolder for admin docs |
| `FOLDER_PERSONAL_FUN` | `Personal/Fun` | Drive subfolder for personal docs |
| `SHEET_NAME` | `SmartStack Log` | Google Sheet name |
| `MAX_WORDS` | `3000` | Max words extracted per PDF |

---

## How It Works

### Page 1 — Organise My Drive

1. Clicks **Scan My Drive** → queries Drive API for PDFs with root as parent.
2. For each PDF:
   - Downloads raw bytes from Drive.
   - Extracts text with pdfplumber (up to 3 000 words).
   - Sends text to Claude, receives `{category, topic, summary}` JSON.
   - Moves the PDF into the matching Drive subfolder (auto-created if absent).
   - Appends a row to the Google Sheet.
3. Displays a results table with per-file status.

### Page 2 — Ask a Question

1. User types a question.
2. All logged summaries are fetched from the Sheet.
3. Summaries + question are sent to Claude.
4. Claude's answer is displayed in a styled box.

---

## Security Notes

- Credentials and tokens are stored locally in `credentials/` and are excluded
  from version control by `.gitignore`.
- API keys are loaded from environment variables — never hardcoded.
- OAuth tokens are refreshed automatically; no manual intervention needed.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ANTHROPIC_API_KEY is not set` | Add your key to `.env` |
| `OAuth client secret not found` | Copy `client_secret.json` to `credentials/` |
| `400 redirect_uri_mismatch` | Ensure Authorised Redirect URI includes `http://localhost` in Cloud Console |
| PDF shows as unreadable | The file is likely a scanned image — convert to searchable PDF first |
| Sheet not found | The sheet is auto-created on first log; check your Google Drive |
| `403 insufficientPermissions` | Add the required scopes and re-authorise (delete token files in `credentials/`) |

---

## Resetting OAuth

Delete the cached tokens to force re-authorisation:

```bash
rm credentials/drive_token.json credentials/sheets_token.json
```

Run the app again and complete the browser-based consent flow.
