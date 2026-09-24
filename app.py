import streamlit as st
import sqlite3
import pytesseract
from PIL import Image, ImageOps
import re
from datetime import datetime
import io

# 1. DATABASE SETUP
conn = sqlite3.connect('fds.db', check_same_thread=False)
c = conn.cursor()
c.execute('''
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
''')
conn.commit()

# 2. MULTI-PASS PARSER (Retries until all fields are populated)
def parse_fd(extracted_text):
    data = {
        'holder_name': '', 'nominee_name': '', 'institution_name': '',
        'account_fd_no': '', 'principal': 0.0, 'rate': 0.0,
        'maturity_date': '', 'maturity_amount': 0.0
    }

    # Clean text lines
    lines = [line.strip() for line in extracted_text.split('\n') if line.strip()]
    full_text = " ".join(lines)

    # 1. INSTITUTION NAME
    top_text = " ".join(lines[:12])
    inst_match = re.search(r'(KAPIL\s+[A-Z0-9\s\,\.]{3,50}\s+(?:LIMITED|LTD|GROUP|DEVELOPERS|CONSTRUCTIONS))', top_text, re.IGNORECASE)
    if not inst_match:
        inst_match = re.search(r'([A-Z0-9\s\,\.]{3,50}\s+(?:LIMITED|LTD|FINANCE|DEVELOPERS|BANK|CORPORATION|SERVICES))', top_text, re.IGNORECASE)
    
    if inst_match:
        clean_inst = re.sub(r'^(MEMBER|GROUP)\s+', '', inst_match.group(1).strip(), flags=re.IGNORECASE)
        data['institution_name'] = clean_inst.upper()
    else:
        for line in lines[:5]:
            if len(line) > 5 and line.isupper() and not any(kw in line.lower() for kw in ['certificate', 'advance', 'receipt', 'application', 'member']):
                data['institution_name'] = line.strip()
                break

    # 2. HOLDER / APPLICANT NAME
    holder_match = re.search(
        r'(?:Name\s*\(?s\)?\s*of\s*(?:the)?\s*applicant|Depositor\s*Name|Holder\s*Name|Applicant)\s*[\:\-\s]+([A-Z\s\.]{3,40})(?=\s+(?:Address|Date|Father|Husband|Customer|S/o|D/o|W/o|H\.NO|\d))', 
        full_text, re.IGNORECASE
    )
    if holder_match:
        data['holder_name'] = holder_match.group(1).strip()
    else:
        # Secondary fallback for applicant line
        app_line = re.search(r'applicant\s*[\:\s]+([A-Z\s\.]{4,35})', full_text, re.IGNORECASE)
        if app_line:
            data['holder_name'] = app_line.group(1).strip()

    # 3. NOMINEE NAME
    nominee_match = re.search(
        r'Nominee\s*Name\s*[\:\-\s]*(?:1[\.\)]|a[\.\)])?\s*([A-Z\.\s]{3,35})(?=\s+(?:Nominee\s*Relation|Relation|HUSBAND|WIFE|FATHER|MOTHER|SON|DAUGHTER|Proportion|100\%|\d))', 
        full_text, re.IGNORECASE
    )
    if nominee_match and nominee_match.group(1).strip().upper() not in ["NOMINEE", "NOMINEE NAME"]:
        clean_nominee = re.sub(r'^(?:1[\.\)]|a[\.\)]|\d+\.)\s*', '', nominee_match.group(1).strip(), flags=re.IGNORECASE)
        data['nominee_name'] = clean_nominee.strip()
    else:
        # Anchor by relationship word
        rel_match = re.search(r'(?:1[\.\)]|\d+\.)?\s*([A-Z][A-Z\.\s]{2,30})\s+(?:HUSBAND|WIFE|FATHER|MOTHER|SON|DAUGHTER)', full_text)
        if rel_match:
            candidate = rel_match.group(1).strip()
            if candidate.upper() not in ["NOMINEE NAME", "NOMINEE", "RELATION"]:
                data['nominee_name'] = candidate

    # 4. CERTIFICATE / RECEIPT NUMBER
    num_match = re.search(
        r'(?:Certificate\s*No\.?|Receipt\s*No\.?|Deposit\s*No\.?|Ref\s*No\.?)\s*[\:\-\s]+([A-Z0-9\/\-\_]{5,30})', 
        full_text, re.IGNORECASE
    )
    if num_match:
        data['account_fd_no'] = num_match.group(1).strip()
    else:
        code_match = re.search(r'\b([A-Z]{3,8}\/[A-Z0-9\/\-]{5,25})\b', full_text)
        if code_match:
            data['account_fd_no'] = code_match.group(1).strip()

    # 5. PRINCIPAL AMOUNT
    principal_match = re.search(
        r'(?:Initial\s*advance|Total\s*advance|Deposit\s*Amount|Principal\s*Amount|Sum\s*of)[\:\s]*[Rs\.\₹]*\s*([\d\,]+(?:\.\d{2})?)', 
        full_text, re.IGNORECASE
    )
    if principal_match:
        data['principal'] = float(principal_match.group(1).replace(',', ''))

    # 6. INTEREST RATE CALCULATION
    rate_match = re.search(r'(?:Rate\s*of\s*Interest|ROI|Interest\s*Rate|Rate)[\:\s]*([\d\.]+)\s*\%', full_text, re.IGNORECASE)
    if rate_match:
        data['rate'] = float(rate_match.group(1))
    elif data['principal'] > 0:
        monthly_match = re.search(
            r'(?:Interest\s*Amount|Monthly\s*Interest|Monthly|Advance\s*Payout)[\:\s]*[Rs\.\₹]*\s*([\d\,]+(?:\.\d{2})?)', 
            full_text, re.IGNORECASE
        )
        if monthly_match:
            monthly_val = float(monthly_match.group(1).replace(',', ''))
            data['rate'] = round(((monthly_val * 12) / data['principal']) * 100, 2)

    # 7. MATURITY / NEXT OPTION DATE
    mat_match = re.search(
        r'(?:Next\s*Option\s*Date|Maturity\s*Date|Date\s*of\s*Maturity|Option\s*Date)[\:\s]*([\d]{2}[\/\-\.][\d]{2}[\/\-\.][\d]{2,4})', 
        full_text, re.IGNORECASE
    )
    if mat_match:
        data['maturity_date'] = mat_match.group(1)
    else:
        all_dates = re.findall(r'\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})\b', full_text)
        if all_dates:
            data['maturity_date'] = all_dates[-1]

    # 8. MATURITY AMOUNT
    mat_amt_match = re.search(
        r'(?:Maturity\s*Amount|Maturity\s*Value)[\:\s]*[Rs\.\₹]*\s*([\d\,]+(?:\.\d{2})?)', 
        full_text, re.IGNORECASE
    )
    if mat_amt_match:
        data['maturity_amount'] = float(mat_amt_match.group(1).replace(',', ''))
    elif data['principal'] > 0:
        data['maturity_amount'] = data['principal']

    return data

# 3. CACHED MULTI-PASS OCR ENGINE
@st.cache_data(show_spinner=False)
def process_ocr_cached(image_bytes, rotate_angle):
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)
    if rotate_angle != 0:
        img = img.rotate(-rotate_angle, expand=True)

    # Pass 1: Standard Auto Layout Detection
    text_pass1 = pytesseract.image_to_string(img, config='--psm 3')
    extracted = parse_fd(text_pass1)

    # Check if critical fields were missed; run Pass 2 with PSM 4 if needed
    if not extracted['holder_name'] or extracted['principal'] == 0.0:
        text_pass2 = pytesseract.image_to_string(img, config='--psm 4')
        extracted_p2 = parse_fd(text_pass2)
        
        # Merge results from Pass 2 if missing in Pass 1
        for k, v in extracted_p2.items():
            if not extracted[k] or extracted[k] == 0.0:
                extracted[k] = v

    return extracted

# 4. STREAMLIT UI SETUP
st.set_page_config(page_title="FD Portfolio Manager", layout="wide")
st.title("💼 Fixed Deposit Portfolio Manager")

st.markdown("---")
col_left, col_right = st.columns([1, 1], gap="large")

with col_left:
    st.subheader("1. Scan Certificate Image")
    uploaded_file = st.file_uploader("Upload FD / Deposit Receipt (JPG/PNG)", type=['png', 'jpg', 'jpeg'])
    
    if uploaded_file:
        rotate_angle = st.radio("Rotate Image if Sideways:", [0, 90, 180, 270], horizontal=True, index=0)
        
        file_bytes = uploaded_file.getvalue()
        img_preview = Image.open(io.BytesIO(file_bytes))
        img_preview = ImageOps.exif_transpose(img_preview)
        if rotate_angle != 0:
            img_preview = img_preview.rotate(-rotate_angle, expand=True)
        st.image(img_preview, caption="Processed Image for Scanning", use_container_width=True)
        
        with st.spinner("Scanning and extracting text details..."):
            extracted = process_ocr_cached(file_bytes, rotate_angle)

with col_right:
    st.subheader("2. Review & Save Details")
    if uploaded_file:
        with st.form("fd_entry_form"):
            holder = st.text_input("Holder / Applicant Name", value=extracted['holder_name'])
            nominee = st.text_input("Nominee Name", value=extracted['nominee_name'])
            inst = st.text_input("Institution / Company Name", value=extracted['institution_name'])
            fd_no = st.text_input("Deposit / Certificate Number", value=extracted['account_fd_no'])
            
            c1, c2 = st.columns(2)
            principal = c1.number_input("Principal / Advance Amount (₹)", value=extracted['principal'])
            rate = c2.number_input("Interest Rate / ROI (%)", value=extracted['rate'])
            
            c3, c4 = st.columns(2)
            mat_date = c3.text_input("Maturity / Option Date", value=extracted['maturity_date'])
            mat_amt = c4.number_input("Maturity Amount (₹)", value=extracted['maturity_amount'])

            submit_button = st.form_submit_button("💾 Save FD Record", use_container_width=True)

            if submit_button:
                try:
                    c.execute('''
                        INSERT INTO fixed_deposits (holder_name, nominee_name, institution_name, account_fd_no, principal_amount, interest_rate, maturity_date, maturity_amount)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (holder, nominee, inst, fd_no, principal, rate, mat_date, mat_amt))
                    conn.commit()
                    st.success("Record successfully saved!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("This Certificate/FD Number already exists in your database.")
    else:
        st.info("Upload a document on the left to extract details automatically.")

st.markdown("---")
st.subheader("📊 Stored Portfolio Holdings")
rows = c.execute("SELECT * FROM fixed_deposits").fetchall()

if rows:
    total_principal = sum(row[5] for row in rows)
    st.metric(label="Total Portfolio Value (Principal)", value=f"₹{total_principal:,.2f}")
    
    for row in rows:
        with st.expander(f"📌 **{row[1]}** | {row[3]} ({row[4]})"):
            c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
            c1.write(f"**Principal:** ₹{row[5]:,.2f}")
            c1.write(f"**Rate:** {row[6]}%")
            c2.write(f"**Nominee:** {row[2] if row[2] else 'N/A'}")
            c2.write(f"**Maturity Amount:** ₹{row[8]:,.2f}")
            c3.write(f"**Maturity Date:** {row[7]}")
            
            if c4.button("Delete", key=f"del_{row[0]}", type="primary"):
                c.execute("DELETE FROM fixed_deposits WHERE id=?", (row[0],))
                conn.commit()
                st.rerun()
else:
    st.write("No records saved yet.")
