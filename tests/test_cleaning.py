"""Cleaning rules: the messy real-world inputs this pipeline is built for."""

import pytest

from webhook_service.cleaning import (
    clean_email,
    clean_lead,
    clean_name,
    clean_phone,
    parse_budget,
    score_lead,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  john   O'BRIEN ", "John O'Brien"),
        ("ANNA SCHMIDT", "Anna Schmidt"),
        ("McDonald", "McDonald"),          # deliberate casing is preserved
        ("piet van beek", "Piet van Beek"),  # particles stay lower-case
        (None, ""),
    ],
)
def test_clean_name(raw, expected):
    assert clean_name(raw) == expected


def test_clean_email_fixes_typo_domains_and_flags_them():
    email, issues = clean_email(" Anna.Schmidt@GMIAL.COM ")
    assert email == "anna.schmidt@gmail.com"
    assert "email_typo_fixed:gmial.com" in issues
    assert "email_invalid" not in issues


@pytest.mark.parametrize(
    "raw,flag",
    [("not-an-email", "email_invalid"), ("", "email_missing"), ("a@mailinator.com", "email_disposable")],
)
def test_clean_email_flags_bad_addresses(raw, flag):
    _, issues = clean_email(raw)
    assert flag in issues


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0049 (170) 555-24-18", "+491705552418"),
        ("+44 20 7946 0958", "+442079460958"),
        ("0170 5552418", "+491705552418"),   # national number gets the default code
        ("12", ""),                          # too short -> rejected
        (None, ""),
    ],
)
def test_clean_phone(raw, expected):
    assert clean_phone(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("around 3k EUR", 3000.0),
        ("1.500 EUR", 1500.0),      # European thousands separator
        ("$2,500", 2300.0),         # converted to EUR at a fixed rate
        (4200, 4200.0),
        ("no idea", None),
        (None, None),
    ],
)
def test_parse_budget(raw, expected):
    assert parse_budget(raw) == expected


def test_clean_lead_produces_a_complete_record():
    record = clean_lead(
        {
            "name": "  anna   SCHMIDT ",
            "email": " Anna.Schmidt@GMIAL.COM ",
            "phone": "0049 (170) 555-24-18",
            "company": "Meridian Analytics Ltd",
            "message": "We scrape 20 supplier sites by hand every Monday and need it automated.",
            "budget": "around 3k EUR",
            "source": "website_form",
        }
    )

    assert record["name"] == "Anna Schmidt"
    assert record["email"] == "anna.schmidt@gmail.com"
    assert record["phone"] == "+491705552418"
    assert record["budget_eur"] == 3000.0
    assert record["is_valid"] is True
    assert record["score"] == 100
    assert len(record["lead_id"]) == 16
    assert record["received_at"].endswith("Z")


def test_lead_id_is_stable_for_the_same_person_and_differs_otherwise():
    first = clean_lead({"email": "a@b.com", "phone": "+49170000000"})
    again = clean_lead({"email": "A@B.COM ", "phone": "0049170000000"})
    other = clean_lead({"email": "c@d.com", "phone": "+49170000001"})

    assert first["lead_id"] == again["lead_id"]   # re-submitting a form is a duplicate
    assert first["lead_id"] != other["lead_id"]


def test_invalid_email_marks_the_lead_but_never_drops_it():
    record = clean_lead({"name": "Bob", "email": "bob(at)example.com"})
    assert record["is_valid"] is False
    assert "email_invalid" in record["issues"]
    assert record["name"] == "Bob"                # payload is still preserved


def test_disposable_address_is_penalised_in_the_score():
    base = {"email": "x@example.com", "phone": "+49170123456", "company": "ACME", "message": "x" * 50}
    clean = clean_lead(base)
    throwaway = clean_lead({**base, "email": "x@mailinator.com"})
    assert throwaway["score"] < clean["score"]


def test_score_is_clamped_to_the_0_100_range():
    empty = {"email": "", "phone": "", "company": "", "message": "", "budget_eur": None, "issues": []}
    assert score_lead(empty) == 0
