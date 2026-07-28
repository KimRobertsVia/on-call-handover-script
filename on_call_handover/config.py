from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

DEFAULT_ALERTS_HEADING = "🚨 High Urgency Paging"
DEFAULT_PREVIOUS_ACTIONS_HEADING = "🌝 Previous actions"
DEFAULT_ACTIONS_HEADING = "🚀 Actions"


class ConfigError(ValueError):
    """Raised when handover configuration is incomplete or invalid."""


@dataclass(frozen=True)
class Config:
    pagerduty_token: str
    notion_token: str
    notion_data_source_id: str
    notion_template_id: str
    pagerduty_primary_schedule_id: str
    notion_alerts_heading: str = DEFAULT_ALERTS_HEADING
    notion_previous_actions_heading: str = DEFAULT_PREVIOUS_ACTIONS_HEADING
    notion_actions_heading: str = DEFAULT_ACTIONS_HEADING
    notion_title_property: str = "Title"
    notion_timezone: str = "Europe/London"
    mention_now_primary: bool = False
    user_map_path: Path = Path("user_map.json")

    @property
    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.notion_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(
                f"Unknown timezone in NOTION_TIMEZONE: {self.notion_timezone!r}"
            ) from exc

    @property
    def template_headings(self) -> tuple[str, str, str]:
        return (
            self.notion_alerts_heading,
            self.notion_previous_actions_heading,
            self.notion_actions_heading,
        )

    @classmethod
    def from_env(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        base_dir: Path | None = None,
        load_env_file: bool = True,
    ) -> Config:
        base_dir = base_dir or Path.cwd()
        if load_env_file:
            load_dotenv(base_dir / ".env")
        values = env if env is not None else os.environ

        required = {
            "PAGERDUTY_API_TOKEN": "pagerduty_token",
            "NOTION_API_TOKEN": "notion_token",
            "NOTION_DATA_SOURCE_ID": "notion_data_source_id",
            "NOTION_TEMPLATE_ID": "notion_template_id",
            "PAGERDUTY_PRIMARY_SCHEDULE_ID": "pagerduty_primary_schedule_id",
        }
        missing = [name for name in required if not values.get(name)]
        if missing:
            raise ConfigError(f"Missing required env vars: {', '.join(missing)}")

        kwargs = {field: values[name] for name, field in required.items()}
        return cls(
            **kwargs,
            notion_title_property=values.get("NOTION_TITLE_PROPERTY", "Title"),
            notion_timezone=values.get("NOTION_TIMEZONE", "Europe/London"),
            mention_now_primary=_is_truthy(values.get("MENTION_NOW_PRIMARY")),
            user_map_path=base_dir / "user_map.json",
        )


def _is_truthy(value: str | None) -> bool:
    return bool(value and value.lower() in {"1", "true", "yes"})
