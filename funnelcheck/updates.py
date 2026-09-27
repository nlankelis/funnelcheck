"""Reported update timing, separate from measurements and causal claims."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Literal
from zoneinfo import ZoneInfo

from .funnel import DataError, FunnelQuery


@dataclass(frozen=True)
class RecordedUpdate:
    name: str
    local_time: str
    time_zone: Literal["Europe/London", "UTC"]
    approximate: bool


@dataclass(frozen=True)
class CohortTiming:
    cohort_date: date
    phase: Literal["before", "transition", "after"]


@dataclass(frozen=True)
class SuggestedComparison:
    before: date
    after: date


@dataclass(frozen=True)
class UpdateContext:
    update: RecordedUpdate
    occurred_at_utc: datetime
    cohorts: list[CohortTiming]
    suggested_comparison: SuggestedComparison | None
    notes: list[str]


def update_in_utc(update: RecordedUpdate) -> datetime:
    """Resolve a wall-clock minute; never guess during a DST gap or overlap."""
    if update.time_zone not in ("Europe/London", "UTC"):
        raise DataError("Choose UK time (Europe/London) or UTC.")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}", update.local_time) is None:
        raise DataError("Use a local update time in YYYY-MM-DDTHH:MM format.")
    try:
        local = datetime.fromisoformat(update.local_time)
    except ValueError as exc:
        raise DataError("The update date or time is invalid.") from exc
    # Leave room for conversion and the end of the daily bucket.
    if not 1900 <= local.year <= 9998:
        raise DataError("Use an update year between 1900 and 9998.")
    zone = ZoneInfo(update.time_zone)
    candidates = set()
    for fold in (0, 1):
        utc = local.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == local:
            candidates.add(utc)
    if not candidates:
        raise DataError("This local time does not exist because the clocks moved forward. Enter the time in UTC instead.")
    if len(candidates) > 1:
        raise DataError("This local time occurs twice when the clocks move back. Enter the time in UTC to identify which one.")
    return candidates.pop()


def build_update_context(
    update: RecordedUpdate, query: FunnelQuery,
    comparison: tuple[date, date] | None = None,
) -> UpdateContext:
    instant = update_in_utc(update)
    cohorts = []
    day = query.start
    while day < query.end_exclusive:
        start = datetime.combine(day, time.min, timezone.utc)
        end = start + timedelta(days=1)
        # Half-open days: a deployment at midnight starts an after day.
        phase = "before" if end <= instant else "after" if start >= instant else "transition"
        cohorts.append(CohortTiming(day, phase))
        day += timedelta(days=1)
    before = [item.cohort_date for item in cohorts if item.phase == "before"]
    after = [item.cohort_date for item in cohorts if item.phase == "after"]
    suggestion = SuggestedComparison(before[-1], after[0]) if before and after else None
    notes = [
        "Labels describe UTC cohort-entry days relative to the reported deployment, not verified exposure to a game version.",
        "A transition day includes time before and after deployment; daily rates cannot separate those periods.",
        "An update marker provides context, not proof of causation. The comparison still uses individual daily rates.",
    ]
    if update.approximate:
        notes.append("The deployment time is approximate. Labels use that estimate; no uncertainty range was supplied.")
    if suggestion is None:
        notes.append("This file does not span both a full before day and a full after day. No surrounding-day comparison is suggested.")
    if comparison is not None:
        phases = {item.cohort_date: item.phase for item in cohorts}
        if phases.get(comparison[0]) != "before" or phases.get(comparison[1]) != "after":
            notes.append("The selected comparison does not pair a full before day with a full after day. It remains a descriptive date comparison.")
    return UpdateContext(update, instant, cohorts, suggestion, notes)
