"""
Need streamlit and pandas 
Program is a parser to take a specific pdf and let you easily copy/filter it
"""

import io
import re
import zipfile

import pandas as pd
import pdfplumber
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="Report Parser",
    page_icon="🔥",
    layout="wide",
)


# ── Parsing functions ─────────────────────────────────────────────────

MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

ROW_PATTERN = re.compile(
    r"^(\d{1,3})\s+"
    r"\d{1,2}:\d{2}:\d{2}\s+"
    r"(\d{1,3})\s+"
    r"([\-\d.]+)\s+"
    r"([\-\d.,]+)\s+"
    r"([\-\d.]+)\s+"
    r"([\-\d.]+)\s+"
    r"(.+?)\s+"
    r"(Pass|Fail)\s*$",
    re.IGNORECASE,
)


def extract_text_from_zip(file_bytes: bytes) -> str:
    """Extract and concatenate all .txt files from a ZIP archive."""
    full_text = ""
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        txt_files = sorted([n for n in z.namelist() if n.endswith(".txt")])
        for name in txt_files:
            content = z.read(name).decode("utf-8", errors="replace")
            full_text += content + "\n\n"
    return full_text


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from a real PDF using pdfplumber."""
    full_text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n\n"
    return full_text


def parse_batch_date(text: str) -> str:
    """Extract and format the Batch Start date as MM/DD/YYYY."""
    # Format in these files:
    #   Batch Start
    #   Batch End
    #   10-Apr-2025 16:39:23    ← start date
    #   10-Apr-2025 17:48:55    ← end date
    m = re.search(
        r"Batch\s*Start\s*[\r\n]+"
        r"Batch\s*End\s*[\r\n]+"
        r"(\d{1,2})-(\w{3})-(\d{4})",
        text, re.IGNORECASE,
    )
    if not m:
        # Fallback: Batch Start immediately followed by date
        m = re.search(
            r"Batch\s*Start\s*[\r\n]+(\d{1,2})-(\w{3})-(\d{4})",
            text, re.IGNORECASE,
        )
    if not m:
        # Fallback: first date-like pattern in text
        m = re.search(r"(\d{1,2})-(\w{3})-(\d{4})", text, re.IGNORECASE)

    if m:
        day, mon_str, year = m.group(1), m.group(2).lower()[:3], m.group(3)
        mon = MONTHS.get(mon_str, "00")
        return f"{mon}/{day.zfill(2)}/{year}"

    # Fallback: batch title pattern like "10APR2025"
    m = re.search(r"(\d{1,2})([A-Z]{3})(\d{4})", text)
    if m:
        day, mon_str, year = m.group(1), m.group(2).lower()[:3], m.group(3)
        mon = MONTHS.get(mon_str, "00")
        return f"{mon}/{day.zfill(2)}/{year}"

    return ""


def parse_report(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Parse a single report and return a DataFrame of test results."""
    text = ""

    # Try ZIP format first (some exports are ZIP archives with .pdf extension)
    try:
        text = extract_text_from_zip(file_bytes)
    except zipfile.BadZipFile:
        pass

    # Fall back to real PDF extraction
    if not text.strip():
        try:
            text = extract_text_from_pdf(file_bytes)
        except Exception as e:
            st.warning(f"Could not read **{filename}**: {e}")
            return pd.DataFrame()

    if not text.strip():
        st.warning(f"**{filename}** — no text could be extracted.")
        return pd.DataFrame()

    batch_date = parse_batch_date(text)
    rows = []

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        m = ROW_PATTERN.match(line)
        if m:
            comment = m.group(7).strip()
            result = m.group(8).capitalize()
            if comment.lower() in ("comments", "result"):
                continue

            rows.append({
                "Source": filename,
                "Batch Date": batch_date,
                "Test #": int(m.group(2)),
                "Comment": comment,
                "C1 (mBar)": float(m.group(3)),
                "C2 (mBar)": float(m.group(4).replace(",", "")),
                "Diff C2 (mBar)": float(m.group(5)),
                "C3 (Pa)": float(m.group(6)),
                "Result": result,
            })

    return pd.DataFrame(rows)



# ── Session state init ────────────────────────────────────────────────
if "data" not in st.session_state:
    st.session_state.data = pd.DataFrame()
if "processed_files" not in st.session_state:
    st.session_state.processed_files = set()


# ── Header ────────────────────────────────────────────────────────────
st.title("PDF Parser")
st.caption("Upload pdf filter results, can export/copy CSV")


# ── File upload ───────────────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "Upload Report PDFs",
    type=["pdf"],
    accept_multiple_files=True,
    help="These are ZIP-based report files with a .pdf extension.",
)

if uploaded_files:
    new_frames = []
    for f in uploaded_files:
        # Skip already-processed files (by name + size)
        file_key = f"{f.name}_{f.size}"
        if file_key not in st.session_state.processed_files:
            df = parse_report(f.read(), f.name)
            if not df.empty:
                new_frames.append(df)
                st.session_state.processed_files.add(file_key)

    if new_frames:
        st.session_state.data = pd.concat(
            [st.session_state.data] + new_frames, ignore_index=True
        )

df_all = st.session_state.data

if df_all.empty:
    st.info("Upload one or more PDFs to get started.")
    st.stop()


# ── Sidebar filters ──────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")

    # Source file
    sources = ["All Files"] + sorted(df_all["Source"].unique().tolist())
    selected_source = st.selectbox("Source File", sources)

    # Result filter
    result_filter = st.radio("Result", ["All", "Pass", "Fail"], horizontal=True)

    # Warm-up toggle
    exclude_warmup = st.checkbox("Exclude warm-up tests", value=False)

    # Comment filter
    st.markdown("---")
    st.subheader("Comment Filter")
    comment_text = st.text_input("Filter text", placeholder="e.g. NL, NH, PC10...")
    comment_mode = st.selectbox("Match mode", ["Contains", "Exact", "Starts with"])

    # Clear button
    st.markdown("---")
    if st.button("🗑️ Clear All Data", use_container_width=True):
        st.session_state.data = pd.DataFrame()
        st.session_state.processed_files = set()
        st.rerun()


# ── Apply filters ─────────────────────────────────────────────────────
df = df_all.copy()

if selected_source != "All Files":
    df = df[df["Source"] == selected_source]

if result_filter != "All":
    df = df[df["Result"] == result_filter]

if exclude_warmup:
    df = df[~df["Comment"].str.lower().str.contains("warm")]

if comment_text.strip():
    ct = comment_text.strip().lower()
    if comment_mode == "Contains":
        df = df[df["Comment"].str.lower().str.contains(ct, na=False)]
    elif comment_mode == "Exact":
        df = df[df["Comment"].str.lower() == ct]
    elif comment_mode == "Starts with":
        df = df[df["Comment"].str.lower().str.startswith(ct)]


# ── Summary cards ─────────────────────────────────────────────────────
total_all = len(df_all)
pass_all = (df_all["Result"] == "Pass").sum()
fail_all = (df_all["Result"] == "Fail").sum()
pass_rate = f"{pass_all / total_all * 100:.1f}%" if total_all > 0 else "—"

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Tests", total_all)
col2.metric("Passed", pass_all)
col3.metric("Failed", fail_all)
col4.metric("Pass Rate", pass_rate)
col5.metric("Showing", len(df))


# ── Data table ────────────────────────────────────────────────────────
if df.empty:
    st.warning("No results match the current filters.")
else:
    st.dataframe(
        df,
        use_container_width=True,
        height=500,
        hide_index=True,
    )
