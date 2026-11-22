import pdfplumber
from config import MAX_PDF_CHARS

KEYWORDS = ("financial position", "total assets", "total liabilities", "total equity",
            "revenue", "profit for the", "profit after tax", "turnover")


def pdf_to_text(file):
    """Pick the pages that look most like financial statements."""
    scored = []
    with pdfplumber.open(file) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            low = text.lower()
            s = sum(k in low for k in KEYWORDS)
            if s >= 2:
                scored.append((s, i, text))
    scored.sort(key=lambda x: -x[0])
    chosen, size = [], 0
    for s, i, text in scored:
        if size >= MAX_PDF_CHARS:
            break
        chosen.append((i, text))
        size += len(text)
    chosen.sort()  # back to page order
    return "\n".join(t for _, t in chosen)[:MAX_PDF_CHARS]
    # Scanned PDFs (images) have no text. Add OCR (pytesseract) later if needed.
