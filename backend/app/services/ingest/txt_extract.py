"""Plain-text extraction (UTF-8)."""

from __future__ import annotations


class TxtExtractError(ValueError):
    """Raised when bytes are not valid UTF-8 or yield no text."""


def extract_txt(data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TxtExtractError("TXT must be UTF-8") from exc
    cleaned = text.strip()
    if not cleaned:
        raise TxtExtractError("TXT has no extractable text")
    return cleaned
