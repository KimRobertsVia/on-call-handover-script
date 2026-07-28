from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def next_monday(day: date) -> date:
    days_ahead = -day.weekday() % 7
    return day + timedelta(days=days_ahead)


def alert_window(
    handover_monday: date,
    timezone: ZoneInfo,
) -> tuple[datetime, datetime]:
    until = datetime.combine(handover_monday, time(12), tzinfo=timezone)
    return until - timedelta(days=7), until
