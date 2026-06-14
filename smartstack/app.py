"""
app.py — Streamlit UI for SmartStack.

Two pages accessible via the sidebar:
  1. Organise My Drive — scan Drive root, classify PDFs, move them to folders.
  2. Ask a Question    — natural-language Q&A against the logged summaries.

Run with:
    streamlit run app.py
"""

import logging
import os
import sys
import time
import traceback

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Logging — write to stdout so Streamlit's terminal shows it
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page config must be the very first Streamlit call
# ---------------------------------------------------------------------------
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "logo.png")

try:
    from PIL import Image as _PILImage
    _page_icon = _PILImage.open(_LOGO_PATH) if os.path.exists(_LOGO_PATH) else "📚"
except Exception:
    _page_icon = "📚"

st.set_page_config(
    page_title="SmartStack",
    page_icon=_page_icon,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Theme CSS — generated from saved color palette, injected every render
# ---------------------------------------------------------------------------

# Built-in presets
_THEME_PRESETS = {
    "light": {"primary": "#FFFFFF", "secondary": "#F5EDD8", "button": "#8B7355"},
    "dark":  {"primary": "#05050D", "secondary": "#0C1829", "button": "#1B3A5C"},
}


def _hex_to_hsl(hex_color: str) -> tuple[float, float, float]:
    """Return (hue 0-360, saturation 0-1, lightness 0-1) for a hex color."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    cmax, cmin = max(r, g, b), min(r, g, b)
    delta = cmax - cmin
    l = (cmax + cmin) / 2
    if delta == 0:
        return 0.0, 0.0, l
    s = delta / (1 - abs(2 * l - 1))
    if cmax == r:
        hue = 60 * (((g - b) / delta) % 6)
    elif cmax == g:
        hue = 60 * (((b - r) / delta) + 2)
    else:
        hue = 60 * (((r - g) / delta) + 4)
    return hue % 360, s, l



def _darken(hex_color: str, amount: float = 0.15) -> str:
    """Return a slightly darkened version of hex_color for hover states."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r = max(0, int(r * (1 - amount)))
        g = max(0, int(g * (1 - amount)))
        b = max(0, int(b * (1 - amount)))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


def _is_dark_bg(hex_color: str) -> bool:
    """True if background is dark enough to need light text/inputs."""
    try:
        _, _, lit = _hex_to_hsl(hex_color)
        return lit < 0.45
    except Exception:
        return False


def _build_theme_css(primary: str, secondary: str, button: str, preset: str = "light") -> str:
    btn_text   = "#F0F4FF" if _is_dark_bg(button) else "#1a1a1a"
    btn_hover  = _darken(button)
    dark_bg    = _is_dark_bg(primary)
    text_color = "#D8E0F0" if dark_bg else "#1a1a1a"
    head_color = "#A8C4E8" if dark_bg else "#2C2416"
    side_text  = "#C5D8F0" if _is_dark_bg(secondary) else "#2a1f0e"
    input_bg   = _darken(primary, -0.04) if dark_bg else _darken(primary, 0.03)
    input_border = _darken(secondary, -0.1) if dark_bg else _darken(secondary, 0.15)

    return f"""
<style>
.stApp, .stApp > header, [data-testid="stAppViewContainer"] {{
    background-color: {primary} !important;
    color: {text_color} !important;
}}
[data-testid="stHeader"] {{ background-color: {primary} !important; }}
[data-testid="stSidebar"], [data-testid="stSidebar"] > div:first-child {{
    background-color: {secondary} !important;
}}
[data-testid="stSidebar"] * {{ color: {side_text} !important; }}
.stMarkdown, .stMarkdown p, .stText, label, span, p {{ color: {text_color}; }}
h1, h2, h3, h4 {{ color: {head_color} !important; }}
.stButton > button {{
    background-color: {button} !important;
    color: {btn_text} !important;
    font-weight: 700 !important;
    border: none !important;
    border-radius: 6px !important;
}}
.stButton > button:hover {{ background-color: {btn_hover} !important; color: {btn_text} !important; }}
.stButton > button[kind="primary"] {{ background-color: {button} !important; color: {btn_text} !important; }}
.stTextInput input, .stTextArea textarea, .stNumberInput input {{
    background-color: {input_bg} !important;
    border: 1px solid {input_border} !important;
    color: {text_color} !important;
}}
.stExpander {{ border: 1px solid {input_border} !important; background-color: {secondary} !important; }}
hr {{ border-color: {input_border} !important; }}
.stSelectbox > div > div {{ background-color: {input_bg} !important; border-color: {input_border} !important; }}
[data-testid="stProgressBar"] > div {{ background-color: {input_border} !important; }}
.ss-stack {{
    background: {"linear-gradient(90deg,#00C6FF,#7B2FBE)" if dark_bg else "linear-gradient(90deg,#FFB800,#FF5500)"};
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
    background-clip: text !important;
    display: inline-block;
}}
</style>
"""


def _inject_theme_css() -> None:
    from settings_manager import load_settings
    settings = load_settings()
    preset = settings.get("preset", "light")
    if preset in _THEME_PRESETS:
        colors = _THEME_PRESETS[preset]
    else:
        colors = settings.get("colors", _THEME_PRESETS["light"])
    primary   = colors.get("primary",   _THEME_PRESETS["light"]["primary"])
    secondary = colors.get("secondary", _THEME_PRESETS["light"]["secondary"])
    button    = colors.get("button",    _THEME_PRESETS["light"]["button"])
    st.markdown(_build_theme_css(primary, secondary, button, preset), unsafe_allow_html=True)


_inject_theme_css()

# ---------------------------------------------------------------------------
# Lazy imports — delayed so Streamlit can render the page before doing OAuth
# ---------------------------------------------------------------------------
def _import_modules():
    """Import project modules lazily to avoid blocking the initial render."""
    from drive_manager import scan_root_for_files as scan_root_for_pdfs, download_pdf_content, move_pdf_to_category, reclassify_file
    from pdf_processor import extract_text_from_bytes
    from claude_classifier import classify_document
    from sheets_logger import log_processed_file, fetch_all_logs, update_row_category
    from query_engine import answer_question
    from config import validate_config
    return (
        scan_root_for_pdfs,
        download_pdf_content,
        move_pdf_to_category,
        reclassify_file,
        extract_text_from_bytes,
        classify_document,
        log_processed_file,
        fetch_all_logs,
        update_row_category,
        answer_question,
        validate_config,
    )


# ---------------------------------------------------------------------------
# Sidebar — account picker + navigation
# ---------------------------------------------------------------------------

def _pic_b64(url: str) -> str:
    """Fetch an image URL and return a base64 data URI, cached in session state."""
    cache = st.session_state.setdefault("_pic_cache", {})
    if url not in cache:
        try:
            import requests as _req
            import base64 as _b64
            r = _req.get(url, timeout=5)
            if r.status_code == 200:
                cache[url] = _b64.b64encode(r.content).decode()
        except Exception:  # noqa: BLE001
            pass
    return cache.get(url, "")


def _initial_circle(initial: str, size: int = 32) -> str:
    """Return an HTML colored circle with the given initial."""
    return (
        f'<div style="width:{size}px;height:{size}px;border-radius:50%;'
        f'background:#4f8ef7;color:#fff;display:flex;align-items:center;'
        f'justify-content:center;font-weight:700;font-size:{size * 0.44:.0f}px">'
        f'{initial}</div>'
    )


def _render_sidebar_profile() -> None:
    """Render the active-account header and multi-account manager."""
    from drive_manager import (
        get_active_account_email,
        get_all_account_emails,
        get_user_info,
        set_active_account,
        delete_account,
        add_new_account,
    )

    active_email = get_active_account_email()
    all_emails = get_all_account_emails()

    # Cache account info per session to avoid repeated API calls
    info_cache = st.session_state.setdefault("_acct_cache", {})
    def _info(email: str) -> dict:
        if email not in info_cache:
            info_cache[email] = get_user_info(email) or {"name": email, "email": email, "picture": ""}
        return info_cache[email]

    # ── Active account header ────────────────────────────────────────────
    if active_email:
        user = _info(active_email)
        first_name = user["name"].split()[0] if user.get("name") else "there"
        pic = _pic_b64(user.get("picture", "")) if user.get("picture") else ""
        if pic:
            img_tag = (
                f'<img src="data:image/jpeg;base64,{pic}" '
                f'style="width:42px;height:42px;border-radius:50%;'
                f'object-fit:cover;border:2px solid #4f8ef7"/>'
            )
        else:
            img_tag = _initial_circle(first_name[0].upper(), 42)
        st.sidebar.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">'
            f'{img_tag}'
            f'<div>'
            f'<div style="font-weight:700;font-size:0.95rem;line-height:1.2">Hi, {first_name}!</div>'
            f'<div style="font-size:0.72rem;color:#888;line-height:1.2">{user["email"]}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.sidebar.markdown(
            "<div style='font-size:0.8rem;color:#888;margin-bottom:4px'>"
            "Sign in to see your profile</div>",
            unsafe_allow_html=True,
        )

    # ── Account manager expander ──────────────────────────────────────────
    other_emails = [e for e in all_emails if e != active_email]
    n = len(other_emails)
    expander_label = "Manage accounts" + (f" · {n} other" + ("s" if n > 1 else "") if n else "")

    with st.sidebar.expander(expander_label):
        # Other stored accounts
        if other_emails:
            st.markdown("**Other accounts**")
            for email in other_emails:
                user = _info(email)
                display = user.get("name") or email
                initial = display[0].upper()

                col_av, col_txt, col_sw, col_del = st.columns([1, 4, 2, 1])
                with col_av:
                    st.markdown(_initial_circle(initial), unsafe_allow_html=True)
                with col_txt:
                    st.markdown(
                        f"<div style='font-size:0.82rem;font-weight:600;line-height:1.2'>{display}</div>"
                        f"<div style='font-size:0.68rem;color:#888;line-height:1.2'>{email}</div>",
                        unsafe_allow_html=True,
                    )
                with col_sw:
                    if st.button("Switch", key=f"_sw_{email}", use_container_width=True):
                        set_active_account(email)
                        info_cache.clear()
                        st.session_state.pop("_confirm_delete", None)
                        st.rerun()
                with col_del:
                    if st.button("🗑️", key=f"_del_{email}"):
                        st.session_state["_confirm_delete"] = email

                # Inline delete confirmation
                if st.session_state.get("_confirm_delete") == email:
                    st.warning(f"Remove **{display}** from this device?")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Remove", key=f"_ok_{email}", type="primary"):
                            delete_account(email)
                            info_cache.pop(email, None)
                            st.session_state.pop("_confirm_delete", None)
                            st.rerun()
                    with c2:
                        if st.button("Cancel", key=f"_cx_{email}"):
                            st.session_state.pop("_confirm_delete", None)
                            st.rerun()

            st.divider()

        # Add account
        if st.button("＋  Add another account", use_container_width=True):
            with st.spinner("Opening browser for sign-in…"):
                try:
                    new_email = add_new_account()
                    set_active_account(new_email)
                    info_cache.clear()
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not add account: {exc}")

        # Sign out (remove active account)
        if active_email:
            if st.button("Sign out", use_container_width=True):
                st.session_state["_confirm_logout"] = True

            if st.session_state.get("_confirm_logout"):
                st.warning(
                    f"Sign out of **{active_email}**?  "
                    "This removes stored credentials from this device."
                )
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Sign out", key="_ok_logout", type="primary"):
                        delete_account(active_email)
                        info_cache.clear()
                        remaining = [e for e in all_emails if e != active_email]
                        set_active_account(remaining[0] if remaining else None)
                        st.session_state.pop("_confirm_logout", None)
                        st.rerun()
                with c2:
                    if st.button("Cancel", key="_cx_logout"):
                        st.session_state.pop("_confirm_logout", None)
                        st.rerun()


_LOGO2_PATH = os.path.join(os.path.dirname(__file__), "logo2.png")

# Determine current theme for sidebar branding
_sb_settings = __import__("settings_manager").load_settings()
_sb_preset   = _sb_settings.get("preset", "light")
_sb_is_dark  = (
    _sb_preset == "dark" or
    (_sb_preset == "custom" and _is_dark_bg(_sb_settings.get("colors", {}).get("secondary", "#F5EDD8")))
)

if _sb_is_dark:
    _smart_color    = "#000000"
    _stack_gradient = "linear-gradient(90deg,#00C6FF,#7B2FBE)"  # cool blue → purple
    _active_logo    = _LOGO2_PATH if os.path.exists(_LOGO2_PATH) else _LOGO_PATH
else:
    _smart_color    = "#FFFFFF"
    _stack_gradient = "linear-gradient(90deg,#FFB800,#FF5500)"  # warm yellow → orange
    _active_logo    = _LOGO_PATH

import base64 as _b64

if os.path.exists(_active_logo):
    with open(_active_logo, "rb") as _f:
        _logo_b64 = _b64.b64encode(_f.read()).decode()
    _logo_img = f'<img src="data:image/png;base64,{_logo_b64}" style="height:54px;width:auto;flex-shrink:0;">'
else:
    _logo_img = ""

st.sidebar.markdown(f"""
<div style="display:flex;align-items:center;gap:12px;padding:6px 0 10px 0;">
  {_logo_img}
  <span style="font-size:24px;font-weight:800;line-height:1;letter-spacing:-0.5px;">
    <span style="color:{_smart_color};">Smart</span><span class="ss-stack">Stack</span>
  </span>
</div>
""", unsafe_allow_html=True)

_render_sidebar_profile()
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Navigate",
    ["Organise My Drive", "Ask a Question", "Reclassify Files", "Settings"],
    index=0,
)
st.sidebar.markdown("---")
st.sidebar.caption(
    "SmartStack uses AI to organise your Google Drive files and lets you "
    "ask questions about your study material."
)


# ===========================================================================
# PAGE 1 — Organise My Drive
# ===========================================================================
def page_organise() -> None:
    """Render the 'Organise My Drive' page."""
    st.title("🗂️ Organise My Drive")
    st.markdown(
        "Click **Scan My Drive** to find loose files in your Drive root, "
        "classify them with AI, and move them into the right folders. "
        "Supports PDF, Google Docs, Google Sheets, Google Slides, Word, Excel, PowerPoint, images and videos."
    )

    if st.button("🔍 Scan My Drive", type="primary"):
        _run_organise_flow()


def _run_organise_flow() -> None:
    """Execute the full scan → classify → move pipeline and display results."""
    (
        scan_root_for_pdfs,
        download_pdf_content,
        move_pdf_to_category,
        _reclassify,
        extract_text_from_bytes,
        classify_document,
        log_processed_file,
        _fetch_logs,
        _update_row,
        _answer_question,
        validate_config,
    ) = _import_modules()

    # Validate config before doing anything visible
    try:
        validate_config()
    except ValueError as exc:
        st.error(f"⚠️ Configuration error: {exc}")
        return

    with st.spinner("Scanning your Google Drive root for loose files…"):
        try:
            pdfs = scan_root_for_pdfs()
        except Exception as exc:  # noqa: BLE001
            st.error(f"❌ Failed to scan Drive: {exc}")
            logger.exception("Drive scan failed.")
            return

    if not pdfs:
        st.info("✅ Nothing to organise! No loose files found in your Drive root.")
        return

    st.success(f"Found **{len(pdfs)} file(s)** to process.")
    st.markdown("---")

    results: list[dict] = []
    progress_bar = st.progress(0)
    status_area = st.empty()

    for idx, pdf_file in enumerate(pdfs):
        filename: str = pdf_file["name"]
        file_id: str = pdf_file["id"]
        progress = (idx) / len(pdfs)
        progress_bar.progress(progress, text=f"Processing {idx + 1}/{len(pdfs)}: {filename}")

        status_area.info(f"⏳ Processing **{filename}**…")

        row: dict = {
            "Filename": filename,
            "Category": "",
            "Topic": "",
            "Summary": "",
            "Status": "",
        }

        try:
            from drive_manager import GOOGLE_EXPORT_MAP
            _VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".webm", ".flv"}
            mime_type: str = pdf_file.get("mimeType", "")
            file_ext = os.path.splitext(filename)[1].lower()
            is_video = file_ext in _VIDEO_EXTENSIONS
            is_google_native = mime_type in GOOGLE_EXPORT_MAP

            # 1. Get content
            if is_video:
                text = (
                    f"This is a video file named: {filename}. "
                    f"Classify it based on the filename alone."
                )
            elif is_google_native:
                # Export Google Docs/Sheets/Slides and use the export extension
                # so the right text extractor is chosen
                effective_ext = GOOGLE_EXPORT_MAP[mime_type]["extension"]
                effective_name = filename + effective_ext
                pdf_bytes = download_pdf_content(file_id, mime_type=mime_type)
                text = extract_text_from_bytes(pdf_bytes, filename=effective_name)
            else:
                pdf_bytes = download_pdf_content(file_id, mime_type=mime_type)
                text = extract_text_from_bytes(pdf_bytes, filename=filename)

            # 2. Classify with AI
            classification = classify_document(text, filename=filename)
            row["Category"] = classification["category"]
            row["Topic"] = classification["topic"]
            row["Summary"] = classification["summary"]

            # 4. Move to correct Drive folder
            move_pdf_to_category(file_id, classification["category"])

            # 5. Log to Google Sheets
            log_processed_file(
                filename=filename,
                category=classification["category"],
                topic=classification["topic"],
                summary=classification["summary"],
            )

            row["Status"] = "✅ Done"
            logger.info("Successfully processed '%s'.", filename)

        except Exception as exc:  # noqa: BLE001
            row["Status"] = f"❌ Error: {exc}"
            logger.exception("Error processing '%s'.", filename)

        results.append(row)

        # Pause between files to stay within rate limits
        if idx < len(pdfs) - 1:
            from settings_manager import load_settings
            time.sleep(load_settings()["processing"]["delay_seconds"])

    progress_bar.progress(1.0, text="All files processed!")
    status_area.empty()

    # Display results table
    st.markdown("### Results")
    df = pd.DataFrame(results)

    # Colour code status column
    def _highlight_status(val: str) -> str:
        if val.startswith("✅"):
            return "color: green"
        if val.startswith("❌"):
            return "color: red"
        return ""

    st.dataframe(
        df.style.map(_highlight_status, subset=["Status"]),
        use_container_width=True,
        hide_index=True,
    )

    success_count = sum(1 for r in results if r["Status"].startswith("✅"))
    error_count = len(results) - success_count
    st.markdown(
        f"**{success_count} file(s) organised successfully.**"
        + (f"  {error_count} file(s) had errors — check the logs." if error_count else "")
    )


# ===========================================================================
# PAGE 2 — Ask a Question
# ===========================================================================
def page_ask() -> None:
    """Render the 'Ask a Question' page."""
    st.title("💬 Ask a Question")
    st.markdown(
        "Ask anything about your study material. SmartStack will search "
        "through your logged document summaries and give you an answer."
    )

    question = st.text_input(
        "Type your doubt or question…",
        placeholder="e.g. What is the difference between RAM and ROM?",
    )

    if st.button("🚀 Get Answer", type="primary"):
        if not question.strip():
            st.warning("Please enter a question first.")
            return
        _run_query_flow(question.strip())


def _run_query_flow(question: str) -> None:
    """Send *question* to Claude via the query engine and display the answer."""
    (
        _scan, _download, _move, _reclassify,
        _extract, _classify, _log, _fetch, _update,
        answer_question,
        validate_config,
    ) = _import_modules()

    try:
        validate_config()
    except ValueError as exc:
        st.error(f"⚠️ Configuration error: {exc}")
        return

    with st.spinner("Searching your study material and asking Claude…"):
        try:
            answer = answer_question(question)
        except Exception as exc:  # noqa: BLE001
            st.error(f"❌ Failed to get an answer: {exc}")
            logger.exception("Query engine failed.")
            return

    # Detect the "no data" signal
    if answer.startswith("No study material has been logged"):
        st.info("📭 No study material logged yet! Go to **Organise My Drive** first.")
        return

    # Display answer in a styled container
    st.markdown("### Claude's Answer")
    st.markdown(
        f"""
        <div style="
            background: #f0f4ff;
            border-left: 4px solid #4f8ef7;
            border-radius: 6px;
            padding: 1rem 1.25rem;
            font-size: 0.97rem;
            line-height: 1.6;
            color: #1a1a2e;
        ">
        {answer.replace(chr(10), "<br>")}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ===========================================================================
# PAGE 3 — Reclassify Files
# ===========================================================================
_CATEGORIES = ["Study", "College Admin", "Personal/Fun", "Miscellaneous"]


def page_reclassify() -> None:
    """Render the 'Reclassify Files' page."""
    st.title("🔄 Reclassify Files")
    st.markdown(
        "Change the category of any processed file. "
        "SmartStack will update the Google Sheet **and** move the file in your Drive."
    )

    (
        _scan, _download, _move, reclassify_file,
        _extract, _classify, _log, fetch_all_logs, update_row_category,
        _answer,
        validate_config,
    ) = _import_modules()

    try:
        validate_config()
    except ValueError as exc:
        st.error(f"⚠️ Configuration error: {exc}")
        return

    with st.spinner("Loading your logged files…"):
        try:
            logs = fetch_all_logs()
        except Exception as exc:  # noqa: BLE001
            st.error(f"❌ Failed to load logs: {exc}")
            logger.exception("Failed to fetch logs for reclassify page.")
            return

    if not logs:
        st.info("📭 No files logged yet. Go to **Organise My Drive** first.")
        return

    # ── AI bulk reclassify ────────────────────────────────────────────────────
    with st.expander("🤖 AI Bulk Reclassify — give rules, apply to all files"):
        st.markdown(
            "Write rules in plain English and the AI will go through every file "
            "and move anything that matches. One rule per line."
        )
        rules = st.text_area(
            "Rules",
            height=130,
            placeholder=(
                "Files with 'AIMUN' or 'MUN' in the name go to College Admin\n"
                "Anything about Netflix or movies goes to Personal/Fun\n"
                "Lecture notes and past papers go to Study"
            ),
            label_visibility="collapsed",
        )
        if st.button("🚀 Apply Rules", type="primary", disabled=not rules.strip()):
            from claude_classifier import suggest_reclassification
            changes: list[tuple[str, str, str]] = []  # (filename, old, new)
            errors: list[str] = []
            bar = st.progress(0, text="Asking AI…")

            for i, entry in enumerate(logs):
                fname = entry.get("Filename", "")
                cur_cat = entry.get("Category", "Study")
                bar.progress((i + 1) / len(logs), text=f"Checking {fname}…")
                new_cat = suggest_reclassification(fname, cur_cat, rules.strip())
                if new_cat:
                    try:
                        reclassify_file(fname, new_cat)
                        update_row_category(fname, new_cat)
                        changes.append((fname, cur_cat, new_cat))
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{fname}: {exc}")

            bar.empty()
            if changes:
                st.success(f"Moved **{len(changes)} file(s)**:")
                for fname, old, new in changes:
                    st.markdown(f"- **{fname}** `{old}` → `{new}`")
            else:
                st.info("No files matched the rules — nothing moved.")
            for err in errors:
                st.error(err)

    st.markdown(f"**{len(logs)} file(s) logged.** Select a new category and click Reclassify.")
    st.markdown("---")

    for entry in logs:
        filename = entry.get("Filename", "Unknown")
        current_category = entry.get("Category", "Study")
        topic = entry.get("Topic", "")

        col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

        with col1:
            st.markdown(f"**{filename}**")
            if topic:
                st.caption(topic)

        with col2:
            st.markdown(f"Current: `{current_category}`")

        with col3:
            new_category = st.selectbox(
                "New category",
                _CATEGORIES,
                index=_CATEGORIES.index(current_category) if current_category in _CATEGORIES else 0,
                key=f"cat_{filename}",
                label_visibility="collapsed",
            )

        with col4:
            if st.button("Reclassify", key=f"btn_{filename}"):
                if new_category == current_category:
                    st.warning("Same category — nothing to change.")
                else:
                    with st.spinner(f"Moving '{filename}'…"):
                        try:
                            reclassify_file(filename, new_category)
                            update_row_category(filename, new_category)
                            st.success(f"Moved to **{new_category}**!")
                            logger.info(
                                "Reclassified '%s': '%s' → '%s'.",
                                filename, current_category, new_category,
                            )
                        except Exception as exc:  # noqa: BLE001
                            st.error(f"❌ {exc}")
                            logger.exception("Reclassify failed for '%s'.", filename)

        st.divider()


# ===========================================================================
# PAGE 4 — Settings
# ===========================================================================
def page_settings() -> None:
    """Render the full Settings page."""
    from datetime import date as _date
    from settings_manager import (
        load_settings, save_settings,
        GROQ_FREE_TIER_DAILY_LIMIT,
    )

    st.title("⚙️ Settings")
    settings = load_settings()

    # ── Text Model ────────────────────────────────────────────────────────────
    st.subheader("🤖 Text Model")
    st.caption("Used for classification, Q&A, and bulk reclassify.")

    # initialise variables so they're always in scope
    tm = settings["text_model"]
    use_custom_text = st.toggle("Use custom text model", value=tm.get("use_custom", False), key="tog_tm")
    custom_text_model = tm.get("model", "")
    custom_text_key   = tm.get("api_key", "")
    custom_text_base  = tm.get("base_url", "")
    if use_custom_text:
        custom_text_model = st.text_input("Model name (LiteLLM format, e.g. openai/gpt-4o)",
                                          value=custom_text_model, key="tm_model")
        custom_text_key   = st.text_input("API Key", value=custom_text_key,
                                          type="password", key="tm_key")
        custom_text_base  = st.text_input("Base URL (optional, for self-hosted)",
                                          value=custom_text_base, key="tm_base")
        if custom_text_model and custom_text_key:
            st.success("✅ Custom text model ready")
        else:
            st.warning("⚠️ Enter a model name and API key to use a custom model")
    else:
        st.info("`groq/llama-3.3-70b-versatile` — no extra key needed")

    st.divider()

    # ── Vision Model ──────────────────────────────────────────────────────────
    st.subheader("👁️ Vision Model")
    st.caption("Used for images and scanned PDFs.")

    vm = settings["vision_model"]
    use_custom_vision = st.toggle("Use custom vision model", value=vm.get("use_custom", False), key="tog_vm")
    custom_vision_model = vm.get("model", "")
    custom_vision_key   = vm.get("api_key", "")
    custom_vision_base  = vm.get("base_url", "")
    if use_custom_vision:
        custom_vision_model = st.text_input("Model name (e.g. openai/gpt-4o, anthropic/claude-opus-4-8)",
                                             value=custom_vision_model, key="vm_model")
        custom_vision_key   = st.text_input("API Key", value=custom_vision_key,
                                             type="password", key="vm_key")
        custom_vision_base  = st.text_input("Base URL (optional)",
                                             value=custom_vision_base, key="vm_base")
        if custom_vision_model and custom_vision_key:
            st.success("✅ Custom vision model ready")
        else:
            st.warning("⚠️ Enter a model name and API key to use a custom vision model")
    else:
        st.info("`groq/meta-llama/llama-4-scout-17b-16e-instruct` — no extra key needed")

    st.divider()

    # ── Folder Names ──────────────────────────────────────────────────────────
    st.subheader("📁 Drive Folder Names")
    st.caption("Names of the folders SmartStack creates in your Google Drive.")
    fl = settings["folders"]
    col1, col2 = st.columns(2)
    with col1:
        folder_study = st.text_input("Study", value=fl.get("Study", "Study"))
        folder_fun   = st.text_input("Personal/Fun", value=fl.get("Personal/Fun", "Personal/Fun"))
    with col2:
        folder_admin = st.text_input("College Admin", value=fl.get("College Admin", "College Admin"))
        folder_misc  = st.text_input("Miscellaneous", value=fl.get("Miscellaneous", "Miscellaneous"))

    st.divider()

    # ── Processing ────────────────────────────────────────────────────────────
    st.subheader("⚙️ Processing")
    pr = settings["processing"]
    max_pages = st.slider("Max pages to read per PDF", 1, 50,
                          value=int(pr.get("max_pages", 10)))
    delay_secs = st.slider("Delay between AI calls (seconds)", 0, 10,
                            value=int(pr.get("delay_seconds", 2)))

    st.divider()

    # ── Google Sheets ─────────────────────────────────────────────────────────
    st.subheader("📊 Google Sheets")
    sheet_name = st.text_input("Log sheet name",
                                value=settings["sheets"].get("sheet_name", "SmartStack Log"))

    st.divider()

    # ── Token Usage ───────────────────────────────────────────────────────────
    st.subheader("📈 Token Usage (Today)")
    token_data = settings.get("token_usage", {})
    today_str  = str(_date.today())
    daily_total = token_data.get("total", 0) if token_data.get("date") == today_str else 0
    pct = daily_total / GROQ_FREE_TIER_DAILY_LIMIT

    st.markdown(f"**{daily_total:,}** / {GROQ_FREE_TIER_DAILY_LIMIT:,} tokens used today")
    st.progress(min(pct, 1.0))
    if pct >= 1.0:
        st.error("🚫 Daily limit reached. Wait ~10 minutes or switch to a custom model.")
    elif pct >= 0.8:
        st.warning("⚠️ Approaching limit — consider slowing down or using fewer files.")

    if st.button("🔄 Reset Counter"):
        settings["token_usage"] = {"date": today_str, "total": 0}
        save_settings(settings)
        st.success("Counter reset!")
        st.rerun()

    st.divider()

    # ── Theme ─────────────────────────────────────────────────────────────────
    st.subheader("🎨 Colour Palette")

    _preset_labels = ["🌤️ Light", "🌙 Dark", "🎨 Custom"]
    _preset_keys   = ["light", "dark", "custom"]
    saved_preset   = settings.get("preset", "light")
    preset_idx     = _preset_keys.index(saved_preset) if saved_preset in _preset_keys else 0

    chosen_preset = st.radio("Theme preset", _preset_labels, index=preset_idx, horizontal=True,
                             label_visibility="collapsed")
    preset_val = _preset_keys[_preset_labels.index(chosen_preset)]

    if preset_val == "light":
        col_primary, col_secondary, col_button = (
            _THEME_PRESETS["light"]["primary"],
            _THEME_PRESETS["light"]["secondary"],
            _THEME_PRESETS["light"]["button"],
        )
        st.caption("White background · Warm beige sidebar · Brown buttons")

    elif preset_val == "dark":
        col_primary, col_secondary, col_button = (
            _THEME_PRESETS["dark"]["primary"],
            _THEME_PRESETS["dark"]["secondary"],
            _THEME_PRESETS["dark"]["button"],
        )
        st.caption("Near-black background · Navy sidebar · Navy-blue buttons")

    else:  # custom
        saved_colors = settings.get("colors", _THEME_PRESETS["light"])
        c1, c2, c3 = st.columns(3)
        with c1:
            col_primary   = st.color_picker("Primary (background)",
                                            value=saved_colors.get("primary",   "#FFFFFF"),
                                            key="color_primary")
        with c2:
            col_secondary = st.color_picker("Secondary (sidebar)",
                                            value=saved_colors.get("secondary", "#F5EDD8"),
                                            key="color_secondary")
        with c3:
            col_button    = st.color_picker("Button colour",
                                            value=saved_colors.get("button",    "#8B7355"),
                                            key="color_button")

    st.divider()

    # ── Save ──────────────────────────────────────────────────────────────────
    if st.button("💾 Save Settings", type="primary", use_container_width=True):
        new_settings = load_settings()  # fresh load to preserve token_usage etc.
        new_settings["text_model"] = {
            "use_custom": use_custom_text,
            "model":      custom_text_model,
            "api_key":    custom_text_key,
            "base_url":   custom_text_base,
        }
        new_settings["vision_model"] = {
            "use_custom": use_custom_vision,
            "model":      custom_vision_model,
            "api_key":    custom_vision_key,
            "base_url":   custom_vision_base,
        }
        new_settings["folders"] = {
            "Study":         folder_study  or "Study",
            "College Admin": folder_admin  or "College Admin",
            "Personal/Fun":  folder_fun    or "Personal/Fun",
            "Miscellaneous": folder_misc   or "Miscellaneous",
        }
        new_settings["processing"] = {
            "max_pages":      max_pages,
            "delay_seconds":  delay_secs,
        }
        new_settings["sheets"]  = {"sheet_name": sheet_name or "SmartStack Log"}
        new_settings["preset"] = preset_val
        new_settings["colors"] = {
            "primary":   col_primary,
            "secondary": col_secondary,
            "button":    col_button,
        }
        save_settings(new_settings)

        st.success("✅ Settings saved!")
        st.rerun()


# ===========================================================================
# Router
# ===========================================================================
if page == "Organise My Drive":
    page_organise()
elif page == "Ask a Question":
    page_ask()
elif page == "Reclassify Files":
    page_reclassify()
elif page == "Settings":
    page_settings()
