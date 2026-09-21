"""Field extraction and routing, checked against the sample invoice."""

from datetime import date
from pathlib import Path

import pytest

from doc_extract.extractor import _parse_amount, extract_fields, read_document, route

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "invoice_sample.txt"


@pytest.fixture(scope="module")
def fields():
    return extract_fields(SAMPLE.read_text(encoding="utf-8"))


def test_invoice_header_fields(fields):
    assert fields["invoice_number"] == "NW-2026-04871"
    assert fields["invoice_date"] == "2026-08-05"
    assert fields["due_date"] == "2026-08-19"


def test_amount_and_currency(fields):
    assert fields["total"] == 2397.85
    assert fields["currency"] == "EUR"
    assert fields["vat_rate"] == 19.0


def test_identifiers_and_contacts(fields):
    assert fields["vat_id"] == "DE123456789"
    assert fields["iban"] == "DE89370400440532013000"
    assert "billing@nordwind-supplies.example" in fields["emails"]
    assert fields["phones"] == ["+4930231252"]
    assert fields["missing_fields"] == []


@pytest.mark.parametrize(
    "raw,expected",
    [("1.234,56", 1234.56), ("1,234.56", 1234.56), ("2 397,85", 2397.85), ("95", 95.0), ("", None)],
)
def test_amount_parsing_handles_both_conventions(raw, expected):
    assert _parse_amount(raw) == expected


def test_read_document_rejects_unsupported_types():
    with pytest.raises(ValueError):
        read_document(b"binary", filename="scan.docx")


def test_read_document_reads_plain_text():
    assert read_document("hello".encode(), filename="note.txt") == "hello"


def test_routing_flags_a_large_invoice_for_review(fields):
    decision = route(fields, auto_approve_below=500, today=date(2026, 8, 10))
    assert decision["action"] == "needs_review"
    assert "amount_over_500" in decision["reasons"]
    assert decision["amount"] == 2397.85


def test_routing_auto_approves_a_small_complete_invoice():
    small = {
        "invoice_number": "X-1",
        "invoice_date": "2026-08-01",
        "due_date": "2026-09-01",
        "total": 120.0,
        "currency": "EUR",
        "missing_fields": [],
    }
    decision = route(small, auto_approve_below=500, today=date(2026, 8, 10))
    assert decision["action"] == "auto_approve"
    assert decision["reasons"] == []


@pytest.mark.parametrize(
    "due,expected_reason",
    [("2026-08-08", "overdue"), ("2026-08-11", "due_soon")],
)
def test_routing_watches_the_due_date(due, expected_reason):
    doc = {
        "invoice_number": "X-2",
        "invoice_date": "2026-08-01",
        "due_date": due,
        "total": 50.0,
        "currency": "EUR",
        "missing_fields": [],
    }
    decision = route(doc, auto_approve_below=500, today=date(2026, 8, 10))
    assert expected_reason in decision["reasons"]


def test_missing_fields_are_reported_and_force_review():
    fields = extract_fields("Just a note with no invoice data at all.")
    assert set(fields["missing_fields"]) >= {"invoice_number", "total", "currency"}
    assert route(fields)["action"] == "needs_review"
