"""End-to-end API tests with FastAPI's TestClient - no network, no Google, no Slack."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webhook_service.config import Settings, get_settings
from webhook_service.main import app

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


@pytest.fixture
def client(tmp_path):
    """A client whose only sink is a CSV inside tmp_path."""
    app.dependency_overrides[get_settings] = lambda: Settings(
        webhook_token="test-token",
        csv_path=str(tmp_path / "leads.csv"),
        sheets_enabled=False,
        notify_url="",
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def payload():
    return json.loads((SAMPLES / "lead_payload.json").read_text(encoding="utf-8"))


def test_health_needs_no_auth(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_missing_token_is_rejected(client):
    assert client.post("/webhook/lead", json=payload()).status_code == 401


def test_lead_is_cleaned_stored_and_echoed(client, tmp_path):
    response = client.post(
        "/webhook/lead", json=payload(), headers={"X-Webhook-Token": "test-token"}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "accepted"
    assert body["lead"]["email"] == "anna.schmidt@gmail.com"   # typo domain fixed
    assert body["lead"]["phone"] == "+491705552418"
    assert body["lead"]["budget_eur"] == 3000.0
    assert body["sinks"]["csv"]["ok"] is True

    csv_text = (tmp_path / "leads.csv").read_text(encoding="utf-8-sig")
    assert "anna.schmidt@gmail.com" in csv_text
    assert csv_text.splitlines()[0].startswith("lead_id,received_at,name")


def test_the_same_lead_twice_is_written_once(client, tmp_path):
    headers = {"X-Webhook-Token": "test-token"}
    first = client.post("/webhook/lead", json=payload(), headers=headers).json()
    second = client.post("/webhook/lead", json=payload(), headers=headers).json()

    assert first["lead"]["lead_id"] == second["lead"]["lead_id"]
    assert second["sinks"]["csv"]["skipped"] == "duplicate"
    assert len((tmp_path / "leads.csv").read_text(encoding="utf-8-sig").strip().splitlines()) == 2


def test_invalid_lead_is_accepted_but_marked(client):
    response = client.post(
        "/webhook/lead",
        json={"name": "Bob", "email": "bob(at)example.com"},
        headers={"X-Webhook-Token": "test-token"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "accepted_with_issues"
    assert body["lead"]["is_valid"] is False
    assert "email_invalid" in body["lead"]["issues"]


def test_document_endpoint_returns_structured_fields(client):
    with (SAMPLES / "invoice_sample.txt").open("rb") as handle:
        response = client.post(
            "/extract/document",
            files={"file": ("invoice_sample.txt", handle, "text/plain")},
            headers={"X-Webhook-Token": "test-token"},
        )
    assert response.status_code == 200
    fields = response.json()["fields"]
    assert fields["invoice_number"] == "NW-2026-04871"
    assert fields["total"] == 2397.85


def test_document_endpoint_rejects_unsupported_type(client):
    response = client.post(
        "/extract/document",
        files={"file": ("scan.docx", b"binary-content", "application/octet-stream")},
        headers={"X-Webhook-Token": "test-token"},
    )
    assert response.status_code == 415
