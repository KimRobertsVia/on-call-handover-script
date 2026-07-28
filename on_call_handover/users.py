from __future__ import annotations

import json
from pathlib import Path


def load_user_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return _empty_user_map()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"Expected a JSON object in {path}")

    return {
        "by_pagerduty_email": _normalize_mapping(raw.get("by_pagerduty_email")),
        "by_pagerduty_name": _normalize_mapping(raw.get("by_pagerduty_name")),
    }


def mapped_notion_user_id(
    user_map: dict[str, dict[str, str]],
    *,
    pagerduty_email: str,
    pagerduty_name: str,
) -> str | None:
    return user_map["by_pagerduty_email"].get(
        pagerduty_email.strip().lower()
    ) or user_map["by_pagerduty_name"].get(pagerduty_name.strip().lower())


def _normalize_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip().lower(): str(mapped).strip()
        for key, mapped in value.items()
        if str(key).strip() and str(mapped).strip()
    }


def _empty_user_map() -> dict[str, dict[str, str]]:
    return {"by_pagerduty_email": {}, "by_pagerduty_name": {}}
