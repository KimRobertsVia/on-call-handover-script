from datetime import UTC, datetime

from on_call_handover.blocks import (
    condense_incident_title,
    find_heading_id,
    incident_duration,
    incident_duration_minutes,
    incident_notion_properties,
    section_after_heading,
)


def test_condense_incident_title_uses_alert_and_specific_detail() -> None:
    title = (
        "[RegionStack | production | TooMany500s] Too many errors - More than 602 RPM"
    )

    assert condense_incident_title(title) == "TooMany500s — More than 602 RPM"


def test_condense_incident_title_defaults_to_table_friendly_length() -> None:
    title = "A" * 80

    condensed = condense_incident_title(title)

    assert len(condensed) == 60
    assert condensed.endswith("…")


def test_incident_duration_can_be_calculated_deterministically() -> None:
    incident = {"created_at": "2026-07-27T10:00:00Z"}
    now = datetime(2026, 7, 27, 11, 12, tzinfo=UTC)

    assert incident_duration(incident, now=now) == "1h 12m"
    assert incident_duration_minutes(incident, now=now) == 72


def test_incident_notion_properties_include_status_and_duration() -> None:
    incident = {
        "id": "PABC",
        "title": "[RegionStack | production | TooMany500s] Too many - More than 10",
        "created_at": "2026-07-27T10:00:00Z",
        "resolved_at": "2026-07-27T11:12:00Z",
        "html_url": "https://example.test/PABC",
    }

    properties = incident_notion_properties(incident)

    assert properties["Name"]["title"][0]["text"]["content"] == (
        "TooMany500s — More than 10"
    )
    assert properties["URL"]["url"] == "https://example.test/PABC"
    assert properties["Created"]["date"]["start"] == "2026-07-27T10:00:00+00:00"
    assert properties["Duration (minutes)"]["number"] == 72
    assert properties["Duration"]["rich_text"][0]["text"]["content"] == "1h 12m"
    assert properties["Status"]["status"]["name"] == "Resolved"
    assert properties["Incident ID"]["rich_text"][0]["text"]["content"] == "PABC"


def test_heading_helpers_stop_at_next_heading() -> None:
    blocks = [
        _block("heading_2", "alerts", "Alerts"),
        _block("paragraph", "first", "One"),
        _block("heading_2", "actions", "Actions"),
        _block("paragraph", "second", "Two"),
    ]

    assert find_heading_id(blocks, "Alerts") == "alerts"
    assert [item["id"] for item in section_after_heading(blocks, "alerts")] == ["first"]


def _block(block_type: str, block_id: str, text: str) -> dict:
    return {
        "id": block_id,
        "type": block_type,
        block_type: {"rich_text": [{"plain_text": text}]},
    }
