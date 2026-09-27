"""Transparent investigation rules, using parsed rates and existing calculations."""

from dataclasses import dataclass
from datetime import date, timedelta
import math

from .analysis import calculate_dropoffs, cohort_issue
from .comparison import compare_daily_cohorts
from .funnel import FunnelQuery, FunnelRow


@dataclass(frozen=True)
class Investigation:
    rule_id: str
    dates: tuple[date, ...]
    step_ids: tuple[str, ...]
    title: str
    evidence: str
    questions: tuple[str, ...]
    limitation: str


def _number(value: float) -> str:
    """Avoid describing a small nonzero change as 0.00 in prompt evidence."""
    return f"{value:.2f}" if value == 0 or abs(value) >= 0.01 else f"{value:.2g}"


def build_investigations(
    rows: list[FunnelRow], query: FunnelQuery,
    comparison_dates: tuple[date, date] | None = None,
) -> list[Investigation]:
    """Use parse_rates output with its matching query; never infer game semantics.

    Rank only complete, usable daily funnels, by percentage points of starters.
    Comparisons with any unavailable change receive a data-check prompt instead.
    Ties within 1e-9 pp are retained to avoid floating-point tie breaking.
    No minimum 'bad' rate, confidence estimate or predicted uplift is assumed.
    """
    comparisons = None
    if comparison_dates is not None:
        before, after = comparison_dates
        comparisons = compare_daily_cohorts(rows, query, before, rows, query, after)

    steps = sorted(query.step_ids, key=int)
    by_day = {}
    for row in rows:
        by_day.setdefault(row.cohort_date, {})[row.step_id] = row
    drops_by_day = {}
    for drop in calculate_dropoffs(rows, query):
        drops_by_day.setdefault(drop.cohort_date, []).append(drop)

    prompts = []
    day = query.start
    while day < query.end_exclusive:
        points = by_day.get(day, {})
        issues = []
        issue = cohort_issue(points)
        if issue:
            issues.append(issue)
        missing = [step for step in steps if step not in points]
        if missing:
            issues.append(f"Missing steps: {', '.join(missing)}.")
        for step in steps:
            row = points.get(step)
            if row is not None and row.status not in (None, "Valid"):
                issues.append(f"Step {step} has Roblox status {row.status}.")
        if len(steps) < 2:
            issues.append("At least two steps must be selected to inspect a transition.")
        elif any(int(b) != int(a) + 1 for a, b in zip(steps, steps[1:])):
            issues.append("Selected step IDs have gaps; the transition sequence needs checking.")

        if issues:
            prompts.append(Investigation(
                "check_daily_data", (day,), tuple(steps), "Check this day's data first",
                " ".join(dict.fromkeys(issues)),
                (
                    "Does the query include the intended steps and the correct daily cohort?",
                    "Do event logs and a fresh export explain the missing, flagged or unusable values?",
                ),
                "No largest-drop ranking is produced for this day; missing or unusable data is not abandonment.",
            ))
        else:
            candidates = [drop for drop in drops_by_day.get(day, []) if drop.percentage_points is not None and drop.percentage_points > 0]
            if candidates:
                largest = max(drop.percentage_points for drop in candidates)
                selected = [drop for drop in candidates if math.isclose(drop.percentage_points, largest, rel_tol=0, abs_tol=1e-9)]
                evidence = []
                selected_steps = []
                for drop in selected:
                    previous, current = points[drop.from_step], points[drop.to_step]
                    evidence.append(
                        f'Step {drop.from_step} "{previous.step_name}" -> step {drop.to_step} "{current.step_name}": '
                        f"{_number(drop.percentage_points)} pp of starters; "
                        f"{_number(drop.relative_drop * 100)}% relative drop."
                    )
                    selected_steps.extend((drop.from_step, drop.to_step))
                prompts.append(Investigation(
                    "largest_daily_drop", (day,), tuple(dict.fromkeys(selected_steps)),
                    "Investigate the largest observed step drop",
                    " ".join(evidence),
                    (
                        "What must an attempt do between these steps, and what does a playtest reveal about that experience?",
                        "Can logs distinguish departures or failures from progress that was completed but not recorded?",
                    ),
                    "Ranked by percentage points within this day's selected steps, not by predicted benefit. Rates alone do not explain causes or sample size.",
                ))
        day += timedelta(days=1)

    if comparisons is not None:
        unavailable = [item for item in comparisons if item.change_pp is None]
        if unavailable:
            reasons = " ".join(dict.fromkeys(item.reason for item in unavailable))
            prompts.append(Investigation(
                "check_comparison_data", comparison_dates, tuple(item.step_id for item in unavailable),
                "Check the comparison before prioritising changes", reasons,
                ("Can you resolve the unavailable step comparisons using matching exports and event logs?",),
                "No change ranking is produced while selected step comparisons are unavailable.",
            ))
        else:
            changed = [item for item in comparisons if item.change_pp != 0]
            if changed:
                largest = max(abs(item.change_pp) for item in changed)
                selected = [item for item in changed if math.isclose(abs(item.change_pp), largest, rel_tol=0, abs_tol=1e-9)]
                evidence = " ".join(
                    f'Step {item.step_id} "{item.step_name}": '
                    f'{_number(item.before_rate * 100)}% -> {_number(item.after_rate * 100)}%, '
                    f'{"+" if item.change_pp > 0 else ""}{_number(item.change_pp)} pp.'
                    for item in selected
                )
                prompts.append(Investigation(
                    "largest_daily_change", comparison_dates, tuple(item.step_id for item in selected),
                    "Investigate the largest observed daily rate change", evidence,
                    (
                        "Did logging definitions or the mix of players differ between these dates?",
                        "Had both cohorts had comparable time to finish, and does the pattern recur on other compatible dates?",
                    ),
                    "Ranked by absolute percentage-point change, not statistical significance. This does not establish an update's effect or predict future improvement.",
                ))
    return prompts
