from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as datetime_time
from typing import Any

from .blocks import (
    child_databases_between_headings,
    clone_block,
    empty_paragraph,
    find_heading_id,
    incident_notion_properties,
    no_incidents_bullet,
    section_after_heading,
    section_by_heading,
    section_has_child_database,
)
from .config import Config
from .notion import NotionClient
from .pagerduty import PagerDutyClient
from .time_utils import alert_window, handover_monday
from .users import load_user_map, mapped_notion_user_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HandoverResult:
    page_url: str
    incident_count: int
    copied_action_count: int
    created: bool


class HandoverService:
    def __init__(
        self,
        config: Config,
        *,
        pagerduty: PagerDutyClient | None = None,
        notion: NotionClient | None = None,
        template_timeout: float = 30,
        template_poll_interval: float = 1,
    ) -> None:
        self._config = config
        self._pagerduty = pagerduty or PagerDutyClient(config.pagerduty_token)
        self._notion = notion or NotionClient(config.notion_token)
        self._template_timeout = template_timeout
        self._template_poll_interval = template_poll_interval

    def run(self, *, now: datetime | None = None) -> HandoverResult:
        timezone = self._config.timezone
        now_local = now.astimezone(timezone) if now else datetime.now(timezone)
        handover_date = handover_monday(now_local, timezone)
        since, until = alert_window(handover_date, timezone)

        logger.info(
            "Fetching high-urgency incidents for handover date %s",
            handover_date.isoformat(),
        )
        incidents = self._pagerduty.high_urgency_incidents(since, until)
        logger.info("Found %d high-urgency incidents", len(incidents))

        existing = self._notion.page_by_date(
            self._config.notion_data_source_id,
            handover_date,
        )
        if existing:
            page_id = existing["id"]
            page_url = existing.get("url") or page_id
            created = False
            logger.info("Updating existing handover page %s", page_id)
            blocks = self._notion.block_children(page_id)
        else:
            primary_user_id = self._resolve_primary_user_id(handover_date)
            actor = self._notion.acting_user()
            title = f"On-call Handover {handover_date.isoformat()}"
            page = self._notion.create_page(
                data_source_id=self._config.notion_data_source_id,
                title_property=self._config.notion_title_property,
                title=title,
                handover_date=handover_date,
                created_by_user_id=actor["id"],
                now_primary_user_id=primary_user_id,
            )
            page_id = page["id"]
            page_url = page.get("url") or page_id
            created = True
            logger.info("Created handover page %s", page_id)
            self._notion.apply_template(
                page_id,
                template_id=self._config.notion_template_id,
                timezone_name=self._config.notion_timezone,
            )
            blocks = self._wait_for_template(page_id)

        self._populate_incidents(
            page_id,
            blocks,
            incidents,
            since=since,
            until=until,
        )
        copied_count = self._copy_previous_actions(
            destination_page_id=page_id,
            destination_blocks=self._notion.block_children(page_id),
        )
        return HandoverResult(page_url, len(incidents), copied_count, created)

    def _resolve_primary_user_id(self, handover_date: date) -> str | None:
        if not self._config.mention_now_primary:
            logger.info("Now Primary is disabled")
            return None

        timezone = self._config.timezone
        shift_start = datetime.combine(
            handover_date,
            datetime_time(12),
            tzinfo=timezone,
        )
        pagerduty_user = self._pagerduty.primary_oncall(
            schedule_id=self._config.pagerduty_primary_schedule_id,
            at=shift_start,
        )
        user_map = load_user_map(self._config.user_map_path)
        user_id = mapped_notion_user_id(
            user_map,
            pagerduty_email=pagerduty_user["email"],
            pagerduty_name=pagerduty_user["name"],
        )
        if user_id:
            logger.info("Resolved Now Primary from user map")
            return user_id

        people = self._notion.people_by_email([self._config.notion_data_source_id])
        person = people.get(pagerduty_user["email"].lower())
        if person:
            logger.info("Resolved Now Primary from existing handover pages")
            return person["id"]
        raise RuntimeError(
            "No Notion user mapping for the PagerDuty primary. "
            "Add their PagerDuty email or name to user_map.json."
        )

    def _wait_for_template(self, page_id: str) -> list[dict[str, Any]]:
        deadline = time.monotonic() + self._template_timeout
        while True:
            blocks = self._notion.block_children(page_id)
            missing = [
                heading
                for heading in self._config.template_headings
                if not find_heading_id(blocks, heading)
            ]
            if not missing:
                return blocks
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Timed out waiting for template headings on page "
                    f"{page_id}: {', '.join(repr(heading) for heading in missing)}"
                )
            time.sleep(self._template_poll_interval)

    def _populate_incidents(
        self,
        page_id: str,
        blocks: list[dict[str, Any]],
        incidents: list[dict[str, Any]],
        *,
        since: datetime,
        until: datetime,
    ) -> None:
        heading_id = find_heading_id(blocks, self._config.notion_alerts_heading)
        linked_databases = child_databases_between_headings(
            blocks,
            self._config.notion_outages_heading,
            self._config.notion_low_urgency_heading,
        )
        has_view = bool(linked_databases) or (
            bool(heading_id)
            and section_has_child_database(section_after_heading(blocks, heading_id))
        )

        for incident in incidents:
            incident_id = incident.get("id")
            if not incident_id:
                logger.warning(
                    "Skipping incident without id: %s",
                    incident.get("title"),
                )
                continue
            self._notion.upsert_incident_page(
                self._config.notion_incidents_data_source_id,
                incident_id=str(incident_id),
                properties=incident_notion_properties(incident),
            )

        if not incidents:
            if has_view:
                logger.info(
                    "No incidents; leaving existing linked view under %s",
                    self._config.notion_alerts_heading,
                )
                return
            if not heading_id:
                raise RuntimeError(
                    f"Missing heading {self._config.notion_alerts_heading!r}"
                )
            self._clear_section(blocks, heading_id)
            self._notion.append_blocks(
                page_id,
                after_block_id=heading_id,
                children=[no_incidents_bullet()],
            )
            return

        if has_view:
            logger.info(
                "Upserted %d incidents; existing linked view will refresh",
                len(incidents),
            )
            return

        if not heading_id:
            raise RuntimeError(
                f"Missing heading {self._config.notion_alerts_heading!r}"
            )

        self._clear_section(blocks, heading_id)

        # Spacer must be inserted before the alerts heading (after Outages
        # content). Positioning a linked DB after a just-created block is
        # unreliable and can append it at the end of the page instead.
        outages_section = section_by_heading(
            blocks,
            self._config.notion_outages_heading,
        )
        spacer_after_id = (
            outages_section[-1]["id"]
            if outages_section
            else find_heading_id(blocks, self._config.notion_outages_heading)
        )
        if not spacer_after_id:
            raise RuntimeError(
                f"Missing heading {self._config.notion_outages_heading!r}"
            )
        self._notion.append_blocks(
            page_id,
            after_block_id=spacer_after_id,
            children=[empty_paragraph()],
        )
        self._notion.create_incidents_linked_view(
            page_id=page_id,
            after_block_id=heading_id,
            data_source_id=self._config.notion_incidents_data_source_id,
            since=since,
            until=until,
            title=self._config.notion_alerts_heading,
        )
        # Linked DBs always show a title; remove the heading to avoid duplicates.
        self._notion.delete_block(heading_id)
        logger.info(
            "Upserted %d incidents and added duration + chronological views as %s",
            len(incidents),
            self._config.notion_alerts_heading,
        )

    def _copy_previous_actions(
        self,
        *,
        destination_page_id: str,
        destination_blocks: list[dict[str, Any]],
    ) -> int:
        source_page = self._notion.latest_page(
            self._config.notion_data_source_id,
            exclude_page_id=destination_page_id,
        )
        if not source_page:
            logger.warning("No previous handover page found; skipping actions")
            return 0

        source_blocks = self._notion.block_children(source_page["id"])
        sections = (
            section_by_heading(
                source_blocks,
                self._config.notion_previous_actions_heading,
            ),
            section_by_heading(
                source_blocks,
                self._config.notion_actions_heading,
            ),
        )
        copied = [
            cloned
            for section in sections
            for block in section
            if (cloned := clone_block(block, self._notion.block_children)) is not None
        ]

        heading_id = find_heading_id(
            destination_blocks,
            self._config.notion_previous_actions_heading,
        )
        if not heading_id:
            raise RuntimeError(
                "Destination page is missing heading "
                f"{self._config.notion_previous_actions_heading!r}"
            )
        self._clear_section(destination_blocks, heading_id)
        self._notion.append_blocks(
            destination_page_id,
            after_block_id=heading_id,
            children=copied,
        )
        logger.info("Replaced previous actions with %d blocks", len(copied))
        return len(copied)

    def _clear_section(
        self,
        blocks: list[dict[str, Any]],
        heading_id: str,
    ) -> None:
        for block in section_after_heading(blocks, heading_id):
            self._notion.delete_block(block["id"])
