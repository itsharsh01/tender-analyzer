# -*- coding: utf-8 -*-
"""
Evidence Merger — post-processing step that merges fragmented
evidence items that were split across PDF text blocks.

Many tender PDFs break sentences across blocks, e.g.:

  Chunk A: "Average annual turnover during the"
  Chunk B: "last 3 years should not be less than 5 crore."

This module detects such fragments and merges them into complete
sentences, producing an *enriched* evidence pool.

Merge conditions (ALL must be true):
  1. Same page
  2. Same heading
  3. Same source (paragraph / list / ocr)
  4. Consecutive position (or adjacent index if position is null)
  5. Fragment heuristic:
       - current item ends without sentence-final punctuation, OR
       - next item starts with a lowercase letter, OR
       - bbox vertical gap is small (if both have bbox)
"""

from __future__ import annotations

import copy
import re
import uuid
from typing import Any, Optional


# ── Heuristics ────────────────────────────────────────────────────────────────

_SENTENCE_END_RE = re.compile(r"[.!?;:)\]\"']\s*$")
_STARTS_LOWER_RE = re.compile(r"^[a-z]")
# Maximum vertical gap (in PDF points) between bboxes to qualify as "nearby"
_MAX_BBOX_GAP = 30.0


def _text_of(ev: dict[str, Any]) -> str:
    """Best available text for heuristic checks."""
    return ev.get("text_norm") or ev.get("text_raw") or ""


def _is_fragment(current: dict[str, Any], next_ev: dict[str, Any]) -> bool:
    """Return True if `current` looks like an incomplete sentence that
    should be merged with `next_ev`."""
    cur_text = _text_of(current).rstrip()
    nxt_text = _text_of(next_ev).lstrip()

    if not cur_text or not nxt_text:
        return False

    # Strong signal: current doesn't end with punctuation
    no_punct = not _SENTENCE_END_RE.search(cur_text)

    # Strong signal: next starts with lowercase
    starts_lower = bool(_STARTS_LOWER_RE.match(nxt_text))

    # Weak signal: very short current (likely a fragment)
    short_current = len(cur_text) < 80

    # Bbox proximity check (only when both have bbox data)
    bbox_ok = True  # default pass when we have no bbox
    cur_bbox = current.get("bbox")
    nxt_bbox = next_ev.get("bbox")
    if cur_bbox and nxt_bbox:
        # cur_bbox = (x0, y0, x1, y1) — y1 of current vs y0 of next
        try:
            gap = float(nxt_bbox[1]) - float(cur_bbox[3])
            bbox_ok = gap < _MAX_BBOX_GAP
        except (TypeError, IndexError, ValueError):
            bbox_ok = True  # can't determine, assume OK

    # Decision: merge if bbox is close AND at least one text signal fires
    if not bbox_ok:
        return False

    return no_punct or starts_lower or (short_current and no_punct is False and starts_lower is False)


def _same_group(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Items must share page, heading, and source to be merge candidates."""
    return (
        a.get("page") == b.get("page")
        and a.get("heading") == b.get("heading")
        and a.get("source") == b.get("source")
    )


def _positions_consecutive(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Check if positions are consecutive (or both null → rely on list order)."""
    pa = a.get("position")
    pb = b.get("position")
    if pa is not None and pb is not None:
        return int(pb) == int(pa) + 1
    # If positions are absent, we rely on list adjacency (caller ensures order)
    return True


def _merge_pair(current: dict[str, Any], next_ev: dict[str, Any]) -> dict[str, Any]:
    """Create a merged evidence item from two fragments."""
    merged = copy.deepcopy(current)
    merged["evidence_id"] = str(uuid.uuid4())

    # Merge text fields
    cur_text = _text_of(current).rstrip()
    nxt_text = _text_of(next_ev).lstrip()
    merged_text = f"{cur_text} {nxt_text}"
    merged["text_norm"] = merged_text
    merged["text_raw"] = f"{current.get('text_raw', '')} {next_ev.get('text_raw', '')}"

    # For tables: merge key/value norms
    if current.get("key_norm") and next_ev.get("key_norm"):
        merged["key_norm"] = f"{current['key_norm']} {next_ev['key_norm']}"
    if current.get("value_norm") and next_ev.get("value_norm"):
        merged["value_norm"] = f"{current['value_norm']} {next_ev['value_norm']}"

    # Track provenance
    cur_from = current.get("merged_from", [current.get("evidence_id")])
    nxt_from = next_ev.get("merged_from", [next_ev.get("evidence_id")])
    merged["merged_from"] = cur_from + nxt_from

    # Confidence: take the max (merged item is more informative)
    merged["confidence"] = max(
        float(current.get("confidence") or 0),
        float(next_ev.get("confidence") or 0),
    )

    return merged


# ── Public API ────────────────────────────────────────────────────────────────

def merge_evidence_pool(evidence_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Walk through the evidence pool and merge adjacent fragments.
    Table evidence (source=table) is passed through unmodified — tables
    already have clean key-value pairs; merging would destroy structure.

    Returns a new list (does not mutate the input).
    """
    if not evidence_docs:
        return []

    # Separate table items (no merge needed) from paragraph/list/ocr items
    tables: list[dict[str, Any]] = []
    mergeable: list[dict[str, Any]] = []
    for ev in evidence_docs:
        if ev.get("source") == "table":
            tables.append(ev)
        else:
            mergeable.append(ev)

    # Merge pass on non-table items
    result: list[dict[str, Any]] = []
    i = 0
    while i < len(mergeable):
        current = copy.deepcopy(mergeable[i])
        # Greedily merge with the next item(s) while they look like fragments
        while i + 1 < len(mergeable):
            next_ev = mergeable[i + 1]
            if (
                _same_group(current, next_ev)
                and _positions_consecutive(current, next_ev)
                and _is_fragment(current, next_ev)
            ):
                current = _merge_pair(current, next_ev)
                i += 1
            else:
                break
        result.append(current)
        i += 1

    # Combine: tables first, then merged non-table items (preserves order)
    return tables + result
