"""Turn a messy inbound payload into one clean, scored, deduplicable record.

This is the part clients actually pay for: form data arrives with typos,
mixed casing, phone numbers in six formats and budgets written as
"around 3k EUR". Everything downstream assumes the output of this module.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[a-z]{2,}$", re.IGNORECASE)
# Typos that account for most bounced form emails.
DOMAIN_TYPOS = {
    "gmial.com": "gmail.com",
    "gmai.com": "gmail.com",
    "gmail.co": "gmail.com",
    "hotmial.com": "hotmail.com",
    "outlok.com": "outlook.com",
    "yahho.com": "yahoo.com",
    # RFC 2606 keeps example.com unregistrable, which makes it the only domain
    # safe to put in public sample data - and it gets mistyped like any other.
    "exmaple.com": "example.com",
}
DISPOSABLE_DOMAINS = {"mailinator.com", "10minutemail.com", "tempmail.com", "guerrillamail.com"}
_MULTISPACE = re.compile(r"\s+")
# Name particles that stay lower-case unless they open the name.
_PARTICLES = {"van", "von", "de", "der", "den", "di", "da", "du", "la", "le", "bin", "al"}
_NON_PHONE = re.compile(r"[^\d+]")
_MONEY = re.compile(r"(\d[\d\s.,]*)\s*(k|тыс|thousand)?", re.IGNORECASE)
_CURRENCY_HINTS = {"$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP"}
# Rough conversion, only used to make budgets comparable in one column.
FX_TO_EUR = {"EUR": 1.0, "USD": 0.92, "GBP": 1.17}


def clean_text(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    return _MULTISPACE.sub(" ", str(value)).strip()[:limit]


def clean_name(value: Any) -> str:
    """'  john   O'BRIEN ' -> 'John O'Brien'.

    Re-cases only words that are entirely upper or lower case, so deliberate
    casing like 'McDonald' or 'van Beek' survives untouched.
    """
    text = clean_text(value, 200)
    words = []
    for index, word in enumerate(text.split(" ")):
        if index and word.lower() in _PARTICLES:
            words.append(word.lower())
        elif word.isupper() or word.islower():
            words.append(word.title())
        else:
            words.append(word)
    return " ".join(words)


def clean_email(value: Any) -> tuple[str, list[str]]:
    """Lower-case, fix common domain typos, flag invalid/disposable addresses."""
    issues: list[str] = []
    email = clean_text(value, 320).lower().replace(" ", "")
    if not email:
        return "", ["email_missing"]
    if "@" in email:
        local, _, domain = email.rpartition("@")
        if domain in DOMAIN_TYPOS:
            issues.append(f"email_typo_fixed:{domain}")
            domain = DOMAIN_TYPOS[domain]
        email = f"{local}@{domain}"
        if domain in DISPOSABLE_DOMAINS:
            issues.append("email_disposable")
    if not EMAIL_RE.match(email):
        issues.append("email_invalid")
    return email, issues


def clean_phone(value: Any, default_country_code: str = "+49") -> str:
    """Strip formatting to digits; '00' and bare national numbers become E.164-ish."""
    raw = _NON_PHONE.sub("", clean_text(value, 50))
    if not raw:
        return ""
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    elif not raw.startswith("+"):
        raw = default_country_code + raw.lstrip("0")
    digits = raw[1:]
    return raw if 7 <= len(digits) <= 15 else ""


def parse_budget(value: Any) -> float | None:
    """'3k EUR' -> 3000.0, '$2,500' -> 2300.0 (EUR), 'no idea' -> None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().lower()
    currency = next((code for token, code in _CURRENCY_HINTS.items() if token in text), "EUR")
    match = _MONEY.search(text)
    if not match:
        return None
    number = match.group(1).replace(" ", "").replace(",", "")
    # "1.500" is European thousands, "1.5" is a decimal.
    if number.count(".") == 1 and len(number.split(".")[1]) == 3:
        number = number.replace(".", "")
    try:
        amount = float(number)
    except ValueError:
        return None
    if match.group(2):
        amount *= 1000
    return round(amount * FX_TO_EUR.get(currency, 1.0), 2)


def score_lead(record: dict[str, Any]) -> int:
    """0-100 priority score, so the team looks at the right lead first."""
    score = 0
    if record["email"] and "email_invalid" not in record["issues"]:
        score += 40
    if record["phone"]:
        score += 15
    if record["company"]:
        score += 15
    if (record["budget_eur"] or 0) >= 1000:
        score += 20
    if len(record["message"]) >= 40:
        score += 10
    if "email_disposable" in record["issues"]:
        score -= 30
    return max(0, min(100, score))


def clean_lead(payload: dict[str, Any]) -> dict[str, Any]:
    """Full pipeline: normalise -> validate -> score -> stable id."""
    email, issues = clean_email(payload.get("email"))
    record: dict[str, Any] = {
        "name": clean_name(payload.get("name")),
        "email": email,
        "phone": clean_phone(payload.get("phone")),
        "company": clean_text(payload.get("company"), 200),
        "message": clean_text(payload.get("message"), 5000),
        "source": clean_text(payload.get("source"), 100) or "unknown",
        "budget_eur": parse_budget(payload.get("budget")),
        "issues": issues,
        "received_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not record["name"]:
        record["issues"].append("name_missing")

    record["score"] = score_lead(record)
    record["is_valid"] = "email_invalid" not in record["issues"] and "email_missing" not in record["issues"]
    # Stable id from the identity fields: re-submitting the same form is a
    # duplicate, not a new lead.
    identity = f"{record['email']}|{record['phone']}".encode()
    record["lead_id"] = hashlib.sha256(identity).hexdigest()[:16]
    return record
