from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import requests

PAGERDUTY_BASE_URL = "https://api.pagerduty.com"
PAGE_SIZE = 100


class PagerDutyClient:
    def __init__(
        self,
        token: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 30,
    ) -> None:
        self._session = session or requests.Session()
        self._timeout = timeout
        self._headers = {
            "Authorization": f"Token token={token}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
        }

    def high_urgency_incidents(
        self,
        since: datetime,
        until: datetime,
    ) -> list[dict[str, Any]]:
        incidents: list[dict[str, Any]] = []
        offset = 0

        while True:
            payload = self._get(
                "/incidents",
                params={
                    "urgencies[]": "high",
                    "since": _utc_timestamp(since),
                    "until": _utc_timestamp(until),
                    "sort_by": "created_at:desc",
                    "limit": PAGE_SIZE,
                    "offset": offset,
                },
            )
            incidents.extend(payload.get("incidents") or [])
            if not payload.get("more"):
                return incidents
            offset += PAGE_SIZE

    def primary_oncall(
        self,
        *,
        schedule_id: str,
        at: datetime,
    ) -> dict[str, str]:
        payload = self._get(
            "/oncalls",
            params={
                "schedule_ids[]": schedule_id,
                "since": _utc_timestamp(at),
                "until": _utc_timestamp(at + timedelta(minutes=1)),
                "earliest": "true",
                "limit": 25,
            },
        )
        oncalls = payload.get("oncalls") or []
        if not oncalls:
            raise RuntimeError(
                f"No on-call found for schedule {schedule_id} at {at.isoformat()}"
            )

        oncall = min(
            oncalls,
            key=lambda item: (
                item.get("escalation_level")
                if item.get("escalation_level") is not None
                else 99
            ),
        )
        user_reference = oncall.get("user") or {}
        user_id = user_reference.get("id")
        if not user_id:
            raise RuntimeError("On-call entry is missing its user id")

        user = self._get(f"/users/{user_id}").get("user") or {}
        email = (user.get("email") or "").strip()
        name = (user.get("name") or user_reference.get("summary") or user_id).strip()
        if not email:
            raise RuntimeError(f"PagerDuty user {name!r} has no email")
        return {"id": user_id, "name": name, "email": email}

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._session.get(
            f"{PAGERDUTY_BASE_URL}{path}",
            headers=self._headers,
            params=params,
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
