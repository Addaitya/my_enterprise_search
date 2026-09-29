"""Internal ingest proof (pass 2 file half, pass 3 connector half).

Stack: API on http://localhost:8000, Keycloak, Postgres, MinIO, OpenSearch.
``KEYCLOAK_INGEST_SECRET`` must match the ``ingest-client`` secret.

Presigned PUT: the API signs with ``MINIO_PRESIGN_ENDPOINT`` (default
``minio:9000``). When that host is localhost, this script PUTs with httpx.
When it is the compose DNS name, it PUTs with curl from the opensearch
container, which can resolve ``minio``. Override
``MINIO_PRESIGN_ENDPOINT=localhost:9000`` and restart the API if you want
the host PUT instead.

Connector cases run after the file half. The live API on :8000 must have an
empty ``INGESTION_PIPELINE_URL``. The 502 case starts a second API on :8013
pointed at an unreachable host. No real pipeline is required.

Run::

    cd backend && uv run python -m scripts.internal_ingest_proof
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import text

from app.core.config import REPO_ROOT, get_settings
from app.db.session import get_engine
from app.services.minio_store import MinioStore
from app.services.opensearch_ingest import build_chunk_document, get_chunks_by_file_id
from init_services.keycloak import (
    REALM_ADMIN_PASSWORD,
    REALM_ADMIN_USERNAME,
    SEARCHER_PASSWORD,
    SEARCHER_USERNAME,
)

API = "http://localhost:8000"
EXTRA_API = "http://127.0.0.1:8013"
PIPELINE_MAX = 104_857_600
_FORBIDDEN_KEYS = frozenset({"config", "password", "secret", "token"})


class ProofFailure(RuntimeError):
    pass


def _assert(condition: bool, detail: object) -> None:
    if not condition:
        raise ProofFailure(str(detail))


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return {"raw": response.text}


def _token_password(username: str, password: str) -> str:
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


def _token_ingest() -> str:
    settings = get_settings()
    response = httpx.post(
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": settings.keycloak_ingest_client_id,
            "client_secret": settings.keycloak_ingest_secret,
        },
        timeout=15,
    )
    if response.is_error:
        raise ProofFailure(f"ingest token: {response.status_code} {response.text}")
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _scalar(sql: str, **params: Any) -> Any:
    with get_engine().connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _execute(sql: str, **params: Any) -> None:
    with get_engine().begin() as conn:
        conn.execute(text(sql), params)


def _forbid_keys(value: Any) -> None:
    if isinstance(value, dict):
        found = _FORBIDDEN_KEYS.intersection(value)
        _assert(not found, f"forbidden keys {sorted(found)} in {value}")
        for item in value.values():
            _forbid_keys(item)
    elif isinstance(value, list):
        for item in value:
            _forbid_keys(item)


def _wait_api() -> None:
    deadline = time.monotonic() + 30
    last = ""
    while time.monotonic() < deadline:
        try:
            health = httpx.get(f"{API}/health", timeout=2)
            spec = httpx.get(f"{API}/openapi.json", timeout=2)
            paths = spec.json().get("paths", {}) if spec.status_code == 200 else {}
            if health.status_code == 200 and "/internal/ingest/files" in paths:
                return
            last = f"health={health.status_code} has_route={'/internal/ingest/files' in paths}"
        except httpx.HTTPError as exc:
            last = str(exc)
        time.sleep(0.5)
    raise ProofFailure(f"API not ready for internal ingest: {last}")


def _put_presigned(url: str, data: bytes) -> str:
    """PUT bytes to the presigned URL. Returns which path the proof used."""
    host = (urlparse(url).hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        response = httpx.put(url, content=data, timeout=60)
        if response.status_code not in {200, 204}:
            raise ProofFailure(f"host presigned PUT {response.status_code}: {response.text[:500]}")
        return f"host httpx (MINIO_PRESIGN_ENDPOINT host {host})"

    proc = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "opensearch",
            "curl",
            "-sS",
            "-X",
            "PUT",
            "-H",
            "Content-Type: application/octet-stream",
            "--data-binary",
            "@-",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            url,
        ],
        input=data,
        capture_output=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    code = proc.stdout.decode().strip()
    if proc.returncode != 0 or code not in {"200", "204"}:
        err = proc.stderr.decode()[:500]
        raise ProofFailure(
            f"compose presigned PUT failed rc={proc.returncode} http={code!r} stderr={err}"
        )
    return f"compose network curl from the opensearch container (presign host {host})"


def _reserve(token: str, body: dict[str, Any]) -> httpx.Response:
    return httpx.post(
        f"{API}/internal/ingest/files",
        headers=_auth(token),
        json=body,
        timeout=30,
    )


def _wait_acl_job(admin: str, job_id: str) -> None:
    """Let the admin grant's update-by-query finish before complete rewrites the chunk."""
    deadline = time.monotonic() + 20
    last: Any = None
    while time.monotonic() < deadline:
        response = httpx.get(f"{API}/admin/acl-jobs/{job_id}", headers=_auth(admin), timeout=15)
        last = _json(response)
        status = last.get("status") if isinstance(last, dict) else None
        if response.status_code == 200 and status == "succeeded":
            return
        if response.status_code == 200 and status == "failed":
            raise ProofFailure(f"acl job failed: {last}")
        time.sleep(0.25)
    raise ProofFailure(f"acl job did not succeed: {last}")


def _complete(token: str, file_id: str, body: dict[str, Any]) -> httpx.Response:
    return httpx.post(
        f"{API}/internal/ingest/files/{file_id}/complete",
        headers=_auth(token),
        json=body,
        timeout=120,
    )


def _reserve_body(source: str, *, size_bytes: int, filename: str = "pass2-note.md") -> dict[str, Any]:
    return {
        "filename": filename,
        "size_bytes": size_bytes,
        "ingestion_type": "pipeline",
        "original_source": source,
        "content_type": "text/plain",
    }


def _complete_body(data: bytes, *, file_type: str = "log", content: str) -> dict[str, Any]:
    return {
        "size_bytes": len(data),
        "file_type": file_type,
        "chunks": [{"seq": 0, "content": content}],
    }


def prove_auth_rejected(admin: str, searcher: str) -> None:
    source = f"pass2://auth/{uuid.uuid4()}"
    data = b"auth-check"
    reserve_body = _reserve_body(source, size_bytes=len(data))
    complete_body = _complete_body(data, content="auth-check")
    complete_url = f"{API}/internal/ingest/files/{uuid.uuid4()}/complete"
    calls = [
        ("POST", f"{API}/internal/ingest/files", reserve_body),
        ("POST", complete_url, complete_body),
    ]
    for _method, url, body in calls:
        missing = httpx.post(url, json=body, timeout=15)
        _assert(missing.status_code == 401, f"no token {url} -> {missing.status_code} {_json(missing)}")
        for label, token in (("realm-admin", admin), ("searcher", searcher)):
            rejected = httpx.post(url, headers=_auth(token), json=body, timeout=15)
            _assert(
                rejected.status_code == 403,
                f"{label} {url} -> {rejected.status_code} {_json(rejected)}",
            )
    print("[ok] 1 no token 401; realm-admin and searcher 403 on reserve and complete")


def prove_file_ingest(token: str, admin: str) -> None:
    sent = build_chunk_document(
        file_id=uuid.uuid4(),
        chunk_seq=0,
        content="shape-check",
        file_type="log",
        size_bytes=1,
        object_store_path="files/pipeline/shape/pass2-note.md",
        uploaded_at="2026-09-28T00:00:00+00:00",
        updated_at="2026-09-28T00:00:00+00:00",
        ingestion_type="pipeline",
    )
    _assert("embedding" not in sent, sent)
    _assert(sent["ingestion_type"] == "pipeline", sent)
    _assert(sent["allowed_roles"] == [] and sent["allowed_groups"] == [], sent)

    data = b"pass-2 internal ingest proof\n"
    content = data.decode()
    source = f"pass2://file/{uuid.uuid4()}"
    filename = "pass2-note.md"
    reserved = _reserve(token, _reserve_body(source, size_bytes=len(data), filename=filename))
    body = _json(reserved)
    _assert(reserved.status_code == 201, body)
    file_id = str(body["file_id"])
    path = body["object_store_path"]
    _assert(path == f"files/pipeline/{file_id}/{filename}", path)
    _assert(isinstance(body.get("upload_url"), str) and body["upload_url"], body)
    _assert(body.get("expires_at"), body)

    files_before = _scalar("SELECT count(*) FROM files WHERE id = :file_id", file_id=file_id)
    job_status = _scalar(
        "SELECT status FROM ingest_jobs WHERE file_id = :file_id ORDER BY created_at DESC LIMIT 1",
        file_id=file_id,
    )
    _assert(files_before == 0, f"files row existed before complete: {files_before}")
    _assert(job_status == "reserved", job_status)
    print(f"[ok] 2 reserved {file_id} path={path} with no files row")

    put_how = _put_presigned(body["upload_url"], data)
    print(f"[ok] 3 PUT {len(data)} bytes via {put_how}")

    completed = _complete(token, file_id, _complete_body(data, file_type="log", content=content))
    completed_body = _json(completed)
    _assert(completed.status_code == 201, completed_body)
    _assert(completed_body["ingestion_type"] == "pipeline", completed_body)
    _assert(completed_body["file_type"] == "log", completed_body)
    _assert(completed_body["chunk_count"] == 1, completed_body)

    file_type = _scalar("SELECT file_type FROM files WHERE id = :file_id", file_id=file_id)
    stored_path = _scalar("SELECT object_store_path FROM files WHERE id = :file_id", file_id=file_id)
    stored_size = _scalar("SELECT size_bytes FROM files WHERE id = :file_id", file_id=file_id)
    job_done = _scalar(
        "SELECT status FROM ingest_jobs WHERE file_id = :file_id ORDER BY created_at DESC LIMIT 1",
        file_id=file_id,
    )
    acl_count = _scalar("SELECT count(*) FROM file_acl WHERE file_id = :file_id", file_id=file_id)
    object_size = MinioStore().stat_object_size(path)
    _assert(file_type == "log", file_type)
    _assert(stored_path == path, stored_path)
    _assert(stored_size == len(data), stored_size)
    _assert(job_done == "completed", job_done)
    _assert(acl_count == 0, acl_count)
    _assert(object_size == len(data), object_size)

    hits = get_chunks_by_file_id(UUID(file_id), wait_seconds=5)
    _assert(len(hits) == 1, hits)
    hit = hits[0]
    expected_id = f"{file_id}:000000"
    _assert(hit.get("_id") == expected_id, hit.get("_id"))
    src = hit.get("_source") or {}
    _assert(src.get("chunk_id") == expected_id, src.get("chunk_id"))
    _assert(src.get("ingestion_type") == "pipeline", src.get("ingestion_type"))
    _assert(src.get("allowed_roles") == [], src.get("allowed_roles"))
    _assert(src.get("allowed_groups") == [], src.get("allowed_groups"))
    _assert(src.get("content") == content, src.get("content"))
    _assert("_empty" not in (src.get("allowed_roles") or []), src)
    print(
        "[ok] 4 complete indexed "
        f"{expected_id} ingestion_type=pipeline allowed_*=[] file_acl=0 "
        "(sent document omits embedding; the ingest pipeline may store a vector)"
    )

    uploaded_at = _scalar("SELECT uploaded_at FROM files WHERE id = :file_id", file_id=file_id)
    role_id = _scalar("SELECT id FROM roles WHERE name = 'search-user'")
    _assert(role_id is not None, "search-user role missing")
    grant = httpx.post(
        f"{API}/admin/files/{file_id}/acl",
        headers=_auth(admin),
        json={
            "principal_type": "role",
            "principal_id": str(role_id),
            "permission": "viewer",
        },
        timeout=30,
    )
    grant_body = _json(grant)
    _assert(grant.status_code == 200, grant_body)
    if grant_body.get("acl_job_id"):
        _wait_acl_job(admin, str(grant_body["acl_job_id"]))
    granted = _scalar(
        """
        SELECT count(*) FROM file_acl a
        JOIN roles r ON r.id = a.role_id
        WHERE a.file_id = :file_id AND r.name = 'search-user' AND a.permission = 'viewer'
        """,
        file_id=file_id,
    )
    _assert(granted == 1, granted)

    again = _reserve(token, _reserve_body(source, size_bytes=len(data), filename=filename))
    again_body = _json(again)
    _assert(again.status_code == 201, again_body)
    _assert(str(again_body["file_id"]) == file_id, again_body)
    _put_presigned(again_body["upload_url"], data)
    resynced = _complete(token, file_id, _complete_body(data, file_type="log", content=content))
    resynced_body = _json(resynced)
    _assert(resynced.status_code == 201, resynced_body)
    uploaded_after = _scalar("SELECT uploaded_at FROM files WHERE id = :file_id", file_id=file_id)
    _assert(uploaded_after == uploaded_at, (uploaded_at, uploaded_after))
    still_granted = _scalar(
        """
        SELECT count(*) FROM file_acl a
        JOIN roles r ON r.id = a.role_id
        WHERE a.file_id = :file_id AND r.name = 'search-user' AND a.permission = 'viewer'
        """,
        file_id=file_id,
    )
    _assert(still_granted == 1, still_granted)
    hits = get_chunks_by_file_id(UUID(file_id), wait_seconds=5)
    _assert(len(hits) == 1, hits)
    roles = list((hits[0].get("_source") or {}).get("allowed_roles") or [])
    _assert("search-user" in roles, roles)
    _assert("_empty" not in roles, roles)
    print("[ok] 5 re-reserve kept file_id; chunk allowed_roles includes search-user; file_acl kept")

    duplicate = _complete(token, file_id, _complete_body(data, file_type="log", content=content))
    duplicate_body = _json(duplicate)
    _assert(duplicate.status_code == 409, duplicate_body)
    _assert("already completed" in str(duplicate_body.get("detail", "")).lower(), duplicate_body)
    different = _complete(
        token,
        file_id,
        {"size_bytes": len(data) + 1, "file_type": "log", "chunks": [{"seq": 0, "content": content}]},
    )
    different_body = _json(different)
    _assert(different.status_code == 409, different_body)
    _assert("reserve again" in str(different_body.get("detail", "")).lower(), different_body)
    print("[ok] 6 complete without a new reserve is 409, including a different size")


def prove_validation(token: str, searcher: str) -> None:
    source = f"pass2://validate/{uuid.uuid4()}"
    base = _reserve_body(source, size_bytes=4)
    too_big = dict(base)
    too_big["size_bytes"] = PIPELINE_MAX + 1
    too_big["original_source"] = f"pass2://too-big/{uuid.uuid4()}"
    oversized = _reserve(token, too_big)
    _assert(oversized.status_code == 413, _json(oversized))

    too_small = dict(base)
    too_small["size_bytes"] = 0
    too_small["original_source"] = f"pass2://too-small/{uuid.uuid4()}"
    undersized = _reserve(token, too_small)
    _assert(undersized.status_code == 413, _json(undersized))

    bad_type = dict(base)
    bad_type["ingestion_type"] = "not-a-type"
    bad_type["original_source"] = f"pass2://bad-type/{uuid.uuid4()}"
    rejected_type = _reserve(token, bad_type)
    _assert(rejected_type.status_code == 422, _json(rejected_type))

    bad_name = dict(base)
    bad_name["filename"] = ".."
    bad_name["original_source"] = f"pass2://bad-name/{uuid.uuid4()}"
    rejected_name = _reserve(token, bad_name)
    _assert(rejected_name.status_code == 422, _json(rejected_name))

    with_file_id = dict(base)
    with_file_id["file_id"] = str(uuid.uuid4())
    with_file_id["original_source"] = f"pass2://file-id/{uuid.uuid4()}"
    rejected_id = _reserve(token, with_file_id)
    _assert(rejected_id.status_code == 422, _json(rejected_id))

    with_embedding = dict(base)
    with_embedding["embedding"] = [0.1, 0.2]
    with_embedding["original_source"] = f"pass2://embedding/{uuid.uuid4()}"
    rejected_embedding = _reserve(token, with_embedding)
    _assert(rejected_embedding.status_code == 422, _json(rejected_embedding))

    mismatch_data = b"size-mismatch"
    mismatch = _reserve(
        token,
        _reserve_body(
            f"pass2://size-mismatch/{uuid.uuid4()}",
            size_bytes=len(mismatch_data),
            filename="pass2-mismatch.md",
        ),
    )
    mismatch_body = _json(mismatch)
    _assert(mismatch.status_code == 201, mismatch_body)
    _put_presigned(mismatch_body["upload_url"], mismatch_data)
    wrong_size = _complete(
        token,
        str(mismatch_body["file_id"]),
        {
            "size_bytes": len(mismatch_data) + 1,
            "file_type": "log",
            "chunks": [{"seq": 0, "content": "size-mismatch"}],
        },
    )
    _assert(wrong_size.status_code == 422, _json(wrong_size))
    print("[ok] 7 over 100 MiB or below 1 is 413; file_id, embedding, bad type, and bad name are 422; size mismatch is 422")

    missing_source = f"pass2://missing/{uuid.uuid4()}"
    missing_data = b"not-uploaded"
    missing = _reserve(
        token,
        _reserve_body(missing_source, size_bytes=len(missing_data), filename="pass2-missing.md"),
    )
    missing_body = _json(missing)
    _assert(missing.status_code == 201, missing_body)
    absent = _complete(
        token,
        str(missing_body["file_id"]),
        _complete_body(missing_data, file_type="log", content="not-uploaded"),
    )
    absent_body = _json(absent)
    _assert(absent.status_code == 409, absent_body)

    human = httpx.post(
        f"{API}/files/uploads",
        headers=_auth(searcher),
        json={
            "filename": "pass2-reject.log",
            "size_bytes": 4,
            "content_type": "text/plain",
        },
        timeout=15,
    )
    _assert(human.status_code == 415, _json(human))
    print("[ok] 8 missing object is 409; human upload still rejects a non-pdf/txt/csv file")


def prove_file_half() -> None:
    _wait_api()
    admin = _token_password(REALM_ADMIN_USERNAME, REALM_ADMIN_PASSWORD)
    searcher = _token_password(SEARCHER_USERNAME, SEARCHER_PASSWORD)
    ingest = _token_ingest()
    prove_auth_rejected(admin, searcher)
    prove_file_ingest(ingest, admin)
    prove_validation(ingest, searcher)
    print("PASS file ingest")


def _wait_base(base: str) -> None:
    deadline = time.monotonic() + 30
    last = ""
    while time.monotonic() < deadline:
        try:
            health = httpx.get(f"{base}/health", timeout=2)
            if health.status_code == 200:
                return
            last = str(health.status_code)
        except httpx.HTTPError as exc:
            last = str(exc)
        time.sleep(0.3)
    raise ProofFailure(f"{base} not healthy: {last}")


def _start_extra_api(pipeline_url: str) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["INGESTION_PIPELINE_URL"] = pipeline_url
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8013"],
        cwd=str(REPO_ROOT / "backend"),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_base(EXTRA_API)
    except Exception:
        proc.terminate()
        raise
    return proc


def _stop_extra_api(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def prove_connectors(admin: str, ingest: str) -> None:
    admin_h = _auth(admin)
    before = int(_scalar("SELECT count(*) FROM connectors") or 0)
    empty = httpx.post(
        f"{API}/admin/connectors",
        headers=admin_h,
        json={"type": "s3", "name": "proof-empty-url", "config": {"password": "nope"}},
        timeout=15,
    )
    after = int(_scalar("SELECT count(*) FROM connectors") or 0)
    _assert(empty.status_code == 503, _json(empty))
    _assert(after == before, f"503 inserted a row {before} -> {after}")
    print("[ok] connectors 1 empty pipeline URL is 503 and connectors count is unchanged")

    proc = _start_extra_api("http://127.0.0.1:9")
    try:
        before = int(_scalar("SELECT count(*) FROM connectors") or 0)
        down = httpx.post(
            f"{EXTRA_API}/admin/connectors",
            headers=admin_h,
            json={"type": "s3", "name": "proof-unreachable", "config": {"token": "nope"}},
            timeout=20,
        )
        after = int(_scalar("SELECT count(*) FROM connectors") or 0)
        _assert(down.status_code == 502, _json(down))
        _assert("nope" not in down.text, down.text)
        _assert(after == before, f"502 inserted a row {before} -> {after}")
    finally:
        _stop_extra_api(proc)
    print("[ok] connectors 2 unreachable pipeline is 502 and inserts nothing")

    connector_id = uuid.uuid4()
    sync_id = uuid.uuid4()
    try:
        _execute(
            """
            INSERT INTO connectors (
                id, type, name, enabled, pipeline_connector_id, status, created_at, updated_at
            ) VALUES (
                :id, 's3', 'proof-status', true, 'pipe-proof', 'idle', now(), now()
            )
            """,
            id=connector_id,
        )
        _execute(
            """
            INSERT INTO connector_syncs (id, connector_id, status, started_at)
            VALUES (:id, :connector_id, 'syncing', now())
            """,
            id=sync_id,
            connector_id=connector_id,
        )
        listed = httpx.get(f"{API}/admin/connectors", headers=admin_h, timeout=15)
        _assert(listed.status_code == 200, _json(listed))
        _forbid_keys(listed.json())
        one = httpx.get(f"{API}/admin/connectors/{connector_id}", headers=admin_h, timeout=15)
        _assert(one.status_code == 200, _json(one))
        _forbid_keys(one.json())
        admin_status = httpx.post(
            f"{API}/internal/connectors/{connector_id}/status",
            headers=admin_h,
            json={"status": "success", "files_count": 1},
            timeout=15,
        )
        _assert(admin_status.status_code == 403, _json(admin_status))
        updated = httpx.post(
            f"{API}/internal/connectors/{connector_id}/status",
            headers=_auth(ingest),
            json={
                "status": "success",
                "files_count": 4,
                "finished_at": "2026-09-28T15:04:00Z",
            },
            timeout=15,
        )
        body = _json(updated)
        _assert(updated.status_code == 200, body)
        _assert(body.get("status") == "success", body)
        _assert(body.get("last_error") is None, body)
        _assert(str(body.get("last_sync_at", "")).startswith("2026-09-28T15:04:00"), body)
        _forbid_keys(body)
        sync_status = _scalar("SELECT status FROM connector_syncs WHERE id = :id", id=sync_id)
        files_count = _scalar("SELECT files_count FROM connector_syncs WHERE id = :id", id=sync_id)
        _assert(sync_status == "success", sync_status)
        _assert(files_count == 4, files_count)
    finally:
        _execute("DELETE FROM connectors WHERE id = :id", id=connector_id)
    print("[ok] connectors 3 status callback closes the open sync; realm-admin is 403")
    print("PASS connectors")


def main() -> None:
    prove_file_half()
    admin = _token_password(REALM_ADMIN_USERNAME, REALM_ADMIN_PASSWORD)
    ingest = _token_ingest()
    prove_connectors(admin, ingest)


if __name__ == "__main__":
    try:
        main()
    except ProofFailure as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
