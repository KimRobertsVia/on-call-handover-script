import json
from datetime import UTC, datetime
from typing import Any

import requests

from on_call_handover.pagerduty import PagerDutyClient


class FakeSession:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = iter(payloads)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append({"url": url, **kwargs})
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(next(self.payloads)).encode()
        return response


def test_incident_query_paginates() -> None:
    session = FakeSession(
        [
            {"incidents": [{"id": "first"}], "more": True},
            {"incidents": [{"id": "second"}], "more": False},
        ]
    )
    client = PagerDutyClient("token", session=session)  # type: ignore[arg-type]
    since = datetime(2026, 7, 20, tzinfo=UTC)
    until = datetime(2026, 7, 27, tzinfo=UTC)

    incidents = client.high_urgency_incidents(since, until)

    assert [incident["id"] for incident in incidents] == ["first", "second"]
    assert [call["params"]["offset"] for call in session.calls] == [0, 100]
