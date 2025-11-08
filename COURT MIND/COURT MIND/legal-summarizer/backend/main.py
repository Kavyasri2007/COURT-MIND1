# ============================================================
# ⚖️ Eudia Legal Summarizer Backend (Firebase + Gemini)
# ============================================================

import os
import re
import datetime
from typing import List
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import credentials, initialize_app, firestore, auth
import google.generativeai as genai
import fitz  # PyMuPDF
import tempfile

# ============================================================
# 1️⃣ LOCAL CONFIGURATION
# ============================================================
cred_path = r"C:\Users\kavya\Downloads\firebase-key.json"
gemini_key = "" # Replace with your valid Gemini API key 

# ============================================================
# 2️⃣ FIREBASE INITIALIZATION (Firestore + Auth)
# ============================================================
cred = credentials.Certificate(cred_path)
initialize_app(cred)
db = firestore.client()

# ============================================================
# 3️⃣ GEMINI CONFIGURATION
# ============================================================
genai.configure(api_key=gemini_key)

def get_gemini_model():
    preferred_models = [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.0-pro-exp",
        "gemini-2.0-flash"
    ]
    for model_name in preferred_models:
        try:
            return genai.GenerativeModel(model_name)
        except Exception:
            continue
    raise RuntimeError("❌ No supported Gemini model found.")

model = get_gemini_model()

# ============================================================
# 4️⃣ FASTAPI INITIALIZATION
# ============================================================
app = FastAPI(title="Eudia Legal Summarizer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 5️⃣ FIREBASE AUTH
# ============================================================
def verify_firebase_token(id_token: str):
    try:
        return auth.verify_id_token(id_token)
    except Exception:
        return None

# ============================================================
# 6️⃣ PDF TEXT EXTRACTION
# ============================================================
def extract_text_from_pdf(pdf_path: str) -> str:
    text = ""
    with fitz.open(pdf_path) as pdf:
        for page in pdf:
            text += page.get_text()
    if not text:
        raise HTTPException(status_code=400, detail="Could not extract text from the PDF.")
    return text.strip()

# ============================================================
# 7️⃣ SUMMARIZE USING GEMINI (Structured + Deterministic)
# ============================================================
def summarize_with_gemini(text: str) -> dict:
    """
    Generate a clear, structured summary + metadata using Gemini,
    formatted as JSON + Markdown for consistency.
    """
    try:
        system_prompt = """
        You are Eudia Legal Summarizer AI.
        Summarize the given legal document in a structured way.
        Extract these fields clearly:

        1️⃣ Case_Name  
        2️⃣ Court_Name  
        3️⃣ Parties (Petitioner / Respondent)  
        4️⃣ Sections_Invoked (List with full references)  
        5️⃣ Facts (Concise factual background)  
        6️⃣ Judgment (if available)  
        7️⃣ Final_Order (if available)  
        8️⃣ Date_of_Judgment (if available)  

        Also include a short markdown summary before the JSON.

        ⚖️ Output Format:
        ```
        ### Case Summary
        (Concise summary text)

        🧩 Structured Data
        {
          "Case_Name": "...",
          "Court_Name": "...",
          "Parties": { "Petitioner": "...", "Respondent": "..." },
          "Sections_Invoked": ["..."],
          "Facts": "...",
          "Judgment": "...",
          "Final_Order": "...",
          "Date_of_Judgment": "..."
        }
        ```
        Make sure JSON is valid and strictly follows this structure.
        """

        response = model.generate_content(f"{system_prompt}\n\n---\n{text}")
        summary_text = response.text or "Summary generation failed."
        return {"structured_summary": summary_text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini summarization failed: {e}")

# ============================================================
# TEXT NORMALIZATION
# ============================================================
def _normalize_text(text: str) -> str:
    import re
    # Replace en/em dashes with hyphen, collapse whitespace, kill NBSP
    clean = (
        text.replace("\u00A0", " ")
            .replace("–", "-")
            .replace("—", "-")
            .replace("‒", "-")
    )
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\s*\n\s*", "\n", clean)  # keep line breaks but trim them
    return clean.strip()


# ============================================================
# DATE UTILITIES
# ============================================================
def _parse_one_date(ds: str):
    """Parse a single date string (already cleaned, no ranges)."""
    from datetime import datetime
    ds = ds.replace(",", " ").strip()
    fmts = [
        "%d %B %Y", "%B %d %Y",        # 15 November 2025 / November 15 2025
        "%d %b %Y",  "%b %d %Y",       # 15 Nov 2025 / Nov 15 2025
        "%B %Y",     "%b %Y",          # March 2026 / Mar 2026
        "%Y-%m-%d",                    # 2025-11-30
        "%d/%m/%Y", "%m/%d/%Y",        # 30/11/2025, 11/30/2025
        "%d-%m-%Y", "%m-%d-%Y",
        "%d.%m.%Y", "%m.%d.%Y",
    ]
    for f in fmts:
        try:
            return datetime.strptime(ds, f).date()
        except ValueError:
            continue
    return None


def _expand_range(mo: str, d1: str, d2: str, year: str):
    """
    Expand a textual range like 'February 5-12, 2026' into
    ['February 5, 2026', 'February 12, 2026'] (as date objects).
    """
    out = []
    m = mo  # Month name (full or short)
    # Normalize both ends to full strings
    left = f"{m} {d1} {year}"
    right = f"{m} {d2} {year}"
    d_left = _parse_one_date(left)
    d_right = _parse_one_date(right)
    if d_left: out.append(d_left)
    if d_right: out.append(d_right)
    return out


# ============================================================
# EXTRACT + CLASSIFY ALL DATES (PAST / UPCOMING) + TOTAL COUNTS
# ============================================================
def extract_and_classify_dates(text: str):
    """
    Returns:
      {
        "all_unique_sorted": [date_str, ...],
        "past": {"count": n, "list": [...]},
        "upcoming": {"count": n, "list": [...]},
        "total_unique": N
      }
    Where date_str is "DD Month YYYY".
    """
    import re
    from datetime import datetime, date

    clean = _normalize_text(text)

    MONTHS = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'

    # 1) Ranges like "February 5-12, 2026" or "Feb 5–12, 2026"
    rng = rf'\b({MONTHS})\s+(\d{{1,2}})\s*[–-]\s*(\d{{1,2}}),\s*(\d{{4}})\b'

    # 2) Full dates "15 November 2025" or "November 15, 2025"
    full1 = rf'\b\d{{1,2}}\s+{MONTHS}\s+\d{{4}}\b'
    full2 = rf'\b{MONTHS}\s+\d{{1,2}},\s*\d{{4}}\b'

    # 3) Month Year "March 2026"
    my = rf'\b{MONTHS}\s+\d{{4}}\b'

    # 4) ISO and numeric dates
    iso = r'\b\d{4}-\d{2}-\d{2}\b'
    num = r'\b\d{1,2}[\/.-]\d{1,2}[\/.-]\d{2,4}\b'

    pattern = rf'({rng})|({full1})|({full2})|({my})|({iso})|({num})'

    matches = list(re.finditer(pattern, clean, flags=re.IGNORECASE))

    found_dates = []

    for m in matches:
        # If it matched the range form, groups 2..5 will be filled
        if m.group(2) and m.group(3) and m.group(4) and m.group(5):
            # month, d1, d2, year
            mo = m.group(2)  # because of overall grouping shift with (rng) inside (...)
            d1 = m.group(3)
            d2 = m.group(4)
            yr = m.group(5)
            found_dates.extend(_expand_range(mo, d1, d2, yr))
        else:
            raw = m.group(0)
            # Clean ordinal suffixes and commas
            raw = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', raw, flags=re.IGNORECASE)
            raw = raw.replace(",", " ")
            dt = _parse_one_date(raw)
            if dt:
                found_dates.append(dt)

    # Unique + sorted
    unique_sorted = sorted(set(found_dates))
    today = datetime.now().date()

    past = [d for d in unique_sorted if d < today]
    upcoming = [d for d in unique_sorted if d >= today]

    pretty_all = [d.strftime("%d %B %Y") for d in unique_sorted]
    pretty_past = [d.strftime("%d %B %Y") for d in past]
    pretty_upcoming = [d.strftime("%d %B %Y") for d in upcoming]

    return {
        "all_unique_sorted": pretty_all,
        "past": {"count": len(past), "list": pretty_past},
        "upcoming": {"count": len(upcoming), "list": pretty_upcoming},
        "total_unique": len(unique_sorted),
    }


# ============================================================
# SECTION EXTRACTION (INDIA + GENERIC CODES + "Franklin Penal Code 312(b)" etc.)
# ============================================================
def extract_sections_invoked(text: str):
    """
    Detects both:
      - 'Section 420 IPC', 'u/s 138 NI Act', 'Sec. 65 IT Act'
      - 'Franklin Penal Code 312(b)', 'Evidence Code 128', 'Digital Security Act 44'
    Returns (unique_list, count)
    """
    import re
    clean = _normalize_text(text)

    # A) Classic "Section ..." patterns (Indian style + generic)
    ACTS_A = r'(?:IPC|CrPC|CPC|NI\s*Act|IT\s*Act|Evidence\s*Act|PMLA|NDPS|Arms\s*Act|PC\s*Act|POCSO|Companies\s*Act|Motor\s*Vehicles\s*Act|Contract\s*Act)'
    patt_a = rf'''
        (?:
            (?:(?:u/s|u\/s)\s*|(?:under\s+)?(?:section|sec\.?)\s*)
            (?P<num>[0-9A-Za-z()\-/]+)
            (?:\s*(?:of\s+the\s+)?)\s*
            (?P<act>{ACTS_A})?
        )
    '''

    # B) Generic "[X] Code ###" and "[X] Act ###" patterns (e.g., Franklin Penal Code 312(b), Evidence Code 128, Digital Security Act 44)
    patt_b = r'''
        (?:
            (?P<title>[A-Z][A-Za-z ]+(?:Code|Act))\s+
            (?P<code_no>[0-9A-Za-z()-]+)
        )
    '''

    found = []

    # Collect A)
    for m in re.finditer(patt_a, clean, flags=re.IGNORECASE | re.VERBOSE):
        nums = m.group('num') or ""
        act  = (m.group('act') or "").strip()
        parts = re.split(r'[\/,]|(?:\s*-\s*)|(?:\s+and\s+)', nums)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if not re.match(r'^[0-9]+[A-Za-z()\-]*$', p):
                continue
            label = f"Section {p}" + (f" {act}" if act else "")
            found.append(label)

    # Collect B)
    for m in re.finditer(patt_b, clean, flags=re.IGNORECASE | re.VERBOSE):
        title = m.group('title').strip()
        code_no = m.group('code_no').strip()
        # Exclude if this is clearly not a legal ref (rare)
        if re.match(r'^[0-9A-Za-z()\-]+$', code_no):
            label = f"{title} {code_no}"
            found.append(label)

    # Deduplicate case-insensitively
    dedup, seen = [], set()
    for s in found:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            dedup.append(s)

    return dedup, len(dedup)


# ============================================================
# TIMELINE (COMPLETE + CLEAN; INCLUDES RANGES & MONTH-YEAR)
# ============================================================
def generate_case_timeline(text: str) -> list:
    """
    Returns a list of dicts:
      [{ "date": "DD Month YYYY", "status": "✅ Completed|⏳ Upcoming", "event_context": "..." }, ...]
    """
    import re
    from datetime import datetime

    clean = _normalize_text(text)

    # Reuse the same extraction to ensure parity with counts
    dates_info = extract_and_classify_dates(clean)
    all_dates = dates_info["all_unique_sorted"]

    # Build context for each date by locating it in text (fuzzy match)
    events = []
    now = datetime.now().date()

    # Create a regex that matches any of the pretty dates in the clean text window
    # We'll also try to recover context by scanning around the first occurrence of components.
    for dstr in all_dates:
        # Try to find "Month" and "Year" proximity for context window
        # Fallback: direct search for year
        try:
            # Pull a small window around the year to show event text
            year = re.search(r'\b(\d{4})\b', dstr).group(1)
        except:
            year = None

        idx = -1
        if year:
            ymatch = re.search(rf'\b{year}\b', clean)
            if ymatch:
                idx = ymatch.start()

        # Context window
        start = max(0, idx - 120) if idx >= 0 else 0
        end   = min(len(clean), (idx + 160) if idx >= 0 else 200)
        context = re.sub(r'\s+', ' ', clean[start:end]).strip()

        # Status
        from datetime import datetime as _dt
        parsed = _parse_one_date(dstr)  # convert "DD Month YYYY" -> date
        status = "⏳ Upcoming" if (parsed and parsed >= now) else "✅ Completed"

        events.append({
            "date": dstr,
            "event_context": context,
            "status": status
        })

    # Sort chronologically
    def _to_date(s): 
        return _parse_one_date(s) or datetime(1970,1,1).date()

    events.sort(key=lambda e: _to_date(e["date"]))
    return events 

# ============================================================
# ⚖️ DETECT CASE STATUS
# ============================================================
def detect_case_status(summary_text: str, metadata: dict) -> str:
    """
    Detect if the case is ongoing or closed based on summary and metadata.
    Returns 'Ongoing' or 'Closed'.
    """
    text = summary_text.lower()
    if (
        "judgment" in text and "delivered" in text
    ) or ("final order" in text and "issued" in text):
        return "Closed"

    # If there are upcoming dates, it’s ongoing
    if metadata.get("dates", {}).get("upcoming", {}).get("count", 0) > 0:
        return "Ongoing"

    # If explicitly says 'case dismissed', 'acquitted', 'convicted'
    keywords_closed = ["dismissed", "acquitted", "convicted", "sentenced"]
    if any(k in text for k in keywords_closed):
        return "Closed"

    return "Ongoing"


# ============================================================
# ⚖️ GENERATE CASE TIPS (For Ongoing Cases)
# ============================================================
def generate_case_tips(summary_text: str, metadata: dict) -> list:
    """
    Use Gemini to generate context-aware tips if the case is ongoing.
    """
    try:
        stage_info = ""
        if metadata.get("dates", {}).get("upcoming", {}).get("count", 0):
            next_hearing = metadata["dates"]["upcoming"]["list"][0]
            stage_info = f"The next upcoming date in the case is {next_hearing}."

        prompt = f"""
        You are a legal strategy advisor for ongoing court cases.
        Based on the following case summary and metadata,
        suggest 3-5 professional and practical tips to prepare or strengthen the case.

        {stage_info}

        Case Summary:
        {summary_text}

        Tips should be specific, clear, and actionable (e.g., review evidence chain, witness prep, digital proof preservation, compliance reminders).
        """

        response = model.generate_content(prompt)
        tips_text = response.text.strip() if response.text else "No tips generated."

        # Split into a clean list
        tips = [line.strip("•- ") for line in tips_text.split("\n") if line.strip()]
        return tips[:5]  # Limit to 5 best suggestions

    except Exception as e:
        return [f"⚠️ Failed to generate tips: {e}"]


# ============================================================
# 🧩 COMBINED STRUCTURED OUTPUT GENERATOR
# ============================================================
def generate_structured_summary(text: str):
    summary_data = summarize_with_gemini(text)
    structured_text = summary_data["structured_summary"]

    # Extract metadata (dates, sections, timeline)
    dates_info = extract_and_classify_dates(text)
    sections, section_count = extract_sections_invoked(text)
    timeline = generate_case_timeline(text)

    metadata = {
        "dates": dates_info,
        "sections": {"count": section_count, "list": sections},
        "timeline": timeline,
    }

    # Detect case status
    case_status = detect_case_status(structured_text, metadata)

    # Generate tips only if ongoing
    tips = []
    if case_status == "Ongoing":
        tips = generate_case_tips(structured_text, metadata)

    return {
        "summary_markdown": structured_text,
        "case_status": case_status,
        "metadata": metadata,
        "recommendations": tips,
    }

# ============================================================
# 1️⃣1️⃣ UPLOAD + SUMMARIZE + STORE
# ============================================================
@app.post("/upload/")
async def upload_and_summarize(
    files: List[UploadFile] = File(...),
    client_name: str = Form(...),
    file_type: str = Form(...),
    authorization: str = Header(None)
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    user = verify_firebase_token(authorization.split("Bearer ")[1])
    if not user:
        raise HTTPException(status_code=403, detail="Invalid or expired Firebase token")
    user_id = user["uid"]
    summaries = []
    for file in files:
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp:
                temp.write(await file.read())
                temp_path = temp.name
            text = extract_text_from_pdf(temp_path)
            if not text:
                continue
            structured_output = generate_structured_summary(text)
            db.collection("summaries").document().set({
                "user_id": user_id,
                "filename": file.filename,
                "client_name": client_name,
                "file_type": file_type,
                "summary": structured_output["summary_markdown"],
                "case_status": structured_output["case_status"],
                "recommendations": structured_output["recommendations"],
                "metadata": structured_output["metadata"],
                "timestamp": firestore.SERVER_TIMESTAMP
            })
            summaries.append({
                "filename": file.filename,
                **structured_output
            })
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
    return {"summaries": summaries}

# ============================================================
# 1️⃣2️⃣ HEALTH CHECK
# ============================================================
@app.get("/")
def root():
    return {
        "status": "✅ Backend running",
        "project_id": "eudia-legalsummarizer",
        "firestore_database": "(default)"
    }
