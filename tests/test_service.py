from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from on_call_handover.config import Config
from on_call_handover.service import HandoverService


class FakePagerDuty:
    def __init__(
        self,
        incidents: list[dict[str, Any]] | None = None,
        *,
        oncall: dict[str, str] | None = None,
        oncall_by_at: dict[datetime, dict[str, str]] | None = None,
    ) -> None:
        self.primary_calls: list[datetime] = []
        self.incidents = incidents or []
        self.oncall = oncall or {
            "id": "PD1",
            "name": "Current Person",
            "email": "current@example.com",
        }
        self.oncall_by_at = oncall_by_at or {}

    def high_urgency_incidents(self, since: datetime, until: datetime) -> list[dict]:
        return self.incidents

    def primary_oncall(self, **kwargs: Any) -> dict[str, str]:
        at = kwargs["at"]
        self.primary_calls.append(at)
        if at in self.oncall_by_at:
            return self.oncall_by_at[at]
        return self.oncall


class FakeNotion:
    def __init__(
        self,
        *,
        existing_page: dict[str, str] | None = None,
        destination_blocks: list[dict[str, Any]] | None = None,
    ) -> None:
        self.appended: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.upserted: list[dict[str, Any]] = []
        self.linked_views: list[dict[str, Any]] = []
        self.created_pages = 0
        self.created_handover_date: date | None = None
        self.created_by_user_id: str | None = None
        self.now_primary_user_id: str | None = None
        self.templates_applied = 0
        self.existing_page = existing_page
        self._destination_blocks = destination_blocks

    def people_by_email(self, data_source_ids: list[str]) -> dict[str, dict[str, str]]:
        return {}

    def page_by_date(
        self,
        data_source_id: str,
        handover_date: date,
    ) -> dict[str, str] | None:
        return self.existing_page

    def create_page(self, **kwargs: Any) -> dict[str, str]:
        self.created_pages += 1
        self.created_handover_date = kwargs["handover_date"]
        self.created_by_user_id = kwargs["created_by_user_id"]
        self.now_primary_user_id = kwargs["now_primary_user_id"]
        return {"id": "destination", "url": "https://notion.test/destination"}

    def apply_template(self, page_id: str, **kwargs: Any) -> None:
        self.templates_applied += 1

    def block_children(self, block_id: str) -> list[dict[str, Any]]:
        if block_id == "source-page":
            return [
                _heading("source-previous", "Previous"),
                _paragraph("old-action", "Follow up"),
                _heading("source-actions", "Actions"),
                _paragraph("new-action", "Investigate"),
            ]
        if self._destination_blocks is not None:
            return self._destination_blocks
        return [
            _heading("announcements", "Announcements"),
            _heading("outages", "🔥 Outages"),
            _paragraph("outage-bullet", ""),
            _heading("alerts", "Alerts"),
            _paragraph("alert-placeholder", ""),
            _heading("low", "😴 Low Urgency Paging Events"),
            _heading("previous", "Previous"),
            _paragraph("previous-placeholder", ""),
            _heading("actions", "Actions"),
        ]

    def append_blocks(self, page_id: str, **kwargs: Any) -> str:
        self.appended.append({"page_id": page_id, **kwargs})
        children = kwargs.get("children") or []
        if children:
            return f"appended-{len(self.appended)}"
        return kwargs["after_block_id"]

    def delete_block(self, block_id: str) -> None:
        self.deleted.append(block_id)

    def latest_page(self, data_source_id: str, **kwargs: Any) -> dict[str, str]:
        return {"id": "source-page"}

    def upsert_incident_page(
        self,
        data_source_id: str,
        *,
        incident_id: str,
        properties: dict[str, Any],
    ) -> dict[str, str]:
        self.upserted.append(
            {
                "data_source_id": data_source_id,
                "incident_id": incident_id,
                "properties": properties,
            }
        )
        return {"id": f"incident-{incident_id}"}

    def create_incidents_linked_view(self, **kwargs: Any) -> dict[str, str]:
        self.linked_views.append(kwargs)
        return {"id": "view"}


def _config(tmp_path: Path, *, mention_now_primary: bool = False) -> Config:
    return Config(
        pagerduty_token="pd",
        notion_token="notion",
        notion_data_source_id="target",
        notion_template_id="template",
        notion_incidents_data_source_id="incidents",
        pagerduty_primary_schedule_id="schedule",
        notion_alerts_heading="Alerts",
        notion_outages_heading="🔥 Outages",
        notion_low_urgency_heading="😴 Low Urgency Paging Events",
        notion_previous_actions_heading="Previous",
        notion_actions_heading="Actions",
        mention_now_primary=mention_now_primary,
        user_map_path=tmp_path / "user_map.json",
    )


def _write_user_map(tmp_path: Path, email: str, notion_user_id: str) -> None:
    (tmp_path / "user_map.json").write_text(
        '{"by_pagerduty_email": {"%s": "%s"}, "by_pagerduty_name": {}}'
        % (email, notion_user_id),
        encoding="utf-8",
    )


def test_run_creates_page_when_none_exists_for_date(tmp_path: Path) -> None:
    pagerduty = FakePagerDuty()
    notion = FakeNotion()

    result = HandoverService(
        _config(tmp_path),
        pagerduty=pagerduty,  # type: ignore[arg-type]
        notion=notion,  # type: ignore[arg-type]
        template_poll_interval=0,
    ).run(now=datetime(2026, 7, 27, 9, tzinfo=UTC))

    assert len(pagerduty.primary_calls) == 1
    assert result.created is True
    assert result.incident_count == 0
    assert result.copied_action_count == 2
    assert notion.created_pages == 1
    assert notion.created_handover_date == date(2026, 7, 27)
    assert notion.created_by_user_id is None
    assert notion.now_primary_user_id is None
    assert notion.templates_applied == 1
    assert notion.deleted == ["alert-placeholder", "previous-placeholder"]
    assert len(notion.appended) == 2
    assert notion.appended[0]["children"][0]["type"] == "bulleted_list_item"
    assert notion.upserted == []
    assert notion.linked_views == []


def test_run_sets_created_by_from_current_oncall(tmp_path: Path) -> None:
    _write_user_map(tmp_path, "current@example.com", "notion-current")
    pagerduty = FakePagerDuty()
    notion = FakeNotion()

    HandoverService(
        _config(tmp_path),
        pagerduty=pagerduty,  # type: ignore[arg-type]
        notion=notion,  # type: ignore[arg-type]
        template_poll_interval=0,
    ).run(now=datetime(2026, 7, 27, 9, tzinfo=UTC))

    assert notion.created_by_user_id == "notion-current"
    assert notion.now_primary_user_id is None
    assert len(pagerduty.primary_calls) == 1
    assert pagerduty.primary_calls[0].isoformat() == "2026-07-27T10:00:00+01:00"


def test_run_sets_now_primary_from_monday_noon_oncall(tmp_path: Path) -> None:
    _write_user_map(tmp_path, "next@example.com", "notion-next")
    now = datetime(2026, 7, 27, 9, tzinfo=UTC)
    monday_noon = datetime.fromisoformat("2026-07-27T12:00:00+01:00")
    pagerduty = FakePagerDuty(
        oncall={
            "id": "PD1",
            "name": "Current Person",
            "email": "current@example.com",
        },
        oncall_by_at={
            monday_noon: {
                "id": "PD2",
                "name": "Next Person",
                "email": "next@example.com",
            }
        },
    )
    notion = FakeNotion()

    HandoverService(
        _config(tmp_path, mention_now_primary=True),
        pagerduty=pagerduty,  # type: ignore[arg-type]
        notion=notion,  # type: ignore[arg-type]
        template_poll_interval=0,
    ).run(now=now)

    assert notion.created_by_user_id is None
    assert notion.now_primary_user_id == "notion-next"
    assert len(pagerduty.primary_calls) == 2


def test_run_leaves_people_unset_when_mapping_missing(tmp_path: Path) -> None:
    (tmp_path / "user_map.json").write_text(
        '{"by_pagerduty_email": {}, "by_pagerduty_name": {}}',
        encoding="utf-8",
    )
    notion = FakeNotion()

    HandoverService(
        _config(tmp_path, mention_now_primary=True),
        pagerduty=FakePagerDuty(),  # type: ignore[arg-type]
        notion=notion,  # type: ignore[arg-type]
        template_poll_interval=0,
    ).run(now=datetime(2026, 7, 27, 9, tzinfo=UTC))

    assert notion.created_pages == 1
    assert notion.created_by_user_id is None
    assert notion.now_primary_user_id is None


def test_run_after_monday_noon_targets_following_week(tmp_path: Path) -> None:
    notion = FakeNotion()

    HandoverService(
        _config(tmp_path),
        pagerduty=FakePagerDuty(),  # type: ignore[arg-type]
        notion=notion,  # type: ignore[arg-type]
        template_poll_interval=0,
    ).run(now=datetime(2026, 7, 27, 11, 5, tzinfo=UTC))

    assert notion.created_handover_date == date(2026, 8, 3)


def test_run_upserts_incidents_and_creates_linked_view(tmp_path: Path) -> None:
    pagerduty = FakePagerDuty(
        [
            {
                "id": "P123",
                "title": "Alert exploded",
                "created_at": "2026-07-22T10:00:00Z",
                "resolved_at": "2026-07-22T11:12:00Z",
                "html_url": "https://example.test/P123",
            }
        ]
    )
    notion = FakeNotion()

    result = HandoverService(
        _config(tmp_path),
        pagerduty=pagerduty,  # type: ignore[arg-type]
        notion=notion,  # type: ignore[arg-type]
        template_poll_interval=0,
    ).run(now=datetime(2026, 7, 27, 9, tzinfo=UTC))

    assert result.created is True
    assert result.incident_count == 1
    assert len(notion.upserted) == 1
    assert notion.upserted[0]["incident_id"] == "P123"
    assert notion.upserted[0]["data_source_id"] == "incidents"
    assert (
        notion.upserted[0]["properties"]["Duration"]["rich_text"][0]["text"]["content"]
        == "1h 12m"
    )
    assert len(notion.linked_views) == 1
    assert notion.linked_views[0]["page_id"] == "destination"
    assert notion.linked_views[0]["after_block_id"] == "alerts"
    assert notion.linked_views[0]["data_source_id"] == "incidents"
    assert notion.linked_views[0]["since"].isoformat() == "2026-07-20T12:00:00+01:00"
    assert notion.linked_views[0]["until"].isoformat() == "2026-07-27T12:00:00+01:00"
    assert notion.linked_views[0]["title"] == "Alerts"
    assert notion.appended[0]["after_block_id"] == "outage-bullet"
    assert notion.appended[0]["children"][0]["type"] == "paragraph"
    assert "alerts" in notion.deleted


def test_run_updates_existing_page_without_recreating_view(tmp_path: Path) -> None:
    pagerduty = FakePagerDuty(
        [
            {
                "id": "P123",
                "title": "Alert exploded",
                "created_at": "2026-07-22T10:00:00Z",
                "resolved_at": "2026-07-22T11:12:00Z",
                "html_url": "https://example.test/P123",
            }
        ]
    )
    notion = FakeNotion(
        existing_page={
            "id": "existing",
            "url": "https://notion.test/existing",
        },
        destination_blocks=[
            _heading("alerts", "Alerts"),
            {
                "id": "alerts-view",
                "type": "child_database",
                "child_database": {"title": "Incidents"},
            },
            _heading("previous", "Previous"),
            _paragraph("stale-action", "Old copy"),
            _heading("actions", "Actions"),
        ],
    )

    result = HandoverService(
        _config(tmp_path),
        pagerduty=pagerduty,  # type: ignore[arg-type]
        notion=notion,  # type: ignore[arg-type]
        template_poll_interval=0,
    ).run(now=datetime(2026, 7, 27, 9, tzinfo=UTC))

    assert result.created is False
    assert result.page_url == "https://notion.test/existing"
    assert notion.created_pages == 0
    assert notion.templates_applied == 0
    assert len(notion.upserted) == 1
    assert notion.linked_views == []
    assert notion.deleted == ["stale-action"]
    assert len(notion.appended) == 1
    assert notion.appended[0]["after_block_id"] == "previous"
    assert result.copied_action_count == 2
    assert pagerduty.primary_calls == []


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
