import streamlit as st
import sqlite3
import pytesseract
from PIL import Image, ImageOps
import re
import io

# ---------------------------------------------------------
# CONSTANTS & VALIDATION
# ---------------------------------------------------------
RELATION_KEYWORDS = {
    'HUSBAND', 'WIFE', 'FATHER', 'MOTHER', 'SON', 
    'DAUGHTER', 'SPOUSE', 'BROTHER', 'SISTER', '100%', 'PROPORTION'
}

def clean_nominee_val(raw_str):
    if not raw_str:
        return ""
    # Remove leading numbering/bullets like "1.", "1)", "(1)"
    cleaned = re.sub(r'^[\s\.\d\-\)\(\:]+', '', raw_str).strip()
    # Truncate if relation labels or percentages got glued to the name
    cleaned = re.sub(
        r'\s+(?:Nominee\s*Relation|Relation|HUSBAND|FATHER|WIFE|MOTHER|SON|DAUGHTER|Proportion|100\%|\d{1,3}\%).*$', 
        '', cleaned, flags=re.IGNORECASE
    ).strip()
    
    # Reject if result is purely a relation word or too short
    if cleaned.upper() in RELATION_KEYWORDS or len(cleaned) < 3:
        return ""
    return cleaned


# ---------------------------------------------------------
# KAPIL FORMAT PARSER
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

    # 2. NOMINEE NAME (Targeted parsing)
    # Match pattern: 1. <NAME> before Nominee Relation / Husband
    nom_match = re.search(
        r'1[\.\)]\s*([A-Z\.\s]{3,35})(?=\s*(?:Nominee\s*Relation|HUSBAND|FATHER|WIFE|MOTHER|100\%|\d{1,3}\%|$))', 
        full_text, re.IGNORECASE
    )
    if nom_match:
        data['nominee_name'] = clean_nominee_val(nom_match.group(1))

    if not data['nominee_name']:
        # Secondary search around "Nominee Name" keyword
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
# MULTI-PASS & BOTTOM-CROP OCR ENGINE WITH VERIFICATION
# ---------------------------------------------------------
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

    # Pass 1: Full-document multi-PSM scan
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

        # Check if nominee name is valid
        if extracted['nominee_name'] and extracted['nominee_name'].upper() not in RELATION_KEYWORDS:
            break

    # Pass 2: Fallback focused crop for bottom 30% of document (Nominee Section)
    if not extracted['nominee_name'] or extracted['nominee_name'].upper() in RELATION_KEYWORDS:
        width, height = img.size
        # Crop lower region containing Nominee Table
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
