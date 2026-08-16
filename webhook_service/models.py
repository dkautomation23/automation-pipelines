"""Request/response schemas. Pydantic rejects malformed payloads at the door."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LeadIn(BaseModel):
    """Raw inbound lead. Deliberately permissive: forms send messy data, and
    rejecting a paying customer's lead over a stray field is worse than
    cleaning it up downstream."""

    model_config = ConfigDict(extra="allow")

    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=5000)
    source: str | None = Field(default=None, max_length=100)
    budget: str | float | None = None


class LeadStored(BaseModel):
    """What the service actually persisted, echoed back to the caller."""

    lead_id: str
    email: str
    name: str
    phone: str
    company: str
    source: str
    budget_eur: float | None
    score: int
    is_valid: bool
    issues: list[str]
    received_at: str


class IngestResponse(BaseModel):
    status: str
    lead: LeadStored
    sinks: dict[str, Any]
