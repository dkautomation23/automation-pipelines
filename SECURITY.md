# Security policy

automation-pipelines is a FastAPI service (`webhook_service`) plus a document
extractor (`doc_extract`) that n8n calls over HTTP. This file defines what
counts as a security issue in that specific service.

## Reporting

Use GitHub's private vulnerability reporting on this repository: **Security →
Report a vulnerability**. It opens a private thread; nothing becomes public
until there is a fix.

If that is not available to you, email **hello@dkautomation.dev** with
`automation-pipelines` in the subject line.

Include the commit or version you ran, the exact request (method, path,
headers with the token value removed), and what happened. A proof of concept
is welcome; a scanner's raw output usually is not.

**Do not open a public issue for a vulnerability.**

## Supported versions

No tagged releases yet — the `main` branch is the supported version. Report
against the commit you actually ran.

## What to expect

| | |
|---|---|
| First reply | within 3 working days |
| Assessment | within 7 working days of the first reply |
| Fix or a stated decision not to fix | within 30 days for anything reproducible |

Single-person commitments, not a company SLA.

## Scope

In scope:

- Reaching `POST /webhook/lead` or `POST /extract/document` without a valid
  `X-Webhook-Token`, while `WEBHOOK_TOKEN` is set, by any means other than
  the documented "empty token disables auth" behaviour.
- A forged, replayed, or otherwise fabricated request being accepted as
  authentic. There is no request-signature scheme today — only the shared
  `X-Webhook-Token` header — so treat any way to pass as authenticated
  without that exact header value as in scope now, and any future signature
  check that can be bypassed as in scope once one exists.
- A request body, or an upload to `POST /extract/document`, large or slow
  enough to exhaust memory or CPU — there is no request size limit in front
  of either endpoint today.
- `GOOGLE_CREDENTIALS_FILE`, `WEBHOOK_TOKEN`, or `NOTIFY_WEBHOOK_URL` values
  appearing in a log line, an API response, or the CSV audit trail.
- A lead field (`name`, `email`, `company`, `message`, `source`) reaching the
  CSV or Google Sheets sink in a way that executes as a formula when the
  sheet is opened.

Out of scope:

- Running the service locally with `WEBHOOK_TOKEN` unset — documented as
  disabling auth for local development only, never for a public deployment.
- The n8n workflow file (`n8n/webhook-to-sheets.json`) itself — it carries no
  credentials; problems with your own n8n instance belong with n8n.
- Google Sheets, Slack, or any other configured sink being unreachable,
  slow, or misconfigured on your end.

## Credit

Named in the fix's release notes if you want that; say so if you would rather
not be.

There is no bug bounty.
