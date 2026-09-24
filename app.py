def parse_fd(extracted_text):
    data = {
        'holder_name': '', 'nominee_name': '', 'institution_name': '',
        'account_fd_no': '', 'principal': 0.0, 'rate': 0.0,
        'maturity_date': '', 'maturity_amount': 0.0
    }

    lines = [line.strip() for line in extracted_text.split('\n') if line.strip()]
    full_text = " ".join(lines)

    # 1. INSTITUTION NAME
    inst_match = re.search(
        r'([A-Z0-9\s\,\.]{3,50}\s+(?:LIMITED|LTD|FINANCE|DEVELOPERS|BANK|CORPORATION|SERVICES))', 
        full_text, re.IGNORECASE
    )
    if inst_match:
        data['institution_name'] = re.sub(r'\s+', ' ', inst_match.group(1)).strip().upper()
    else:
        for line in lines[:5]:
            if len(line) > 5 and line.isupper() and not any(kw in line.lower() for kw in ['certificate', 'advance', 'receipt', 'application']):
                data['institution_name'] = line.strip()
                break

    # 2. HOLDER / APPLICANT NAME
    holder_match = re.search(
        r'(?:Name\s*\(?s\)?\s*of\s*(?:the)?\s*applicant|Depositor\s*Name|Holder\s*Name)\s*[\:\-\s]+([A-Z\s\.]{3,40})(?=\s+(?:Address|Date|Father|Husband|Customer|S/o|D/o|W/o|\d))', 
        full_text, re.IGNORECASE
    )
    if holder_match:
        data['holder_name'] = holder_match.group(1).strip()

    # 3. NOMINEE NAME (Excludes table header terms like NOMINEE / RELATION)
    # Search for text following 'Nominee Name' that isn't just the header word 'NOMINEE'
    nominee_match = re.search(
        r'Nominee\s*Name[\:\-\s]*(?:Nominee\s*Relation)?[\:\-\s]*([A-Z\.\s]{3,35})(?=\s+(?:HUSBAND|WIFE|FATHER|MOTHER|SON|DAUGHTER|BROTHER|SISTER|MAJOR|MINOR|GUARDIAN|\d))', 
        full_text, re.IGNORECASE
    )
    if nominee_match and nominee_match.group(1).strip().upper() != "NOMINEE":
        data['nominee_name'] = nominee_match.group(1).strip()
    else:
        # Fallback: Find name appearing directly before relation keywords (e.g., HUSBAND/WIFE)
        relation_match = re.search(
            r'([A-Z][A-Z\.\s]{2,30})\s+(?:HUSBAND|WIFE|FATHER|MOTHER|SON|DAUGHTER|BROTHER|SISTER)', 
            full_text
        )
        if relation_match:
            candidate = relation_match.group(1).strip()
            # Ensure we didn't capture static header words
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
        r'(?:Total\s*advance|Deposit\s*Amount|Initial\s*advance|Principal\s*Amount)[\:\s]*[Rs\.\₹]*\s*([\d,]+(?:\.\d{2})?)', 
        full_text, re.IGNORECASE
    )
    if principal_match:
        data['principal'] = float(principal_match.group(1).replace(',', ''))

    # 6. INTEREST RATE (Calculated dynamically if monthly payout is detected)
    rate_match = re.search(r'(?:Rate\s*of\s*Interest|ROI|Interest\s*Rate|Rate)[\:\s]*([\d\.]+)\s*\%', full_text, re.IGNORECASE)
    if rate_match:
        data['rate'] = float(rate_match.group(1))
    elif data['principal'] > 0:
        # Look for monthly interest values (e.g., 5500.00 or 5,500)
        monthly_match = re.search(
            r'(?:Monthly|Monthly\s*Interest|Interest\s*Amount|Advance\s*Payout)[\:\s]*[Rs\.\₹]*\s*([\d,]+(?:\.\d{2})?)', 
            full_text, re.IGNORECASE
        )
        if monthly_match:
            monthly_val = float(monthly_match.group(1).replace(',', ''))
            # Calculate annual rate: (Monthly Interest * 12 / Principal) * 100
            data['rate'] = round(((monthly_val * 12) / data['principal']) * 100, 2)

    # 7. MATURITY / NEXT OPTION DATE
    mat_match = re.search(
        r'(?:Next\s*Option\s*Date|Maturity\s*Date|Date\s*of\s*Maturity|Option\s*Date)[\:\s]*([\d]{2}[\/\-\.][\d]{2}[\/\-\.][\d]{2,4})', 
        full_text, re.IGNORECASE
    )
    if mat_match:
        data['maturity_date'] = mat_match.group(1)
    else:
        # Find all dates in the text and select the latest date
        all_dates = re.findall(r'\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4})\b', full_text)
        if all_dates:
            data['maturity_date'] = all_dates[-1]

    # 8. MATURITY AMOUNT
    mat_amt_match = re.search(
        r'(?:Maturity\s*Amount|Maturity\s*Value)[\:\s]*[Rs\.\₹]*\s*([\d,]+(?:\.\d{2})?)', 
        full_text, re.IGNORECASE
    )
    if mat_amt_match:
        data['maturity_amount'] = float(mat_amt_match.group(1).replace(',', ''))
    elif data['principal'] > 0:
        data['maturity_amount'] = data['principal']

    return data
