"""Token estimator + overlapping text chunker.

C2: target 600 tokens / 75-token overlap. Estimator is ≈4 chars/token
(lightweight; no tiktoken / OpenSearch call). Documented choice — not the
MiniLM tokenizer. Embedding dim 384 is unrelated to this input window.
"""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Approximate token count as ceil(len / 4). Empty → 0."""
    if not text:
        return 0
    return (len(text) + 3) // 4


def chunk_text(
    text: str,
    *,
    chunk_tokens: int = 600,
    overlap_tokens: int = 75,
) -> list[str]:
    """Split text into overlapping chunks by the char≈token estimator.

    Overlap is applied in character space as ``overlap_tokens * 4``.
    Leading/trailing whitespace on each emitted chunk is stripped; empty
    chunks are dropped. If the whole text fits in one budget, returns a
    single chunk (or [] for blank input).
    """
    if chunk_tokens < 1:
        raise ValueError("chunk_tokens must be >= 1")
    if overlap_tokens < 0:
        raise ValueError("overlap_tokens must be >= 0")
    if overlap_tokens >= chunk_tokens:
        raise ValueError("overlap_tokens must be < chunk_tokens")

    cleaned = text.strip()
    if not cleaned:
        return []

    if estimate_tokens(cleaned) <= chunk_tokens:
        return [cleaned]

    chunk_chars = chunk_tokens * 4
    overlap_chars = overlap_tokens * 4
    step = max(1, chunk_chars - overlap_chars)

    chunks: list[str] = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(length, start + chunk_chars)
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start += step
    return chunks
