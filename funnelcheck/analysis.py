"""Drop-off calculations for parsed daily session-cohort rates; no I/O."""

from dataclasses import dataclass
from datetime import date, timedelta
import math

from .funnel import FunnelQuery, FunnelRow


@dataclass(frozen=True)
class StepDropoff:
    cohort_date: date
    from_step: str
    to_step: str
    percentage_points: float | None
    relative_drop: float | None
    reason: str | None = None


def calculate_dropoffs(rows: list[FunnelRow], query: FunnelQuery) -> list[StepDropoff]:
    """Use rows from parse_rates with their matching query, without rounding.

    Return one result per requested adjacent pair per day, including unavailable
    results. None means unavailable; it is never replaced with a measured zero.
    This function assumes parse_rates already checked types, ranges and duplicates.
    """
    by_day = {}
    for row in rows:
        by_day.setdefault(row.cohort_date, {})[row.step_id] = row
    steps = sorted(query.step_ids, key=int)
    results = []
    day = query.start
    while day < query.end_exclusive:
        points = by_day.get(day, {})
        baseline = points.get("1")
        cohort_reason = None
        if baseline is None:
            cohort_reason = "Step 1 is missing; starting cohort cannot be checked."
        elif baseline.status not in (None, "Valid"):
            cohort_reason = f"Step 1 has Roblox status {baseline.status}."
        elif not math.isclose(baseline.completion_rate, 1, rel_tol=0, abs_tol=1e-6):
            cohort_reason = "Step 1 is not 100%; no usable starting-cohort baseline."
        else:
            observed = sorted(points.values(), key=lambda row: int(row.step_id))
            if any(b.completion_rate > a.completion_rate for a, b in zip(observed, observed[1:])):
                # Even a tiny increase is withheld, rather than rounded to zero.
                cohort_reason = "Cumulative rates increase; check this cohort before interpreting drop-off."

        for from_step, to_step in zip(steps, steps[1:]):
            previous = points.get(from_step)
            current = points.get(to_step)
            reason = cohort_reason
            if reason is None and int(to_step) != int(from_step) + 1:
                reason = "Step IDs are not consecutive; intermediate steps may be unselected."
            if reason is None and (previous is None or current is None):
                reason = "A step value is missing; this pair cannot be calculated."
            if reason is None and any(row.status not in (None, "Valid") for row in (previous, current)):
                reason = "A step has a Roblox status other than Valid; inspect the source rows."

            if reason is not None:
                results.append(StepDropoff(day, from_step, to_step, None, None, reason))
                continue

            difference = previous.completion_rate - current.completion_rate
            percentage_points = difference * 100
            if previous.completion_rate == 0:
                relative_drop = None
                reason = "Previous step is zero; relative drop is undefined."
            else:
                relative_drop = difference / previous.completion_rate
            results.append(StepDropoff(day, from_step, to_step, percentage_points, relative_drop, reason))
        day += timedelta(days=1)
    return results
