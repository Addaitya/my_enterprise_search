"""Ingest pipeline: parse → chunk → (orchestrator indexes)."""

from __future__ import annotations

from app.services.ingest.chunker import chunk_text
from app.services.ingest.csv_extract import CsvExtractError, extract_csv_units
from app.services.ingest.txt_extract import TxtExtractError, extract_txt


class IngestParseError(ValueError):
    """Unified parse/processing error surfaced as HTTP 422."""


def build_content_chunks(
    *,
    file_type: str,
    data: bytes,
    chunk_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """Return ordered content strings for OpenSearch chunks (no embeddings)."""
    try:
        if file_type == "txt":
            text = extract_txt(data)
            chunks = chunk_text(
                text, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens
            )
        elif file_type == "pdf":
            from app.services.ingest.pdf_extract import PdfExtractError, extract_pdf

            try:
                text = extract_pdf(data)
            except PdfExtractError as exc:
                raise IngestParseError(str(exc)) from exc
            chunks = chunk_text(
                text, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens
            )
        elif file_type == "csv":
            chunks = extract_csv_units(
                data, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens
            )
        else:
            raise IngestParseError(f"unsupported file_type: {file_type}")
    except (TxtExtractError, CsvExtractError) as exc:
        raise IngestParseError(str(exc)) from exc

    if not chunks:
        raise IngestParseError("no chunks produced")
    return chunks
