"""Configuration, read once from the environment (.env in development).

Every secret is an environment variable - nothing is hard-coded and nothing
sensitive is committed. See .env.example for the full list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    # Shared secret expected in the X-Webhook-Token header. Empty = auth disabled
    # (fine for local testing, never for a public deployment).
    webhook_token: str = os.getenv("WEBHOOK_TOKEN", "")

    # CSV sink - always on, it is the audit trail if a remote sink fails.
    csv_path: str = os.getenv("CSV_PATH", "data/leads.csv")

    # Google Sheets sink (optional).
    sheets_enabled: bool = _flag("SHEETS_ENABLED", False)
    sheets_credentials_file: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "service_account.json")
    sheets_spreadsheet_id: str = os.getenv("SHEETS_SPREADSHEET_ID", "")
    sheets_worksheet: str = os.getenv("SHEETS_WORKSHEET", "Leads")

    # Notification sink (optional): any incoming-webhook URL - Slack, Discord,
    # Telegram bridge, or an n8n webhook node.
    notify_url: str = os.getenv("NOTIFY_WEBHOOK_URL", "")
    notify_min_score: int = int(os.getenv("NOTIFY_MIN_SCORE", "0"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
