from __future__ import annotations

import logging
from datetime import date
from typing import Any

import requests

NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
PAGE_SIZE = 100

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

    def acting_user(self) -> dict[str, str]:
        user = self._request("GET", "/users/me")
        if user.get("type") == "person":
            return {"id": user["id"], "name": user.get("name") or user["id"]}

        owner = (user.get("bot") or {}).get("owner") or {}
        if owner.get("type") == "user":
            owner_user = owner.get("user") or {}
            if owner_user.get("id"):
                return {
                    "id": owner_user["id"],
                    "name": owner_user.get("name") or owner_user["id"],
                }
        raise RuntimeError(
            "Could not resolve a Notion person for Created By from users/me"
        )

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
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {
                "sorts": [{"property": "Date", "direction": "descending"}],
                "page_size": page_size,
            }
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

    def create_page(
        self,
        *,
        data_source_id: str,
        title_property: str,
        title: str,
        handover_date: date,
        created_by_user_id: str,
        now_primary_user_id: str | None,
    ) -> dict[str, Any]:
        properties: dict[str, Any] = {
            title_property: {
                "title": [{"type": "text", "text": {"content": title}}],
            },
            "Date": {"date": {"start": handover_date.isoformat()}},
            "Created By": {"people": [{"id": created_by_user_id}]},
        }
        if now_primary_user_id:
            properties["Now Primary"] = {"people": [{"id": now_primary_user_id}]}

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
    ) -> None:
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
