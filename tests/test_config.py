from pathlib import Path

import pytest

from on_call_handover.config import Config, ConfigError

REQUIRED_ENV = {
    "PAGERDUTY_API_TOKEN": "pd-token",
    "NOTION_API_TOKEN": "notion-token",
    "NOTION_DATA_SOURCE_ID": "target",
    "NOTION_TEMPLATE_ID": "template",
    "NOTION_INCIDENTS_DATA_SOURCE_ID": "incidents",
    "PAGERDUTY_PRIMARY_SCHEDULE_ID": "schedule",
}


def test_config_loads_defaults_and_user_map_path(tmp_path: Path) -> None:
    config = Config.from_env(
        env=REQUIRED_ENV,
        base_dir=tmp_path,
        load_env_file=False,
    )

    assert config.notion_timezone == "Europe/London"
    assert config.mention_now_primary is False
    assert config.template_headings == (
        "🚨 High Urgency Paging",
        "🌝 Previous actions",
        "🚀 Actions",
    )
    assert config.user_map_path == tmp_path / "user_map.json"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_config_accepts_truthy_primary_flag(tmp_path: Path, value: str) -> None:
    config = Config.from_env(
        env={**REQUIRED_ENV, "MENTION_NOW_PRIMARY": value},
        base_dir=tmp_path,
        load_env_file=False,
    )

    assert config.mention_now_primary is True


def test_config_reports_all_missing_values(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="PAGERDUTY_API_TOKEN.*NOTION_API_TOKEN"):
        Config.from_env(env={}, base_dir=tmp_path, load_env_file=False)
