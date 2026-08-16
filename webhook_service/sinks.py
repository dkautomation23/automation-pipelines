"""Where a cleaned lead goes: CSV always, Google Sheets and a notifier optionally.

Each sink is independent and never raises into the request path - a broken
Slack webhook must not lose the lead. Failures are reported in the response.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

import requests

from .config import Settings

log = logging.getLogger(__name__)

COLUMNS = [
    "lead_id",
    "received_at",
    "name",
    "email",
    "phone",
    "company",
    "source",
    "budget_eur",
    "score",
    "is_valid",
    "issues",
    "message",
]


def _row(record: dict[str, Any]) -> list[Any]:
    flat = dict(record)
    flat["issues"] = "; ".join(record.get("issues", []))
    flat["budget_eur"] = "" if record.get("budget_eur") is None else record["budget_eur"]
    return [flat.get(column, "") for column in COLUMNS]


class CsvSink:
    """Append-only CSV. Writes the header once and skips known lead_ids."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def existing_ids(self) -> set[str]:
        if not self.path.exists():
            return set()
        with self.path.open(encoding="utf-8-sig", newline="") as handle:
            return {row["lead_id"] for row in csv.DictReader(handle) if row.get("lead_id")}

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        if record["lead_id"] in self.existing_ids():
            return {"ok": True, "skipped": "duplicate"}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        is_new_file = not self.path.exists()
        with self.path.open("a", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            if is_new_file:
                writer.writerow(COLUMNS)
            writer.writerow(_row(record))
        return {"ok": True, "path": str(self.path)}


class GoogleSheetsSink:
    """Appends a row to a worksheet via gspread + a service account.

    The credentials file is never committed; its path comes from the
    GOOGLE_CREDENTIALS_FILE environment variable. Share the spreadsheet with
    the service account e-mail before the first run.
    """

    def __init__(self, credentials_file: str, spreadsheet_id: str, worksheet: str) -> None:
        self.credentials_file = credentials_file
        self.spreadsheet_id = spreadsheet_id
        self.worksheet_name = worksheet
        self._worksheet = None

    def _connect(self):
        if self._worksheet is not None:
            return self._worksheet
        import gspread  # imported lazily so the service runs without the dep

        client = gspread.service_account(filename=self.credentials_file)
        spreadsheet = client.open_by_key(self.spreadsheet_id)
        try:
            worksheet = spreadsheet.worksheet(self.worksheet_name)
        except Exception:  # worksheet missing on first run
            worksheet = spreadsheet.add_worksheet(self.worksheet_name, rows=1000, cols=len(COLUMNS))
            worksheet.append_row(COLUMNS)
        self._worksheet = worksheet
        return worksheet

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            worksheet = self._connect()
            worksheet.append_row(_row(record), value_input_option="USER_ENTERED")
            return {"ok": True, "worksheet": self.worksheet_name}
        except Exception as exc:  # never break intake because Sheets is down
            log.exception("sheets append failed")
            return {"ok": False, "error": str(exc)}


class NotifySink:
    """POSTs a short summary to any incoming webhook (Slack, Discord, n8n)."""

    def __init__(self, url: str, min_score: int = 0, timeout: float = 8.0) -> None:
        self.url = url
        self.min_score = min_score
        self.timeout = timeout

    def send(self, record: dict[str, Any]) -> dict[str, Any]:
        if record["score"] < self.min_score:
            return {"ok": True, "skipped": f"score<{self.min_score}"}
        budget = record["budget_eur"]
        text = (
            f"New lead ({record['score']}/100): {record['name'] or 'no name'} "
            f"<{record['email']}> - {record['company'] or 'no company'}"
            f"{f', ~{budget:.0f} EUR' if budget else ''}"
        )
        try:
            response = requests.post(
                self.url, json={"text": text, "lead": record}, timeout=self.timeout
            )
            response.raise_for_status()
            return {"ok": True, "status": response.status_code}
        except requests.RequestException as exc:
            log.warning("notify failed: %s", exc)
            return {"ok": False, "error": str(exc)}


def build_sinks(settings: Settings) -> dict[str, Any]:
    """Assemble the sinks that are actually configured."""
    sinks: dict[str, Any] = {"csv": CsvSink(settings.csv_path)}
    if settings.sheets_enabled and settings.sheets_spreadsheet_id:
        sinks["sheets"] = GoogleSheetsSink(
            settings.sheets_credentials_file,
            settings.sheets_spreadsheet_id,
            settings.sheets_worksheet,
        )
    if settings.notify_url:
        sinks["notify"] = NotifySink(settings.notify_url, settings.notify_min_score)
    return sinks
