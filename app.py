import streamlit as st
import sqlite3
import pytesseract
from PIL import Image, ImageOps
import re
from datetime import datetime

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

# 2. DYNAMIC OCR TEXT PARSER
def parse_fd(extracted_text):
    data = {
        'holder_name': '', 'nominee_name': '', 'institution_name': '',
        'account_fd_no': '', 'principal': 0.0, 'rate': 0.0,
        'maturity_date': '', 'maturity_amount': 0.0
    }

    lines = [line.strip() for line in extracted_text.split('\n') if line.strip()]
    full_text = " ".join(lines)

    # 1. DYNAMIC INSTITUTION NAME
    # Matches prominent header text ending in corporate designations (LTD, LIMITED, FINANCE, BANK, DEVELOPERS, etc.)
    inst_match = re.search(r'([A-Z0-9\s\,\.]{3,50}\s+(?:LIMITED|LTD|FINANCE|DEVELOPERS|BANK|CORPORATION|SERVICES))', full_text, re.IGNORECASE)
    if inst_match:
        data['institution_name'] = re.sub(r'\s+', ' ', inst_match.group(1)).strip().upper()
    else:
        # Fallback to first bold/capital line if no standard corporate suffix found
        for line in lines[:5]:
            if len(line) > 5 and line.isupper() and not any(kw in line.lower() for kw in ['certificate', 'advance', 'receipt', 'application']):
                data['institution_name'] = line.strip()
                break

    # 2. DYNAMIC HOLDER / APPLICANT NAME
    holder_match = re.search(
        r'(?:Name\s*\(?s\)?\s*of\s*(?:the)?\s*applicant|Depositor\s*Name|Holder\s*Name|Client\s*Name)\s*[\:\-\s]+([A-Z\s\.]{3,40})(?=\s+(?:Address|Date|Father|Husband|Customer|S/o|D/o|W/o|\d))', 
        full_text, re.IGNORECASE
    )
    if holder_match:
        data['holder_name'] = holder_match.group(1).strip()

    # 3. DYNAMIC NOMINEE NAME
    # Matches text following "Nominee Name" or "Nominee" until relationship/guardian keywords
    nominee_match = re.search(
        r'(?:Nominee\s*Name|Nominee)\s*[\:\-\s]+([A-Z\s\.]{3,35})(?=\s+(?:Nominee\s*Relation|Relation|Guardian|HUSBAND|WIFE|FATHER|MOTHER|SON|DAUGHTER|MAJOR|MINOR|\d))', 
        full_text, re.IGNORECASE
    )
    if nominee_match:
        data['nominee_name'] = nominee_match.group(1).strip()

    # 4. CERTIFICATE / RECEIPT NUMBER
    num_match = re.search(
        r'(?:Certificate\s*No\.?|Receipt\s*No\.?|Deposit\s*No\.?|Account\s*No\.?|Ref\s*No\.?)\s*[\:\-\s]+([A-Z0-9\/\-\_]{5,30})', 
        full_text, re.IGNORECASE
    )
    if num_match:
        data['account_fd_no'] = num_match.group(1).strip()
    else:
        # Search for alpha-numeric document identifiers containing slashes or hyphens
        code_match = re.search(r'\b([A-Z]{3,8}\/[A-Z0-9\/\-]{5,25})\b', full_text)
        if code_match:
            data['account_fd_no'] = code_match.group(1).strip()

    # 5. DYNAMIC PRINCIPAL AMOUNT
    principal_match = re.search(
        r'(?:Total\s*advance|Deposit\s*Amount|Initial\s*advance|Principal\s*Amount|Amount\s*Received|Sum\s*of)[\:\s]*[Rs\.\₹]*\s*([\d,]+(?:\.\d{2})?)', 
        full_text, re.IGNORECASE
    )
    if principal_match:
        data['principal'] = float(principal_match.group(1).replace(',', ''))

    # 6. DYNAMIC INTEREST RATE CALCULATION
    # First attempt: Find explicit ROI percentage
    rate_match = re.search(r'(?:Rate\s*of\s*Interest|ROI|Interest\s*Rate|Rate)[\:\s]*([\d\.]+)\s*\%', full_text, re.IGNORECASE)
    if rate_match:
        data['rate'] = float(rate_match.group(1))
    elif data['principal'] > 0:
        # Second attempt: Dynamic calculation from monthly/periodic interest payout amounts
        monthly_match = re.search(
            r'(?:Monthly\s*Interest|Monthly\s*Payout|Interest\s*Amount|Advance\s*Payout|Monthly)[\:\s]*[Rs\.\₹]*\s*([\d,]+(?:\.\d{2})?)', 
            full_text, re.IGNORECASE
        )
        if monthly_match:
            monthly_val = float(monthly_match.group(1).replace(',', ''))
            # Dynamic ROI formula: (Monthly Interest * 12 / Principal) * 100
            calculated_rate = ((monthly_val * 12) / data['principal']) * 100
            data['rate'] = round(calculated_rate, 2)

    # 7. DYNAMIC MATURITY / NEXT OPTION DATE
    # Matches dates associated with "Next Option Date", "Maturity Date", or "Expiry Date"
    mat_match = re.search(
        r'(?:Next\s*Option\s*Date|Maturity\s*Date|Date\s*of\s*Maturity|Option\s*Date|Valid\s*Upto)[\:\s]*([\d]{2}[\/\-\.][\d]{2}[\/\-\.][\d]{2,4})', 
        full_text, re.IGNORECASE
    )
    if mat_match:
        data['maturity_date'] = mat_match.group(1)
    else:
        # Fallback: Extract all dates found in document and select the furthest date into the future
        all_dates = re.findall(r'\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})\b', full_text)
        parsed_dates = []
        for d in all_dates:
            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"):
                try:
                    parsed_dates.append((datetime.strptime(d, fmt), d))
                    break
                except ValueError:
                    pass
        if parsed_dates:
            # Pick the furthest date found
            parsed_dates.sort(key=lambda x: x[0])
            data['maturity_date'] = parsed_dates[-1][1]

    # 8. MATURITY AMOUNT
    mat_amt_match = re.search(
        r'(?:Maturity\s*Amount|Maturity\s*Value|Maturity\s*Payable)[\:\s]*[Rs\.\₹]*\s*([\d,]+(?:\.\d{2})?)', 
        full_text, re.IGNORECASE
    )
    if mat_amt_match:
        data['maturity_amount'] = float(mat_amt_match.group(1).replace(',', ''))
    elif data['principal'] > 0:
        data['maturity_amount'] = data['principal']

    return data

# 3. STREAMLIT UI SETUP
st.set_page_config(page_title="FD Portfolio Manager", layout="wide")
st.title("💼 Fixed Deposit Portfolio Manager")

st.markdown("---")
col_left, col_right = st.columns([1, 1], gap="large")

with col_left:
    st.subheader("1. Scan Certificate Image")
    uploaded_file = st.file_uploader("Upload FD / Deposit Receipt (JPG/PNG)", type=['png', 'jpg', 'jpeg'])
    
    if uploaded_file:
        image = Image.open(uploaded_file)
        image = ImageOps.exif_transpose(image)
        
        # Rotation controls for misaligned uploads
        rotate_angle = st.radio("Rotate Image if Sideways:", [0, 90, 180, 270], horizontal=True, index=1)
        if rotate_angle != 0:
            image = image.rotate(-rotate_angle, expand=True)

        st.image(image, caption="Processed Image for Scanning", use_container_width=True)
        
        with st.spinner("Extracting text details..."):
            extracted_text = pytesseract.image_to_string(image)
            extracted = parse_fd(extracted_text)

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
