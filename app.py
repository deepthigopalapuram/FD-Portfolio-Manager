import streamlit as st
import sqlite3
import pytesseract
from PIL import Image
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

# 2. OCR TEXT PARSER
def parse_fd(extracted_text):
    data = {
        'holder_name': '', 'nominee_name': '', 'institution_name': '',
        'account_fd_no': '', 'principal': 0.0, 'rate': 0.0,
        'maturity_date': '', 'maturity_amount': 0.0
    }

    inst = re.search(r'(KAPIL\s+PROPERTY\s+DEVELOPERS|SHRIRAM\s+FINANCE|HDFC|ICICI|SBI|AXIS|CANARA|KOTAK)', extracted_text, re.IGNORECASE)
    if inst: data['institution_name'] = inst.group(0).upper()

    holder = re.search(r'(?:Depositor|applicant)\s*[\:\-\s]+([A-Z\s]{4,35})(?=\s+Address|\s+Date|\s+Father|\s+Customer|\s+PAN)', extracted_text)
    if holder: data['holder_name'] = holder.group(1).strip()

    nominee = re.search(r'Nominee\s*(?:Name)?\s*[\:\-\s]+([A-Z\s]{4,35})(?=\s+Nominee|\s+Proportion|\s+Guardian)', extracted_text, re.IGNORECASE)
    if nominee: data['nominee_name'] = nominee.group(1).strip()

    num = re.search(r'(?:Deposit\s*No\.?|Certificate\s*No\.?)\s*[\:\-\s]+([A-Z0-9\/\-]+)', extracted_text, re.IGNORECASE)
    if num: data['account_fd_no'] = num.group(1).strip()

    principal = re.search(r'(?:Deposit\s*Amount|Initial\s*advance|Principal)[\:\s]*[Rs\.\₹]*\s*([\d,]+(?:\.\d{2})?)', extracted_text, re.IGNORECASE)
    if principal: data['principal'] = float(principal.group(1).replace(',', ''))

    rate = re.search(r'(?:Rate\s*of\s*Interest|ROI)[\:\s]*([\d\.]+)\s*\%', extracted_text, re.IGNORECASE)
    if rate: data['rate'] = float(rate.group(1))

    mat_date = re.search(r'(?:Date\s*of\s*Maturity|Next\s*Option\s*Date|Maturity\s*Date)[\:\s]*([\d]{2}[\/\-\.][\d]{2}[\/\-\.][\d]{2,4})', extracted_text, re.IGNORECASE)
    if mat_date: data['maturity_date'] = mat_date.group(1)

    mat_amt = re.search(r'(?:Maturity\s*Amount|Maturity\s*Value)[\:\s]*[\*\₹\s]*([\d,]+(?:\.\d{2})?)', extracted_text, re.IGNORECASE)
    if mat_amt: data['maturity_amount'] = float(mat_amt.group(1).replace(',', ''))

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
        st.image(image, caption="Uploaded Document", use_container_width=True)
        
        with st.spinner("Extracting text details..."):
            # Auto-rotate sideways images if needed
            try:
                osd = pytesseract.image_to_osd(image)
                angle = int(re.search(r'Rotate:\s*(\d+)', osd).group(1))
                if angle != 0:
                    image = image.rotate(360 - angle, expand=True)
            except Exception:
                pass

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
