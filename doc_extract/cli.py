"""Extract fields from a document and print them (or JSON for piping).

    python -m doc_extract samples/invoice_sample.txt
    python -m doc_extract invoice.pdf --json --auto-approve-below 1000
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .extractor import extract_fields, read_document, route


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doc_extract",
        description="Extract invoice fields from a PDF or text file and route the result.",
    )
    parser.add_argument("path", help="PDF or text document")
    parser.add_argument("--json", action="store_true", help="print raw JSON instead of a summary")
    parser.add_argument(
        "--auto-approve-below",
        type=float,
        default=500.0,
        help="amounts below this go through without review (default: 500)",
    )
    args = parser.parse_args(argv)

    source = Path(args.path)
    if not source.exists():
        parser.error(f"file not found: {source}")

    text = read_document(source.read_bytes(), filename=source.name)
    fields = extract_fields(text)
    decision = route(fields, auto_approve_below=args.auto_approve_below)

    if args.json:
        print(json.dumps({"fields": fields, "decision": decision}, indent=2, ensure_ascii=False))
        return 0

    amount = f"{fields['total']:.2f} {fields['currency']}" if fields["total"] else "-"
    contacts = ", ".join(fields["emails"] + fields["phones"]) or "-"
    print(f"file           : {source.name} ({len(text)} chars)")
    print(f"invoice number : {fields['invoice_number'] or '-'}")
    print(f"invoice date   : {fields['invoice_date'] or '-'}")
    print(f"due date       : {fields['due_date'] or '-'}")
    print(f"total          : {amount}")
    print(f"vat            : {fields['vat_rate'] or '-'}%  id: {fields['vat_id'] or '-'}")
    print(f"iban           : {fields['iban'] or '-'}")
    print(f"contacts       : {contacts}")
    print(f"decision       : {decision['action']} ({', '.join(decision['reasons']) or 'all checks passed'})")
    return 0
