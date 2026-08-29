"""CSV → serialized row groups packed by token budget (G4–G6, C1).

- UTF-8, comma delimiter, excel dialect, first row = header.
- Reject zero data rows.
- Serialize every column as ``ColumnName: value`` lines; skip empty cells;
  rows in a packed group separated by a blank line.
- Pack consecutive rows while estimate_tokens(group) ≤ chunk_tokens.
- Never split mid-row when packing; oversized single row → text chunker.
"""

from __future__ import annotations

import csv
from io import StringIO

from app.services.ingest.chunker import chunk_text, estimate_tokens


class CsvExtractError(ValueError):
    """Raised for bad encoding, missing header, or zero data rows."""


def serialize_row(row: dict[str, str | None]) -> str:
    lines: list[str] = []
    for key, value in row.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        col = (key or "").strip() or "column"
        lines.append(f"{col}: {text}")
    return "\n".join(lines)


def extract_csv_units(
    data: bytes,
    *,
    chunk_tokens: int = 600,
    overlap_tokens: int = 75,
) -> list[str]:
    """Return text units ready for chunk identity assignment.

    Most units are already ≤ chunk_tokens (packed groups). Oversized single
    rows are pre-split by the overlapping chunker.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CsvExtractError("CSV must be UTF-8") from exc

    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        raise CsvExtractError("CSV requires a header row")

    rows = list(reader)
    if not rows:
        raise CsvExtractError("CSV has zero data rows")

    serialized_rows: list[str] = []
    for row in rows:
        unit = serialize_row(row)
        if unit:
            serialized_rows.append(unit)

    if not serialized_rows:
        raise CsvExtractError("CSV has no non-empty cells")

    units: list[str] = []
    group_parts: list[str] = []

    def flush_group() -> None:
        nonlocal group_parts
        if not group_parts:
            return
        group_text = "\n\n".join(group_parts)
        if estimate_tokens(group_text) <= chunk_tokens:
            units.append(group_text)
        else:
            # Estimator drift on a packed group — force-split.
            units.extend(
                chunk_text(
                    group_text,
                    chunk_tokens=chunk_tokens,
                    overlap_tokens=overlap_tokens,
                )
            )
        group_parts = []

    for row_text in serialized_rows:
        row_tokens = estimate_tokens(row_text)
        if row_tokens > chunk_tokens:
            flush_group()
            units.extend(
                chunk_text(
                    row_text,
                    chunk_tokens=chunk_tokens,
                    overlap_tokens=overlap_tokens,
                )
            )
            continue

        if not group_parts:
            group_parts = [row_text]
            continue

        candidate = "\n\n".join([*group_parts, row_text])
        if estimate_tokens(candidate) <= chunk_tokens:
            group_parts.append(row_text)
        else:
            flush_group()
            group_parts = [row_text]

    flush_group()
    if not units:
        raise CsvExtractError("CSV produced no chunks")
    return units
