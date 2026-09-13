"""Live proofs for folder ingest CLI. Not part of init_services.

Run (backend venv, stack up)::

    cd backend
    uv run python -m scripts.ingest_folder_proof

Walks the proof table in ``prompts/cursor_summary/14_ingestion_script.md``.
Proof 9 and 13 are offline (no Docker). Proof 12 needs the API (ingest_proof 3–10).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine
from app.services.minio_store import MinioStore
from app.services.opensearch_ingest import get_chunks_by_file_id
from scripts.ingest_folder import ingest_folder
from scripts.ingest_folder_unit_checks import (
    test_classify_hidden_unsupported_eligible,
    test_csv_cell_over_default_field_limit,
    test_file_over_http_cap_is_eligible,
)
from scripts.ingest_proof import (
    _make_empty_pdf,
    _make_pdf_with_text,
    _token,
    proof_3_oversize,
    proof_4_5_txt,
    proof_6_long_txt,
    proof_7_pdf,
    proof_8_empty_pdf,
    proof_9_csv_short,
    proof_10_csv_long_row,
)
from init_services.keycloak import SEARCHER_PASSWORD, SEARCHER_USERNAME

BACKEND = Path(__file__).resolve().parents[1]
API = "http://localhost:8000"


class ProofFailure(RuntimeError):
    pass


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise ProofFailure(msg)


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.ingest_folder", *args],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )


def _files_count() -> int:
    with get_engine().connect() as conn:
        row = conn.execute(text("SELECT count(*) FROM files")).scalar()
    return int(row or 0)


def _file_row(file_id: UUID) -> dict[str, Any]:
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT object_store_path, file_type, ingestion_type, original_source "
                "FROM files WHERE id = :fid"
            ),
            {"fid": str(file_id)},
        ).mappings().first()
    if row is None:
        raise ProofFailure(f"files row missing: {file_id}")
    return dict(row)


def _acl_count(file_id: UUID) -> int:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT count(*) FROM file_acl WHERE file_id = :fid"),
            {"fid": str(file_id)},
        ).scalar()
    return int(row or 0)


def _upload_session_count(file_id: UUID) -> int:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT count(*) FROM upload_sessions WHERE file_id = :fid"),
            {"fid": str(file_id)},
        ).scalar()
    return int(row or 0)


def _write_short_csv(path: Path) -> None:
    lines = ["From,To,Subject,Body"]
    for i in range(30):
        lines.append(f"a{i}@co,b{i}@co,Hi {i},Short {i}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_fixture(root: Path, *, empty_pdf: bool = False) -> None:
    (root / "notes.txt").write_text("hello folder ingest\n", encoding="utf-8")
    nested = root / "nested"
    nested.mkdir()
    (nested / "q1.pdf").write_bytes(_make_pdf_with_text("Quarter one report"))
    _write_short_csv(nested / "export.csv")
    (root / "skip.me.exe").write_bytes(b"MZ")
    (root / ".hidden.txt").write_text("secret\n", encoding="utf-8")
    cache = nested / ".cache"
    cache.mkdir()
    (cache / "x.txt").write_text("cached\n", encoding="utf-8")
    if empty_pdf:
        (root / "empty.pdf").write_bytes(_make_empty_pdf())


def _ok_by_rel(result) -> dict[str, Any]:
    return {
        o.relative_posix: o
        for o in result.outcomes
        if o.status == "ok" and o.file_id is not None
    }


def _require_stores() -> None:
    settings = get_settings()
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    store = MinioStore(settings)
    if not store.client.bucket_exists(store.bucket):
        raise ProofFailure(f"MinIO bucket missing: {store.bucket}")
    response = httpx.get(
        settings.opensearch_url,
        auth=("admin", settings.opensearch_initial_admin_password),
        verify=settings.opensearch_verify_certs,
        timeout=10,
    )
    if response.is_error:
        raise ProofFailure(
            f"OpenSearch not reachable: {response.status_code} {response.text}"
        )


def proof_1_missing_folder() -> None:
    before = _files_count()
    proc = _run_cli("/no/such/ingest-folder/does-not-exist")
    _assert(proc.returncode == 1, f"expected exit 1, got {proc.returncode}: {proc.stderr}")
    _assert(_files_count() == before, "missing folder must not write files")
    print("[ok] 1 missing folder → exit 1, no writes")


def proof_2_dry_run() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _build_fixture(root)
        before = _files_count()
        proc = _run_cli(str(root), "--dry-run")
        _assert(proc.returncode == 0, f"dry-run exit {proc.returncode}: {proc.stderr}")
        out = proc.stdout
        _assert("[ingest] notes.txt" in out or "notes.txt" in out, out)
        _assert("nested/q1.pdf" in out, out)
        _assert("nested/export.csv" in out, out)
        _assert("skip.me.exe" in out and "unsupported" in out, out)
        _assert(".hidden.txt" in out and "hidden" in out, out)
        _assert("nested/.cache/x.txt" in out, out)
        _assert(_files_count() == before, "dry-run wrote files rows")
        print("[ok] 2 --dry-run classifies; zero new files rows")


def proof_3_to_7_real_run() -> list[UUID]:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _build_fixture(root)
        before = _files_count()
        result = ingest_folder(root)
        _assert(result.exit_code == 0, f"ingest failed: {result}")
        _assert(result.ingested == 3, f"expected 3 ingested, got {result.ingested}")
        _assert(result.failed == 0, f"failed={result.failed}")
        _assert(result.skipped_type == 1, f"skipped_type={result.skipped_type}")
        _assert(result.skipped_hidden == 2, f"skipped_hidden={result.skipped_hidden}")
        _assert(_files_count() == before + 3, "expected +3 files rows")

        ok = _ok_by_rel(result)
        _assert(set(ok) == {"notes.txt", "nested/q1.pdf", "nested/export.csv"}, set(ok))

        store = MinioStore()
        ids: list[UUID] = []
        for rel, outcome in ok.items():
            assert outcome.file_id is not None
            ids.append(outcome.file_id)
            row = _file_row(outcome.file_id)
            _assert(row["ingestion_type"] == "local", row)
            _assert(row["original_source"] == rel, row)
            _assert(_acl_count(outcome.file_id) == 0, f"file_acl for {outcome.file_id}")
            _assert(
                _upload_session_count(outcome.file_id) == 0,
                f"upload_sessions for {outcome.file_id}",
            )
            path = row["object_store_path"]
            basename = Path(rel).name
            _assert(
                path == f"local/{outcome.file_id}/{basename}",
                f"unexpected minio path {path}",
            )
            _assert("/nested/" not in path, path)
            _assert(store.object_exists(path), f"missing minio object {path}")

            hits = get_chunks_by_file_id(outcome.file_id, wait_seconds=10)
            _assert(len(hits) >= 1, f"no OS chunks for {rel}")
            src = hits[0]["_source"]
            emb = src.get("embedding")
            _assert(
                isinstance(emb, list) and len(emb) == 384,
                f"embedding dim {None if emb is None else len(emb)}",
            )
            _assert(src.get("allowed_roles") == [], src)
            _assert(src.get("allowed_groups") == [], src)
            _assert(src.get("chunk_id") and src.get("chunk_seq") is not None, src)
            _assert(src.get("original_source") == rel, src)
            _assert("_empty" not in src.get("allowed_roles", []), src)

            if rel == "nested/export.csv":
                content = src["content"]
                _assert("From:" in content and "Subject:" in content, content[:200])
                _assert(outcome.chunk_count is not None and outcome.chunk_count < 30, outcome)

        print("[ok] 3–7 real run: PG/MinIO/OS + CSV packing + relative original_source")
        return ids


def proof_8_textless_pdf_continues() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _build_fixture(root, empty_pdf=True)
        before = _files_count()
        result = ingest_folder(root)
        _assert(result.exit_code == 1, f"expected exit 1, got {result.exit_code}")
        _assert(result.failed == 1, f"failed={result.failed}")
        _assert(result.ingested == 3, f"ingested={result.ingested}")
        fail = [o for o in result.outcomes if o.status == "fail"]
        _assert(len(fail) == 1 and fail[0].relative_posix == "empty.pdf", fail)
        _assert(fail[0].file_id is None, fail[0])
        _assert(_files_count() == before + 3, "textless PDF must not insert files")
        print("[ok] 8 textless PDF [fail]; continue; remaining ingested")


def proof_10_fail_fast() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _build_fixture(root, empty_pdf=True)
        before = _files_count()
        result = ingest_folder(root, fail_fast=True)
        _assert(result.exit_code == 1, f"expected exit 1, got {result.exit_code}")
        _assert(result.stopped_early, "expected fail-fast stop")
        _assert(result.ingested == 0, f"ingested={result.ingested}")
        _assert(result.failed == 1, f"failed={result.failed}")
        ok_rels = {o.relative_posix for o in result.outcomes if o.status == "ok"}
        _assert("notes.txt" not in ok_rels, ok_rels)
        _assert("nested/export.csv" not in ok_rels, ok_rels)
        _assert(_files_count() == before, "fail-fast must not ingest later files")
        print("[ok] 10 --fail-fast stops; later eligible files not ingested")


def proof_11_rerun_new_ids(previous_ids: list[UUID]) -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _build_fixture(root)
        result = ingest_folder(root)
        _assert(result.ingested == 3, result)
        new_ids = [o.file_id for o in result.outcomes if o.file_id is not None]
        _assert(len(new_ids) == 3, new_ids)
        overlap = set(previous_ids) & set(new_ids)
        _assert(not overlap, f"re-run reused file_ids: {overlap}")
        for fid in previous_ids:
            _file_row(fid)  # still present
        print("[ok] 11 re-run creates new file_ids; previous rows remain")


def proof_12_http_still_works() -> None:
    try:
        httpx.get(f"{API}/health", timeout=5).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise ProofFailure(f"API not reachable at {API}: {exc}") from exc
    searcher = _token(SEARCHER_USERNAME, SEARCHER_PASSWORD)
    proof_3_oversize(searcher)
    proof_4_5_txt(searcher)
    proof_6_long_txt(searcher)
    proof_7_pdf(searcher)
    proof_8_empty_pdf(searcher)
    proof_9_csv_short(searcher)
    proof_10_csv_long_row(searcher)
    print("[ok] 12 HTTP ingest_proof 3–10 still PASS (413 oversize + complete path)")


def main() -> int:
    print("=== folder ingest proofs ===")
    test_csv_cell_over_default_field_limit()
    print("[ok] 9 csv cell > 128 KiB parses and chunks (offline)")
    test_classify_hidden_unsupported_eligible()
    test_file_over_http_cap_is_eligible()
    print("[ok] 13 walker classification + 25 MiB file still eligible (offline)")

    try:
        _require_stores()
    except Exception as exc:  # noqa: BLE001
        print(f"stores not reachable: {exc}", file=sys.stderr)
        print("Start ./start-dev.sh and ensure docker services are up.", file=sys.stderr)
        return 2

    proof_1_missing_folder()
    proof_2_dry_run()
    previous_ids = proof_3_to_7_real_run()
    proof_8_textless_pdf_continues()
    proof_10_fail_fast()
    proof_11_rerun_new_ids(previous_ids)
    proof_12_http_still_works()
    print("=== all runnable folder ingest proofs passed ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProofFailure as exc:
        print(f"PROOF FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
