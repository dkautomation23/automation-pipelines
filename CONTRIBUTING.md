# Contributing

Real commands for this repository. `.github/workflows/ci.yml` is the source of
truth if this page and CI ever disagree.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
cp .env.example .env          # then edit; .env is git-ignored, never commit it
```

Run it locally:

```bash
uvicorn webhook_service.main:app --reload --port 8000
```

## Before you write code

This repository carries two independent pieces glued by one n8n workflow: the
FastAPI intake (`webhook_service/`) and the document extractor
(`doc_extract/`). A change to one should not require touching the other. Open
an issue first for anything beyond a fix.

## The one rule that is not negotiable

A new check starts as a failing test. Add it to whichever file already covers
that area — `tests/test_cleaning.py`, `tests/test_extractor.py`, or
`tests/test_api.py` (drives the FastAPI app through `TestClient`, including
the `X-Webhook-Token` and de-duplication paths). Confirm it fails for the
right reason, then implement.

## Running the tests

```bash
python -m compileall -q .
python -m pytest -q
```

Same two steps CI runs, in that order. 47 tests today, no network, no Google,
no Slack.

## Commit messages

Match `git log --oneline` in this repository. It mixes two styles: a
`type:` prefix (`feat:`, `test:`, `docs:`, `chore:`) for a larger addition,
and a plain imperative sentence — optionally `Component: what changed` — for
a smaller one. Recent examples:

```
feat: lead cleaning, validation and scoring
test: cleaning, extraction and API coverage (47 tests, no network)
requirements: add python-multipart, which the upload endpoint needs
LICENSE: name the copyright holder, not the account handle
```

Match whichever style fits the size of the change. No ticket prefixes, no
emoji.

## License

Contributions are published under this repository's MIT license.
