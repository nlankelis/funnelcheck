"""Pure query construction, parsing and validation. No HTTP or file access."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import math
import re


METRIC = "FunnelCohortSessionCompletionRate"


class DataError(ValueError):
    """The input cannot safely be interpreted as this funnel's daily rates."""


@dataclass(frozen=True)
class FunnelQuery:
    universe_id: str
    funnel_name: str
    start: date
    end_exclusive: date
    step_ids: tuple[str, ...]

    def __post_init__(self):
        if not re.fullmatch(r"[1-9][0-9]*", self.universe_id):
            raise DataError("Universe ID must be a positive integer written as text.")
        if not self.funnel_name.strip():
            raise DataError("Funnel name cannot be empty.")
        if self.start >= self.end_exclusive:
            raise DataError("Start must be before the exclusive end date.")
        if not self.step_ids or any(
            not re.fullmatch(r"[1-9][0-9]*", step) for step in self.step_ids
        ):
            raise DataError("Provide the positive numeric step IDs returned by Roblox.")
        if len(set(self.step_ids)) != len(self.step_ids):
            raise DataError("Step IDs must be unique.")

    def payload(self) -> dict:
        return {
            "metric": METRIC,
            "granularity": "OneDay",
            "breakdown": ["FunnelStep"],
            "filter": [
                {"dimension": "FunnelName", "values": [self.funnel_name], "operation": "In"},
                {"dimension": "FunnelStep", "values": list(self.step_ids), "operation": "In"},
            ],
            "startTime": self.start.isoformat() + "T00:00:00Z",
            "endTime": self.end_exclusive.isoformat() + "T00:00:00Z",
        }


@dataclass(frozen=True)
class FunnelRow:
    step_id: str
    step_name: str
    cohort_date: date
    completion_rate: float
    status: str | None = None


def parse_rates(envelope: dict, query: FunnelQuery) -> list[FunnelRow]:
    """Flatten a completed API response without filling gaps or rounding rates.

    The response does not echo its metric or filters. The caller must retain the
    matching query: counts and rates must never be guessed from their values.
    """
    if not isinstance(envelope, dict) or envelope.get("done") is not True:
        raise DataError("Expected a completed query response.")
    if "error" in envelope:
        raise DataError("The query failed; it does not contain usable results.")
    response = envelope.get("response")
    if not isinstance(response, dict) or not isinstance(response.get("values"), list):
        raise DataError("Expected response.values to be a list.")

    rows = []
    seen = set()
    names = {}
    for series in response["values"]:
        if not isinstance(series, dict):
            raise DataError("Each series must be an object.")
        breakdowns = series.get("breakdowns")
        if (
            not isinstance(breakdowns, list)
            or len(breakdowns) != 1
            or not isinstance(breakdowns[0], dict)
            or breakdowns[0].get("dimension") != "FunnelStep"
        ):
            raise DataError("Expected only a FunnelStep breakdown; segmented data needs a different parser.")
        step = breakdowns[0].get("value")
        if not isinstance(step, str) or step not in query.step_ids:
            raise DataError("Response contains an unrequested or invalid step ID.")
        name = breakdowns[0].get("displayValue", step)
        if not isinstance(name, str) or not name.strip():
            raise DataError("Step labels must be non-empty strings.")
        if step in names and names[step] != name:
            raise DataError(f"Step {step} has conflicting labels.")
        names[step] = name
        points = series.get("dataPoints")
        if not isinstance(points, list):
            raise DataError(f"Step {step}: expected a dataPoints list.")
        for point in points:
            if not isinstance(point, dict):
                raise DataError(f"Step {step}: each data point must be an object.")
            raw_time = point.get("time")
            if not isinstance(raw_time, str):
                raise DataError(f"Step {step}: missing timestamp.")
            try:
                timestamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            except ValueError as exc:
                raise DataError(f"Step {step}: invalid timestamp.") from exc
            if timestamp.tzinfo is None:
                raise DataError(f"Step {step}: timestamp must include a timezone.")
            timestamp = timestamp.astimezone(timezone.utc)
            if timestamp.time() != time(0):
                raise DataError(f"Step {step}: expected a daily bucket at UTC midnight.")
            day = timestamp.date()
            if not query.start <= day < query.end_exclusive:
                raise DataError(f"Step {step}: date lies outside the requested window.")
            rate = point.get("value")
            # bool is a subclass of int in Python, but true is not a measured rate.
            if type(rate) not in (int, float) or not 0 <= rate <= 1 or not math.isfinite(rate):
                raise DataError(f"Step {step} on {day}: rate must be a finite number from 0 to 1.")
            status = point.get("status")
            if status is not None and (not isinstance(status, str) or not status.strip()):
                raise DataError(f"Step {step} on {day}: invalid data-point status.")
            key = (day, step)
            if key in seen:
                raise DataError(f"Duplicate date/step pair: {day}, step {step}.")
            seen.add(key)
            rows.append(FunnelRow(step, name, day, float(rate), status))
    return sorted(rows, key=lambda row: (row.cohort_date, int(row.step_id)))


def validation_notes(rows: list[FunnelRow], query: FunnelQuery) -> list[str]:
    """Report incomplete/suspicious cohorts; never silently repair the data."""
    notes = []
    by_day = {}
    for row in rows:
        by_day.setdefault(row.cohort_date, {})[row.step_id] = row
        if row.status not in (None, "Valid"):
            notes.append(f"{row.cohort_date}, step {row.step_id}: Roblox status {row.status}.")
    day = query.start
    while day < query.end_exclusive:
        points = by_day.get(day, {})
        missing = set(query.step_ids) - points.keys()
        if missing:
            notes.append(f"{day}: missing steps {', '.join(sorted(missing, key=int))}; missing is not zero.")
        if "1" in points:
            baseline = points["1"].completion_rate
            if baseline == 0:
                notes.append(f"{day}: no usable starting-cohort rate; do not interpret as 100% abandonment.")
            elif not math.isclose(baseline, 1, abs_tol=1e-6):
                notes.append(f"{day}: step 1 is not 100%; confirm the metric and cohort definition.")
        else:
            notes.append(f"{day}: step 1 is unavailable; starting-cohort checks cannot be performed.")
        ordered = sorted(points.values(), key=lambda row: int(row.step_id))
        for previous, current in zip(ordered, ordered[1:]):
            if current.completion_rate > previous.completion_rate + 1e-6:
                notes.append(f"{day}: cumulative rate increases from step {previous.step_id} to {current.step_id}.")
        day += timedelta(days=1)
    return notes
