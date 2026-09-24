import io
import re
import sqlite3
import pandas as pd
import pytesseract
from PIL import Image, ImageOps
import streamlit as st

# ---------------------------------------------------------
# 1. DATABASE SETUP
# ---------------------------------------------------------
conn = sqlite3.connect("fds.db", check_same_thread=False)
c = conn.cursor()
c.execute("""
    CREATE TABLE IF NOT EXISTS fixed_deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        holder_name TEXT,
        nominee_name TEXT,
        institution_name TEXT, 
        account_fd_no TEXT UNIQUE,
        principal_amount REAL, 
        interest_rate REAL,
        maturity_date TEXT,
        maturity_amount REAL
    )
""")
conn.commit()


# ---------------------------------------------------------
# HELPER FOR SAFE FLOAT CONVERSION
# ---------------------------------------------------------
def safe_float(val_str):
  if not val_str:
    return 0.0
  cleaned = re.sub(r"[^\d\.]", "", str(val_str))
  parts = cleaned.split(".")
  if len(parts) > 2:
    cleaned = parts[0] + "." + "".join(parts[1:])
  try:
    return float(cleaned) if cleaned else 0.0
  except ValueError:
    return 0.0


# ---------------------------------------------------------
# 2. PARSER FOR KAPIL / VEDA GROUP
# ---------------------------------------------------------
def parse_kapil_format(full_text):
  data = {
      "holder_name": "",
      "nominee_name": "",
      "institution_name": "KAPIL PROPERTY DEVELOPERS LTD",
      "account_fd_no": "",
      "principal": 0.0,
      "rate": 0.0,
      "maturity_date": "",
      "maturity_amount": 0.0,
  }

  holder_match = re.search(
      r"Name\(s\)\s*of\s*(?:the)?\s*applicant\s*[\:\-\s]*([A-Z\s\.]{3,50})",
      full_text,
      re.IGNORECASE,
  )
  if holder_match:
    raw_name = holder_match.group(1).strip()
    clean_name = re.sub(
        r"\s*Address.*$", "", raw_name, flags=re.IGNORECASE
    ).strip()
    data["holder_name"] = clean_name

  num_match = re.search(
      r"Certificate\s*No\.?\s*[\:\-\s]*([A-Z0-9\/\-]{8,35})",
      full_text,
      re.IGNORECASE,
  )
  if num_match:
    data["account_fd_no"] = num_match.group(1).strip()

  principal_match = re.search(
      r"Initial\s*advance\s*[\:\-\s]*[Rs\.\₹]*\s*([\d\,]+(?:\.\d{2})?)",
      full_text,
      re.IGNORECASE,
  )
  if principal_match:
    data["principal"] = safe_float(principal_match.group(1))

  row_match = re.search(
      r"(?:1st|1)\s+(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})\s+(\d{1,3})\s+(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})",
      full_text,
      re.IGNORECASE,
  )
  if row_match:
    data["maturity_date"] = row_match.group(3).strip()
  else:
    dates = re.findall(r"\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})\b", full_text)
    if dates:
      data["maturity_date"] = dates[-1]

  monthly_payout = 0.0
  payout_table_match = re.search(r"\b(3[,.]?333|4[,.]?583)\b", full_text)
  if payout_table_match:
    monthly_payout = safe_float(payout_table_match.group(1))

  if data["principal"] > 0 and monthly_payout > 0:
    annual_rate = ((monthly_payout * 12) / data["principal"]) * 100
    data["rate"] = round(annual_rate, 2)
  else:
    data["rate"] = 10.0

  data["maturity_amount"] = data["principal"]
  return data


# ---------------------------------------------------------
# 3. PARSER FOR SHRIRAM FINANCE
# ---------------------------------------------------------
def parse_shriram_format(full_text):
  data = {
      "holder_name": "",
      "nominee_name": "",
      "institution_name": "SHRIRAM FINANCE LIMITED",
      "account_fd_no": "",
      "principal": 0.0,
      "rate": 0.0,
      "maturity_date": "",
      "maturity_amount": 0.0,
  }

  holder_match = re.search(
      r"(?:Name\s*of\s*Depositor|Received\s*with\s*thanks\s*from)\s*[\:\-\s]*(?:MS|MR|MRS)?\s*([A-Z\s\.]{3,40})",
      full_text,
      re.IGNORECASE,
  )
  if holder_match:
    data["holder_name"] = holder_match.group(1).strip()

  dep_match = re.search(
      r"Deposit\s*No[\.\:]?\s*([A-Z0-9\-]{5,20})", full_text, re.IGNORECASE
  )
  if dep_match:
    data["account_fd_no"] = dep_match.group(1).strip()

  principal_match = re.search(
      r"Deposit\s*Amount\s*[\:\-\s]*[Rs\.\₹\*\#]*\s*([\d\,]+(?:\.\d{2})?)",
      full_text,
      re.IGNORECASE,
  )
  if principal_match:
    data["principal"] = safe_float(principal_match.group(1))

  rate_match = re.search(
      r"(?:Rate\s*of\s*Interest|Interest\s*Rate)\s*[\:\-\s]*([\d\.]+)\s*\%",
      full_text,
      re.IGNORECASE,
  )
  if rate_match:
    data["rate"] = safe_float(rate_match.group(1))

  mat_date_match = re.search(
      r"Date\s*of\s*Maturity\s*[\:\-\s]*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})",
      full_text,
      re.IGNORECASE,
  )
  if mat_date_match:
    data["maturity_date"] = mat_date_match.group(1).strip()

  return data


def parse_fd(extracted_text):
  full_text = " ".join(
      [line.strip() for line in extracted_text.split("\n") if line.strip()]
  )
  if "SHRIRAM" in full_text.upper():
    return parse_shriram_format(full_text)
  else:
    return parse_kapil_format(full_text)


@st.cache_data(show_spinner=False)
def process_ocr_cached(image_bytes, rotate_angle):
  img = Image.open(io.BytesIO(image_bytes))
  img = ImageOps.exif_transpose(img)
  if rotate_angle != 0:
    img = img.rotate(-rotate_angle, expand=True)
  text = pytesseract.image_to_string(img, config="--psm 6")
  return parse_fd(text)


# ---------------------------------------------------------
# 4. STREAMLIT UI CONFIG & REFINED AESTHETIC STYLING
# ---------------------------------------------------------
st.set_page_config(
    page_title="FD Portfolio Manager", page_icon="💼", layout="wide"
)

st.markdown(
    """
    <style>
    /* Global Clean Font & Background Settings */
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 3rem !important;
        padding-left: 3rem !important;
        padding-right: 3rem !important;
        background-color: #f8fafc;
    }
    
    /* Modern Header Banner */
    .app-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        color: #ffffff;
        padding: 24px 32px;
        border-radius: 12px;
        margin-bottom: 24px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }
    .app-title {
        font-size: 24px;
        font-weight: 700;
        letter-spacing: -0.025em;
        margin-bottom: 4px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .app-subtitle {
        font-size: 14px;
        color: #94a3b8;
        font-weight: 400;
    }

    /* Metric Cards Styling */
    .metric-card-container {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05);
        transition: all 0.2s ease-in-out;
    }
    .metric-card-container:hover {
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.08);
        border-color: #cbd5e1;
    }
    .metric-label {
        font-size: 11px;
        letter-spacing: 0.05em;
        color: #64748b;
        text-transform: uppercase;
        font-weight: 600;
        margin-bottom: 8px;
    }
    .metric-value {
        font-size: 26px;
        font-weight: 700;
        color: #0f172a;
        letter-spacing: -0.02em;
    }

    /* Custom Table Styling */
    .custom-table-wrapper {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 10px;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05);
        margin-top: 15px;
        overflow-x: auto;
    }
    .custom-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
        text-align: left;
    }
    .custom-table th {
        background-color: #f1f5f9;
        color: #334155;
        padding: 12px 14px;
        font-weight: 600;
        border-bottom: 2px solid #e2e8f0;
        text-transform: uppercase;
        font-size: 11px;
        letter-spacing: 0.04em;
    }
    .custom-table td {
        padding: 14px;
        border-bottom: 1px solid #f1f5f9;
        color: #1e293b;
    }
    .custom-table tr:hover {
        background-color: #f8fafc;
    }
    
    /* Tabs custom polish */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 8px 18px;
        color: #475569;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background-color: #0f172a !important;
        color: #ffffff !important;
        border-color: #0f172a !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# Modern Header Section
st.markdown(
    """
    <div class="app-header">
        <div class="app-title">💼 Fixed Deposit Portfolio Manager</div>
        <div class="app-subtitle">Smart document extraction, structured tracking, and portfolio performance analytics.</div>
    </div>
""",
    unsafe_allow_html=True,
)

# Navigation Tabs
tab1, tab2 = st.tabs(["📊 View Portfolio", "📄 Scan & Add Certificate"])

# ---------------------------------------------------------
# TAB 1: VIEW PORTFOLIO
# ---------------------------------------------------------
with tab1:
  df = pd.read_sql_query(
      "SELECT id, holder_name, institution_name, account_fd_no, principal_amount,"
      " interest_rate, maturity_date FROM fixed_deposits",
      conn,
  )

  if not df.empty:
    df["monthly_interest"] = (
        df["principal_amount"] * (df["interest_rate"] / 100)
    ) / 12

    total_deposits = len(df)
    total_principal = df["principal_amount"].sum()
    total_monthly_interest = df["monthly_interest"].sum()
    weighted_rate = (
        (df["principal_amount"] * df["interest_rate"]).sum() / total_principal
        if total_principal > 0
        else 0.0
    )

    # Metric Cards Layout
    c1, c2, c3, c4 = st.columns(4)
    with c1:
      st.markdown(
          f"""<div class="metric-card-container"><div"
          " class="metric-label">Total Deposits</div><div"
          " class="metric-value">{total_deposits}</div></div>""",
          unsafe_allow_html=True,
      )
    with c2:
      st.markdown(
          f"""<div class="metric-card-container"><div"
          " class="metric-label">Total Principal</div><div"
          " class="metric-value">₹{total_principal:,.2f}</div></div>""",
          unsafe_allow_html=True,
      )
    with c3:
      st.markdown(
          f"""<div class="metric-card-container"><div"
          " class="metric-label">Monthly Interest</div><div"
          " class="metric-value">₹{total_monthly_interest:,.2f}</div></div>""",
          unsafe_allow_html=True,
      )
    with c4:
      st.markdown(
          f"""<div class="metric-card-container"><div"
          " class="metric-label">Weighted ROI</div><div"
          " class="metric-value">{weighted_rate:.2f}%</div></div>""",
          unsafe_allow_html=True,
      )

    st.write("")
    st.write("")

    # Clean HTML Data Table
    table_html = """
        <div class="custom-table-wrapper">
        <table class="custom-table">
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Holder Name</th>
                    <th>Institution</th>
                    <th>FD / Cert No.</th>
                    <th>Principal (₹)</th>
                    <th>ROI (%)</th>
                    <th>Maturity Date</th>
                    <th>Monthly Interest (₹)</th>
                </tr>
            </thead>
            <tbody>
        """
    for _, row in df.iterrows():
      table_html += f"""
            <tr>
                <td><b>{row['id']}</b></td>
                <td>{row['holder_name']}</td>
                <td>{row['institution_name']}</td>
                <td><code>{row['account_fd_no']}</code></td>
                <td>₹{row['principal_amount']:,.2f}</td>
                <td><span style="color: #059669; font-weight: 600;">{row['interest_rate']:.2f}%</span></td>
                <td>{row['maturity_date']}</td>
                <td><b>₹{row['monthly_interest']:,.2f}</b></td>
            </tr>
        """
    table_html += "</tbody></table></div>"
    st.markdown(table_html, unsafe_allow_html=True)
  else:
    st.info("No fixed deposit records saved yet. Use the scan tab to add one.")

# ---------------------------------------------------------
# TAB 2: SCAN & ADD CERTIFICATE
# ---------------------------------------------------------
with tab2:
  col_left, col_right = st.columns(2, gap="large")

  with col_left:
    st.markdown("### 1. Upload Certificate Image")
    uploaded_file = st.file_uploader(
        "Choose an image of your FD / Deposit Receipt",
        type=["png", "jpg", "jpeg"],
    )
    extracted = None

    if uploaded_file:
      rotate_angle = st.radio(
          "Rotate Image Orientation:",
          [0, 90, 180, 270],
          horizontal=True,
          index=0,
      )
      file_bytes = uploaded_file.getvalue()

      img_preview = Image.open(io.BytesIO(file_bytes))
      img_preview = ImageOps.exif_transpose(img_preview)
      if rotate_angle != 0:
        img_preview = img_preview.rotate(-rotate_angle, expand=True)
      st.image(
          img_preview,
          caption="Processed Receipt Preview",
          use_container_width=True,
      )

      with st.spinner("Extracting details with OCR..."):
        extracted = process_ocr_cached(file_bytes, rotate_angle)

  with col_right:
    st.markdown("### 2. Verify & Save Details")
    if uploaded_file and extracted:
      with st.form("fd_entry_form"):
        holder = st.text_input(
            "Holder Name", value=extracted.get("holder_name", "")
        )
        nominee = st.text_input(
            "Nominee Name", value=extracted.get("nominee_name", "")
        )
        inst = st.text_input(
            "Institution Name", value=extracted.get("institution_name", "")
        )
        fd_no = st.text_input(
            "Certificate Number", value=extracted.get("account_fd_no", "")
        )

        sc1, sc2 = st.columns(2)
        principal = sc1.number_input(
            "Principal Amount (₹)",
            value=float(extracted.get("principal", 0.0)),
        )
        rate = sc2.number_input(
            "Interest Rate - ROI (%)",
            value=float(extracted.get("rate", 0.0)),
        )

        mat_date = st.text_input(
            "Maturity Date", value=extracted.get("maturity_date", "")
        )

        st.write("")
        submit_btn = st.form_submit_button(
            "💾 Save FD Record to Database", use_container_width=True
        )

        if submit_btn:
          try:
            c.execute(
                """
                INSERT INTO fixed_deposits (holder_name, nominee_name, institution_name, account_fd_no, principal_amount, interest_rate, maturity_date, maturity_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    holder,
                    nominee,
                    inst,
                    fd_no,
                    principal,
                    rate,
                    mat_date,
                    principal,
                ),
            )
            conn.commit()
            st.success(
                "Record successfully saved! Switch to 'View Portfolio' tab to"
                " check."
            )
          except sqlite3.IntegrityError:
            st.error("This Certificate Number already exists in the database.")
    else:
      st.info(
          "Please upload a certificate image on the left to extract details"
          " automatically."
      )
