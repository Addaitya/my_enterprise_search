"""Filename / content-type → product file_type (pdf|txt|csv)."""

from __future__ import annotations

from pathlib import Path

ALLOWED_EXTENSIONS = {
    ".pdf": "pdf",
    ".txt": "txt",
    ".csv": "csv",
}

# Advisory only — extension is source of truth (MIME allowlist table).
ADVISORY_CONTENT_TYPES: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "txt": {"text/plain"},
    "csv": {"text/csv", "application/csv", "text/plain"},
}


def safe_filename(filename: str) -> str:
    """Basename only; reject empty / path traversal residue."""
    name = Path(filename.replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("invalid filename")
    return name


def detect_file_type(filename: str) -> str:
    """Return pdf|txt|csv from lowercased extension. Raises ValueError if unsupported."""
    name = safe_filename(filename)
    ext = Path(name).suffix.lower()
    file_type = ALLOWED_EXTENSIONS.get(ext)
    if file_type is None:
        raise ValueError(f"unsupported extension: {ext or '(none)'}")
    return file_type
