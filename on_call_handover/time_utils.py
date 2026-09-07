from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def handover_monday(now: datetime, timezone: ZoneInfo) -> date:
    """Return the Monday whose 12:00 local cutoff is next after ``now``.

    If ``now`` is already at or after that week's Monday 12:00, the following
    Monday is used. A Monday 11:20 run therefore targets this week's page; a
    Monday 12:05 run targets next week.
    """
    now_local = now.astimezone(timezone)
    week_monday = now_local.date() - timedelta(days=now_local.weekday())
    cutoff = datetime.combine(week_monday, time(12), tzinfo=timezone)
    if now_local < cutoff:
        return week_monday
    return week_monday + timedelta(days=7)


def alert_window(
    handover_monday: date,
    timezone: ZoneInfo,
) -> tuple[datetime, datetime]:
    until = datetime.combine(handover_monday, time(12), tzinfo=timezone)
    return until - timedelta(days=7), until
