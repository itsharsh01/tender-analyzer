# -*- coding: utf-8 -*-
"""
Matching Service — Semantic vector similarity matching.

For each canonical criterion, finds the top-k most similar
submission evidence items using cosine similarity on embeddings.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def match_criteria_to_submission(
    canonical_items: list[dict[str, Any]],
    submission_evidence: list[dict[str, Any]],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    For each canonical criterion (with embedding), find the top-k
    most similar submission evidence items.

    Returns a list of match records:
    {
        "evidence_id": <canonical evidence_id>,
        "category": ...,
        "sub_component": ...,
        "matched_evidence": [
            {"evidence_id": ..., "similarity": ..., "text": ..., "page": ...},
            ...
        ],
        "aggregated_text": <merged text from all matches>,
    }
    """
    # Pre-filter: only evidence with valid embeddings
    valid_submission = [
        ev for ev in submission_evidence
        if ev.get("embedding") and len(ev["embedding"]) > 0
    ]

    if not valid_submission:
        logger.warning("No valid submission embeddings for matching.")
        return []

    # Build submission embedding matrix for vectorized similarity
    sub_matrix = np.array(
        [ev["embedding"] for ev in valid_submission], dtype=np.float32
    )
    sub_norms = np.linalg.norm(sub_matrix, axis=1, keepdims=True)
    sub_norms[sub_norms == 0] = 1.0  # Prevent division by zero
    sub_matrix_normed = sub_matrix / sub_norms

    matches = []

    for canon in canonical_items:
        canon_emb = canon.get("embedding")
        if not canon_emb or len(canon_emb) == 0:
            continue

        canon_vec = np.array(canon_emb, dtype=np.float32)
        canon_norm = np.linalg.norm(canon_vec)
        if canon_norm == 0:
            continue
        canon_vec_normed = canon_vec / canon_norm

        # Vectorized cosine similarity against all submission evidence
        similarities = sub_matrix_normed @ canon_vec_normed

        # Get top-k indices
        if len(similarities) <= top_k:
            top_indices = np.argsort(similarities)[::-1]
        else:
            top_indices = np.argpartition(similarities, -top_k)[-top_k:]
            top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]

        matched_evidence = []
        for idx in top_indices:
            sim_score = float(similarities[idx])
            if sim_score < 0.1:  # Skip very low similarity
                continue
            ev = valid_submission[idx]
            matched_evidence.append({
                "evidence_id": ev.get("evidence_id"),
                "similarity": round(sim_score, 4),
                "text": ev.get("search_text", ev.get("text", "")),
                "page": ev.get("page"),
                "source": ev.get("source"),
                "heading": ev.get("heading"),
                "key_norm": ev.get("key_norm"),
                "value_norm": ev.get("value_norm"),
            })

        # Aggregate all matched text
        aggregated_text = " ".join(
            m["text"] for m in matched_evidence if m.get("text")
        )

        matches.append({
            "evidence_id": canon.get("evidence_id"),
            "category": canon.get("category"),
            "sub_component": canon.get("sub_component"),
            "canonical_text": canon.get("text", ""),
            "matched_evidence": matched_evidence,
            "aggregated_text": aggregated_text,
        })

    logger.info(
        "Matching complete: %d canonical criteria → %d with matches",
        len(canonical_items), sum(1 for m in matches if m["matched_evidence"]),
    )
    return matches
