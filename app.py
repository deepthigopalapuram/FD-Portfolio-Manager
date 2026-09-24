import streamlit as st
import sqlite3
import pytesseract
from PIL import Image, ImageOps
import re

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

# 2. CUSTOM PARSER FOR KAPIL PROPERTY & OTHER FD RECEIPTS
def parse_fd(extracted_text):
    data = {
        'holder_name': '', 'nominee_name': '', 'institution_name': '',
        'account_fd_no': '', 'principal': 0.0, 'rate': 0.0,
        'maturity_date': '', 'maturity_amount': 0.0
    }

    # Normalize extracted text line by line
    lines = [line.strip() for line in extracted_text.split('\n') if line.strip()]
    full_text = " ".join(lines)

    # 1. Institution Name
    if re.search(r'KAPIL', full_text, re.IGNORECASE):
        data['institution_name'] = "KAPIL PROPERTY DEVELOPERS LTD"
    else:
        inst = re.search(r'(SHRIRAM\s+FINANCE|HDFC|ICICI|SBI|AXIS|CANARA|KOTAK)', full_text, re.IGNORECASE)
        if inst:
            data['institution_name'] = inst.group(0).upper().strip()

    # 2. Holder / Applicant Name
    holder = re.search(r'(?:Name\s*\(s\)\s*of\s*the\s*applicant|Depositor)\s*[\:\-\s]+([A-Z\s]{4,40})(?=\s+Address|\s+Date|\s+Father|\s+Customer)', full_text, re.IGNORECASE)
    if holder:
        data['holder_name'] = holder.group(1).strip()

    # 3. Nominee Name
    nominee = re.search(r'(?:Nominee\s*Name|Nominee)\s*[\:\-\s]*([A-Z\.\s]{3,35})(?=\s+Nominee|\s+Relation|\s+HUSBAND|\s+WIFE|\s+FATHER|\s+MOTHER|\s+SON)', full_text, re.IGNORECASE)
    if nominee:
        clean_nominee = nominee.group(1).strip()
        if len(clean_nominee) > 2 and not clean_nominee.isupper():
            clean_nominee = clean_nominee.upper()
        data['nominee_name'] = clean_nominee
    else:
        # Fallback search for G. DURGA PRASAD pattern
        fallback_nominee = re.search(r'([A-Z]\.?\s*[A-Z\s]{3,30})(?=\s+HUSBAND|\s+WIFE)', full_text)
        if fallback_nominee:
            data['nominee_name'] = fallback_nominee.group(1).strip()

    # 4. Certificate / Receipt Number
    num = re.search(r'(?:SAHRB\/KPD[A-Z0-9\/\-]+|[A-Z0-9]{4,}\/[A-Z0-9\/\-]+)', full_text)
    if num:
        data['account_fd_no'] = num.group(0).strip()
    else:
        num_alt = re.search(r'(?:Deposit\s*No\.?|Certificate\s*No\.?|Receipt\s*No\.?)\s*[\:\-\s]+([A-Z0-9\/\-]+)', full_text, re.IGNORECASE)
        if num_alt:
            data['account_fd_no'] = num_alt.group(1).strip()

    # 5. Principal Amount
    principal = re.search(r'(?:Total\s*advance|Deposit\s*Amount|Initial\s*advance|Principal)[\:\s]*[Rs\.\₹]*\s*([\d,]+(?:\.\d{2})?)', full_text, re.IGNORECASE)
    if principal:
        data['principal'] = float(principal.group(1).replace(',', ''))

    # 6. Interest Rate Calculation (Monthly Interest -> Annual ROI %)
    # Look for explicit rate first
    rate_match = re.search(r'(?:Rate\s*of\s*Interest|ROI|Rate)[\:\s]*([\d\.]+)\s*\%', full_text, re.IGNORECASE)
    if rate_match:
        data['rate'] = float(rate_match.group(1))
    elif data['principal'] > 0:
        # Calculate from Monthly Interest Amount
        monthly_interest = re.search(r'(?:Monthly|Monthly\s*Interest|Interest\s*Amount|Advance\s*Payout)[\:\s]*[Rs\.\₹]*\s*([\d,]+(?:\.\d{2})?)', full_text, re.IGNORECASE)
        if monthly_interest:
            m_amt = float(monthly_interest.group(1).replace(',', ''))
            calculated_rate = ((m_amt * 12) / data['principal']) * 100
            data['rate'] = round(calculated_rate, 2)

    # 7. Maturity / Next Option Date
    mat_date = re.search(r'(?:Next\s*Option\s*Date|Date\s*of\s*Maturity|Maturity\s*Date)[\:\s]*([\d]{2}[\/\-\.][\d]{2}[\/\-\.][\d]{2,4})', full_text, re.IGNORECASE)
    if mat_date:
        data['maturity_date'] = mat_date.group(1)
    else:
        # Fallback date search
        dates = re.findall(r'(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})', full_text)
        if len(dates) >= 2:
            data['maturity_date'] = dates[-1] # Pick latest date as option/maturity date

    # 8. Maturity Amount
    mat_amt = re.search(r'(?:Maturity\s*Amount|Maturity\s*Value)[\:\s]*[\*\₹\s]*([\d,]+(?:\.\d{2})?)', full_text, re.IGNORECASE)
    if mat_amt:
        data['maturity_amount'] = float(mat_amt.group(1).replace(',', ''))
    elif data['principal'] > 0:
        data['maturity_amount'] = data['principal']

    return data

# 3. WEB INTERFACE
st.set_page_config(page_title="FD Portfolio Manager", layout="wide")
st.title("💼 Fixed Deposit Portfolio Manager")

st.markdown("---")
col_left, col_right = st.columns([1, 1], gap="large")

with col_left:
    st.subheader("1. Scan Certificate Image")
    uploaded_file = st.file_uploader("Upload FD / Deposit Receipt (JPG/PNG)", type=['png', 'jpg', 'jpeg'])
    
    if uploaded_file:
        image = Image.open(uploaded_file)
        
        # Auto-correct orientation metadata
        image = ImageOps.exif_transpose(image)
        
        # Manual rotation control
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
