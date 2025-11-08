from PyPDF2 import PdfReader

def extract_text_from_pdf(file_bytes):
    reader = PdfReader(file_bytes)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text
    return text.strip()