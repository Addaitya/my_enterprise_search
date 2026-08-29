"""Ingest API proof driver (Task 4). Not part of init_services.

Run (backend venv, stack up, migration applied)::

    cd backend
    uv sync
    uv run alembic upgrade head
    uv run python -m scripts.ingest_proof

Walks the proof table in ``prompts/cursor_summary/7_ingest_api.md``.
"""

from __future__ import annotations

import csv
import io
import sys
from typing import Any
from uuid import UUID

import httpx

from app.core.config import get_settings
from app.db.session import get_engine
from app.services.minio_store import MinioStore
from app.services.opensearch_ingest import get_chunks_by_file_id
from init_services.keycloak import (
    REALM_ADMIN_PASSWORD,
    REALM_ADMIN_USERNAME,
    SEARCHER_PASSWORD,
    SEARCHER_USERNAME,
)
from sqlalchemy import text

API = "http://localhost:8000"
PART = 256 * 1024


class ProofFailure(RuntimeError):
    pass


def _token(username: str, password: str) -> str:
    settings = get_settings()
    response = httpx.post(
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": settings.keycloak_client_id,
            "client_secret": settings.keycloak_api_secret,
            "username": username,
            "password": password,
        },
        timeout=15,
    )
    if response.is_error:
        raise ProofFailure(f"token {username}: {response.status_code} {response.text}")
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _initiate(token: str, filename: str, data: bytes, content_type: str) -> dict:
    response = httpx.post(
        f"{API}/files/uploads",
        headers=_auth(token),
        json={
            "filename": filename,
            "size_bytes": len(data),
            "content_type": content_type,
        },
        timeout=30,
    )
    return {"status_code": response.status_code, "body": _json(response), "raw": response}


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return response.text


def _put_parts(token: str, upload_id: str, data: bytes, *, stop_after: int | None = None) -> int:
    """Upload sequential parts. If stop_after set, stop once bytes_received >= stop_after."""
    total = len(data)
    offset = 0
    while offset < total:
        end = min(total, offset + PART) - 1
        if offset + PART < total:
            # align non-final to 256KiB
            end = offset + PART - 1
        chunk = data[offset : end + 1]
        response = httpx.put(
            f"{API}/files/uploads/{upload_id}",
            headers={
                **_auth(token),
                "Content-Range": f"bytes {offset}-{end}/{total}",
                "Content-Type": "application/octet-stream",
            },
            content=chunk,
            timeout=60,
        )
        if response.status_code not in {200, 308}:
            raise ProofFailure(f"PUT {response.status_code}: {response.text}")
        body = _json(response)
        received = int(body["bytes_received"])
        offset = received
        if stop_after is not None and received >= stop_after:
            return received
    return offset


def _complete(token: str, upload_id: str) -> httpx.Response:
    return httpx.post(
        f"{API}/files/uploads/{upload_id}/complete",
        headers=_auth(token),
        timeout=180,
    )


def _status(token: str, upload_id: str) -> httpx.Response:
    return httpx.get(f"{API}/files/uploads/{upload_id}", headers=_auth(token), timeout=30)


def _acl_count(file_id: UUID) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT count(*) FROM file_acl WHERE file_id = :fid"),
            {"fid": str(file_id)},
        ).scalar()
    return int(row or 0)


def _files_exists(file_id: UUID) -> bool:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM files WHERE id = :fid"),
            {"fid": str(file_id)},
        ).first()
    return row is not None


def _make_pdf_with_text(text: str) -> bytes:
    """Minimal PDF via pypdf blank page + note — use reportlab-free approach.

    pypdf cannot easily write text without a page content stream. Build a
    tiny hand-written PDF with the text as a stream.
    """
    # Simple one-page PDF with Helvetica text.
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 50 750 Td ({escaped[:200]}) Tj ET".encode("latin-1", errors="replace")
    objects = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream)} >>stream\n".encode() + stream + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return bytes(out)


def _make_empty_pdf() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise ProofFailure(msg)


def proof_1_no_token() -> None:
    response = httpx.post(
        f"{API}/files/uploads",
        json={"filename": "a.txt", "size_bytes": 1, "content_type": "text/plain"},
        timeout=15,
    )
    _assert(response.status_code == 401, f"expected 401 got {response.status_code}")
    print("[ok] 1 initiate without token → 401")


def proof_2_exe(token: str) -> None:
    response = httpx.post(
        f"{API}/files/uploads",
        headers=_auth(token),
        json={"filename": "malware.exe", "size_bytes": 10, "content_type": "application/octet-stream"},
        timeout=15,
    )
    _assert(response.status_code == 415, f"expected 415 got {response.status_code} {_json(response)}")
    print("[ok] 2 initiate .exe → 415")


def proof_3_oversize(token: str) -> None:
    settings = get_settings()
    response = httpx.post(
        f"{API}/files/uploads",
        headers=_auth(token),
        json={
            "filename": "big.txt",
            "size_bytes": settings.ingest_max_upload_bytes + 1,
            "content_type": "text/plain",
        },
        timeout=15,
    )
    _assert(response.status_code == 413, f"expected 413 got {response.status_code}")
    print("[ok] 3 initiate oversize → 413")


def proof_4_5_txt(token: str) -> UUID:
    data = b"hello enterprise search ingest proof\n"
    init = _initiate(token, "hello.txt", data, "text/plain")
    _assert(init["status_code"] == 201, f"initiate: {init}")
    upload_id = init["body"]["upload_id"]
    _put_parts(token, upload_id, data)
    completed = _complete(token, upload_id)
    _assert(completed.status_code == 201, f"complete: {completed.status_code} {completed.text}")
    body = completed.json()
    file_id = UUID(body["id"])
    _assert(body["status"] == "completed", body)
    _assert(body["ingestion_type"] == "local", body)
    _assert(_acl_count(file_id) == 0, "file_acl should be empty")
    store = MinioStore()
    _assert(store.object_exists(body["object_store_path"]), "minio final object missing")

    # Wait briefly for ingest pipeline embeddings.
    hits = get_chunks_by_file_id(file_id, wait_seconds=10)
    _assert(len(hits) >= 1, "expected >=1 OS chunk")
    src = hits[0]["_source"]
    emb = src.get("embedding")
    _assert(isinstance(emb, list) and len(emb) == 384, f"embedding dim {None if emb is None else len(emb)}")
    _assert(src.get("allowed_roles") == [], src)
    _assert(src.get("allowed_groups") == [], src)
    _assert(src.get("chunk_id") and src.get("chunk_seq") is not None, src)
    _assert(src.get("ingestion_type") == "local", src)
    print("[ok] 4/5 TXT complete + OS embedding 384 + empty ACL")
    return file_id


def proof_6_long_txt(token: str) -> None:
    data = ("lorem " * 2000).encode("utf-8")  # >> 600 tokens
    init = _initiate(token, "long.txt", data, "text/plain")
    _assert(init["status_code"] == 201, init)
    upload_id = init["body"]["upload_id"]
    _put_parts(token, upload_id, data)
    completed = _complete(token, upload_id)
    _assert(completed.status_code == 201, completed.text)
    body = completed.json()
    _assert(body["chunk_count"] > 1, body)
    hits = get_chunks_by_file_id(UUID(body["id"]), wait_seconds=10)
    seqs = [h["_source"]["chunk_seq"] for h in hits]
    _assert(seqs == list(range(len(seqs))), f"chunk_seq not contiguous: {seqs}")
    print(f"[ok] 6 long TXT chunk_count={body['chunk_count']}")


def proof_7_pdf(token: str) -> None:
    data = _make_pdf_with_text("PDF ingest proof alpha-token")
    init = _initiate(token, "note.pdf", data, "application/pdf")
    _assert(init["status_code"] == 201, init)
    upload_id = init["body"]["upload_id"]
    _put_parts(token, upload_id, data)
    completed = _complete(token, upload_id)
    _assert(completed.status_code == 201, f"pdf complete: {completed.status_code} {completed.text}")
    body = completed.json()
    _assert(body["chunk_count"] >= 1, body)
    print("[ok] 7 PDF with text")


def proof_8_empty_pdf(token: str) -> None:
    data = _make_empty_pdf()
    init = _initiate(token, "blank.pdf", data, "application/pdf")
    _assert(init["status_code"] == 201, init)
    upload_id = init["body"]["upload_id"]
    _put_parts(token, upload_id, data)
    completed = _complete(token, upload_id)
    _assert(completed.status_code == 422, f"expected 422 got {completed.status_code} {completed.text}")
    status = _status(token, upload_id).json()
    _assert(status["status"] == "failed", status)
    print("[ok] 8 textless PDF → 422/failed")


def proof_9_csv_short(token: str) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["From", "To", "Subject", "Body"])
    writer.writeheader()
    for i in range(30):
        writer.writerow(
            {
                "From": f"a{i}@co",
                "To": f"b{i}@co",
                "Subject": f"Hi {i}",
                "Body": f"Short {i}",
            }
        )
    data = buf.getvalue().encode("utf-8")
    init = _initiate(token, "mail.csv", data, "text/csv")
    upload_id = init["body"]["upload_id"]
    _put_parts(token, upload_id, data)
    completed = _complete(token, upload_id)
    _assert(completed.status_code == 201, completed.text)
    body = completed.json()
    _assert(body["chunk_count"] < 30, f"expected packing, got {body['chunk_count']}")
    hits = get_chunks_by_file_id(UUID(body["id"]), wait_seconds=10)
    _assert(len(hits) >= 1, f"expected OS chunks for csv file_id={body['id']}")
    content = hits[0]["_source"]["content"]
    _assert("From:" in content and "Subject:" in content, content[:200])
    print(f"[ok] 9 CSV short rows packed chunk_count={body['chunk_count']}")


def proof_10_csv_long_row(token: str) -> None:
    body_cell = "email-body-" + ("word " * 800)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["From", "To", "Subject", "Body"])
    writer.writeheader()
    writer.writerow({"From": "a@co", "To": "b@co", "Subject": "Reset", "Body": body_cell})
    data = buf.getvalue().encode("utf-8")
    init = _initiate(token, "longrow.csv", data, "text/csv")
    upload_id = init["body"]["upload_id"]
    _put_parts(token, upload_id, data)
    completed = _complete(token, upload_id)
    _assert(completed.status_code == 201, completed.text)
    body = completed.json()
    _assert(body["chunk_count"] > 1, body)
    print(f"[ok] 10 CSV long row chunk_count={body['chunk_count']}")


def proof_11_resume(token: str) -> None:
    data = b"x" * (PART + 1000)
    init = _initiate(token, "resume.txt", data, "text/plain")
    upload_id = init["body"]["upload_id"]
    received = _put_parts(token, upload_id, data, stop_after=PART)
    _assert(received == PART, f"expected interrupt at {PART}, got {received}")
    st = _status(token, upload_id).json()
    _assert(st["bytes_received"] == PART, st)
    # resume from bytes_received
    offset = st["bytes_received"]
    total = len(data)
    while offset < total:
        end = min(total, offset + PART) - 1
        chunk = data[offset : end + 1]
        response = httpx.put(
            f"{API}/files/uploads/{upload_id}",
            headers={
                **_auth(token),
                "Content-Range": f"bytes {offset}-{end}/{total}",
            },
            content=chunk,
            timeout=60,
        )
        _assert(response.status_code in {200, 308}, response.text)
        offset = response.json()["bytes_received"]
    completed = _complete(token, upload_id)
    _assert(completed.status_code == 201, completed.text)
    print("[ok] 11 interrupt mid-PUT → resume → complete")


def proof_12_other_user(searcher_token: str, admin_token: str) -> None:
    data = b"secret\n"
    init = _initiate(searcher_token, "owned.txt", data, "text/plain")
    upload_id = init["body"]["upload_id"]
    response = _status(admin_token, upload_id)
    _assert(response.status_code == 403, f"expected 403 got {response.status_code}")
    print("[ok] 12 other user → 403")


def proof_14_jwt_cannot_index(token: str) -> None:
    settings = get_settings()
    response = httpx.put(
        f"{settings.opensearch_url}/{settings.opensearch_index}/_doc/proof-jwt-should-fail",
        headers=_auth(token),
        json={"content": "nope", "allowed_roles": [], "allowed_groups": []},
        timeout=30,
        verify=settings.opensearch_verify_certs,
    )
    _assert(response.status_code in {401, 403}, f"expected 401/403 got {response.status_code}")
    print(f"[ok] 14 JWT cannot index → {response.status_code}")


def proof_15_health_me(token: str) -> None:
    health = httpx.get(f"{API}/health", timeout=10)
    _assert(health.status_code == 200, health.text)
    me = httpx.get(f"{API}/auth/me", headers=_auth(token), timeout=10)
    _assert(me.status_code == 200, me.text)
    print("[ok] 15 /health + /auth/me")


def main() -> int:
    print("=== ingest proofs ===")
    # Smoke: API up
    try:
        httpx.get(f"{API}/health", timeout=5).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"API not reachable at {API}: {exc}", file=sys.stderr)
        print("Start ./start-dev.sh and ensure docker services are up.", file=sys.stderr)
        return 2

    searcher = _token(SEARCHER_USERNAME, SEARCHER_PASSWORD)
    admin = _token(REALM_ADMIN_USERNAME, REALM_ADMIN_PASSWORD)

    proof_1_no_token()
    proof_2_exe(searcher)
    proof_3_oversize(searcher)
    proof_4_5_txt(searcher)
    proof_6_long_txt(searcher)
    proof_7_pdf(searcher)
    proof_8_empty_pdf(searcher)
    proof_9_csv_short(searcher)
    proof_10_csv_long_row(searcher)
    proof_11_resume(searcher)
    proof_12_other_user(searcher, admin)
    # proof 13 (OS bulk failure) is hard to force without mocking — skip with note
    print("[skip] 13 OS bulk failure compensation (manual/chaos only)")
    proof_14_jwt_cannot_index(searcher)
    proof_15_health_me(searcher)
    print("=== all runnable proofs passed ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProofFailure as exc:
        print(f"PROOF FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
