"""Pull structured fields out of an invoice-like document, then decide what to do.

Text first, regex second, rules third - the boring approach that survives
production. An LLM can be dropped in later for the fuzzy leftovers; the
deterministic layer keeps the numbers exact and the running cost at zero.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime
from typing import Any

# --- patterns -------------------------------------------------------------
# Bilingual (EN/DE) on purpose: most EU invoices arrive in one of the two.

# Keyword is case-insensitive, the captured id is NOT: with re.IGNORECASE the
# [A-Z0-9] class would also match lower-case words and grab "invoice data".
# The id must contain at least one digit, and must sit on the keyword's line.
INVOICE_NO = re.compile(
    r"(?i:invoice|rechnung|faktura)[ 	]*(?i:no\.?|nr\.?|number|#)?[ 	]*[:.#\-]?[ 	]*"
    r"([A-Z0-9][A-Z0-9\-/]*\d[A-Z0-9\-/]*)"
)
DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "%Y-%m-%d"),
    (re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b"), "%d.%m.%Y"),
    (re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b"), "%d %B %Y"),
]
ISSUE_DATE_LINE = re.compile(
    r"(?:invoice date|date of issue|rechnungsdatum|datum)\s*[:.]?\s*(.+)", re.IGNORECASE
)
DUE_DATE_LINE = re.compile(
    r"(?:due date|payment due|faelligkeitsdatum|fällig(?:keitsdatum)?|zahlbar bis)\s*[:.]?\s*(.+)",
    re.IGNORECASE,
)
TOTAL_LINE = re.compile(
    r"(?:total\s*(?:due|amount)?|amount due|grand total|gesamtbetrag|gesamtsumme|rechnungsbetrag)"
    r"\s*[:.]?\s*([€$£]?\s*\d[\d\s.,]*)\s*(EUR|USD|GBP)?",
    re.IGNORECASE,
)
VAT_RATE = re.compile(r"(?:vat|ust|mwst|tax)\D{0,12}?(\d{1,2}(?:[.,]\d)?)\s*%", re.IGNORECASE)
VAT_ID = re.compile(
    r"\b(?:VAT(?:\s*ID)?|USt-?IdNr\.?|TAX\s*ID)\s*[:.]?\s*([A-Z]{2}\s?[0-9A-Z]{8,12})\b",
    re.IGNORECASE,
)
IBAN = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?)\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?:\+|00)\d[\d\s().\-]{7,17}\d")
CURRENCY_SYMBOL = {"€": "EUR", "$": "USD", "£": "GBP"}


def read_document(content: bytes, filename: str = "") -> str:
    """Return the plain text of a PDF or text file.

    Raises ValueError for unsupported types so callers can answer 415 instead
    of guessing.
    """
    name = filename.lower()
    if name.endswith(".pdf") or content[:5] == b"%PDF-":
        import pdfplumber  # lazy import: text-only installs do not need it

        pages: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        text = "\n".join(pages)
        if not text.strip():
            raise ValueError("PDF contains no extractable text (scan? needs OCR)")
        return text
    if name.endswith((".txt", ".md", ".csv", ".eml")) or not name:
        return content.decode("utf-8", errors="replace")
    raise ValueError(f"unsupported file type: {filename}")


def _parse_date(text: str) -> str | None:
    """First date found in `text`, normalised to YYYY-MM-DD."""
    for pattern, fmt in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        raw = match.group(0).replace("/", ".")
        for candidate in (fmt, fmt.replace("%B", "%b")):
            try:
                return datetime.strptime(raw, candidate).date().isoformat()
            except ValueError:
                continue
    return None


def _parse_amount(raw: str) -> float | None:
    """Handles both conventions: '1.234,56' and '1,234.56' -> 1234.56."""
    cleaned = re.sub(r"[^\d.,]", "", raw)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        # The rightmost separator is the decimal one.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        decimals = len(cleaned.split(",")[-1])
        cleaned = cleaned.replace(",", ".") if decimals == 2 else cleaned.replace(",", "")
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def extract_fields(text: str) -> dict[str, Any]:
    """Extract the fields an accounting workflow routes on."""
    fields: dict[str, Any] = {
        "invoice_number": None,
        "invoice_date": None,
        "due_date": None,
        "total": None,
        "currency": None,
        "vat_rate": None,
        "vat_id": None,
        "iban": None,
        "emails": [],
        "phones": [],
        "missing_fields": [],
    }

    match = INVOICE_NO.search(text)
    if match:
        fields["invoice_number"] = match.group(1).strip(".,;")

    for key, pattern in (("invoice_date", ISSUE_DATE_LINE), ("due_date", DUE_DATE_LINE)):
        line = pattern.search(text)
        if line:
            fields[key] = _parse_date(line.group(1))
    if fields["invoice_date"] is None:
        fields["invoice_date"] = _parse_date(text)  # fall back to any date in the doc

    match = TOTAL_LINE.search(text)
    if match:
        fields["total"] = _parse_amount(match.group(1))
        symbol = next((c for c in match.group(1) if c in CURRENCY_SYMBOL), "")
        fields["currency"] = (match.group(2) or CURRENCY_SYMBOL.get(symbol, "")).upper() or None

    match = VAT_RATE.search(text)
    if match:
        fields["vat_rate"] = float(match.group(1).replace(",", "."))
    match = VAT_ID.search(text)
    if match:
        fields["vat_id"] = match.group(1).replace(" ", "").upper()
    match = IBAN.search(text)
    if match:
        fields["iban"] = match.group(1).replace(" ", "")

    fields["emails"] = sorted(set(EMAIL.findall(text)))
    # Mask the IBAN first: "... 0532 0130 00" otherwise looks like a phone number.
    without_iban = IBAN.sub(" ", text)
    fields["phones"] = sorted({re.sub(r"[\s().\-]", "", p) for p in PHONE.findall(without_iban)})
    fields["missing_fields"] = [
        key for key in ("invoice_number", "invoice_date", "total", "currency") if not fields[key]
    ]
    return fields


def route(
    fields: dict[str, Any], auto_approve_below: float = 500.0, today: date | None = None
) -> dict[str, Any]:
    """Decide what the automation should do next with this document.

    This is the "takes action" step: complete, small and not urgent goes
    straight through; anything unusual is queued for a human.
    """
    reasons: list[str] = []
    if fields["missing_fields"]:
        reasons.append("missing:" + ",".join(fields["missing_fields"]))

    total = fields.get("total") or 0.0
    if total > auto_approve_below:
        reasons.append(f"amount_over_{auto_approve_below:.0f}")

    if fields.get("due_date"):
        days_left = (date.fromisoformat(fields["due_date"]) - (today or date.today())).days
        if days_left < 0:
            reasons.append("overdue")
        elif days_left <= 3:
            reasons.append("due_soon")

    return {
        "action": "auto_approve" if not reasons else "needs_review",
        "reasons": reasons,
        "amount": total,
        "currency": fields.get("currency"),
    }
