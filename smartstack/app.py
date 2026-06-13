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
st.set_page_config(
    page_title="SmartStack",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

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


_render_sidebar_profile()
st.sidebar.title("📚 SmartStack")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Navigate",
    ["Organise My Drive", "Ask a Question", "Reclassify Files"],
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
        "Supports PDF, Word, Excel, PowerPoint, images and videos."
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

    st.success(f"Found **{len(pdfs)} PDF(s)** to process.")
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
            _VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".webm", ".flv"}
            file_ext = os.path.splitext(filename)[1].lower()
            is_video = file_ext in _VIDEO_EXTENSIONS

            # 1. Get content — videos are classified by filename only (no download)
            if is_video:
                text = (
                    f"This is a video file named: {filename}. "
                    f"Classify it based on the filename alone."
                )
            else:
                pdf_bytes = download_pdf_content(file_id)
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
# Router
# ===========================================================================
if page == "Organise My Drive":
    page_organise()
elif page == "Ask a Question":
    page_ask()
elif page == "Reclassify Files":
    page_reclassify()
