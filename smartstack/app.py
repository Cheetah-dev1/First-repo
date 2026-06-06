"""
app.py — Streamlit UI for SmartStack.

Two pages accessible via the sidebar:
  1. Organise My Drive — scan Drive root, classify PDFs, move them to folders.
  2. Ask a Question    — natural-language Q&A against the logged summaries.

Run with:
    streamlit run app.py
"""

import logging
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
    from drive_manager import scan_root_for_pdfs, download_pdf_content, move_pdf_to_category
    from pdf_processor import extract_text_from_bytes
    from claude_classifier import classify_document
    from sheets_logger import log_processed_file
    from query_engine import answer_question
    from config import validate_config
    return (
        scan_root_for_pdfs,
        download_pdf_content,
        move_pdf_to_category,
        extract_text_from_bytes,
        classify_document,
        log_processed_file,
        answer_question,
        validate_config,
    )


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.title("📚 SmartStack")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Navigate",
    ["Organise My Drive", "Ask a Question"],
    index=0,
)
st.sidebar.markdown("---")
st.sidebar.caption(
    "SmartStack automatically organises your Google Drive PDFs using AI "
    "and lets you ask questions about your study material."
)


# ===========================================================================
# PAGE 1 — Organise My Drive
# ===========================================================================
def page_organise() -> None:
    """Render the 'Organise My Drive' page."""
    st.title("🗂️ Organise My Drive")
    st.markdown(
        "Click **Scan My Drive** to find loose PDFs in your Drive root, "
        "classify them with Claude, and move them into the right folders."
    )

    if st.button("🔍 Scan My Drive", type="primary"):
        _run_organise_flow()


def _run_organise_flow() -> None:
    """Execute the full scan → classify → move pipeline and display results."""
    (
        scan_root_for_pdfs,
        download_pdf_content,
        move_pdf_to_category,
        extract_text_from_bytes,
        classify_document,
        log_processed_file,
        _answer_question,
        validate_config,
    ) = _import_modules()

    # Validate config before doing anything visible
    try:
        validate_config()
    except ValueError as exc:
        st.error(f"⚠️ Configuration error: {exc}")
        return

    with st.spinner("Scanning your Google Drive root for loose PDFs…"):
        try:
            pdfs = scan_root_for_pdfs()
        except Exception as exc:  # noqa: BLE001
            st.error(f"❌ Failed to scan Drive: {exc}")
            logger.exception("Drive scan failed.")
            return

    if not pdfs:
        st.info("✅ Nothing to organise! No loose PDFs found in your Drive root.")
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
            # 1. Download PDF bytes
            pdf_bytes = download_pdf_content(file_id)

            # 2. Extract text
            text = extract_text_from_bytes(pdf_bytes, filename=filename)

            # 3. Classify with Claude
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
        _scan, _download, _move,
        _extract, _classify, _log,
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
# Router
# ===========================================================================
if page == "Organise My Drive":
    page_organise()
elif page == "Ask a Question":
    page_ask()
