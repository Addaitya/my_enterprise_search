from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from app.core.config import get_settings, save_runtime_config

CONFIG_DIR = Path(__file__).resolve().parents[2] / "docker_service_configs" / "opensearch"
MODEL_GROUP_NAME = "enterprise-search-embeddings"
# ONNX: TorchScript 1.0.2 failed to deploy on OpenSearch 2.19
# (aten::scaled_dot_product_attention). Keep ONNX on 3.8 unless proofs fail.
MODEL_FORMAT = "ONNX"
_TERMINAL_TASK_STATES = frozenset(
    {"COMPLETED", "FAILED", "CANCELLED", "COMPLETED_WITH_ERROR", "EXPIRED", "UNREACHABLE"}
)
_READY_MODEL_STATES = frozenset({"DEPLOYED", "PARTIALLY_DEPLOYED"})
_REGISTER_TIMEOUT_S = 600
_DEPLOY_TIMEOUT_S = 300
_POLL_INTERVAL_S = 5


def _client(*, timeout: float = 30) -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        base_url=settings.opensearch_url,
        verify=settings.opensearch_verify_certs,
        auth=("admin", settings.opensearch_initial_admin_password),
        timeout=timeout,
    )


def _json(response: httpx.Response) -> dict:
    if response.is_error:
        raise RuntimeError(
            f"opensearch {response.request.method} {response.request.url.path} "
            f"{response.status_code}: {response.text}"
        )
    if not response.content:
        return {}
    return response.json()


def cluster_health() -> None:
    with _client() as client:
        body = _json(client.get("/_cluster/health"))
        print(f"[ok] opensearch {body.get('status')}")


def enable_ml_commons() -> None:
    """Allow local models on this single data node (no dedicated ML node)."""
    with _client() as client:
        _json(
            client.put(
                "/_cluster/settings",
                json={
                    "persistent": {
                        "plugins.ml_commons.only_run_on_ml_node": False,
                        "plugins.ml_commons.model_access_control_enabled": False,
                        "plugins.ml_commons.native_memory_threshold": 99,
                    }
                },
            )
        )
        print("[ok] ml commons enabled on data node")


def _poll_ml_task(client: httpx.Client, task_id: str, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = _json(client.get(f"/_plugins/_ml/tasks/{task_id}"))
        state = body.get("state")
        print(f"[..] ml task {task_id} {state}")
        if state in _TERMINAL_TASK_STATES:
            if state != "COMPLETED":
                raise RuntimeError(f"ml task {task_id} {state}: {body.get('error') or body}")
            return body
        time.sleep(_POLL_INTERVAL_S)
    raise TimeoutError(f"ml task {task_id} did not finish within {timeout_s}s")


def _search_hits(client: httpx.Client, path: str, query: dict) -> list[dict]:
    body = _json(client.post(path, json={"size": 10, "query": query}))
    return body.get("hits", {}).get("hits", [])


def _existing_model_id(client: httpx.Client, name: str) -> str | None:
    hits = _search_hits(
        client,
        "/_plugins/_ml/models/_search",
        {
            "bool": {
                "must": [{"match": {"name": name}}],
                "filter": [{"exists": {"field": "model_state"}}],
            }
        },
    )
    for hit in hits:
        source = hit.get("_source") or {}
        if source.get("name") == name or name in str(source.get("name", "")):
            return hit.get("_id")
    return hits[0].get("_id") if hits else None


def _existing_model_group_id(client: httpx.Client) -> str | None:
    hits = _search_hits(
        client,
        "/_plugins/_ml/model_groups/_search",
        {"bool": {"must": [{"match": {"name": MODEL_GROUP_NAME}}]}},
    )
    for hit in hits:
        source = hit.get("_source") or {}
        if source.get("name") == MODEL_GROUP_NAME:
            return hit.get("_id")
    return hits[0].get("_id") if hits else None


def _ensure_model_group(client: httpx.Client) -> str:
    existing = _existing_model_group_id(client)
    if existing:
        print(f"[ok] model group {MODEL_GROUP_NAME} {existing}")
        return existing
    body = _json(
        client.post(
            "/_plugins/_ml/model_groups/_register",
            json={
                "name": MODEL_GROUP_NAME,
                "description": "Embedding models for enterprise search",
            },
        )
    )
    group_id = body.get("model_group_id")
    if not group_id:
        raise RuntimeError(f"model group register returned no id: {body}")
    print(f"[ok] registered model group {MODEL_GROUP_NAME} {group_id}")
    return group_id


def _get_model(client: httpx.Client, model_id: str) -> dict | None:
    response = client.get(f"/_plugins/_ml/models/{model_id}")
    if response.status_code == 404:
        return None
    return _json(response)


def _deploy_model(client: httpx.Client, model_id: str) -> None:
    model = _get_model(client, model_id)
    if model and model.get("model_state") in _READY_MODEL_STATES:
        print(f"[ok] model {model_id} already {model.get('model_state')}")
        return
    body = _json(client.post(f"/_plugins/_ml/models/{model_id}/_deploy"))
    task_id = body.get("task_id")
    if not task_id:
        raise RuntimeError(f"model deploy returned no task_id: {body}")
    print(f"[ok] deploying model {model_id} task {task_id}")
    _poll_ml_task(client, task_id, _DEPLOY_TIMEOUT_S)
    print(f"[ok] deployed model {model_id}")


def _register_pretrained_model(client: httpx.Client) -> str:
    settings = get_settings()
    existing = _existing_model_id(client, settings.opensearch_embedding_model)
    if existing:
        print(f"[ok] found registered model {existing}")
        return existing

    group_id = _ensure_model_group(client)
    body = _json(
        client.post(
            "/_plugins/_ml/models/_register",
            json={
                "name": settings.opensearch_embedding_model,
                "version": settings.opensearch_embedding_version,
                "model_group_id": group_id,
                "model_format": MODEL_FORMAT,
            },
        )
    )
    task_id = body.get("task_id")
    if not task_id:
        raise RuntimeError(f"model register returned no task_id: {body}")
    print(
        f"[ok] registering {settings.opensearch_embedding_model} "
        f"{settings.opensearch_embedding_version} ({MODEL_FORMAT}) task {task_id}"
    )
    completed = _poll_ml_task(client, task_id, _REGISTER_TIMEOUT_S)
    model_id = completed.get("model_id")
    if not model_id:
        raise RuntimeError(f"register task completed without model_id: {completed}")
    print(f"[ok] registered model {model_id}")
    return model_id


def ensure_embedding_model() -> str:
    """Register/deploy MiniLM and persist `opensearch_model_id` so restarts skip download."""
    settings = get_settings()
    with _client(timeout=60) as client:
        model_id = settings.opensearch_model_id
        if model_id:
            model = _get_model(client, model_id)
            if model is None:
                print(f"[skip] stored model {model_id} missing; registering again")
                model_id = _register_pretrained_model(client)
        else:
            model_id = _register_pretrained_model(client)
        _deploy_model(client, model_id)

    save_runtime_config({"opensearch_model_id": model_id})
    print(f"[ok] opensearch_model_id={model_id}")
    return model_id


def _assert_index_compatible(client: httpx.Client, index: str, expected_dim: int, default_pipeline: str) -> None:
    """G6: fail loudly on wrong mapping/settings; never auto-delete the index."""
    mapping_body = _json(client.get(f"/{index}/_mapping"))
    settings_body = _json(client.get(f"/{index}/_settings"))
    props = mapping_body.get(index, {}).get("mappings", {}).get("properties", {})
    index_settings = settings_body.get(index, {}).get("settings", {}).get("index", {})

    problems: list[str] = []
    for field, expected_type in (
        ("file_id", "keyword"),
        ("chunk_id", "keyword"),
        ("content", "text"),
        ("allowed_roles", "keyword"),
        ("allowed_groups", "keyword"),
    ):
        actual = (props.get(field) or {}).get("type")
        if actual != expected_type:
            problems.append(f"{field} type={actual!r} (want {expected_type})")

    embedding = props.get("embedding") or {}
    if embedding.get("type") != "knn_vector":
        problems.append(f"embedding type={embedding.get('type')!r} (want knn_vector)")
    dim = embedding.get("dimension")
    if dim is not None and int(dim) != expected_dim:
        problems.append(f"embedding dimension={dim} (want {expected_dim})")
    method = embedding.get("method") or {}
    if method.get("engine") and method.get("engine") != "lucene":
        problems.append(f"embedding engine={method.get('engine')!r} (want lucene)")
    if method.get("space_type") and method.get("space_type") != "cosinesimil":
        problems.append(f"embedding space_type={method.get('space_type')!r} (want cosinesimil)")

    knn = str(index_settings.get("knn", "")).lower()
    if knn not in {"true", "1"}:
        problems.append(f"index.knn={index_settings.get('knn')!r} (want true)")
    pipeline = index_settings.get("default_pipeline")
    if pipeline != default_pipeline:
        problems.append(f"default_pipeline={pipeline!r} (want {default_pipeline})")

    if problems:
        raise RuntimeError(
            f"index {index} mapping/settings drift (G6). Delete it manually if this "
            f"local volume may be wiped, then re-run init_services. Problems: "
            + "; ".join(problems)
        )
    print(f"[ok] index {index} mapping/settings match required shape")


def ensure_index_and_pipelines(model_id: str) -> None:
    """Create ingest/search pipelines and the chunk index if missing."""
    settings = get_settings()
    mapping_path = CONFIG_DIR / "index-mapping.json"
    ingest_path = CONFIG_DIR / "ingest-pipeline.json"
    search_path = CONFIG_DIR / "search-pipeline.json"
    if not mapping_path.exists():
        print("[skip] opensearch mapping files not found")
        return

    with _client() as client:
        if ingest_path.exists():
            pipeline = json.loads(ingest_path.read_text(encoding="utf-8"))
            patched = False
            for processor in pipeline.get("processors", []):
                embedding = processor.get("text_embedding")
                if embedding is not None:
                    embedding["model_id"] = model_id
                    patched = True
            if not patched:
                raise RuntimeError("ingest-pipeline.json has no text_embedding processor")
            client.put(f"/_ingest/pipeline/{settings.opensearch_ingest_pipeline}", json=pipeline)
        if search_path.exists():
            client.put(
                f"/_search/pipeline/{settings.opensearch_search_pipeline}",
                json=json.loads(search_path.read_text(encoding="utf-8")),
            )
        exists = client.head(f"/{settings.opensearch_index}")
        if exists.status_code == 404:
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            mapping.setdefault("settings", {}).setdefault("index", {})
            mapping["settings"]["index"]["default_pipeline"] = settings.opensearch_ingest_pipeline
            client.put(f"/{settings.opensearch_index}", json=mapping)
            print(f"[ok] created index {settings.opensearch_index}")
        else:
            _assert_index_compatible(
                client,
                settings.opensearch_index,
                settings.opensearch_embedding_dim,
                settings.opensearch_ingest_pipeline,
            )

    save_runtime_config(
        {
            "opensearch_ingest_pipeline": settings.opensearch_ingest_pipeline,
            "opensearch_search_pipeline": settings.opensearch_search_pipeline,
        }
    )


def configure() -> None:
    cluster_health()
    from init_services.opensearch_security import configure as configure_security

    configure_security()
    enable_ml_commons()
    model_id = ensure_embedding_model()
    ensure_index_and_pipelines(model_id)
