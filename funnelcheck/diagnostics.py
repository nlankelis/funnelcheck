"""Explicit expected directions against validated daily rates; no inferred mechanics."""

from dataclasses import dataclass
from datetime import date
import re
from typing import Literal

from .comparison import compare_daily_cohorts
from .funnel import DataError, FunnelQuery, FunnelRow
from .updates import RecordedUpdate, build_update_context

Direction = Literal["increase", "decrease", "unchanged"]
ObservationStatus = Literal["supporting", "conflicting", "unchanged", "missing"]
DiagnosticStatus = Literal["supporting", "conflicting", "mixed", "unchanged", "insufficient_evidence"]


@dataclass(frozen=True)
class Expectation:
    step_id: str
    expected_direction: Direction

    def __post_init__(self):
        if not isinstance(self.step_id, str) or re.fullmatch(r"[1-9][0-9]{0,19}", self.step_id) is None:
            raise DataError("A hypothesis step ID must be positive numeric text.")
        if self.expected_direction not in ("increase", "decrease", "unchanged"):
            raise DataError("Choose increase, decrease or unchanged for each expected direction.")


@dataclass(frozen=True)
class Hypothesis:
    statement: str
    expectations: tuple[Expectation, ...]

    def __post_init__(self):
        if not isinstance(self.statement, str) or not self.statement.strip() or len(self.statement) > 500:
            raise DataError("Provide a nonblank hypothesis of at most 500 characters.")
        if not isinstance(self.expectations, tuple) or not 1 <= len(self.expectations) <= 10:
            raise DataError("Select between 1 and 10 hypothesis measurements.")
        if any(not isinstance(item, Expectation) for item in self.expectations):
            raise DataError("Each hypothesis measurement must be an Expectation.")
        if len({item.step_id for item in self.expectations}) != len(self.expectations):
            raise DataError("Select each hypothesis step only once.")


@dataclass(frozen=True)
class DiagnosticObservation:
    step_id: str
    step_name: str
    measurement: str
    expected_direction: Direction
    observed_direction: Direction | None
    before_date: date | None
    after_date: date | None
    before_rate: float | None
    after_rate: float | None
    change_pp: float | None
    status: ObservationStatus
    reason: str | None
    question: str


@dataclass(frozen=True)
class DiagnosticResult:
    statement: str
    update_name: str | None
    status: DiagnosticStatus
    observations: list[DiagnosticObservation]
    limitations: list[str]


def evaluate_hypothesis(
    hypothesis: Hypothesis, rows: list[FunnelRow], query: FunnelQuery,
    comparison: tuple[date, date] | None, update: RecordedUpdate | None,
) -> DiagnosticResult:
    """Use parsed rows and the existing compatibility/quality checks, without I/O.

    A blocked timing context retains available rates and descriptive changes, but
    withholds an update-hypothesis verdict. Any missing observation prevents a
    complete summary; usable individual observations remain visible.
    """
    if any(item.step_id not in query.step_ids for item in hypothesis.expectations):
        raise DataError("Hypothesis measurements must be steps selected in this query.")
    comparisons = {} if comparison is None else {
        item.step_id: item for item in compare_daily_cohorts(
            rows, query, comparison[0], rows, query, comparison[1],
        )
    }
    context = build_update_context(update, query, comparison) if update else None
    blocked = None
    if context is None:
        blocked = "Record an update before evaluating its hypothesis."
    elif comparison is None:
        blocked = "Apply comparison dates: a full before day and a full after day."
    else:
        phases = {item.cohort_date: item.phase for item in context.cohorts}
        if phases[comparison[0]] != "before" or phases[comparison[1]] != "after":
            blocked = "Use a full before day and a full after day; transition or same-side dates cannot evaluate this update hypothesis."
    names = {row.step_id: row.step_name for row in rows}
    observations = []
    for expected in hypothesis.expectations:
        item = comparisons.get(expected.step_id)
        reason = " ".join(part for part in (blocked, item.reason if item else None) if part) or None
        change = item.change_pp if item else None
        observed = None if change is None else "increase" if change > 0 else "decrease" if change < 0 else "unchanged"
        if reason is not None or observed is None:
            status = "missing"
            question = f"For step {expected.step_id}, can you supply valid daily rates on full days either side of the recorded update and verify its event definition?"
        elif observed == expected.expected_direction:
            status = "supporting"
            question = f"Does the step {expected.step_id} pattern recur on more comparable days, and what version-exposure or playtest evidence links this event to the hypothesis?"
        elif observed == "unchanged":
            status = "unchanged"
            question = f"Does step {expected.step_id} measure the intended behaviour, or is a separate event for that behaviour needed? Check logging and time available to finish."
        else:
            status = "conflicting"
            question = f"What do playtests and logs show at step {expected.step_id}, and could logging changes, player mix or time to finish explain the unexpected direction?"
        observations.append(DiagnosticObservation(
            expected.step_id, names.get(expected.step_id, f"Step {expected.step_id}"),
            "Daily session-cohort cumulative completion rate (fraction of starters)",
            expected.expected_direction, observed,
            comparison[0] if comparison else None, comparison[1] if comparison else None,
            item.before_rate if item else None, item.after_rate if item else None,
            change, status, reason, question,
        ))
    statuses = {item.status for item in observations}
    if "missing" in statuses:
        summary = "insufficient_evidence"
    elif "supporting" in statuses and "conflicting" in statuses:
        summary = "mixed"
    elif "conflicting" in statuses:
        summary = "conflicting"
    elif "unchanged" in statuses:
        summary = "unchanged"
    else:
        summary = "supporting"
    return DiagnosticResult(hypothesis.statement, update.name if update else None, summary, observations, [
        "Agreement is an observation, not proof that the update caused it or a prediction of improvement.",
        "Direction uses the unrounded signed difference; unchanged means exactly zero, not statistical equivalence. No significance threshold is applied.",
        "These are session/attempt cohorts, not unique players. Rates provide no counts or verified game-version exposure.",
        "The mapping is user-defined. Event labels do not prove behaviour, comprehension or that an issued reveal was seen.",
        "Missing or unusable selected evidence makes the summary insufficient; inspect each observation. Measurements are not pooled or weighted.",
    ])
