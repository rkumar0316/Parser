"""
PTI Veripac 465-M8 Report Parser — Streamlit App
==================================================
Upload PTI test report, filter results, and export to CSV.

Install & Run:
    pip install streamlit pandas
    streamlit run app.py
"""

import io
import re
import zipfile

import pandas as pd
import pdfplumber
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="PTI Report Parser",
    page_icon="🔬",
    layout="wide",
)

# ── Custom styling ────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Tighten up padding */
    .block-container { padding-top: 2rem; }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: #f8f9fb;
        border: 1px solid #e2e5ea;
        border-radius: 10px;
        padding: 16px 20px;
    }

    /* Pass/fail badge colors in dataframe */
    .pass-badge { color: #059669; font-weight: 600; }
    .fail-badge { color: #dc2626; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


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
    """Parse a single PTI report and return a DataFrame of test results."""
    text = ""

    # Try ZIP format first (some PTI exports are ZIP archives with .pdf extension)
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


def color_result(val):
    """Style Pass/Fail cells."""
    if val == "Pass":
        return "color: #059669; font-weight: 600"
    elif val == "Fail":
        return "color: #dc2626; font-weight: 600"
    return ""


# ── Session state init ────────────────────────────────────────────────
if "data" not in st.session_state:
    st.session_state.data = pd.DataFrame()
if "processed_files" not in st.session_state:
    st.session_state.processed_files = set()


# ── Header ────────────────────────────────────────────────────────────
st.title("🔬 PTI Report Parser")
st.caption("Veripac 465-M8  ·  Upload reports, filter results, export CSV")


# ── File upload ───────────────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "Upload PTI Report PDFs",
    type=["pdf"],
    accept_multiple_files=True,
    help="These are ZIP-based PTI report files with a .pdf extension.",
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
    st.info("Upload one or more PTI report PDFs to get started.")
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
    # pandas >=2.1 uses .map(), older uses .applymap()
    styler = df.style
    try:
        styled = styler.map(color_result, subset=["Result"])
    except AttributeError:
        styled = styler.applymap(color_result, subset=["Result"])
    styled = styled.format({
        "C1 (mBar)": "{:.1f}",
        "C2 (mBar)": "{:.1f}",
        "Diff C2 (mBar)": "{:.1f}",
        "C3 (Pa)": "{:.1f}",
    })

    st.dataframe(
        styled,
        use_container_width=True,
        height=500,
        hide_index=True,
    )


# ── CSV download ──────────────────────────────────────────────────────
if not df.empty:
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)

    st.download_button(
        label=f"📥 Download CSV ({len(df)} rows)",
        data=csv_buffer.getvalue(),
        file_name="pti_results.csv",
        mime="text/csv",
    )