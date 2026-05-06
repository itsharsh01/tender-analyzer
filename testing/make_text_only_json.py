# -*- coding: utf-8 -*-
"""
Create a simplified text-only JSON from paragraph_chunks.json.

Input shape: list of chunk trees with keys like id/level/content/metadata/children.
Output shape: same hierarchy but only:
  - level
  - text
  - children
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List


def simplify_node(node: Dict[str, Any]) -> Dict[str, Any]:
    children = node.get("children") or []
    return {
        "level": node.get("level"),
        "text": node.get("content", ""),
        "children": [simplify_node(c) for c in children],
    }


def run(in_path: str, out_path: str) -> None:
    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Expected top-level JSON list.")

    simplified: List[Dict[str, Any]] = [simplify_node(n) for n in data]

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(simplified, f, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="in_path", default="paragraph_chunks.json")
    parser.add_argument("--out", dest="out_path", default="paragraph_chunks_text_only.json")
    args = parser.parse_args()
    run(args.in_path, args.out_path)
    print(f"Wrote {args.out_path}")


if __name__ == "__main__":
    main()

