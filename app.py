import io
import re
import sqlite3
import pandas as pd
import pytesseract
import streamlit as st
from PIL import Image, ImageOps

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

  nominee_match = re.search(
      r"Nominee\s*Name\s*[\:\-\s]*(?:1[\.\)]\s*)?([A-Z\.\s]{3,35})(?=\s*(?:Nominee\s*Relation|Proportion|HUSBAND|FATHER|100\%|$))",
      full_text,
      re.IGNORECASE,
  )
  if nominee_match:
    raw_nominee = nominee_match.group(1).strip()
    data["nominee_name"] = re.sub(r"^[\s\.\d\-\)\(]+", "", raw_nominee).strip()
  else:
    fallback_nom = re.search(
        r"(?:Nominee\s*Name\s*[\:\-\s]*)?([A-Z\s\.]{3,30})\s+(?:Nominee\s*Relation|HUSBAND)",
        full_text,
        re.IGNORECASE,
    )
    if fallback_nom:
      raw_nominee = re.sub(
          r"^(?:Nominee\s*Name|1[\.\)])\s*",
          "",
          fallback_nom.group(1),
          flags=re.IGNORECASE,
      ).strip()
      data["nominee_name"] = re.sub(
          r"^[\s\.\d\-\)\(]+", "", raw_nominee
      ).strip()

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

  # Updated row match to capture the Next Option Date (Group 3)
  row_match = re.search(
      r"(?:1st|1)\s+(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})\s+(\d{1,3})\s+(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})\s+([\d,]+(?:\.\d{2})?)",
      full_text,
      re.IGNORECASE,
  )
  if row_match:
    data["maturity_date"] = row_match.group(3).strip()
  else:
    dates = re.findall(r"\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})\b", full_text)
    if len(dates) >= 2:
      data["maturity_date"] = dates[1]
    elif dates:
      data["maturity_date"] = dates[-1]

  monthly_payout = 0.0
  payout_table_match = re.search(r"\b(3[,.]?333|4[,.]?583|3[,.]?750)\b", full_text)
  if payout_table_match:
    monthly_payout = safe_float(payout_table_match.group(1))
  else:
    candidates = re.findall(r"\b([3-6]\d{3})\b", full_text)
    if candidates:
      monthly_payout = safe_float(candidates[0])

  if data["principal"] > 0 and monthly_payout > 0:
    annual_rate = ((monthly_payout * 12) / data["principal"]) * 100
    calculated_roi = round(annual_rate, 2)
    if 8.0 <= calculated_roi <= 12.0:
      data["rate"] = calculated_roi
    else:
      data["rate"] = 10.0
  elif data["principal"] > 0:
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
      r"(?:Name\s*of\s*Depositor|Received\s*with\s*thanks\s*from)\s*[\:\-\s]*(?:MS|MR|MRS)?\s*([A-Z\s\.]{3,40})(?=\s+(?:Customer|Address|PAN|HNO|SANSKRUTI|GUARDIAN|\d))",
      full_text,
      re.IGNORECASE,
  )
  if holder_match:
    data["holder_name"] = holder_match.group(1).strip()

  nominee_match = re.search(
      r"Nominee\s*[\:\-\s]*([A-Z\s\.]{3,35})(?=\s+(?:Guardian|Jointly|Acknowledgement))",
      full_text,
      re.IGNORECASE,
  )
  if nominee_match:
    raw_nominee = nominee_match.group(1).strip()
    data["nominee_name"] = re.sub(r"^[\s\.\d\-\)\(]+", "", raw_nominee).strip()

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
  else:
    para_p_match = re.search(
        r"for\s+[Rs\.\₹\*\#]*\s*([\d\,]+(?:\.\d{2})?)", full_text, re.IGNORECASE
    )
    if para_p_match:
      data["principal"] = safe_float(para_p_match.group(1))

  rate_match = re.search(
      r"(?:Rate\s*of\s*Interest|Interest\s*Rate)\s*[\:\-\s]*([\d\.]+)\s*\%",
      full_text,
      re.IGNORECASE,
  )
  if rate_match:
    data["rate"] = safe_float(rate_match.group(1))

  mat_amt_match = re.search(
      r"Maturity\s*Amount\s*\(?\₹?\)?\s*[\:\-\s\*\#]*([\d\,]+(?:\.\d{2})?)",
      full_text,
      re.IGNORECASE,
  )
  if mat_amt_match:
    data["maturity_amount"] = safe_float(mat_amt_match.group(1))
  elif data["principal"] > 0:
    data["maturity_amount"] = data["principal"]

  mat_date_match = re.search(
      r"Date\s*of\s*Maturity\s*[\:\-\s]*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})",
      full_text,
      re.IGNORECASE,
  )
  if mat_date_match:
    data["maturity_date"] = mat_date_match.group(1).strip()

  return data


# ---------------------------------------------------------
# 4. DISPATCHER ROUTER
# ---------------------------------------------------------
def parse_fd(extracted_text):
  lines = [line.strip() for line in extracted_text.split("\n") if line.strip()]
  full_text = " ".join(lines)
  text_upper = full_text.upper()

  if "SHRIRAM" in text_upper:
    return parse_shriram_format(full_text)
  else:
    return parse_kapil_format(full_text)


# ---------------------------------------------------------
# 5. MULTI-PASS RETRY OCR ENGINE
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def process_ocr_cached(image_bytes, rotate_angle):
  img = Image.open(io.BytesIO(image_bytes))
  img = ImageOps.exif_transpose(img)
  if rotate_angle != 0:
    img = img.rotate(-rotate_angle, expand=True)

  psm_configs = ["--psm 3", "--psm 6", "--psm 11"]
  extracted = {
      "holder_name": "",
      "nominee_name": "",
      "institution_name": "",
      "account_fd_no": "",
      "principal": 0.0,
      "rate": 0.0,
      "maturity_date": "",
      "maturity_amount": 0.0,
  }

  for config in psm_configs:
    text = pytesseract.image_to_string(img, config=config)
    pass_data = parse_fd(text)

    for field, val in pass_data.items():
      if (
          not extracted[field]
          or extracted[field] == 0.0
          or (field == "rate" and val > 0.0)
      ):
        extracted[field] = val

    if extracted["nominee_name"]:
      extracted["nominee_name"] = re.sub(
          r"^[\s\.\d\-\)\(]+", "", extracted["nominee_name"]
      ).strip()

    is_complete = all([
        extracted["holder_name"],
        extracted["nominee_name"],
        extracted["institution_name"],
        extracted["account_fd_no"],
        extracted["principal"] > 0,
        extracted["rate"] > 0,
        extracted["maturity_date"],
        extracted["maturity_amount"] > 0,
    ])

    if is_complete:
      break

  return extracted


# ---------------------------------------------------------
# 6. STREAMLIT UI SETUP & COMPACT AESTHETIC STYLING
# ---------------------------------------------------------
st.set_page_config(
    page_title="FD Portfolio Manager",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 0.8rem !important;
            padding-bottom: 0.5rem !important;
            padding-left: 1.5rem !important;
            padding-right: 1.5rem !important;
        }
        .stApp {
            background-color: #F8FAFC;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        .header-hero {
            background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
            color: #FFFFFF;
            padding: 0.75rem 1.25rem;
            border-radius: 10px;
            margin-bottom: 0.75rem;
            box-shadow: 0 4px 12px rgba(15, 23, 42, 0.1);
        }
        .header-hero h1 {
            color: #F8FAFC !important;
            font-weight: 700 !important;
            font-size: 1.35rem !important;
            margin: 0 !important;
        }
        .header-hero p {
            color: #94A3B8;
            font-size: 0.8rem;
            margin-top: 0.15rem;
            margin-bottom: 0;
        }
        div[data-testid="stMetric"] {
            background-color: #FFFFFF;
            padding: 0.4rem 0.8rem;
            border-radius: 8px;
            border: 1px solid #E2E8F0;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.02);
        }
        div[data-testid="stMetricLabel"] {
            color: #64748B !important;
            font-size: 0.7rem !important;
            font-weight: 600 !important;
            text-transform: uppercase;
        }
        div[data-testid="stMetricValue"] {
            color: #0F172A !important;
            font-size: 1.15rem !important;
            font-weight: 700 !important;
        }
        div[data-testid="stForm"] {
            background-color: #FFFFFF;
            padding: 0.8rem;
            border-radius: 8px;
            border: 1px solid #E2E8F0;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 6px;
        }
        .stTabs [data-baseweb="tab"] {
            height: 34px;
            border-radius: 6px;
            padding: 0 14px;
            font-weight: 600;
            font-size: 0.85rem;
        }
        .stTabs [aria-selected="true"] {
            background-color: #2563EB !important;
            color: #FFFFFF !important;
        }
        hr {
            margin: 0.5rem 0 !important;
        }
        h2, h3 {
            margin-top: 0.2rem !important;
            margin-bottom: 0.4rem !important;
            font-size: 1.1rem !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="header-hero">
        <h1>💼 Fixed Deposit Portfolio Manager</h1>
        <p>Smart document extraction, structured tracking, and portfolio performance analytics.</p>
    </div>
""",
    unsafe_allow_html=True,
)

tab1, tab2 = st.tabs(["📊 View Portfolio", "📄 Scan & Add Certificate"])

# --- TAB 1: PORTFOLIO & ANALYTICS ---
with tab1:
  df = pd.read_sql_query(
      "SELECT id, holder_name, nominee_name, institution_name, account_fd_no, "
      "principal_amount, interest_rate, maturity_date, maturity_amount FROM"
      " fixed_deposits",
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

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Deposits", total_deposits)
    m2.metric("Total Principal", f"₹{total_principal:,.2f}")
    m3.metric("Monthly Interest", f"₹{total_monthly_interest:,.2f}")
    m4.metric("Weighted ROI", f"{weighted_rate:.2f}%")

    df_display = (
        df.drop(columns=["nominee_name", "maturity_amount"])
        .rename(
            columns={
                "id": "ID",
                "holder_name": "Holder Name",
                "institution_name": "Institution",
                "account_fd_no": "FD / Cert No.",
                "principal_amount": "Principal (₹)",
                "interest_rate": "ROI (%)",
                "maturity_date": "Maturity Date",
                "monthly_interest": "Monthly Interest (₹)",
            }
        )
        .round({"Monthly Interest (₹)": 2})
    )

    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        height=210,
        column_config={
            "ID": st.column_config.NumberColumn("ID", width="small"),
            "Holder Name": st.column_config.TextColumn(
                "Holder Name", width="medium"
            ),
            "Institution": st.column_config.TextColumn(
                "Institution", width="medium"
            ),
            "FD / Cert No.": st.column_config.TextColumn(
                "FD / Cert No.", width="medium"
            ),
            "Principal (₹)": st.column_config.NumberColumn(
                "Principal (₹)", format="₹%,.2f", width="medium"
            ),
            "ROI (%)": st.column_config.NumberColumn(
                "ROI (%)", format="%.2f%%", width="small"
            ),
            "Maturity Date": st.column_config.TextColumn(
                "Maturity Date", width="small"
            ),
            "Monthly Interest (₹)": st.column_config.NumberColumn(
                "Monthly Interest (₹)", format="₹%,.2f", width="medium"
            ),
        },
    )

    col_edit, col_del = st.columns(2, gap="large")

    with col_edit:
      with st.expander("✏️ Update a Record"):
        edit_id = st.number_input(
            "Record ID to Edit",
            min_value=int(df["id"].min()),
            max_value=int(df["id"].max()),
            step=1,
            key="edit_id_input",
        )

        record_to_edit = df[df["id"] == edit_id]

        if not record_to_edit.empty:
          rec = record_to_edit.iloc[0]
          with st.form("edit_fd_form"):
            e_holder = st.text_input(
                "Holder Name", value=str(rec["holder_name"])
            )
            e_nominee = st.text_input(
                "Nominee Name", value=str(rec["nominee_name"])
            )
            e_inst = st.text_input(
                "Institution Name", value=str(rec["institution_name"])
            )
            e_fd_no = st.text_input(
                "Deposit / Certificate Number", value=str(rec["account_fd_no"])
            )

            e_c1, e_c2 = st.columns(2)
            e_principal = e_c1.number_input(
                "Principal (₹)", value=float(rec["principal_amount"])
            )
            e_rate = e_c2.number_input(
                "ROI (%)", value=float(rec["interest_rate"])
            )

            e_c3, e_c4 = st.columns(2)
            e_mat_date = e_c3.text_input(
                "Maturity Date", value=str(rec["maturity_date"])
            )
            e_monthly_int = e_c4.number_input(
                "Monthly Interest Amount (₹)",
                value=round(float(rec["monthly_interest"]), 2),
            )

            update_button = st.form_submit_button(
                "🔄 Update Record", use_container_width=True
            )

            if update_button:
              try:
                c.execute(
                    """
                                UPDATE fixed_deposits
                                SET holder_name = ?, nominee_name = ?, institution_name = ?,
                                    account_fd_no = ?, principal_amount = ?, interest_rate = ?,
                                    maturity_date = ?
                                WHERE id = ?
                            """,
                    (
                        e_holder,
                        e_nominee,
                        e_inst,
                        e_fd_no,
                        e_principal,
                        e_rate,
                        e_mat_date,
                        int(edit_id),
                    ),
                )
                conn.commit()
                st.success(f"Record #{edit_id} updated successfully!")
                st.rerun()
              except sqlite3.IntegrityError:
                st.error("Certificate Number conflict.")

    with col_del:
      with st.expander("🗑️ Delete a Record"):
        del_id = st.number_input(
            "Record ID to delete", min_value=1, step=1, key="del_id_input"
        )
        if st.button("Delete Record", use_container_width=True):
          c.execute("DELETE FROM fixed_deposits WHERE id = ?", (del_id,))
          conn.commit()
          st.success(f"Record #{del_id} deleted successfully.")
          st.rerun()
  else:
    st.info("No fixed deposit records saved yet.")


# --- TAB 2: SCAN & ADD ---
with tab2:
  col_left, col_right = st.columns([1, 1], gap="large")

  with col_left:
    st.subheader("1. Scan Certificate Image")
    uploaded_file = st.file_uploader(
        "Upload FD / Deposit Receipt", type=["png", "jpg", "jpeg"]
    )

    if uploaded_file:
      rotate_angle = st.radio(
          "Rotate Image:", [0, 90, 180, 270], horizontal=True, index=0
      )
      file_bytes = uploaded_file.getvalue()
      img_preview = Image.open(io.BytesIO(file_bytes))
      img_preview = ImageOps.exif_transpose(img_preview)
      if rotate_angle != 0:
        img_preview = img_preview.rotate(-rotate_angle, expand=True)
      st.image(
          img_preview, caption="Processed Image", use_container_width=True
      )

      with st.spinner("Scanning document..."):
        extracted = process_ocr_cached(file_bytes, rotate_angle)

  with col_right:
    st.subheader("2. Review & Save Details")
    if uploaded_file:
      with st.form("fd_entry_form"):
        holder = st.text_input(
            "Holder / Applicant Name", value=extracted["holder_name"]
        )
        nominee = st.text_input("Nominee Name", value=extracted["nominee_name"])
        inst = st.text_input(
            "Institution / Company Name", value=extracted["institution_name"]
        )
        fd_no = st.text_input(
            "Deposit / Certificate Number", value=extracted["account_fd_no"]
        )

        c1, c2 = st.columns(2)
        principal = c1.number_input(
            "Principal (₹)", value=extracted["principal"]
        )
        rate = c2.number_input("ROI (%)", value=extracted["rate"])

        est_monthly_interest = (principal * (rate / 100)) / 12

        c3, c4 = st.columns(2)
        mat_date = c3.text_input(
            "Maturity Date", value=extracted["maturity_date"]
        )
        monthly_interest_input = c4.number_input(
            "Monthly Interest Amount (₹)",
            value=round(est_monthly_interest, 2),
        )

        submit_button = st.form_submit_button(
            "💾 Save FD Record", use_container_width=True
        )

        if submit_button:
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
            st.success("Record successfully saved!")
            st.rerun()
          except sqlite3.IntegrityError:
            st.error("This Certificate/FD Number already exists.")
    else:
      st.info("Upload a document on the left to extract details.")
