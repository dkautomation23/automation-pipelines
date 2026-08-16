"""Structured-data extraction from PDFs and plain text documents."""

from .extractor import extract_fields, read_document, route

__all__ = ["extract_fields", "read_document", "route"]
