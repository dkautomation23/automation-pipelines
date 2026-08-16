# automation-pipelines

Sample project demonstrating production web-scraping / automation patterns.

An n8n workflow plus the Python service it calls: a webhook arrives, Python
cleans, validates, scores and de-duplicates the payload, then it is written to
CSV and Google Sheets and announced in Slack. A second module reads a PDF or
text document, extracts the fields an accounting workflow needs, and decides
whether it can be auto-approved or has to go to a human.

This is the shape of most "connect these tools and stop doing it by hand" jobs:
n8n owns the plumbing, Python owns the logic that would be painful inside a
no-code node.

---

## The flow

```
   form / CRM / n8n / curl
             |
             v
   [1] n8n Webhook  (POST /webhook/lead-intake)
             |
             v
   [2] HTTP Request -> FastAPI  POST /webhook/lead      <- the Python glue
             |                   . normalise name, email, phone, budget
             |                   . fix typo domains, flag disposable ones
             |                   . score the lead 0-100
             |                   . stable lead_id  -> de-duplication
             |                   . append to CSV (audit trail, always)
             v
   [3] IF  is_valid ?
        |            \
        | true        \ false
        v              v
   [4] Google Sheets   [6] Wait / review queue
        |                    |
        v                    |
   [5] Slack notify          |
        |                    |
        +---------> [7] Respond to caller (status + lead_id)
```

Importable workflow: [`n8n/webhook-to-sheets.json`](n8n/webhook-to-sheets.json)
(Import from File in n8n). It references `$env.PY_SERVICE_URL`,
`$env.WEBHOOK_TOKEN`, `$env.SHEETS_SPREADSHEET_ID` and `$env.SLACK_WEBHOOK_URL`
— no credentials are stored inside the JSON.

## What is in here

| Part | File | Job |
| --- | --- | --- |
| Intake API | `webhook_service/main.py` | FastAPI: `/health`, `/webhook/lead`, `/extract/document` |
| Cleaning | `webhook_service/cleaning.py` | normalisation, validation, scoring, stable `lead_id` |
| Sinks | `webhook_service/sinks.py` | CSV (always), Google Sheets via gspread, any notify webhook |
| Config | `webhook_service/config.py` | every secret comes from the environment |
| Documents | `doc_extract/extractor.py` | PDF/text → invoice fields → routing decision |
| Workflow | `n8n/webhook-to-sheets.json` | the n8n side of the pipeline |

Design rules the code follows:

- **The lead is never lost.** CSV is written before the remote sinks, and a
  failing Sheets or Slack call is reported in the response instead of raised.
- **Bad data is marked, not dropped.** An invalid e-mail returns
  `accepted_with_issues` and lands in the review branch.
- **The same submission twice is one row.** `lead_id` is a hash of the
  identity fields, and every sink checks it.
- **Secrets only in the environment.** `.env.example` documents every variable;
  the real `.env` and the service-account key are git-ignored.

## Install and run

```bash
git clone https://github.com/dkautomation23/automation-pipelines.git
cd automation-pipelines
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                              # then edit
uvicorn webhook_service.main:app --reload --port 8000
```

Python 3.10+. Interactive API docs at `http://localhost:8000/docs`.

### Send a lead

```bash
curl -X POST http://localhost:8000/webhook/lead \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: demo-token" \
  -d @samples/lead_payload.json
```

Input (`samples/lead_payload.json`) — deliberately messy, like a real form:

```json
{
  "name": "  anna   SCHMIDT ",
  "email": " Anna.Schmidt@GMIAL.COM ",
  "phone": "0049 (170) 555-24-18",
  "company": "Meridian Analytics Ltd",
  "budget": "around 3k EUR",
  "source": "website_form"
}
```

Response:

```json
{
  "status": "accepted",
  "lead": {
    "lead_id": "eca1c85b8ee0860c",
    "email": "anna.schmidt@gmail.com",
    "name": "Anna Schmidt",
    "phone": "+491705552418",
    "company": "Meridian Analytics Ltd",
    "budget_eur": 3000.0,
    "score": 100,
    "is_valid": true,
    "issues": ["email_typo_fixed:gmial.com"],
    "received_at": "2026-08-16T07:02:52Z"
  },
  "sinks": { "csv": { "ok": true, "path": "data/leads.csv" } }
}
```

Posting it a second time returns the same `lead_id` and
`"sinks": {"csv": {"ok": true, "skipped": "duplicate"}}`. Without the token the
endpoint answers `401`.

Stored rows (`samples/leads_out.csv`, produced by the run above):

```csv
lead_id,received_at,name,email,phone,company,source,budget_eur,score,is_valid,issues,message
eca1c85b8ee0860c,2026-08-16T07:02:52Z,Anna Schmidt,anna.schmidt@gmail.com,+491705552418,Meridian Analytics Ltd,website_form,3000.0,100,True,email_typo_fixed:gmial.com,...
70ae7f4153bf9c2f,2026-08-16T07:03:03Z,Piet van Beek,p.vanbeek@example.com,+31205558899,Delta Retail BV,referral,2300.0,100,True,,...
2803fafb855a7a8f,2026-08-16T07:03:03Z,Bob,bob(at)example.com,,,landing_page,,0,False,email_invalid,...
```

### Read a document

```bash
python -m doc_extract samples/invoice_sample.txt
```

```console
file           : invoice_sample.txt (1037 chars)
invoice number : NW-2026-04871
invoice date   : 2026-08-05
due date       : 2026-08-19
total          : 2397.85 EUR
vat            : 19.0%  id: DE123456789
iban           : DE89370400440532013000
contacts       : accounts@nordwind-supplies.example, billing@nordwind-supplies.example, +49405550122
decision       : needs_review (amount_over_500, due_soon)
```

`--json` prints the same data as JSON for piping back into n8n, and
`--auto-approve-below` moves the review threshold. The same code is exposed over
HTTP at `POST /extract/document` (multipart upload), which is how n8n hands over
an e-mail attachment.

Extraction is deterministic — regex and rules, no API cost, no hallucinated
totals. Handles EN/DE wording, both decimal conventions (`1.234,56` and
`1,234.56`), and reports what it could **not** find in `missing_fields` so the
routing step can send exactly those documents to a human.

## Google Sheets

1. Google Cloud Console → enable the Sheets API → create a **service account**
   → create a JSON key.
2. Store the key outside the repository and point `GOOGLE_CREDENTIALS_FILE` at it.
3. Share the spreadsheet with the service-account e-mail (`...iam.gserviceaccount.com`)
   as an Editor — this is the step everyone forgets.
4. Set `SHEETS_ENABLED=true` and `SHEETS_SPREADSHEET_ID=<id from the URL>`.

The worksheet and its header row are created automatically on the first write.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `WEBHOOK_TOKEN` | – | shared secret for `X-Webhook-Token`; empty disables auth (local only) |
| `CSV_PATH` | `data/leads.csv` | local audit trail |
| `SHEETS_ENABLED` | `false` | turn the Google Sheets sink on |
| `GOOGLE_CREDENTIALS_FILE` | – | path to the service-account key (never committed) |
| `SHEETS_SPREADSHEET_ID` | – | id from the spreadsheet URL |
| `NOTIFY_WEBHOOK_URL` | – | Slack/Discord/n8n incoming webhook |
| `NOTIFY_MIN_SCORE` | `0` | only notify above this lead score |

## Tests

```bash
pytest -q
```

```console
...............................................                          [100%]
47 passed in 0.62s
```

Covers the cleaning rules (typo domains, phone formats, budgets like
`around 3k EUR`), invoice extraction against the sample document, routing
decisions, and the API end to end via `TestClient` — including auth,
de-duplication and the 415 path. No network, no Google, no Slack.

## License

MIT — see [LICENSE](LICENSE).
