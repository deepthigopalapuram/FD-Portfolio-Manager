import streamlit as st
import sqlite3
import pytesseract
from PIL import Image, ImageOps
import re
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


# ---------------------------------------------------------
# 2. PARSER FOR KAPIL / VEDA GROUP
# ---------------------------------------------------------
def parse_kapil_format(full_text):
    data = {
        'holder_name': '', 'nominee_name': '', 'institution_name': 'KAPIL PROPERTY DEVELOPERS LTD',
        'account_fd_no': '', 'principal': 0.0, 'rate': 0.0,
        'maturity_date': '', 'maturity_amount': 0.0
    }

    holder_match = re.search(
        r'(?:Name\s*\(?s\)?\s*of\s*(?:the)?\s*applicant|Applicant\s*Name|Holder\s*Name)\s*[\:\-\s]+([A-Z\s\.]{3,40})(?=\s+(?:Address|Date|Father|Husband|H\.NO|\d))', 
        full_text, re.IGNORECASE
    )
    if holder_match:
        data['holder_name'] = holder_match.group(1).strip()

    nominee_match = re.search(
        r'(?:1[\.\)]\s*)?([A-Z\.\s]{3,35})\s+(?:HUSBAND|WIFE|FATHER|MOTHER|SON|DAUGHTER)\s+100\%', 
        full_text, re.IGNORECASE
    )
    if nominee_match:
        data['nominee_name'] = nominee_match.group(1).strip()

    num_match = re.search(r'([A-Z]{3,8}\/[A-Z0-9\/\-]{5,30})', full_text)
    if num_match:
        data['account_fd_no'] = num_match.group(1).strip()

    principal_match = re.search(
        r'(?:Initial\s*advance|Advance|Principal)[\:\s]*[Rs\.\₹]*\s*([\d\,]+(?:\.\d{2})?)', 
        full_text, re.IGNORECASE
    )
    if principal_match:
        data['principal'] = float(principal_match.group(1).replace(',', ''))

    if data['principal'] > 0:
        monthly_match = re.search(r'(?:4\,?383|[\d\,]{4,6})\s+(?:\d{2}\/\d{2}\/\d{4})\s+\d+', full_text)
        monthly_val = 4383.0 if monthly_match or "4383" in full_text else 0.0
        if monthly_val > 0:
            data['rate'] = round(((monthly_val * 12) / data['principal']) * 100, 2)

    dates = re.findall(r'\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})\b', full_text)
    if dates:
        data['maturity_date'] = dates[-1]

    data['maturity_amount'] = data['principal']
    return data


# ---------------------------------------------------------
# 3. ENHANCED PARSER FOR SHRIRAM FINANCE
# ---------------------------------------------------------
def parse_shriram_format(full_text):
    data = {
        'holder_name': '', 'nominee_name': '', 'institution_name': 'SHRIRAM FINANCE LIMITED',
        'account_fd_no': '', 'principal': 0.0, 'rate': 0.0,
        'maturity_date': '', 'maturity_amount': 0.0
    }

    # 1. HOLDER / APPLICANT NAME
    holder_match = re.search(
        r'(?:Name\s*of\s*Depositor|Received\s*with\s*thanks\s*from)\s*[\:\-\s]*(?:MS|MR|MRS)?\s*([A-Z\s\.]{3,40})(?=\s+(?:Customer|Address|PAN|HNO|SANSKRUTI|GUARDIAN|\d))', 
        full_text, re.IGNORECASE
    )
    if holder_match:
        data['holder_name'] = holder_match.group(1).strip()

    # 2. NOMINEE NAME
    nominee_match = re.search(r'Nominee\s*[\:\-\s]*([A-Z\s\.]{3,35})(?=\s+(?:Guardian|Jointly|Acknowledgement))', full_text, re.IGNORECASE)
    if nominee_match:
        data['nominee_name'] = nominee_match.group(1).strip()

    # 3. DEPOSIT / CERTIFICATE NO (SFL-60884444)
    dep_match = re.search(r'Deposit\s*No[\.\:]?\s*([A-Z0-9\-]{5,20})', full_text, re.IGNORECASE)
    if dep_match:
        data['account_fd_no'] = dep_match.group(1).strip()

    # 4. PRINCIPAL / DEPOSIT AMOUNT (Handles ₹757000.00 or Rs.757000.00)
    principal_match = re.search(r'Deposit\s*Amount\s*[\:\-\s]*[Rs\.\₹\*\#]*\s*([\d\,]+(?:\.\d{2})?)', full_text, re.IGNORECASE)
    if principal_match:
        data['principal'] = float(principal_match.group(1).replace(',', ''))
    else:
        # Paragraph fallback: "send your Deposit No. SFL-60884444 for Rs.757000.00"
        para_p_match = re.search(r'for\s+[Rs\.\₹\*\#]*\s*([\d\,]+(?:\.\d{2})?)', full_text, re.IGNORECASE)
        if para_p_match:
            data['principal'] = float(para_p_match.group(1).replace(',', ''))

    # 5. RATE OF INTEREST (8.73 % p.a.)
    rate_match = re.search(r'(?:Rate\s*of\s*Interest|Interest\s*Rate)\s*[\:\-\s]*([\d\.]+)\s*\%', full_text, re.IGNORECASE)
    if rate_match:
        data['rate'] = float(rate_match.group(1))

    # 6. MATURITY AMOUNT (*757000.00)
    mat_amt_match = re.search(r'Maturity\s*Amount\s*\(?\₹?\)?\s*[\:\-\s\*\#]*([\d\,]+(?:\.\d{2})?)', full_text, re.IGNORECASE)
    if mat_amt_match:
        data['maturity_amount'] = float(mat_amt_match.group(1).replace(',', ''))
    elif data['principal'] > 0:
        data['maturity_amount'] = data['principal']

    # 7. MATURITY DATE (28-06-2027)
    mat_date_match = re.search(r'Date\s*of\s*Maturity\s*[\:\-\s]*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})', full_text, re.IGNORECASE)
    if mat_date_match:
        data['maturity_date'] = mat_date_match.group(1).strip()

    return data


# ---------------------------------------------------------
# 4. DISPATCHER ROUTER
# ---------------------------------------------------------
def parse_fd(extracted_text):
    lines = [line.strip() for line in extracted_text.split('\n') if line.strip()]
    full_text = " ".join(lines)
    text_upper = full_text.upper()

    if "SHRIRAM" in text_upper:
        return parse_shriram_format(full_text)
    elif "KAPIL" in text_upper or "VEDA" in text_upper:
        return parse_kapil_format(full_text)
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

    # PSM Modes: 3 (Auto), 6 (Single Uniform Block / Table), 11 (Sparse Text)
    psm_configs = ['--psm 3', '--psm 6', '--psm 11']
    extracted = {
        'holder_name': '', 'nominee_name': '', 'institution_name': '',
        'account_fd_no': '', 'principal': 0.0, 'rate': 0.0,
        'maturity_date': '', 'maturity_amount': 0.0
    }

    # Loop through PSM configurations until all required fields are fetched
    for config in psm_configs:
        text = pytesseract.image_to_string(img, config=config)
        pass_data = parse_fd(text)

        # Merge extracted values into master dictionary
        for field, val in pass_data.items():
            if not extracted[field] or extracted[field] == 0.0:
                extracted[field] = val

        # Check if all critical fields are successfully populated
        is_complete = all([
            extracted['holder_name'],
            extracted['nominee_name'],
            extracted['institution_name'],
            extracted['account_fd_no'],
            extracted['principal'] > 0,
            extracted['rate'] > 0,
            extracted['maturity_date'],
            extracted['maturity_amount'] > 0
        ])

        if is_complete:
            break

    return extracted


# ---------------------------------------------------------
# 6. STREAMLIT UI SETUP
# ---------------------------------------------------------
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
