"""Offline walker + CSV field-limit checks (no Docker).

Run: ``cd backend && uv run python -m scripts.ingest_folder_unit_checks``
"""

from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.config import get_settings
from app.services.ingest.csv_extract import extract_csv_units
from app.services.ingest.folder_walk import classify_tree


def test_classify_hidden_unsupported_eligible() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "notes.txt").write_text("hello\n", encoding="utf-8")
        nested = root / "nested"
        nested.mkdir()
        (nested / "q1.pdf").write_bytes(b"%PDF-1.4\n")
        (nested / "export.csv").write_text("From,To\na,b\n", encoding="utf-8")
        (root / "skip.me.exe").write_bytes(b"MZ")
        (root / ".hidden.txt").write_text("secret\n", encoding="utf-8")
        cache = nested / ".cache"
        cache.mkdir()
        (cache / "x.txt").write_text("cached\n", encoding="utf-8")

        items = classify_tree(root)
        by_rel = {item.relative_posix: item.kind for item in items}
        assert by_rel["notes.txt"] == "eligible"
        assert by_rel["nested/q1.pdf"] == "eligible"
        assert by_rel["nested/export.csv"] == "eligible"
        assert by_rel["skip.me.exe"] == "unsupported"
        assert by_rel[".hidden.txt"] == "hidden"
        assert by_rel["nested/.cache/x.txt"] == "hidden"
        rels = [item.relative_posix for item in items]
        assert rels == sorted(rels)


def test_file_over_http_cap_is_eligible() -> None:
    """Proof 13: folder CLI does not skip on 25 MiB (A1 / S8)."""
    cap = get_settings().ingest_max_upload_bytes
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        big = root / "big.txt"
        with big.open("wb") as handle:
            handle.seek(cap)
            handle.write(b"x")
        items = classify_tree(root)
        assert len(items) == 1
        assert items[0].kind == "eligible"
        assert items[0].size_bytes == cap + 1


def test_symlink_file_not_followed() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        real = root / "real.txt"
        real.write_text("hello\n", encoding="utf-8")
        link = root / "link.txt"
        link.symlink_to(real)
        items = classify_tree(root)
        rels = {item.relative_posix for item in items}
        assert "real.txt" in rels
        assert "link.txt" not in rels


def test_csv_cell_over_default_field_limit() -> None:
    """Proof 9: cell > 128 KiB parses (default limit would fail) and splits."""
    body = "x" * 200_000
    csv_data = f"From,To,Subject,Body\na@co,b@co,Reset,{body}\n".encode("utf-8")
    units = extract_csv_units(csv_data, chunk_tokens=600, overlap_tokens=75)
    assert len(units) > 1
    assert csv.field_size_limit() >= 512 * 1024 * 1024 + 1


def main() -> None:
    test_classify_hidden_unsupported_eligible()
    print("[ok] walker hidden / unsupported / eligible")
    test_file_over_http_cap_is_eligible()
    print("[ok] file over 25 MiB is eligible")
    test_symlink_file_not_followed()
    print("[ok] symlink file skipped")
    test_csv_cell_over_default_field_limit()
    print("[ok] csv cell > 128 KiB parses and chunks")
    print("all folder unit checks passed")


if __name__ == "__main__":
    main()
