import io
import re
import sqlite3
import altair as alt
import cv2
import numpy as np
import pandas as pd
import pytesseract
import streamlit as st
from PIL import Image, ImageOps

# -----------------------------------------------------------
# 1. DATABASE SETUP
# -----------------------------------------------------------
conn = sqlite3.connect("fds.db", check_same_thread=False)
c = conn.cursor()
c.execute(
    """
    CREATE TABLE IF NOT EXISTS fixed_deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        holder_name TEXT,
        nominee_name TEXT,
        institution_name TEXT,
        account_fd_no TEXT UNIQUE,
        principal_amount REAL,
        interest_rate REAL,
        tenure_months INTEGER,
        start_date TEXT,
        maturity_date TEXT,
        maturity_amount REAL,
        interest_payout TEXT,
        interest_amount REAL,
        receipt_image BLOB
    )
"""
)
conn.commit()


# -----------------------------------------------------------
# 2. HELPER FUNCTIONS FOR OCR & EXTRACTION
# -----------------------------------------------------------
def preprocess_image(image):
    """Enhances image contrast and removes noise for better OCR accuracy."""
    img_cv = np.array(image)
    if len(img_cv.shape) == 3:
        gray = cv2.cvtColor(img_cv, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_cv

    # Resize image to improve OCR quality for small text
    gray = cv2.resize(gray, (0, 0), fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    # Apply adaptive thresholding to clear background noise
    processed = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )
    return processed


def extract_text_from_image(image):
    """Extracts raw text from receipt using Tesseract OCR."""
    processed_img = preprocess_image(image)
    text = pytesseract.image_to_string(processed_img, config="--psm 6")
    return text


def parse_kapil_receipt(text):
    """Parses extracted text specifically for Kapil receipts."""
    data = {}
    # Example regex patterns for Kapil receipts
    fd_match = re.search(
        r"(?:F\.?D\.?|Receipt|No\.?)\s*[:\-]?\s*([A-Z0-9\-\/]+)", text, re.I
    )
    if fd_match:
        data["account_fd_no"] = fd_match.group(1).strip()

    principal_match = re.search(
        r"(?:Principal|Amount)\s*[:\-]?\s*[\₹]?\s*([\d,]+\.?\d*)", text, re.I
    )
    if principal_match:
        clean_amt = principal_match.group(1).replace(",", "")
        try:
            data["principal_amount"] = float(clean_amt)
        except ValueError:
            pass

    rate_match = re.search(r"(?:Rate|Interest)\s*[:\-]?\s*([\d\.]+)%", text, re.I)
    if rate_match:
        try:
            data["interest_rate"] = float(rate_match.group(1))
        except ValueError:
            pass

    return data


def parse_shriram_receipt(text):
    """Parses extracted text specifically for Shriram receipts."""
    data = {}
    fd_match = re.search(
        r"(?:Deposit|FD|Receipt)\s*(?:No\.?|Number)\s*[:\-]?\s*([A-Z0-9\-\/]+)",
        text,
        re.I,
    )
    if fd_match:
        data["account_fd_no"] = fd_match.group(1).strip()

    principal_match = re.search(
        r"(?:Principal|Deposit\s*Amount)\s*[:\-]?\s*[\₹]?\s*([\d,]+\.?\d*)",
        text,
        re.I,
    )
    if principal_match:
        clean_amt = principal_match.group(1).replace(",", "")
        try:
            data["principal_amount"] = float(clean_amt)
        except ValueError:
            pass

    return data


# -----------------------------------------------------------
# 3. STREAMLIT APP LAYOUT
# -----------------------------------------------------------
st.set_page_config(
    page_title="FD Portfolio Manager", page_icon="💰", layout="wide"
)

st.title("💰 Fixed Deposit Portfolio Manager")

tab1, tab2, tab3 = st.tabs(
    ["📊 View Portfolio", "➕ Add / Scan Deposit", "⚙️ Manage Records"]
)

# -----------------------------------------------------------
# TAB 1: VIEW PORTFOLIO (WITH ANALYTICAL DASHBOARD & PIE CHART)
# -----------------------------------------------------------
with tab1:
    st.header("Portfolio Overview")

    # Fetch all records from database
    query = "SELECT * FROM fixed_deposits"
    df = pd.read_sql_query(query, conn)

    if df.empty:
        st.info(
            "No fixed deposits found in the database. Add one using the 'Add / Scan Deposit' tab."
        )
    else:
        # --- ANALYTICAL DASHBOARD & PIE CHART ---
        st.subheader("📈 Institution Portfolio Breakdown")

        # Group by institution to calculate totals
        summary_df = (
            df.groupby("institution_name")
            .agg(
                total_principal=("principal_amount", "sum"),
                total_monthly_interest=("interest_amount", "sum"),
            )
            .reset_index()
        )

        # Calculate portfolio share percentage
        total_portfolio = summary_df["total_principal"].sum()
        summary_df["portfolio_share"] = (
            summary_df["total_principal"] / total_portfolio
        ) * 100

        # Format values for neat presentation in the summary table
        display_summary = summary_df.copy()
        display_summary["total_principal"] = display_summary[
            "total_principal"
        ].apply(lambda x: f"₹{x:,.2f}")
        display_summary["total_monthly_interest"] = display_summary[
            "total_monthly_interest"
        ].apply(lambda x: f"₹{x:,.2f}")
        display_summary["portfolio_share"] = display_summary[
            "portfolio_share"
        ].apply(lambda x: f"{x:.2f}%")

        display_summary.columns = [
            "Institution",
            "Total Principal",
            "Monthly Interest",
            "Portfolio Share",
        ]

        # Layout: Summary Table on Left, Donut Pie Chart on Right
        col_table, col_chart = st.columns([1.3, 1])

        with col_table:
            st.dataframe(
                display_summary, hide_index=True, use_container_width=True
            )

        with col_chart:
            pie_chart = (
                alt.Chart(summary_df)
                .mark_arc(innerRadius=60)
                .encode(
                    theta=alt.Theta(
                        field="total_principal", type="quantitative"
                    ),
                    color=alt.Color(
                        field="institution_name",
                        type="nominal",
                        legend=alt.Legend(title="Institution"),
                    ),
                    tooltip=[
                        "institution_name",
                        alt.Tooltip(
                            "total_principal",
                            title="Principal",
                            format=",.2f",
                        ),
                        alt.Tooltip(
                            "portfolio_share", title="Share (%)", format=".2f"
                        ),
                    ],
                )
                .properties(height=220)
            )
            st.altair_chart(pie_chart, use_container_width=True)

        st.markdown("---")

        # --- INTERACTIVE PORTFOLIO RECORDS DATAFRAME ---
        st.subheader("📋 Detailed Deposit Records")
        st.dataframe(df, use_container_width=True)

# -----------------------------------------------------------
# TAB 2: ADD / SCAN DEPOSIT
# -----------------------------------------------------------
with tab2:
    st.header("Add New Fixed Deposit (Manual or via Receipt Scan)")

    institution_choice = st.selectbox(
        "Select Institution", ["KAPIL PROPERTY", "SHRIRAM FINANCE", "OTHER"]
    )

    uploaded_file = st.file_uploader(
        "Upload FD Receipt (Image)", type=["png", "jpg", "jpeg"]
    )

    extracted_data = {}
    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption="Uploaded Receipt", width=300)

        if st.button("Scan Receipt with OCR"):
            with st.spinner("Extracting details..."):
                raw_text = extract_text_from_image(image)
                if "KAPIL" in institution_choice:
                    extracted_data = parse_kapil_receipt(raw_text)
                else:
                    extracted_data = parse_shriram_receipt(raw_text)
                st.success("Scan complete! Review fields below.")

    with st.form("fd_form"):
        holder = st.text_input("Holder Name")
        nominee = st.text_input("Nominee Name")
        fd_no = st.text_input(
            "Account / FD Number",
            value=extracted_data.get("account_fd_no", ""),
        )
        principal = st.number_format = st.number_input(
            "Principal Amount (₹)",
            value=float(extracted_data.get("principal_amount", 0.0)),
        )
        rate = st.number_input(
            "Interest Rate (%)",
            value=float(extracted_data.get("interest_rate", 0.0)),
        )
        tenure = st.number_input("Tenure (Months)", value=12, step=1)
        start_date = st.date_input("Start Date")
        maturity_date = st.date_input("Maturity Date")
        maturity_amt = st.number_input("Maturity Amount (₹)", value=0.0)
        payout = st.selectbox(
            "Interest Payout Frequency",
            ["Monthly", "Quarterly", "Cumulative", "At Maturity"],
        )
        interest_amt = st.number_input(
            "Estimated Periodic Interest (₹)", value=0.0
        )

        submit_btn = st.form_submit_button("Save Deposit")

        if submit_btn:
            try:
                img_byte_arr = None
                if uploaded_file is not None:
                    img_byte_arr = io.BytesIO()
                    image.save(img_byte_arr, format=image.format or "JPEG")
                    img_byte_arr = img_byte_arr.getvalue()

                c.execute(
                    """
                    INSERT INTO fixed_deposits (
                        holder_name, nominee_name, institution_name, account_fd_no, 
                        principal_amount, interest_rate, tenure_months, start_date, 
                        maturity_date, maturity_amount, interest_payout, interest_amount, receipt_image
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        holder,
                        nominee,
                        institution_choice,
                        fd_no,
                        principal,
                        rate,
                        tenure,
                        str(start_date),
                        str(maturity_date),
                        maturity_amt,
                        payout,
                        interest_amt,
                        img_byte_arr,
                    ),
                )
                conn.commit()
                st.success("Fixed Deposit saved successfully!")
            except sqlite3.IntegrityError:
                st.error(
                    "Error: An FD with this Account/FD Number already exists."
                )

# -----------------------------------------------------------
# TAB 3: MANAGE RECORDS
# -----------------------------------------------------------
with tab3:
    st.header("Manage Existing Records")
    df_manage = pd.read_sql_query(
        "SELECT id, institution_name, account_fd_no, principal_amount FROM fixed_deposits",
        conn,
    )

    if df_manage.empty:
        st.info("No records available to manage.")
    else:
        selected_fd_id = st.selectbox(
            "Select FD Record to Delete",
            df_manage["id"],
            format_func=lambda x: f"ID: {x} - {df_manage.loc[df_manage['id'] == x, 'institution_name'].values[0]} ({df_manage.loc[df_manage['id'] == x, 'account_fd_no'].values[0]})",
        )

        if st.button("Delete Selected Record", type="primary"):
            c.execute(
                "DELETE FROM fixed_deposits WHERE id = ?", (selected_fd_id,)
            )
            conn.commit()
            st.success(f"Successfully deleted record ID {selected_fd_id}!")
            st.rerun()
