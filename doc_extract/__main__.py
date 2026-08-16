"""Allow `python -m doc_extract <file>`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
