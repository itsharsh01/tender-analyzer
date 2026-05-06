from typing import Any


def score_placeholder(evaluation: dict[str, Any]) -> dict[str, Any]:
    checks = evaluation.get("checks", [])
    passed = sum(1 for c in checks if c.get("passed"))
    total = len(checks) or 1
    return {"score": passed / total, "passed": passed, "total": total}

