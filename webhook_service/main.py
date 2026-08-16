"""FastAPI intake service - the Python glue between n8n and storage.

    uvicorn webhook_service.main:app --reload --port 8000

Endpoints:
    GET  /health              liveness probe for n8n / uptime checks
    POST /webhook/lead        clean + store + notify one inbound lead
    POST /extract/document    pull structured fields out of a PDF or text file
"""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile

from .cleaning import clean_lead
from .config import Settings, get_settings
from .models import IngestResponse, LeadIn, LeadStored
from .sinks import build_sinks

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("webhook_service")

app = FastAPI(
    title="automation-pipelines webhook service",
    version="0.1.0",
    description="Receives webhooks from n8n (or any form), cleans the payload and stores it.",
)


def require_token(
    x_webhook_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Shared-secret check. Skipped when WEBHOOK_TOKEN is empty (local dev)."""
    if not settings.webhook_token:
        return
    if x_webhook_token != settings.webhook_token:
        raise HTTPException(status_code=401, detail="invalid or missing X-Webhook-Token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.post("/webhook/lead", response_model=IngestResponse, dependencies=[Depends(require_token)])
def ingest_lead(
    payload: LeadIn, settings: Settings = Depends(get_settings)
) -> IngestResponse:
    """Clean one lead, write it to every configured sink, report what happened.

    A sink failure is reported, not raised: the CSV audit trail is written
    first, so a lead is never lost because Sheets or Slack was unavailable.
    """
    record = clean_lead(payload.model_dump())
    results: dict[str, object] = {}

    sinks = build_sinks(settings)
    results["csv"] = sinks["csv"].append(record)
    if "sheets" in sinks:
        results["sheets"] = sinks["sheets"].append(record)
    if "notify" in sinks and record["is_valid"]:
        results["notify"] = sinks["notify"].send(record)

    log.info("lead %s stored (score=%s, issues=%s)", record["lead_id"], record["score"], record["issues"])
    return IngestResponse(
        status="accepted" if record["is_valid"] else "accepted_with_issues",
        lead=LeadStored(**{k: record[k] for k in LeadStored.model_fields}),
        sinks=results,
    )


@app.post("/extract/document", dependencies=[Depends(require_token)])
async def extract_document(file: UploadFile = File(...)) -> dict[str, object]:
    """Upload a PDF or .txt invoice and get the structured fields back.

    This is the 'read a document, then act on it' half of the pipeline: n8n
    hands over the attachment, Python returns fields it can route on.
    """
    from doc_extract.extractor import extract_fields, read_document

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        text = read_document(content, filename=file.filename or "upload")
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    fields = extract_fields(text)
    return {"filename": file.filename, "characters": len(text), "fields": fields}
