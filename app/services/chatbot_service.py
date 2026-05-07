from __future__ import annotations

import json
from typing import Any

import numpy as np

from app.models.db import get_db
from app.services.embedding_service import _get_embedding_model
from app.utils.groq_llm import _chat_completion_with_fallback, _strip_markdown_fences


def _cosine(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    na = np.linalg.norm(va)
    nb = np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _flatten_canonical(canonical_doc: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    skip = {
        "tender_id",
        "total_classified",
        "total_ignored",
        "batch_count",
        "fields",
        "evidence",
        "created_at",
        "pdf_path",
    }
    for key, bucket in canonical_doc.items():
        if key in skip or not isinstance(bucket, list):
            continue
        for it in bucket:
            text = (
                it.get("text_norm")
                or it.get("text_raw")
                or it.get("value_norm")
                or it.get("key_norm")
                or ""
            ).strip()
            if not text:
                continue
            items.append(
                {
                    "doc_id": it.get("evidence_id"),
                    "scope": "tender",
                    "category": it.get("category") or key,
                    "sub_component": it.get("sub_component"),
                    "page": it.get("page"),
                    "heading": it.get("heading"),
                    "text": text,
                    "key_norm": it.get("key_norm"),
                    "value_norm": it.get("value_norm"),
                }
            )
    return items


def _submission_docs(tender_id: str, submission_id: str) -> list[dict[str, Any]]:
    db = get_db()
    docs = list(
        db.submission_evidence.find(
            {"tender_id": tender_id, "submission_id": submission_id},
            {"_id": 0},
        )
    )
    out: list[dict[str, Any]] = []
    for d in docs:
        text = (
            d.get("text_norm")
            or d.get("text_raw")
            or d.get("value_norm")
            or d.get("key_norm")
            or ""
        ).strip()
        if not text:
            continue
        out.append(
            {
                "doc_id": d.get("evidence_id"),
                "scope": "submission",
                "category": None,
                "sub_component": None,
                "page": d.get("page"),
                "heading": d.get("heading"),
                "text": text,
                "key_norm": d.get("key_norm"),
                "value_norm": d.get("value_norm"),
            }
        )
    return out


def _keyword_score(query: str, text: str) -> float:
    q_tokens = [t for t in query.lower().split() if len(t) > 2]
    if not q_tokens:
        return 0.0
    t = text.lower()
    hits = sum(1 for tok in q_tokens if tok in t)
    return hits / len(q_tokens)


def _rerank(query: str, query_vec: list[float], docs: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    model = _get_embedding_model()
    texts = [d["text"] for d in docs]
    vecs = model.encode(texts, convert_to_numpy=True)
    for idx, d in enumerate(docs):
        emb = vecs[idx].tolist()
        sem = _cosine(query_vec, emb)
        key = _keyword_score(query, d["text"])
        # Hybrid rerank: semantic + lexical
        score = 0.75 * sem + 0.25 * key
        scored.append({**d, "score": round(score, 4), "semantic": round(sem, 4), "lexical": round(key, 4)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def _short_answer(query: str, contexts: list[dict[str, Any]]) -> str:
    context_payload = [
        {
            "doc_id": c.get("doc_id"),
            "scope": c.get("scope"),
            "page": c.get("page"),
            "heading": c.get("heading"),
            "text": c.get("text"),
        }
        for c in contexts
    ]
    system_prompt = (
        "You are a tender analysis assistant. Answer briefly (3-5 lines), "
        "strictly using provided context. If uncertain, say so. "
        "Include doc_id citations in square brackets like [doc_id]."
    )
    user_message = (
        f"Query: {query}\n"
        f"Context:\n{json.dumps(context_payload, ensure_ascii=False, indent=2)}\n"
        "Return only the answer text."
    )
    raw = _chat_completion_with_fallback(
        system_prompt=system_prompt,
        user_message=user_message,
        temperature=0.0,
    )
    return _strip_markdown_fences(raw).strip()


def answer_query(tender_id: str, submission_id: str, query: str, top_k: int = 8) -> dict[str, Any]:
    db = get_db()
    if not db.tenders.find_one({"_id": tender_id}, {"_id": 1}):
        raise ValueError(f"Tender '{tender_id}' not found.")
    if not db.submissions.find_one({"_id": submission_id, "tender_id": tender_id}, {"_id": 1}):
        raise ValueError("Submission not found for this tender.")

    canonical_doc = db.canonical_tenders.find_one({"tender_id": tender_id}, {"_id": 0}) or {}
    tender_docs = _flatten_canonical(canonical_doc)
    submission_docs = _submission_docs(tender_id, submission_id)
    corpus = tender_docs + submission_docs
    if not corpus:
        raise RuntimeError("No retrievable context found for this tender/submission.")

    model = _get_embedding_model()
    query_vec = model.encode([query], convert_to_numpy=True)[0].tolist()
    top_contexts = _rerank(query=query, query_vec=query_vec, docs=corpus, top_k=max(1, min(top_k, 20)))
    answer = _short_answer(query, top_contexts)
    return {
        "tender_id": tender_id,
        "submission_id": submission_id,
        "query": query,
        "top_k": len(top_contexts),
        "answer": answer,
        "contexts": top_contexts,
    }

