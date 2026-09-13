"""Offline unit checks for chunker + CSV packing (no Docker).

Run: ``cd backend && uv run python -m scripts.ingest_unit_checks``
"""

from __future__ import annotations

import csv

from app.services.ingest.chunker import chunk_text, estimate_tokens
from app.services.ingest.csv_extract import extract_csv_units, serialize_row
from app.services.opensearch_ingest import (
    bulk_failure_is_retryable,
    bulk_item_error_details,
    execute_bulk_with_retry,
)


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


def test_csv_cell_over_default_field_limit() -> None:
    """Proof 9: a cell > 128 KiB must parse and split; field limit ≥ 512 MiB + 1."""
    body = "x" * 200_000
    csv_data = f"From,To,Subject,Body\na@co,b@co,Reset,{body}\n".encode("utf-8")
    units = extract_csv_units(csv_data, chunk_tokens=600, overlap_tokens=75)
    assert len(units) > 1
    assert csv.field_size_limit() >= 512 * 1024 * 1024 + 1


def test_transient_circuit_break_is_retryable() -> None:
    """Same shape as the folder-proof bulk failure (TRANSIENT, bytes 0)."""
    err = {
        "type": "circuit_breaking_exception",
        "reason": "Memory Circuit Breaker is open, please check your resources!",
        "bytes_wanted": 0,
        "bytes_limit": 0,
        "durability": "TRANSIENT",
    }
    assert bulk_failure_is_retryable(item_errors=[err]) is True
    assert bulk_failure_is_retryable(http_status=429) is True
    assert bulk_failure_is_retryable(http_status=503) is True
    assert (
        bulk_failure_is_retryable(
            http_status=200,
            response_text="circuit_breaking_exception",
        )
        is True
    )
    assert (
        bulk_failure_is_retryable(
            item_errors=[{"type": "circuit_breaking_exception", "durability": "PERMANENT"}]
        )
        is False
    )
    assert bulk_failure_is_retryable(item_errors=[{"type": "mapper_parsing_exception"}]) is False
    assert bulk_failure_is_retryable(http_status=400, item_errors=[]) is False


def test_bulk_item_error_details() -> None:
    payload = {
        "errors": True,
        "items": [
            {"index": {"_id": "a", "error": {"type": "circuit_breaking_exception"}}},
            {"index": {"_id": "b", "status": 201}},
        ],
    }
    details = bulk_item_error_details(payload)
    assert details == [{"type": "circuit_breaking_exception"}]


def test_execute_bulk_retries_transient_then_succeeds() -> None:
    calls = {"n": 0}
    slept: list[float] = []

    def send() -> tuple[int, dict | None, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            return (
                200,
                {
                    "errors": True,
                    "items": [
                        {
                            "index": {
                                "error": {
                                    "type": "circuit_breaking_exception",
                                    "durability": "TRANSIENT",
                                }
                            }
                        }
                    ],
                },
                "",
            )
        return 200, {"errors": False, "items": [{"index": {"status": 201}}]}, ""

    payload = execute_bulk_with_retry(send, max_attempts=5, sleep=slept.append)
    assert payload["errors"] is False
    assert calls["n"] == 2
    assert slept == [2.0]


def test_execute_bulk_does_not_retry_mapping_error() -> None:
    calls = {"n": 0}

    def send() -> tuple[int, dict | None, str]:
        calls["n"] += 1
        return (
            200,
            {
                "errors": True,
                "items": [{"index": {"error": {"type": "mapper_parsing_exception"}}}],
            },
            "",
        )

    try:
        execute_bulk_with_retry(send, max_attempts=5, sleep=lambda _s: None)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "mapper_parsing_exception" in str(exc)
    assert calls["n"] == 1


def main() -> None:
    test_estimate_and_chunk()
    print("[ok] chunker")
    test_csv_pack_short_rows()
    print("[ok] csv pack short rows")
    test_csv_oversized_row_splits()
    print("[ok] csv oversized row splits")
    test_serialize_skips_empty()
    print("[ok] serialize")
    test_csv_cell_over_default_field_limit()
    print("[ok] csv cell > 128 KiB parses and chunks")
    test_transient_circuit_break_is_retryable()
    print("[ok] transient circuit breaker is retryable")
    test_bulk_item_error_details()
    print("[ok] bulk item error details")
    test_execute_bulk_retries_transient_then_succeeds()
    print("[ok] bulk retry then success")
    test_execute_bulk_does_not_retry_mapping_error()
    print("[ok] mapping error is not retried")
    print("all unit checks passed")


if __name__ == "__main__":
    main()
