"""PDF text extraction via pypdf (C4). No OCR."""

from __future__ import annotations

from io import BytesIO


class PdfExtractError(ValueError):
    """Raised when PDF has no extractable text or cannot be parsed."""


def extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfExtractError(
            "pypdf is not installed; run `uv sync` in backend/"
        ) from exc

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — surface as processing error
        raise PdfExtractError(f"invalid PDF: {exc}") from exc

    parts: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            page_text = ""
        if page_text.strip():
            parts.append(page_text.strip())

    text = "\n\n".join(parts).strip()
    if not text:
        raise PdfExtractError("PDF has no extractable text (OCR not supported)")
    return text
