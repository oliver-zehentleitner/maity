"""A jour fixe series' schedule (docs/api.md §20.1): its validation and the slots it
describes, on the wall clock of its time zone. A schedule is the series' `config` with its
`enabled` flag: `recurrence`, `time`, `timezone` and the three windows.

A `time` that falls into a DST gap opens at the first minute after the gap; one that
occurs twice opens at its first occurrence. A month without the `month_day` uses its
last day.
"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
FREQS = ("daily", "weekly", "monthly")
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "recurrence": None,
    "time": None,
    "timezone": None,
    "answer_window_minutes": 120,
    "step_window_minutes": 120,
    "report_window_hours": 12,
}
WINDOWS = {
    "answer_window_minutes": (30, 1440),
    "step_window_minutes": (30, 1440),
    "report_window_hours": (1, 72),
}
TIME = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")


def filled(given: dict[str, Any]) -> dict[str, Any]:
    """A schedule as stored: what was given over the defaults."""
    return {**DEFAULTS, **given}


def errors(policy: dict[str, Any], key: str = "") -> dict[str, str]:
    """`details.fields` for an invalid schedule, each field under `key`."""
    found: dict[str, str] = {}
    if not isinstance(policy.get("enabled"), bool):
        found[key + "enabled"] = "not_a_boolean"
    zone = policy.get("timezone")
    if zone is not None:
        try:
            ZoneInfo(str(zone))
        except (ZoneInfoNotFoundError, ValueError):
            found[key + "timezone"] = "unknown_timezone"
    if policy.get("enabled") is True:
        if policy.get("time") is None:
            found[key + "time"] = "required"
        if zone is None:
            found[key + "timezone"] = "required"
        if policy.get("recurrence") is None:
            found[key + "recurrence"] = "required"
    if policy.get("time") is not None and not TIME.fullmatch(str(policy["time"])):
        found[key + "time"] = "format"
    for name, (low, high) in WINDOWS.items():
        value = policy.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            found[key + name] = "out_of_range"
    recurrence = policy.get("recurrence")
    if recurrence is not None:
        found.update(_recurrence_errors(recurrence, key + "recurrence."))
    return found


def _recurrence_errors(rule: Any, key: str) -> dict[str, str]:
    if not isinstance(rule, dict):
        return {key.rstrip("."): "not_an_object"}
    found: dict[str, str] = {}
    freq = rule.get("freq")
    if freq not in FREQS:
        return {key + "freq": "unknown"}
    interval = rule.get("interval", 1)
    high = 8 if freq == "weekly" else 1
    if not isinstance(interval, int) or isinstance(interval, bool) or not 1 <= interval <= high:
        found[key + "interval"] = "out_of_range"
    weekdays = rule.get("weekdays")
    if freq == "weekly":
        if not weekdays:
            found[key + "weekdays"] = "required"
        elif not isinstance(weekdays, list) or any(d not in WEEKDAYS for d in weekdays):
            found[key + "weekdays"] = "unknown"
    elif weekdays is not None:
        found[key + "weekdays"] = "not_for_freq"
    day, nth = rule.get("month_day"), rule.get("month_weekday")
    if freq == "monthly":
        if (day is None) == (nth is None):
            found[key + "month_day"] = "one_of"
        elif day is not None and (not isinstance(day, int) or not 1 <= day <= 31):
            found[key + "month_day"] = "out_of_range"
        elif nth is not None and not _nth_ok(nth):
            found[key + "month_weekday"] = "invalid"
    elif day is not None or nth is not None:
        found[key + ("month_day" if day is not None else "month_weekday")] = "not_for_freq"
    return found


def _nth_ok(nth: Any) -> bool:
    return (
        isinstance(nth, dict)
        and nth.get("ordinal") in (1, 2, 3, 4, -1)
        and nth.get("weekday") in WEEKDAYS
    )


# --- the series -------------------------------------------------------------------------------


def _on_wall_clock(day: date, at: time, zone: ZoneInfo) -> datetime:
    """`day` at `at` in `zone`, as UTC: a time in a DST gap moves to the first minute
    after it; a time that occurs twice is its first occurrence (`fold=0`)."""
    local = datetime.combine(day, at, tzinfo=zone)
    back = local.astimezone(UTC).astimezone(zone)
    if back.replace(tzinfo=None) != local.replace(tzinfo=None):  # it does not exist
        probe = local.replace(tzinfo=None)
        while True:
            probe += timedelta(minutes=1)
            candidate = probe.replace(tzinfo=zone)
            if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == probe:
                return candidate.astimezone(UTC)
    return local.astimezone(UTC)


def _month_day(year: int, month: int, rule: dict[str, Any]) -> date:
    last = calendar.monthrange(year, month)[1]
    if rule.get("month_day") is not None:
        return date(year, month, min(int(rule["month_day"]), last))
    nth = rule["month_weekday"]
    weekday = WEEKDAYS.index(nth["weekday"])
    days = [d for d in range(1, last + 1) if date(year, month, d).weekday() == weekday]
    return date(year, month, days[-1] if nth["ordinal"] == -1 else days[nth["ordinal"] - 1])


def _days(policy: dict[str, Any], start: date, anchor: date) -> Any:
    """The days of the series from `start` on; `anchor` is the day the week count of an
    `interval` starts from (the first occurrence after the field was last set)."""
    rule = policy["recurrence"]
    freq = rule["freq"]
    if freq == "daily":
        day = start
        while True:
            yield day
            day += timedelta(days=1)
    elif freq == "weekly":
        interval = int(rule.get("interval", 1))
        wanted = {WEEKDAYS.index(d) for d in rule["weekdays"]}
        anchor_week = anchor - timedelta(days=anchor.weekday())
        day = start
        while True:
            week = (day - timedelta(days=day.weekday()) - anchor_week).days // 7
            if day.weekday() in wanted and week % interval == 0:
                yield day
            day += timedelta(days=1)
    else:
        year, month = start.year, start.month
        while True:
            day = _month_day(year, month, rule)
            if day >= start:
                yield day
            month += 1
            if month > 12:
                year, month = year + 1, 1


def slots_between(
    policy: dict[str, Any], after: datetime, until: datetime, anchor: date
) -> list[datetime]:
    """Every slot of the series in (`after`, `until`], in UTC."""
    zone = ZoneInfo(policy["timezone"])
    at = time.fromisoformat(policy["time"])
    start = (after.astimezone(zone) - timedelta(days=1)).date()
    found = []
    for day in _days(policy, start, anchor):
        slot = _on_wall_clock(day, at, zone)
        if slot > until:
            break
        if slot > after:
            found.append(slot)
    return found


def next_slot(policy: dict[str, Any], after: datetime, anchor: date) -> datetime | None:
    """The first slot after `after`, within a year; None when there is none."""
    if not policy.get("enabled") or policy.get("recurrence") is None:
        return None
    found = slots_between(policy, after, after + timedelta(days=366), anchor)
    return found[0] if found else None
