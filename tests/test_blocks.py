from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from on_call_handover.blocks import (
    condense_incident_title,
    find_heading_id,
    incident_bullet,
    incident_duration,
    section_after_heading,
)


def test_condense_incident_title_uses_alert_and_specific_detail() -> None:
    title = (
        "[RegionStack | production | TooMany500s] Too many errors - More than 602 RPM"
    )

    assert condense_incident_title(title) == "TooMany500s — More than 602 RPM"


def test_incident_duration_can_be_calculated_deterministically() -> None:
    incident = {"created_at": "2026-07-27T10:00:00Z"}
    now = datetime(2026, 7, 27, 11, 12, tzinfo=UTC)

    assert incident_duration(incident, now=now) == "1h 12m"


def test_heading_helpers_stop_at_next_heading() -> None:
    blocks = [
        _block("heading_2", "alerts", "Alerts"),
        _block("paragraph", "first", "One"),
        _block("heading_2", "actions", "Actions"),
        _block("paragraph", "second", "Two"),
    ]

    assert find_heading_id(blocks, "Alerts") == "alerts"
    assert [item["id"] for item in section_after_heading(blocks, "alerts")] == ["first"]


def test_incident_bullet_contains_local_date_link_and_duration() -> None:
    incident = {
        "title": "A useful title",
        "created_at": "2026-07-27T10:00:00Z",
        "resolved_at": "2026-07-27T10:05:00Z",
        "html_url": "https://example.test/incident",
    }

    block = incident_bullet(incident, ZoneInfo("Europe/London"))
    rich_text = block["bulleted_list_item"]["rich_text"]

    assert rich_text[0]["mention"]["date"]["start"] == "2026-07-27T11:00:00+01:00"
    assert rich_text[2]["text"]["link"]["url"] == incident["html_url"]
    assert rich_text[3]["text"]["content"] == " (5m)"


def _block(block_type: str, block_id: str, text: str) -> dict:
    return {
        "id": block_id,
        "type": block_type,
        block_type: {"rich_text": [{"plain_text": text}]},
    }
