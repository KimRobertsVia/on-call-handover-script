from __future__ import annotations

import logging
from pathlib import Path

import requests

from .config import Config, ConfigError
from .service import HandoverService

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    project_dir = Path(__file__).resolve().parent.parent
    try:
        config = Config.from_env(base_dir=project_dir)
        result = HandoverService(config).run()
    except (ConfigError, requests.RequestException, RuntimeError, TimeoutError) as exc:
        logger.error("Handover creation failed: %s", exc)
        return 1

    logger.info(
        "Created handover with %d incidents and %d copied actions: %s",
        result.incident_count,
        result.copied_action_count,
        result.page_url,
    )
    return 0
