"""
Need streamlit and pandas 
Program is a parser to take a specific pdf and let you easily copy/filter it
"""

import io
import re
from datetime import datetime

import pandas as pd
import pdfplumber
import streamlit as st

#Initial streamlit page configuration - title, icon, layout
st.set_page_config(
    page_title="Report Parser",
    page_icon="🔥",
    layout="wide",
)

#Parsing functions

### Do not change, report pdfs have terrible formatting. re.match() takes way too long.
ROW_PATTERN = re.compile(r"""
    ^(\d{1,3})          \s+   # col 1: row number
    \d{1,2}:\d{2}:\d{2} \s+   # timestamp (ignored)
    (\d{1,3})           \s+   # col 2: test number
    ([\-\d.]+)          \s+   # col 3: C1 (mBar)
    ([\-\d.,]+)         \s+   # col 4: C2 (mBar)
    ([\-\d.]+)          \s+   # col 5: Diff C2 (mBar)
    ([\-\d.]+)          \s+   # col 6: C3 (Pa)
    (.+?)               \s+   # col 7: comment
    (Pass|Fail)         \s*$  # col 8: result
""", re.IGNORECASE | re.VERBOSE)

#Formats a regex match into MM/DD/YYYY
def make_date(m):
    day, mon_str, year = m.group(1), m.group(2), m.group(3)
    try:
        parsed = datetime.strptime(mon_str[:3], "%b")
        mon = parsed.month
    except ValueError:
        mon = 0
    return f"{str(mon).zfill(2)}/{day.zfill(2)}/{year}"

#Converts batch date to the desired format for excels with multiple days of results.
def get_date(text):
    m = re.search(r"Batch\s*Start\s*[\r\n]+Batch\s*End\s*[\r\n]+(\d{1,2})-(\w{3})-(\d{4})", text, re.IGNORECASE)
    if not m:
        m = re.search(r"Batch\s*Start\s*[\r\n]+(\d{1,2})-(\w{3})-(\d{4})", text, re.IGNORECASE)
    if not m:
        m = re.search(r"(\d{1,2})-(\w{3})-(\d{4})", text, re.IGNORECASE)
    if not m:
        m = re.search(r"(\d{1,2})([A-Z]{3})(\d{4})", text)
    if m:
        return make_date(m)
    return ""

#Parses report and returns dataframe of results.
def read_pdf(raw_pdf, filename):
    try:
        pdf_file = io.BytesIO(raw_pdf)
        with pdfplumber.open(pdf_file) as pdf:
            text = ""
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n\n"
    except Exception as e:
        st.warning(f"Could not read {filename}: {e}")
        return pd.DataFrame()

    if not text.strip():
        st.warning(f"{filename} - no text could be extracted.")
        return pd.DataFrame()

    batch_date = get_date(text)
    rows = []

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        m = ROW_PATTERN.match(line)
        if m:
            comment = m.group(7).strip()
            result = m.group(8).capitalize()
            if comment.lower() == "comments" or comment.lower() == "result":
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

# Initialize session
if "data" not in st.session_state:
    st.session_state.data = pd.DataFrame()
if "processed_files" not in st.session_state:
    st.session_state.processed_files = set()

# Webpage UI
st.title("PDF Parser to make my life easier")
st.caption("Upload pdf filter results, can export/copy CSV")

#Add streamlit file uploader
uploaded_files = st.file_uploader(
    "Upload Report PDFs",
    type=["pdf"],
    accept_multiple_files=True,
    help="Upload .pdf report files.",
)

if uploaded_files:
    new_dfs = []
    for f in uploaded_files:
        # Skips files that are duplicates, accidentally uploaded triplicate files once.
        file_key = f"{f.name}_{f.size}"
        if file_key not in st.session_state.processed_files:
            df = read_pdf(f.read(), f.name)
            if not df.empty:
                new_dfs.append(df)
                st.session_state.processed_files.add(file_key)

#added due to bug when initially trying to use index lookups. Index lookups not being used but keeping this just in case.
    if new_dfs:
        combined = [st.session_state.data] + new_dfs
        st.session_state.data = pd.concat(combined, ignore_index=True)

all_data = st.session_state.data

if all_data.empty:
    st.info("Upload one or more PDFs to get started.")
    st.stop()

###### Sidebar filters - critical part of making the app useful.
with st.sidebar:
    st.header("Filters")

    # Source file
    sources = ["All Files"] + sorted(all_data["Source"].unique().tolist())
    picked_file = st.selectbox("Source File", sources)

    # Result filter
    show_result = st.radio("Result", ["All", "Pass", "Fail"], horizontal=True)

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

# Apply filters to data
df = all_data.copy()

if picked_file != "All Files":
    df = df[df["Source"] == picked_file]

if show_result != "All":
    df = df[df["Result"] == show_result]

if exclude_warmup:
    df = df[~df["Comment"].str.lower().str.contains("warm")]

if comment_text.strip():
    ct = comment_text.strip().lower()
    if comment_mode == "Contains":
        df = df[df["Comment"].str.lower().str.contains(ct, na=False)]  # na=False prevents crash on empty comment cells
    elif comment_mode == "Exact":
        df = df[df["Comment"].str.lower() == ct]
    elif comment_mode == "Starts with":
        df = df[df["Comment"].str.lower().str.startswith(ct)]

# Summary metrics, not actual results but useful for quick overview if uploading a lot of files.
total = len(all_data)
passes = len(all_data[all_data["Result"] == "Pass"])
fails = len(all_data[all_data["Result"] == "Fail"])
pass_rate = f"{passes / total * 100:.1f}%" if total > 0 else "—"

#Summary metrics columns
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Tests", total)
col2.metric("Passed", passes)
col3.metric("Failed", fails)
col4.metric("Pass Rate", pass_rate)
col5.metric("Showing", len(df))

# Display filtered results in table.
if df.empty:
    st.warning("No results match the current filters.")
else:
    st.dataframe(
        df,
        use_container_width=True,
        height=500,
        hide_index=True,
    )
