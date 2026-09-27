"""Descriptive comparisons between two daily cohorts; no pooling or causality."""

from dataclasses import dataclass
from datetime import date

from .analysis import cohort_issue
from .funnel import DataError, FunnelQuery, FunnelRow


@dataclass(frozen=True)
class StepComparison:
    step_id: str
    step_name: str
    before_date: date
    after_date: date
    before_rate: float | None
    after_rate: float | None
    change_pp: float | None
    reason: str | None = None


def validate_comparison_queries(
    before_query: FunnelQuery, after_query: FunnelQuery,
    before_date: date, after_date: date,
) -> None:
    """Check metadata and dates before fetching or comparing any values.

    FunnelQuery fixes metric, OneDay granularity, FunnelStep breakdown and the
    two supported filters. Comparing universe, exact funnel name and step IDs
    therefore covers all currently variable query settings except the date window.
    If additional filters/metrics are introduced, extend this check as well.
    """
    if before_query.universe_id != after_query.universe_id:
        raise DataError("Cannot compare different experiences (universe IDs).")
    if before_query.funnel_name != after_query.funnel_name:
        raise DataError("Cannot compare different funnel names or versions.")
    if set(before_query.step_ids) != set(after_query.step_ids):
        raise DataError("Cannot compare different requested step sets.")
    if before_date >= after_date:
        raise DataError("Comparison requires the before date to be earlier than the after date.")
    for label, query, day in (
        ("Before", before_query, before_date), ("After", after_query, after_date),
    ):
        if not query.start <= day < query.end_exclusive:
            raise DataError(f"{label} date lies outside its query window (end is exclusive).")


def compare_daily_cohorts(
    before_rows: list[FunnelRow], before_query: FunnelQuery, before_date: date,
    after_rows: list[FunnelRow], after_query: FunnelQuery, after_date: date,
) -> list[StepComparison]:
    """Compare parsed rows, each paired with the query that produced them.

    Match by step ID, never row position. Preserve observed rates when a change
    is unavailable. Matching metadata cannot detect unversioned logging changes
    or establish that cohorts had equal time to complete the funnel.
    """
    validate_comparison_queries(before_query, after_query, before_date, after_date)
    before = {row.step_id: row for row in before_rows if row.cohort_date == before_date}
    after = {row.step_id: row for row in after_rows if row.cohort_date == after_date}

    # parse_rates enforces consistent labels within each response; check across
    # responses too. A rename needs review even when IDs and funnel name match.
    before_names = {row.step_id: row.step_name for row in before_rows}
    after_names = {row.step_id: row.step_name for row in after_rows}
    for step in before_names.keys() & after_names.keys():
        if before_names[step] != after_names[step]:
            raise DataError(f"Step {step} has different labels across the two responses; check its definition.")

    issues = []
    for label, points in (("Before", before), ("After", after)):
        issue = cohort_issue(points)
        if issue:
            issues.append(f"{label}: {issue}")
    cohort_reason = " ".join(issues) or None
    comparisons = []
    for step in sorted(before_query.step_ids, key=int):
        earlier = before.get(step)
        later = after.get(step)
        before_rate = earlier.completion_rate if earlier is not None else None
        after_rate = later.completion_rate if later is not None else None
        reason = cohort_reason
        if reason is None and (earlier is None or later is None):
            reason = "A selected date is missing this step; missing is not zero."
        if reason is None:
            statuses = [
                f"{label} status: {row.status}."
                for label, row in (("Before", earlier), ("After", later))
                if row.status not in (None, "Valid")
            ]
            reason = " ".join(statuses) or None
        change = None if reason is not None else (after_rate - before_rate) * 100
        name = before_names.get(step, after_names.get(step, step))
        comparisons.append(StepComparison(
            step, name, before_date, after_date, before_rate, after_rate, change, reason,
        ))
    return comparisons
