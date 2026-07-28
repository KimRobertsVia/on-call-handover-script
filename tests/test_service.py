from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from on_call_handover.config import Config
from on_call_handover.service import HandoverService


class FakePagerDuty:
    def __init__(self) -> None:
        self.primary_calls = 0

    def high_urgency_incidents(self, since: datetime, until: datetime) -> list[dict]:
        return []

    def primary_oncall(self, **kwargs: Any) -> dict[str, str]:
        self.primary_calls += 1
        raise AssertionError("Primary on-call should not be resolved when disabled")


class FakeNotion:
    def __init__(self) -> None:
        self.appended: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def acting_user(self) -> dict[str, str]:
        return {"id": "actor", "name": "Actor"}

    def create_page(self, **kwargs: Any) -> dict[str, str]:
        assert kwargs["now_primary_user_id"] is None
        return {"id": "destination", "url": "https://notion.test/destination"}

    def apply_template(self, page_id: str, **kwargs: Any) -> None:
        pass

    def block_children(self, block_id: str) -> list[dict[str, Any]]:
        if block_id == "source-page":
            return [
                _heading("source-previous", "Previous"),
                _paragraph("old-action", "Follow up"),
                _heading("source-actions", "Actions"),
                _paragraph("new-action", "Investigate"),
            ]
        return [
            _heading("alerts", "Alerts"),
            _paragraph("alert-placeholder", ""),
            _heading("previous", "Previous"),
            _paragraph("previous-placeholder", ""),
            _heading("actions", "Actions"),
        ]

    def append_blocks(self, page_id: str, **kwargs: Any) -> None:
        self.appended.append({"page_id": page_id, **kwargs})

    def delete_block(self, block_id: str) -> None:
        self.deleted.append(block_id)

    def latest_page(self, data_source_id: str, **kwargs: Any) -> dict[str, str]:
        return {"id": "source-page"}


def test_run_skips_primary_lookup_when_feature_is_disabled(tmp_path: Path) -> None:
    pagerduty = FakePagerDuty()
    notion = FakeNotion()
    config = Config(
        pagerduty_token="pd",
        notion_token="notion",
        notion_data_source_id="target",
        notion_template_id="template",
        pagerduty_primary_schedule_id="schedule",
        notion_alerts_heading="Alerts",
        notion_previous_actions_heading="Previous",
        notion_actions_heading="Actions",
        mention_now_primary=False,
        user_map_path=tmp_path / "user_map.json",
    )

    result = HandoverService(
        config,
        pagerduty=pagerduty,  # type: ignore[arg-type]
        notion=notion,  # type: ignore[arg-type]
        template_poll_interval=0,
    ).run(now=datetime(2026, 7, 27, 9, tzinfo=UTC))

    assert pagerduty.primary_calls == 0
    assert result.incident_count == 0
    assert result.copied_action_count == 2
    assert notion.deleted == ["alert-placeholder", "previous-placeholder"]
    assert len(notion.appended) == 2


def _heading(block_id: str, text: str) -> dict[str, Any]:
    return {
        "id": block_id,
        "type": "heading_2",
        "heading_2": {"rich_text": [{"plain_text": text}]},
    }


def _paragraph(block_id: str, text: str) -> dict[str, Any]:
    return {
        "id": block_id,
        "type": "paragraph",
        "has_children": False,
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "plain_text": text,
                    "text": {"content": text},
                }
            ]
        },
    }
