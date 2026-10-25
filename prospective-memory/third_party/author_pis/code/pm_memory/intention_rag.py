"""PIS-RAG ablation: Mem0-style hybrid retrieval over intention records.

This module is only used when ``IntentionStoreBackend.retrieval_mode`` is
``similarity``. The default due-checking path must not import or call it
at recall time.

Retrieval matches Mem0 OSS in spirit, not via ``Memory.search``:

  score = (cosine(emb(q), emb(d(I))) + minmax(BM25(q, d(I)))) / 2

Documents are flattened intention fields (including status). Candidate pool
is the whole store (pending + done + canceled). No TIME-DUE / event-due /
CHECK labels are produced here.
"""

from __future__ import annotations

import math
import os
import re
from typing import Any, Callable, Sequence

EmbedFn = Callable[[list[str]], list[list[float]]]

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
_BM25_K1 = 1.5
_BM25_B = 0.75


def serialize_intention(intent: Any) -> str:
    """One retrieval document: typed fields as text, status first."""
    due_day = (intent.due.day or "").strip()
    due_time = (intent.due.time or "").strip()
    watch = ",".join(w for w in (intent.watch or []) if str(w).strip())
    bits = [
        f"status={intent.status or 'pending'}",
        f"action={(intent.action or '').strip()}",
        f"due_day={due_day}",
        f"due_time={due_time}",
        f"event_cue={(intent.event_cue or '').strip()}",
        f"watch={watch}",
    ]
    return " | ".join(bits)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) > 1]


def _l2_normalize(vec: Sequence[float]) -> list[float]:
    s = math.sqrt(sum(x * x for x in vec))
    if s <= 0.0:
        return [0.0] * len(vec)
    return [x / s for x in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def bm25_scores(query: str, docs: list[str]) -> list[float]:
    """BM25 over a tiny in-memory collection (the current intention store)."""
    q_toks = tokenize(query)
    if not q_toks or not docs:
        return [0.0] * len(docs)
    doc_toks = [tokenize(d) for d in docs]
    n_docs = len(docs)
    avgdl = sum(len(t) for t in doc_toks) / n_docs
    df: dict[str, int] = {}
    for toks in doc_toks:
        for w in set(toks):
            df[w] = df.get(w, 0) + 1
    scores = []
    for toks in doc_toks:
        tf: dict[str, int] = {}
        for w in toks:
            tf[w] = tf.get(w, 0) + 1
        dl = len(toks) or 1
        score = 0.0
        for w in q_toks:
            f = tf.get(w, 0)
            if not f:
                continue
            n_q = df.get(w, 0)
            idf = math.log((n_docs - n_q + 0.5) / (n_q + 0.5) + 1.0)
            denom = f + _BM25_K1 * (1.0 - _BM25_B + _BM25_B * dl / (avgdl or 1.0))
            score += idf * (f * (_BM25_K1 + 1.0) / denom)
        scores.append(score)
    return scores


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.0 if v <= 0.0 else 1.0 for v in values]
    return [(v - lo) / (hi - lo) for v in values]


def hashed_embed_many(texts: list[str], *, dim: int = 64) -> list[list[float]]:
    """Deterministic bag-of-tokens vectors for probes (no API)."""
    out: list[list[float]] = []
    for text in texts:
        vec = [0.0] * dim
        for tok in tokenize(text):
            # Stable across processes; avoid PYTHONHASHSEED-randomized hash().
            idx = int.from_bytes(tok.encode("utf-8"), "little", signed=False) % dim
            vec[idx] += 1.0
        out.append(_l2_normalize(vec))
    return out


def make_openai_embedder(
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout: float = 60.0,
) -> EmbedFn:
    """OpenAI-compatible embeddings (same gateway Mem0 uses via MEM0_EMBED_*)."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    def embed(texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = client.embeddings.create(model=model, input=texts)
        by_index = {item.index: list(item.embedding) for item in resp.data}
        vecs = [by_index[i] for i in range(len(texts))]
        return [_l2_normalize(v) for v in vecs]

    return embed


def embedder_from_mem0_env(*, timeout: float = 60.0) -> EmbedFn | None:
    """Reuse Mem0's embedder env so the ablation shares the same model."""
    key = os.environ.get("MEM0_EMBED_API_KEY") or ""
    url = os.environ.get("MEM0_EMBED_BASE_URL") or ""
    model = os.environ.get("MEM0_EMBED_MODEL") or "text-embedding-3-small"
    if not key or not url:
        return None
    return make_openai_embedder(
        api_key=key, base_url=url, model=model, timeout=timeout
    )


def rank_documents(
    query: str,
    docs: list[str],
    *,
    embeddings: list[list[float]] | None,
    query_vec: list[float] | None,
    top_k: int,
) -> list[dict[str, Any]]:
    """Hybrid rank. embeddings/query_vec None → BM25 only (embed fail-open)."""
    n = len(docs)
    if n == 0:
        return []
    k = max(1, int(top_k or 1))
    lexical = _minmax(bm25_scores(query, docs))
    use_dense = bool(
        query_vec
        and embeddings
        and len(embeddings) == n
        and len(query_vec) == len(embeddings[0])
    )
    rows: list[dict[str, Any]] = []
    for i, doc in enumerate(docs):
        sem = cosine(query_vec, embeddings[i]) if use_dense else 0.0
        bm = lexical[i]
        combined = (sem + bm) / 2.0 if use_dense else bm
        rows.append(
            {
                "index": i,
                "doc": doc,
                "semantic": round(float(sem), 4),
                "bm25": round(float(bm), 4),
                "score": round(float(combined), 4),
            }
        )
    rows.sort(key=lambda r: (-r["score"], r["index"]))
    return rows[:k]


def retrieve_intentions(
    query: str,
    intentions: Sequence[Any],
    *,
    top_k: int = 5,
    embed_fn: EmbedFn | None = None,
    vec_cache: dict[str, tuple[str, list[float]]] | None = None,
) -> list[dict[str, Any]]:
    """Rank the full store. vec_cache maps intent_id → (doc_text, vector)."""
    items = list(intentions)
    if not items:
        return []
    docs = [serialize_intention(i) for i in items]
    embeddings: list[list[float]] | None = None
    query_vec: list[float] | None = None
    cache = vec_cache if vec_cache is not None else {}
    dense_ok = False
    if embed_fn is not None:
        try:
            need: list[str] = []
            need_pos: list[int] = []
            embeddings = []
            for i, (intent, doc) in enumerate(zip(items, docs)):
                hit = cache.get(intent.intent_id)
                if hit and hit[0] == doc:
                    embeddings.append(hit[1])
                else:
                    embeddings.append([])  # placeholder
                    need.append(doc)
                    need_pos.append(i)
            if need:
                fresh = embed_fn(need)
                if len(fresh) != len(need):
                    raise RuntimeError("embedder returned wrong batch size")
                for pos, vec in zip(need_pos, fresh):
                    embeddings[pos] = vec
                    cache[items[pos].intent_id] = (docs[pos], vec)
            qv = embed_fn([query])
            if qv:
                query_vec = qv[0]
                dense_ok = True
        except Exception:
            embeddings = None
            query_vec = None
            dense_ok = False
    ranked = rank_documents(
        query,
        docs,
        embeddings=embeddings if dense_ok else None,
        query_vec=query_vec if dense_ok else None,
        top_k=top_k,
    )
    out = []
    for row in ranked:
        intent = items[row["index"]]
        out.append(
            {
                "intent": intent,
                "doc": row["doc"],
                "score": row["score"],
                "semantic": row["semantic"],
                "bm25": row["bm25"],
                "mode": "hybrid" if dense_ok else "bm25",
            }
        )
    return out


def format_rag_injection(
    hits: list[dict[str, Any]],
    *,
    day: str,
    query: str,
) -> str:
    header = (
        f"PIS-RAG @ {day or '?'} (Mem0-style similarity top-k over intention "
        "records; rows are not due stamps)"
    )
    if not hits:
        return header + "\n(No relevant memories)"
    lines = [header]
    for hit in hits:
        lines.append(f"- {hit['doc']}")
    return "\n".join(lines)
