import streamlit as st
import sqlite3
import pytesseract
from PIL import Image, ImageOps
import re
import io

# ---------------------------------------------------------
# 1. CONSTANTS & RELATION KEYWORDS
# ---------------------------------------------------------
RELATION_KEYWORDS = {
    'HUSBAND', 'WIFE', 'FATHER', 'MOTHER', 'SON', 
    'DAUGHTER', 'SPOUSE', 'BROTHER', 'SISTER', '100%', 'PROPORTION'
}

# ---------------------------------------------------------
# 2. DATABASE SETUP
# ---------------------------------------------------------
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
# 3. HELPER FUNCTIONS
# ---------------------------------------------------------
def safe_float(val_str):
    if not val_str:
        return 0.0
    cleaned = re.sub(r'[^\d\.]', '', str(val_str))
    parts = cleaned.split('.')
    if len(parts) > 2:
        cleaned = parts[0] + '.' + ''.join(parts[1:])
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def clean_nominee_val(raw_str):
    if not raw_str:
        return ""
    cleaned = re.sub(r'^[\s\.\d\-\)\(\:]+', '', raw_str).strip()
    cleaned = re.sub(
        r'\s+(?:Nominee\s*Relation|Relation|HUSBAND|FATHER|WIFE|MOTHER|SON|DAUGHTER|Proportion|100\%|\d{1,3}\%).*$', 
        '', cleaned, flags=re.IGNORECASE
    ).strip()
    
    if cleaned.upper() in RELATION_KEYWORDS or len(cleaned) < 3:
        return ""
    return cleaned


# ---------------------------------------------------------
# 4. KAPIL / VEDA GROUP PARSER
# ---------------------------------------------------------
def parse_kapil_format(full_text):
    data = {
        'holder_name': '', 
        'nominee_name': '', 
        'institution_name': 'KAPIL PROPERTY DEVELOPERS LTD',
        'account_fd_no': '', 
        'principal': 0.0, 
        'rate': 0.0,
        'maturity_date': '', 
        'maturity_amount': 0.0
    }

    # 1. HOLDER / APPLICANT NAME
    holder_match = re.search(
        r'Name\(s\)\s*of\s*(?:the)?\s*applicant\s*[\:\-\s]*([A-Z\s\.]{3,50})', 
        full_text, re.IGNORECASE
    )
    if holder_match:
        raw_name = holder_match.group(1).strip()
        clean_name = re.sub(r'\s*Address.*$', '', raw_name, flags=re.IGNORECASE).strip()
        data['holder_name'] = clean_name

    # 2. NOMINEE NAME
    nom_match = re.search(
        r'1[\.\)]\s*([A-Z\.\s]{3,35})(?=\s*(?:Nominee\s*Relation|HUSBAND|FATHER|WIFE|MOTHER|100\%|\d{1,3}\%|$))', 
        full_text, re.IGNORECASE
    )
    if nom_match:
        data['nominee_name'] = clean_nominee_val(nom_match.group(1))

    if not data['nominee_name']:
        sec_match = re.search(r'Nominee\s*Name\s*[\:\-\s]*([A-Z0-9\.\s]{3,35})', full_text, re.IGNORECASE)
        if sec_match:
            data['nominee_name'] = clean_nominee_val(sec_match.group(1))

    # 3. CERTIFICATE NUMBER
    num_match = re.search(r'Certificate\s*No\.?\s*[\:\-\s]*([A-Z0-9\/\-]{8,35})', full_text, re.IGNORECASE)
    if num_match:
        data['account_fd_no'] = num_match.group(1).strip()

    # 4. INITIAL ADVANCE / PRINCIPAL
    principal_match = re.search(
        r'Initial\s*advance\s*[\:\-\s]*[Rs\.\₹]*\s*([\d\,]+(?:\.\d{2})?)', 
        full_text, re.IGNORECASE
    )
    if principal_match:
        data['principal'] = safe_float(principal_match.group(1))

    # 5. MATURITY DATE
    row_match = re.search(
        r'(?:1st|1)\s+(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})\s+(\d{1,3})\s+(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})', 
        full_text, re.IGNORECASE
    )
    if row_match:
        data['maturity_date'] = row_match.group(3).strip()
    else:
        dates = re.findall(r'\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})\b', full_text)
        if dates:
            data['maturity_date'] = dates[-1]

    # 6. MONTHLY INTEREST PAYOUT & ROI
    monthly_payout = 0.0
    payout_table_match = re.search(r'\b(3[,.]?333|4[,.]?583|6[,.]?667)\b', full_text)
    if payout_table_match:
        monthly_payout = safe_float(payout_table_match.group(1))

    if data['principal'] > 0 and monthly_payout > 0:
        annual_rate = ((monthly_payout * 12) / data['principal']) * 100
        calculated_roi = round(annual_rate, 2)
        data['rate'] = calculated_roi if 8.0 <= calculated_roi <= 14.0 else 10.0
    elif data['principal'] > 0:
        data['rate'] = 10.0

    data['maturity_amount'] = data['principal']
    return data


# ---------------------------------------------------------
# 5. SHRIRAM FINANCE PARSER
# ---------------------------------------------------------
def parse_shriram_format(full_text):
    data = {
        'holder_name': '', 
        'nominee_name': '', 
        'institution_name': 'SHRIRAM FINANCE LIMITED',
        'account_fd_no': '', 
        'principal': 0.0, 
        'rate': 0.0,
        'maturity_date': '', 
        'maturity_amount': 0.0
    }

    holder_match = re.search(
        r'(?:Name\s*of\s*Depositor|Received\s*with\s*thanks\s*from)\s*[\:\-\s]*(?:MS|MR|MRS)?\s*([A-Z\s\.]{3,40})(?=\s+(?:Customer|Address|PAN|HNO|SANSKRUTI|GUARDIAN|\d))', 
        full_text, re.IGNORECASE
    )
    if holder_match:
        data['holder_name'] = holder_match.group(1).strip()

    nominee_match = re.search(r'Nominee\s*[\:\-\s]*([A-Z\s\.]{3,35})(?=\s+(?:Guardian|Jointly|Acknowledgement))', full_text, re.IGNORECASE)
    if nominee_match:
        data['nominee_name'] = clean_nominee_val(nominee_match.group(1))

    dep_match = re.search(r'Deposit\s*No[\.\:]?\s*([A-Z0-9\-]{5,20})', full_text, re.IGNORECASE)
    if dep_match:
        data['account_fd_no'] = dep_match.group(1).strip()

    principal_match = re.search(r'Deposit\s*Amount\s*[\:\-\s]*[Rs\.\₹\*\#]*\s*([\d\,]+(?:\.\d{2})?)', full_text, re.IGNORECASE)
    if principal_match:
        data['principal'] = safe_float(principal_match.group(1))

    rate_match = re.search(r'(?:Rate\s*of\s*Interest|Interest\s*Rate)\s*[\:\-\s]*([\d\.]+)\s*\%', full_text, re.IGNORECASE)
    if rate_match:
        data['rate'] = safe_float(rate_match.group(1))

    mat_amt_match = re.search(r'Maturity\s*Amount\s*\(?\₹?\)?\s*[\:\-\s\*\#]*([\d\,]+(?:\.\d{2})?)', full_text, re.IGNORECASE)
    if mat_amt_match:
        data['maturity_amount'] = safe_float(mat_amt_match.group(1))
    elif data['principal'] > 0:
        data['maturity_amount'] = data['principal']

    mat_date_match = re.search(r'Date\s*of\s*Maturity\s*[\:\-\s]*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})', full_text, re.IGNORECASE)
    if mat_date_match:
        data['maturity_date'] = mat_date_match.group(1).strip()

    return data


# ---------------------------------------------------------
# 6. ROUTER & MULTI-PASS OCR ENGINE
# ---------------------------------------------------------
def parse_fd(extracted_text):
    lines = [line.strip() for line in extracted_text.split('\n') if line.strip()]
    full_text = " ".join(lines)
    if "SHRIRAM" in full_text.upper():
        return parse_shriram_format(full_text)
    return parse_kapil_format(full_text)


@st.cache_data(show_spinner=False)
def process_ocr_cached(image_bytes, rotate_angle):
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)
    if rotate_angle != 0:
        img = img.rotate(-rotate_angle, expand=True)

    extracted = {
        'holder_name': '', 'nominee_name': '', 'institution_name': '',
        'account_fd_no': '', 'principal': 0.0, 'rate': 0.0,
        'maturity_date': '', 'maturity_amount': 0.0
    }

    psm_configs = ['--psm 3', '--psm 6', '--psm 4', '--psm 11']
    for config in psm_configs:
        text = pytesseract.image_to_string(img, config=config)
        pass_data = parse_fd(text)

        for field, val in pass_data.items():
            if field == 'nominee_name':
                if val and val.upper() not in RELATION_KEYWORDS:
                    extracted['nominee_name'] = val
            elif not extracted[field] or extracted[field] == 0.0 or (field == 'rate' and val > 0.0):
                extracted[field] = val

        if extracted['nominee_name'] and extracted['nominee_name'].upper() not in RELATION_KEYWORDS:
            break

    # Bottom 30% Crop fallback for Nominee section
    if not extracted['nominee_name'] or extracted['nominee_name'].upper() in RELATION_KEYWORDS:
        width, height = img.size
        bottom_crop = img.crop((0, int(height * 0.70), width, height))
        
        for config in ['--psm 6', '--psm 11', '--psm 3']:
            crop_text = pytesseract.image_to_string(bottom_crop, config=config)
            nom_match = re.search(
                r'1[\.\)]\s*([A-Z\.\s]{3,35})(?=\s*(?:HUSBAND|FATHER|WIFE|MOTHER|100\%|\d{1,3}\%|$))', 
                crop_text, re.IGNORECASE
            )
            if nom_match:
                cand = clean_nominee_val(nom_match.group(1))
                if cand:
                    extracted['nominee_name'] = cand
                    break

    return extracted


# ---------------------------------------------------------
# 7. STREAMLIT UI
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
        
        with st.spinner("Scanning document details..."):
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
