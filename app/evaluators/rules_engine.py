from typing import Any


def evaluate_placeholder(canonical: dict[str, Any]) -> dict[str, Any]:
    fields = canonical.get("fields", {})
    return {
        "status": "not_implemented",
        "checks": [
            {"name": "has_bid_end_date", "passed": "bid.end_date_time" in fields},
            {"name": "has_bid_opening_date", "passed": "bid.opening_date_time" in fields},
        ],
    }

