"""Offline unit checks for client-hybrid normalize/merge (no Docker).

Run: ``cd backend && uv run python -m scripts.search_unit_checks``
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.services.opensearch_search import (
    RawHit,
    hit_to_dto,
    merge_hybrid_scores,
    min_max_normalize,
)


def test_settings_defaults() -> None:
    get_settings.cache_clear()
    s = Settings()
    assert s.search_keyword_weight == 0.3
    assert s.search_neural_weight == 0.7
    assert s.search_fetch_multiplier == 5
    assert s.search_max_fetch == 100
    assert s.search_default_size == 10
    assert s.search_max_size == 50
    assert s.search_snippet_chars == 400
    assert s.search_mode == "client_hybrid"
    assert s.search_neural_k == 50


def test_min_max_empty() -> None:
    assert min_max_normalize([]) == []


def test_min_max_equal_scores() -> None:
    assert min_max_normalize([5.0, 5.0, 5.0]) == [1.0, 1.0, 1.0]


def test_min_max_single() -> None:
    assert min_max_normalize([42.0]) == [1.0]


def test_min_max_range() -> None:
    norms = min_max_normalize([0.0, 5.0, 10.0])
    assert norms == [0.0, 0.5, 1.0]


def test_merge_missing_side_zero() -> None:
    kw = [RawHit(id="a", score=10.0, source={"content": "A"})]
    nn = [RawHit(id="b", score=10.0, source={"content": "B"})]
    ranked = merge_hybrid_scores(kw, nn, w_kw=0.3, w_nn=0.7)
    by_id = {h.id: h for h in ranked}
    assert by_id["a"].score_kw == 1.0
    assert by_id["a"].score_nn == 0.0
    assert abs(by_id["a"].score - 0.3) < 1e-9
    assert by_id["b"].score_kw == 0.0
    assert by_id["b"].score_nn == 1.0
    assert abs(by_id["b"].score - 0.7) < 1e-9
    assert ranked[0].id == "b"  # higher combined


def test_merge_union_and_weights() -> None:
    kw = [
        RawHit(id="shared", score=10.0, source={"content": "kw"}),
        RawHit(id="kw_only", score=5.0, source={"content": "k"}),
    ]
    nn = [
        RawHit(id="shared", score=20.0, source={"content": "nn", "file_id": "f1"}),
        RawHit(id="nn_only", score=10.0, source={"content": "n"}),
    ]
    ranked = merge_hybrid_scores(kw, nn, w_kw=0.3, w_nn=0.7, size=10)
    by_id = {h.id: h for h in ranked}
    assert set(by_id) == {"shared", "kw_only", "nn_only"}
    # shared: both sides max after min_max → 1.0 each → 1.0 combined
    assert by_id["shared"].score_kw == 1.0
    assert by_id["shared"].score_nn == 1.0
    assert abs(by_id["shared"].score - 1.0) < 1e-9
    assert by_id["shared"].source.get("file_id") == "f1"  # richer source preferred
    assert ranked[0].id == "shared"


def test_merge_top_n() -> None:
    kw = [RawHit(id=f"k{i}", score=float(i), source={}) for i in range(5)]
    nn: list[RawHit] = []
    ranked = merge_hybrid_scores(kw, nn, w_kw=0.3, w_nn=0.7, size=2)
    assert len(ranked) == 2
    assert ranked[0].score >= ranked[1].score


def test_hit_to_dto_strips_embedding() -> None:
    from app.services.opensearch_search import MergedHit

    hit = MergedHit(
        id="proof-role-search-user",
        score=0.85,
        source={
            "content": "alpha-proof-token " + ("x" * 500),
            "embedding": [0.1, 0.2],
            "file_id": None,
            "chunk_seq": 0,
            "meta_file_type": "txt",
            "object_store_path": "local/abc/hello.txt",
            "uploaded_at": "2026-08-29T00:00:00Z",
        },
    )
    dto = hit_to_dto(hit, snippet_chars=400)
    assert "embedding" not in dto
    assert dto["chunk_id"] == "proof-role-search-user"
    assert dto["display_name"] == "hello.txt"
    assert len(dto["snippet"]) <= 400
    assert dto["snippet"].endswith("…")


def main() -> None:
    test_settings_defaults()
    print("[ok] settings defaults")
    test_min_max_empty()
    test_min_max_equal_scores()
    test_min_max_single()
    test_min_max_range()
    print("[ok] min_max_normalize")
    test_merge_missing_side_zero()
    test_merge_union_and_weights()
    test_merge_top_n()
    print("[ok] merge_hybrid_scores")
    test_hit_to_dto_strips_embedding()
    print("[ok] hit_to_dto")
    print("all search unit checks passed")


if __name__ == "__main__":
    main()
