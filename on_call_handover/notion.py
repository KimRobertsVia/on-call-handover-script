from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import requests

NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
PAGE_SIZE = 100

INCIDENT_VIEW_VISIBLE = ("Name", "Created", "Duration")
INCIDENT_VIEW_HIDDEN = (
    "URL",
    "Duration (minutes)",
    "Status",
    "Incident ID",
)
INCIDENT_VIEW_WIDTHS = {
    "Name": 520,
    "Created": 240,
    "Duration": 100,
}
DURATION_VIEW_NAME = "By duration"
CHRONOLOGICAL_VIEW_NAME = "Chronological"

logger = logging.getLogger(__name__)


class NotionClient:
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
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        self._property_ids_by_data_source: dict[str, dict[str, str]] = {}

    def people_by_email(self, data_source_ids: list[str]) -> dict[str, dict[str, str]]:
        people: dict[str, dict[str, str]] = {}
        for data_source_id in data_source_ids:
            for page in self.query_pages(data_source_id):
                for prop in (page.get("properties") or {}).values():
                    if prop.get("type") != "people":
                        continue
                    for person in prop.get("people") or []:
                        email = (
                            ((person.get("person") or {}).get("email") or "")
                            .strip()
                            .lower()
                        )
                        if email and person.get("id"):
                            people[email] = {
                                "id": person["id"],
                                "name": person.get("name") or person["id"],
                                "email": email,
                            }
        return people

    def query_pages(
        self,
        data_source_id: str,
        *,
        page_size: int = PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        return self.query_data_source(
            data_source_id,
            sorts=[{"property": "Date", "direction": "descending"}],
            page_size=page_size,
        )

    def query_data_source(
        self,
        data_source_id: str,
        *,
        filter: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        page_size: int = PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": page_size}
            if filter:
                body["filter"] = filter
            if sorts:
                body["sorts"] = sorts
            if cursor:
                body["start_cursor"] = cursor
            payload = self._request(
                "POST",
                f"/data_sources/{data_source_id}/query",
                json=body,
            )
            pages.extend(payload.get("results") or [])
            if not payload.get("has_more"):
                return pages
            cursor = payload.get("next_cursor")

    def latest_page(
        self,
        data_source_id: str,
        *,
        exclude_page_id: str | None = None,
    ) -> dict[str, Any] | None:
        payload = self._request(
            "POST",
            f"/data_sources/{data_source_id}/query",
            json={
                "sorts": [{"property": "Date", "direction": "descending"}],
                "page_size": 2 if exclude_page_id else 1,
            },
        )
        for page in payload.get("results") or []:
            if exclude_page_id and page.get("id") == exclude_page_id:
                continue
            return page
        return None

    def page_by_date(
        self,
        data_source_id: str,
        handover_date: date,
    ) -> dict[str, Any] | None:
        pages = self.query_data_source(
            data_source_id,
            filter={
                "property": "Date",
                "date": {"equals": handover_date.isoformat()},
            },
            sorts=[{"property": "Date", "direction": "descending"}],
            page_size=1,
        )
        return pages[0] if pages else None

    def create_page(
        self,
        *,
        data_source_id: str,
        title_property: str,
        title: str,
        handover_date: date,
        created_by_user_id: str | None,
        now_primary_user_id: str | None,
    ) -> dict[str, Any]:
        properties: dict[str, Any] = {
            title_property: {
                "title": [{"type": "text", "text": {"content": title}}],
            },
            "Date": {"date": {"start": handover_date.isoformat()}},
        }
        if created_by_user_id:
            properties["Created By"] = {"people": [{"id": created_by_user_id}]}
        if now_primary_user_id:
            properties["Now Primary"] = {"people": [{"id": now_primary_user_id}]}

        return self.create_data_source_page(data_source_id, properties)

    def create_data_source_page(
        self,
        data_source_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/pages",
            json={
                "parent": {
                    "type": "data_source_id",
                    "data_source_id": data_source_id,
                },
                "properties": properties,
            },
        )

    def update_page_properties(
        self,
        page_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/pages/{page_id}",
            json={"properties": properties},
        )

    def upsert_incident_page(
        self,
        data_source_id: str,
        *,
        incident_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self.query_data_source(
            data_source_id,
            filter={
                "property": "Incident ID",
                "rich_text": {"equals": incident_id},
            },
            page_size=1,
        )
        if existing:
            return self.update_page_properties(existing[0]["id"], properties)
        return self.create_data_source_page(data_source_id, properties)

    def property_ids(self, data_source_id: str) -> dict[str, str]:
        cached = self._property_ids_by_data_source.get(data_source_id)
        if cached is not None:
            return cached

        payload = self._request("GET", f"/data_sources/{data_source_id}")
        mapping = {
            name: prop["id"]
            for name, prop in (payload.get("properties") or {}).items()
            if prop.get("id")
        }
        self._property_ids_by_data_source[data_source_id] = mapping
        return mapping

    def create_incidents_linked_view(
        self,
        *,
        page_id: str,
        after_block_id: str,
        data_source_id: str,
        since: datetime,
        until: datetime,
        title: str,
    ) -> dict[str, Any]:
        properties_config = self._incident_view_properties(data_source_id)
        week_filter = {
            "and": [
                {
                    "property": "Created",
                    "date": {"on_or_after": since.isoformat()},
                },
                {
                    "property": "Created",
                    "date": {"before": until.isoformat()},
                },
            ]
        }
        duration_view = self._request(
            "POST",
            "/views",
            json={
                "data_source_id": data_source_id,
                "name": DURATION_VIEW_NAME,
                "type": "table",
                "filter": week_filter,
                "sorts": [
                    {
                        "property": "Duration (minutes)",
                        "direction": "descending",
                    }
                ],
                "configuration": {
                    "type": "table",
                    "wrap_cells": True,
                    "properties": properties_config,
                },
                "create_database": {
                    "parent": {"type": "page_id", "page_id": page_id},
                    "position": {
                        "type": "after_block",
                        "block_id": after_block_id,
                    },
                },
            },
        )
        linked_database_id = (duration_view.get("parent") or {}).get("database_id")
        if not linked_database_id:
            raise RuntimeError(
                "Linked incidents view did not return a parent database_id"
            )

        chronological_view = self._request(
            "POST",
            "/views",
            json={
                "database_id": linked_database_id,
                "data_source_id": data_source_id,
                "name": CHRONOLOGICAL_VIEW_NAME,
                "type": "table",
                "filter": week_filter,
                "sorts": [
                    {
                        "property": "Created",
                        "direction": "ascending",
                    }
                ],
                "configuration": {
                    "type": "table",
                    "wrap_cells": True,
                    "properties": properties_config,
                },
                "position": {"type": "end"},
            },
        )
        self.set_database_title(linked_database_id, title)
        return {
            "database_id": linked_database_id,
            "duration_view": duration_view,
            "chronological_view": chronological_view,
        }

    def set_database_title(self, database_id: str, title: str) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/databases/{database_id}",
            json={
                "title": [
                    {
                        "type": "text",
                        "text": {"content": title},
                    }
                ]
            },
        )

    def _incident_view_properties(
        self,
        data_source_id: str,
    ) -> list[dict[str, Any]]:
        property_ids = self.property_ids(data_source_id)
        properties_config: list[dict[str, Any]] = []
        for property_name in (*INCIDENT_VIEW_VISIBLE, *INCIDENT_VIEW_HIDDEN):
            property_id = property_ids.get(property_name)
            if not property_id:
                raise RuntimeError(
                    f"Incidents data source is missing property {property_name!r}"
                )
            entry: dict[str, Any] = {
                "property_id": property_id,
                "property_name": property_name,
                "visible": property_name in INCIDENT_VIEW_VISIBLE,
                "width": INCIDENT_VIEW_WIDTHS.get(property_name, 160),
            }
            if property_name == "Name":
                entry["wrap"] = True
            properties_config.append(entry)
        return properties_config

    def apply_template(
        self,
        page_id: str,
        *,
        template_id: str,
        timezone_name: str,
    ) -> None:
        self._request(
            "PATCH",
            f"/pages/{page_id}",
            json={
                "template": {
                    "type": "template_id",
                    "template_id": template_id,
                    "timezone": timezone_name,
                },
                "erase_content": True,
            },
        )

    def block_children(self, block_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": PAGE_SIZE}
            if cursor:
                params["start_cursor"] = cursor
            payload = self._request(
                "GET",
                f"/blocks/{block_id}/children",
                params=params,
            )
            blocks.extend(payload.get("results") or [])
            if not payload.get("has_more"):
                return blocks
            cursor = payload.get("next_cursor")

    def append_blocks(
        self,
        page_id: str,
        *,
        after_block_id: str,
        children: list[dict[str, Any]],
    ) -> str:
        after = after_block_id
        for start in range(0, len(children), PAGE_SIZE):
            payload = self._request(
                "PATCH",
                f"/blocks/{page_id}/children",
                timeout=60,
                json={
                    "children": children[start : start + PAGE_SIZE],
                    "position": {
                        "type": "after_block",
                        "after_block": {"id": after},
                    },
                },
            )
            results = payload.get("results") or []
            if results:
                after = results[-1]["id"]
        return after

    def delete_block(self, block_id: str) -> None:
        self._request("DELETE", f"/blocks/{block_id}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        response = self._session.request(
            method,
            f"{NOTION_BASE_URL}{path}",
            headers=self._headers,
            timeout=timeout or self._timeout,
            **kwargs,
        )
        if response.status_code >= 400:
            logger.error(
                "Notion request failed: %s %s returned %s",
                method,
                path,
                response.status_code,
            )
        response.raise_for_status()
        return response.json() if response.content else {}
