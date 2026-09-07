from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from on_call_handover.time_utils import alert_window, handover_monday

LONDON = ZoneInfo("Europe/London")


def test_monday_before_noon_targets_this_week() -> None:
    now = datetime(2026, 7, 27, 10, 20, tzinfo=LONDON)
    assert handover_monday(now, LONDON).isoformat() == "2026-07-27"


def test_monday_at_noon_targets_next_week() -> None:
    now = datetime(2026, 7, 27, 12, 0, tzinfo=LONDON)
    assert handover_monday(now, LONDON).isoformat() == "2026-08-03"


def test_monday_after_noon_targets_next_week() -> None:
    now = datetime(2026, 7, 27, 12, 5, tzinfo=LONDON)
    assert handover_monday(now, LONDON).isoformat() == "2026-08-03"


def test_sunday_targets_upcoming_monday() -> None:
    now = datetime(2026, 7, 26, 18, 0, tzinfo=LONDON)
    assert handover_monday(now, LONDON).isoformat() == "2026-07-27"


def test_tuesday_targets_following_monday() -> None:
    now = datetime(2026, 7, 28, 9, 0, tzinfo=LONDON)
    assert handover_monday(now, LONDON).isoformat() == "2026-08-03"


def test_winter_monday_noon_uses_gmt() -> None:
    now = datetime(2026, 1, 12, 12, 0, tzinfo=LONDON)
    assert now.utcoffset().total_seconds() == 0
    assert handover_monday(now, LONDON).isoformat() == "2026-01-19"


def test_bst_monday_noon_from_utc() -> None:
    now = datetime(2026, 7, 27, 11, 0, tzinfo=UTC)
    assert handover_monday(now, LONDON).isoformat() == "2026-08-03"


def test_alert_window_is_monday_noon_to_monday_noon() -> None:
    since, until = alert_window(datetime(2026, 7, 27).date(), LONDON)
    assert since.isoformat() == "2026-07-20T12:00:00+01:00"
    assert until.isoformat() == "2026-07-27T12:00:00+01:00"
