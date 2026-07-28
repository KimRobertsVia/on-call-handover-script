from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

HEADING_TYPES = {"heading_1", "heading_2", "heading_3"}
COPYABLE_BLOCK_TYPES = {
    "to_do",
    "bulleted_list_item",
    "numbered_list_item",
    "paragraph",
    "toggle",
    "quote",
    "callout",
}


def rich_text_plain(rich_text: list[dict[str, Any]] | None) -> str:
    return "".join(part.get("plain_text", "") for part in rich_text or [])


def block_plain_text(block: dict[str, Any]) -> str:
    block_type = block.get("type", "")
    return rich_text_plain((block.get(block_type) or {}).get("rich_text"))


def find_heading_id(
    blocks: list[dict[str, Any]],
    heading_text: str,
) -> str | None:
    for block in blocks:
        block_type = block.get("type")
        if block_type in HEADING_TYPES and block_plain_text(block) == heading_text:
            return block["id"]
    return None


def section_after_heading(
    blocks: list[dict[str, Any]],
    heading_id: str,
) -> list[dict[str, Any]]:
    section: list[dict[str, Any]] = []
    started = False
    for block in blocks:
        if block["id"] == heading_id:
            started = True
            continue
        if started and block.get("type") in HEADING_TYPES:
            break
        if started:
            section.append(block)
    return section


def section_by_heading(
    blocks: list[dict[str, Any]],
    heading_text: str,
) -> list[dict[str, Any]]:
    heading_id = find_heading_id(blocks, heading_text)
    return section_after_heading(blocks, heading_id) if heading_id else []


def is_empty_placeholder(block: dict[str, Any]) -> bool:
    if block.get("type") not in {"bulleted_list_item", "to_do", "paragraph"}:
        return False
    return not block_plain_text(block).strip() and not block.get("has_children")


def clone_rich_text(
    rich_text: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    cloned: list[dict[str, Any]] = []
    for part in rich_text or []:
        part_type = part.get("type")
        if part_type == "text":
            cloned.append(_clone_text(part))
        elif part_type == "mention":
            cloned_part = _clone_mention(part)
            if cloned_part:
                cloned.append(cloned_part)
        elif part_type == "equation":
            expression = (part.get("equation") or {}).get("expression")
            if expression:
                cloned.append(
                    {"type": "equation", "equation": {"expression": expression}}
                )
        elif part.get("plain_text"):
            cloned.append(_plain_text(part["plain_text"]))
    return cloned


def clone_block(
    block: dict[str, Any],
    children_for: Callable[[str], list[dict[str, Any]]],
) -> dict[str, Any] | None:
    if is_empty_placeholder(block):
        return None

    block_type = block.get("type")
    if block_type not in COPYABLE_BLOCK_TYPES:
        logger.warning("Skipping unsupported block type: %s", block_type)
        return None

    source = block.get(block_type) or {}
    body: dict[str, Any] = {
        "rich_text": clone_rich_text(source.get("rich_text")),
        "color": source.get("color", "default"),
    }
    if block_type == "to_do":
        body["checked"] = bool(source.get("checked"))
    if block_type == "callout" and source.get("icon"):
        body["icon"] = source["icon"]

    if block.get("has_children"):
        children = [
            cloned
            for child in children_for(block["id"])
            if (cloned := clone_block(child, children_for)) is not None
        ]
        if children:
            body["children"] = children

    return {"object": "block", "type": block_type, block_type: body}


def condense_incident_title(title: str, max_length: int = 100) -> str:
    text = " ".join(title.split())
    alert_name = ""
    detail = text

    if text.startswith("[") and "]" in text:
        bracket, _, detail = text[1:].partition("]")
        parts = [part.strip() for part in bracket.split("|") if part.strip()]
        alert_name = parts[-1] if parts else ""
        detail = detail.strip()
    if " - " in detail:
        detail = detail.rsplit(" - ", 1)[-1].strip()

    condensed = " — ".join(part for part in (alert_name, detail) if part)
    if len(condensed) > max_length:
        condensed = condensed[: max_length - 1].rstrip() + "…"
    return condensed or "(untitled)"


def incident_duration(
    incident: dict[str, Any],
    *,
    now: datetime | None = None,
) -> str | None:
    created_at = incident.get("created_at")
    if not created_at:
        return None

    start = _parse_datetime(created_at)
    end = (
        _parse_datetime(incident["resolved_at"])
        if incident.get("resolved_at")
        else now or datetime.now(UTC)
    )
    total_seconds = max(0, int((end - start).total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return "<1m" if total_seconds else "0m"


def incident_bullet(
    incident: dict[str, Any],
    timezone: ZoneInfo,
) -> dict[str, Any]:
    title = incident.get("title") or incident.get("summary") or "(untitled)"
    rich_text: list[dict[str, Any]] = []
    if incident.get("created_at"):
        created = _parse_datetime(incident["created_at"]).astimezone(timezone)
        rich_text.extend(
            [
                {
                    "type": "mention",
                    "mention": {
                        "type": "date",
                        "date": {"start": created.isoformat()},
                    },
                },
                _plain_text(" - "),
            ]
        )

    title_text: dict[str, Any] = {"content": condense_incident_title(title)}
    if incident.get("html_url"):
        title_text["link"] = {"url": incident["html_url"]}
    rich_text.append({"type": "text", "text": title_text})

    duration = incident_duration(incident)
    if duration:
        rich_text.append(_plain_text(f" ({duration})"))
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text},
    }


def no_incidents_bullet() -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [_plain_text("No high-urgency incidents in the past week.")]
        },
    }


def _clone_text(part: dict[str, Any]) -> dict[str, Any]:
    source = part.get("text") or {}
    text: dict[str, Any] = {"content": source.get("content", "")}
    if source.get("link"):
        text["link"] = source["link"]
    cloned: dict[str, Any] = {"type": "text", "text": text}
    if part.get("annotations"):
        cloned["annotations"] = {
            key: part["annotations"][key]
            for key in (
                "bold",
                "italic",
                "strikethrough",
                "underline",
                "code",
                "color",
            )
            if key in part["annotations"]
        }
    return cloned


def _clone_mention(part: dict[str, Any]) -> dict[str, Any] | None:
    mention = part.get("mention") or {}
    if mention.get("type") == "user":
        user_id = (mention.get("user") or {}).get("id")
        if user_id:
            return {
                "type": "mention",
                "mention": {"type": "user", "user": {"id": user_id}},
            }
    elif mention.get("type") == "date":
        source = mention.get("date") or {}
        return {
            "type": "mention",
            "mention": {
                "type": "date",
                "date": {
                    key: source[key]
                    for key in ("start", "end", "time_zone")
                    if source.get(key) is not None
                },
            },
        }
    return _plain_text(part["plain_text"]) if part.get("plain_text") else None


def _plain_text(content: str) -> dict[str, Any]:
    return {"type": "text", "text": {"content": content}}


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
