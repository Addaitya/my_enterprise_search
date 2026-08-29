"""Offline unit checks for chunker + CSV packing (no Docker).

Run: ``cd backend && uv run python -m scripts.ingest_unit_checks``
"""

from __future__ import annotations

from app.services.ingest.chunker import chunk_text, estimate_tokens
from app.services.ingest.csv_extract import extract_csv_units, serialize_row


def test_estimate_and_chunk() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    long = ("word " * 500).strip()  # well over 600 tokens at ~4 chars
    assert estimate_tokens(long) > 600
    chunks = chunk_text(long, chunk_tokens=600, overlap_tokens=75)
    assert len(chunks) > 1
    # Overlap: consecutive chunks should share a suffix/prefix region.
    assert chunks[0][-50:] in chunks[1] or chunks[1][:80] in chunks[0]


def test_csv_pack_short_rows() -> None:
    header = "From,To,Subject,Body\n"
    rows = "".join(f"a{i}@co,b{i}@co,Hi{i},Short body {i}\n" for i in range(20))
    units = extract_csv_units((header + rows).encode("utf-8"), chunk_tokens=600, overlap_tokens=75)
    assert len(units) >= 1
    assert len(units) < 20  # packing should collapse short rows
    assert "From:" in units[0]
    assert "Subject:" in units[0]


def test_csv_oversized_row_splits() -> None:
    body = "x" * 4000  # ~1000 tokens
    csv_data = f"From,To,Subject,Body\na@co,b@co,Reset,{body}\n".encode("utf-8")
    units = extract_csv_units(csv_data, chunk_tokens=600, overlap_tokens=75)
    assert len(units) > 1
    assert all(estimate_tokens(u) <= 600 + 5 for u in units)  # small slack for boundaries


def test_serialize_skips_empty() -> None:
    text = serialize_row({"From": "a@co", "To": "", "Subject": None, "Body": "Hi"})
    assert text == "From: a@co\nBody: Hi"


def main() -> None:
    test_estimate_and_chunk()
    print("[ok] chunker")
    test_csv_pack_short_rows()
    print("[ok] csv pack short rows")
    test_csv_oversized_row_splits()
    print("[ok] csv oversized row splits")
    test_serialize_skips_empty()
    print("[ok] serialize")
    print("all unit checks passed")


if __name__ == "__main__":
    main()
