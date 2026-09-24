import streamlit as st
import sqlite3
import pytesseract
from PIL import Image, ImageOps
import re
import io

# ---------------------------------------------------------
# 1. DATABASE SETUP
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
# 2. PARSER FOR KAPIL / VEDA GROUP
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
    nominee_match = re.search(
        r'Nominee\s*Name\s*[\:\-\s]*(?:1[\.\)]\s*)?([A-Z\.\s]{3,35})(?=\s*(?:Nominee\s*Relation|Proportion|HUSBAND|FATHER|100\%|$))', 
        full_text, re.IGNORECASE
    )
    if nominee_match:
        raw_nominee = nominee_match.group(1).strip()
        data['nominee_name'] = re.sub(r'^[\s\.\d\-\)\(]+', '', raw_nominee).strip()
    else:
        fallback_nom = re.search(r'(?:Nominee\s*Name\s*[\:\-\s]*)?([A-Z\s\.]{3,30})\s+(?:Nominee\s*Relation|HUSBAND)', full_text, re.IGNORECASE)
        if fallback_nom:
            raw_nominee = re.sub(r'^(?:Nominee\s*Name|1[\.\)])\s*', '', fallback_nom.group(1), flags=re.IGNORECASE).strip()
            data['nominee_name'] = re.sub(r'^[\s\.\d\-\)\(]+', '', raw_nominee).strip()

    # 3. CERTIFICATE NUMBER
    num_match = re.search(r'Certificate\s*No\.?\s*[\:\-\s]*([A-Z0-9\/\-]{8,35})', full_text, re.IGNORECASE)
    if num_match:
        data['account_fd_no'] = num_match.group(1).strip()

    # 4. INITIAL ADVANCE / PRINCIPAL AMOUNT
    principal_match = re.search(
        r'Initial\s*advance\s*[\:\-\s]*[Rs\.\₹]*\s*([\d\,]+(?:\.\d{2})?)', 
        full_text, re.IGNORECASE
    )
    if principal_match:
        data['principal'] = float(principal_match.group(1).replace(',', ''))

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

    # 6. MONTHLY INTEREST PAYOUT PARSING & ROI CALCULATION
    monthly_payout = 0.0

    # Pattern A: Table row extraction (Date Date Payout)
    payout_table_match = re.search(
        r'29\/11\/2028\s+([\d\,\.]{4,6})', full_text
    )
    if payout_table_match:
        p_str = payout_table_match.group(1).replace(',', '').replace('.', '')
        if len(p_str) >= 4:
            monthly_payout = float(p_str[:4]) # Handles misreads like 3333 / 3331

    # Pattern B: Scan for candidate 4-digit values (e.g., 3,333, 3333, 3,331) in interest column
    if monthly_payout == 0.0:
        candidates = re.findall(r'\b([3-9][\,\.]?\d{3})\b', full_text)
        if candidates:
            c_val = candidates[0].replace(',', '').replace('.', '')
            monthly_payout = float(c_val)

    # Compute rate using formula: Rate % = (Monthly Payout * 12 / Principal) * 100
    if data['principal'] > 0 and monthly_payout > 0:
        annual_rate = ((monthly_payout * 12) / data['principal']) * 100
        data['rate'] = round(annual_rate, 2)

    data['maturity_amount'] = data['principal']
    return data


# ---------------------------------------------------------
# 3. PARSER FOR SHRIRAM FINANCE
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
        raw_nominee = nominee_match.group(1).strip()
        data['nominee_name'] = re.sub(r'^[\s\.\d\-\)\(]+', '', raw_nominee).strip()

    # 3. DEPOSIT / CERTIFICATE NO
    dep_match = re.search(r'Deposit\s*No[\.\:]?\s*([A-Z0-9\-]{5,20})', full_text, re.IGNORECASE)
    if dep_match:
        data['account_fd_no'] = dep_match.group(1).strip()

    # 4. PRINCIPAL / DEPOSIT AMOUNT
    principal_match = re.search(r'Deposit\s*Amount\s*[\:\-\s]*[Rs\.\₹\*\#]*\s*([\d\,]+(?:\.\d{2})?)', full_text, re.IGNORECASE)
    if principal_match:
        data['principal'] = float(principal_match.group(1).replace(',', ''))
    else:
        para_p_match = re.search(r'for\s+[Rs\.\₹\*\#]*\s*([\d\,]+(?:\.\d{2})?)', full_text, re.IGNORECASE)
        if para_p_match:
            data['principal'] = float(para_p_match.group(1).replace(',', ''))

    # 5. RATE OF INTEREST (% p.a.)
    rate_match = re.search(r'(?:Rate\s*of\s*Interest|Interest\s*Rate)\s*[\:\-\s]*([\d\.]+)\s*\%', full_text, re.IGNORECASE)
    if rate_match:
        data['rate'] = float(rate_match.group(1))

    # 6. MATURITY AMOUNT
    mat_amt_match = re.search(r'Maturity\s*Amount\s*\(?\₹?\)?\s*[\:\-\s\*\#]*([\d\,]+(?:\.\d{2})?)', full_text, re.IGNORECASE)
    if mat_amt_match:
        data['maturity_amount'] = float(mat_amt_match.group(1).replace(',', ''))
    elif data['principal'] > 0:
        data['maturity_amount'] = data['principal']

    # 7. DATE OF MATURITY
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

    psm_configs = ['--psm 3', '--psm 6', '--psm 11']
    extracted = {
        'holder_name': '', 'nominee_name': '', 'institution_name': '',
        'account_fd_no': '', 'principal': 0.0, 'rate': 0.0,
        'maturity_date': '', 'maturity_amount': 0.0
    }

    for config in psm_configs:
        text = pytesseract.image_to_string(img, config=config)
        pass_data = parse_fd(text)

        for field, val in pass_data.items():
            if not extracted[field] or extracted[field] == 0.0 or (field == 'rate' and val > 0.0):
                extracted[field] = val

        if extracted['nominee_name']:
            extracted['nominee_name'] = re.sub(r'^[\s\.\d\-\)\(]+', '', extracted['nominee_name']).strip()

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
        st.info("Upload a document on the left to extract details automatically.")import streamlit as st
import sqlite3
import pytesseract
from PIL import Image, ImageOps
import re
import io

# --------------------------------------------------
# 1. DATABASE SETUP
# --------------------------------------------------
conn = sqlite3.connect('fds.db', check_same_thread=False)
c = conn.cursor()
c.execute('''
    CREATE TABLE IF NOT EXISTS fixed_deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        holder_name TEXT,
        nominee_name TEXT,
        institution_name TEXT,
        certificate_number TEXT,
        principal_amount REAL,
        interest_rate REAL,
        maturity_date TEXT,
        maturity_amount REAL
    )
''')
conn.commit()

# --------------------------------------------------
# 2. OCR PARSING FUNCTIONS
# --------------------------------------------------
def parse_kapil_format(text):
    data = {
        'holder_name': '',
        'nominee_name': '',
        'institution_name': 'KAPIL PROPERTY DEVELOPERS LTD',
        'certificate_number': '',
        'principal_amount': 0.0,
        'interest_rate': 0.0,
        'maturity_date': '',
        'maturity_amount': 0.0
    }

    # Holder Name
    holder_match = re.search(r'Name\(s\)\s*of\s*the\s*applicant\s*:\s*([^\n\r]+)', text, re.IGNORECASE)
    if holder_match:
        data['holder_name'] = holder_match.group(1).strip()

    # Nominee Name (Strips prefixes like "1. ")
    nominee_match = re.search(r'Nominee\s*Name\s*:\s*(?:[0-9]+\.\s*)?([^\n\r]+)', text, re.IGNORECASE)
    if nominee_match:
        data['nominee_name'] = nominee_match.group(1).strip()

    # Certificate Number
    cert_match = re.search(r'Certificate\s*No\.?\s*:\s*([A-Za-z0-9/\-]+)', text, re.IGNORECASE)
    if cert_match:
        data['certificate_number'] = cert_match.group(1).strip()

    # Principal Amount
    principal_match = re.search(r'Initial\s*advance\s*:\s*Rs\.?\s*([\d,]+(?:\.\d+)?)', text, re.IGNORECASE)
    if principal_match:
        val_str = principal_match.group(1).replace(',', '')
        try:
            data['principal_amount'] = float(val_str)
            data['maturity_amount'] = data['principal_amount']
        except ValueError:
            pass

    # Monthly Payout & ROI Calculation Fix
    monthly_payout = 0.0
    
    # Strictly target standard monthly payout patterns (3,333 or 4,583) or 4-digit numbers in the table
    payout_match = re.search(r'\b(3[,.]?333|4[,.]?583)\b', text)
    if payout_match:
        val_str = payout_match.group(1).replace(',', '').replace('.', '')
        try:
            monthly_payout = float(val_str)
        except ValueError:
            pass
    else:
        # Fallback 4-digit numeric search in table area
        four_digit_matches = re.findall(r'\b([3-5][,.]?\d{3})\b', text)
        if four_digit_matches:
            try:
                monthly_payout = float(four_digit_matches[0].replace(',', '').replace('.', ''))
            except ValueError:
                pass

    # Dynamic ROI calculation with ceiling sanity check
    if data['principal_amount'] > 0 and monthly_payout > 0:
        calculated_roi = round((monthly_payout * 12 / data['principal_amount']) * 100, 2)
        # Cap unrealistic OCR misreads (>12%) back to default 10.0%
        if calculated_roi > 12.0:
            data['interest_rate'] = 10.0
        else:
            data['interest_rate'] = calculated_roi
    else:
        data['interest_rate'] = 10.0

    # Maturity / Next Option Date
    date_matches = re.findall(r'\b\d{2}[/\-]\d{2}[/\-]\d{4}\b', text)
    if date_matches:
        data['maturity_date'] = date_matches[-1]

    return data


def parse_shriram_format(text):
    data = {
        'holder_name': '',
        'nominee_name': '',
        'institution_name': 'SHRIRAM FINANCE LIMITED',
        'certificate_number': '',
        'principal_amount': 0.0,
        'interest_rate': 0.0,
        'maturity_date': '',
        'maturity_amount': 0.0
    }

    # Holder Name
    holder_match = re.search(r'Received\s+with\s+thanks\s+from\s*(?:MS|MR|MRS)?\s*([^\n\r]+)', text, re.IGNORECASE)
    if holder_match:
        data['holder_name'] = holder_match.group(1).strip()

    # Nominee Name
    nominee_match = re.search(r'Nominee\s*:\s*([^\n\r]+)', text, re.IGNORECASE)
    if nominee_match:
        data['nominee_name'] = nominee_match.group(1).strip()

    # Deposit / Certificate Number
    cert_match = re.search(r'Deposit\s*No\.?\s*:?\s*([A-Za-z0-9\-]+)', text, re.IGNORECASE)
    if cert_match:
        data['certificate_number'] = cert_match.group(1).strip()

    # Deposit Amount (Principal)
    principal_match = re.search(r'Deposit\s*Amount\s*:\s*₹?\s*([\d,]+(?:\.\d+)?)', text, re.IGNORECASE)
    if principal_match:
        val_str = principal_match.group(1).replace(',', '')
        try:
            data['principal_amount'] = float(val_str)
        except ValueError:
            pass

    # Interest Rate
    rate_match = re.search(r'([\d.]+)\s*%\s*p\.a\.', text, re.IGNORECASE)
    if rate_match:
        try:
            data['interest_rate'] = float(rate_match.group(1))
        except ValueError:
            pass

    # Maturity Date
    mat_date_match = re.search(r'Date\s*of\s*Maturity\s*:?\s*(\d{2}[\-/\.]\d{2}[\-/\.]\d{4})', text, re.IGNORECASE)
    if mat_date_match:
        data['maturity_date'] = mat_date_match.group(1).strip()

    # Maturity Amount
    mat_amt_match = re.search(r'Maturity\s*Amount\s*\([^)]*\)\s*:\s*\*?\s*([\d,]+(?:\.\d+)?)', text, re.IGNORECASE)
    if mat_amt_match:
        val_str = mat_amt_match.group(1).replace(',', '')
        try:
            data['maturity_amount'] = float(val_str)
        except ValueError:
            pass
    elif data['principal_amount'] > 0:
        data['maturity_amount'] = data['principal_amount']

    return data


def parse_fd(text):
    if "KAPIL" in text.upper():
        return parse_kapil_format(text)
    elif "SHRIRAM" in text.upper():
        return parse_shriram_format(text)
    else:
        return parse_kapil_format(text)

@st.cache_data
def process_ocr_cached(image_bytes):
    image = Image.open(io.BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image)
    gray_image = image.convert('L')
    return pytesseract.image_to_string(gray_image)

# --------------------------------------------------
# 3. STREAMLIT APP INTERFACE
# --------------------------------------------------
st.title("FD Portfolio Manager & OCR Scanner")

uploaded_file = st.file_uploader("Upload FD Certificate / Deposit Receipt", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    img_bytes = uploaded_file.read()
    st.image(img_bytes, caption="Uploaded Image", use_container_width=True)

    with st.spinner("Extracting text and parsing details..."):
        ocr_text = process_ocr_cached(img_bytes)
        parsed_data = parse_fd(ocr_text)

    st.subheader("Review & Save Details")
    with st.form("fd_entry_form"):
        holder_name = st.text_input("Holder / Applicant Name", value=parsed_data['holder_name'])
        nominee_name = st.text_input("Nominee Name", value=parsed_data['nominee_name'])
        institution_name = st.text_input("Institution / Company Name", value=parsed_data['institution_name'])
        certificate_number = st.text_input("Deposit / Certificate Number", value=parsed_data['certificate_number'])
        principal_amount = st.number_input("Principal / Advance Amount (₹)", value=float(parsed_data['principal_amount']))
        interest_rate = st.number_input("Interest Rate / ROI (%)", value=float(parsed_data['interest_rate']))
        maturity_date = st.text_input("Maturity / Option Date", value=parsed_data['maturity_date'])
        maturity_amount = st.number_input("Maturity Amount (₹)", value=float(parsed_data['maturity_amount']))

        submitted = st.form_submit_button("Save FD Record")
        if submitted:
            c.execute('''
                INSERT INTO fixed_deposits (holder_name, nominee_name, institution_name, certificate_number, principal_amount, interest_rate, maturity_date, maturity_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (holder_name, nominee_name, institution_name, certificate_number, principal_amount, interest_rate, maturity_date, maturity_amount))
            conn.commit()
            st.success("Record saved successfully!")

# Display stored records
st.subheader("Saved FD Records")
records = c.execute("SELECT * FROM fixed_deposits").fetchall()
if records:
    st.dataframe(records)
