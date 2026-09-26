"""Synthetic edge cases plus a reconciliation with the real offline example."""

from dataclasses import replace
from datetime import date
import json
from pathlib import Path

import pytest

from funnelcheck.analysis import calculate_dropoffs
from funnelcheck.__main__ import main
from funnelcheck.funnel import FunnelQuery, FunnelRow, parse_rates


DAY = date(2026, 9, 19)
QUERY = FunnelQuery("1", "Test_v1", DAY, date(2026, 9, 20), ("1", "2", "3"))


def rows_for(*rates):
    return [FunnelRow(str(i), f"Step {i}", DAY, rate) for i, rate in enumerate(rates, 1)]


def test_distinguishes_percentage_points_from_relative_drop_without_rounding():
    rows = rows_for(1, 0.8, 0.6)
    original = rows.copy()
    drops = calculate_dropoffs(rows, QUERY)
    assert drops[1].percentage_points == pytest.approx(20)
    assert drops[1].relative_drop == pytest.approx(0.25)
    assert drops[1].percentage_points == (0.8 - 0.6) * 100
    assert drops[1].reason is None
    assert rows == original


def test_equal_positive_rates_are_measured_zero_drop():
    drop = calculate_dropoffs(rows_for(1, 0.8, 0.8), QUERY)[1]
    assert drop.percentage_points == 0
    assert drop.relative_drop == 0
    assert drop.reason is None


def test_positive_to_zero_is_full_relative_drop_but_zero_to_zero_is_undefined():
    first, second = calculate_dropoffs(rows_for(1, 0, 0), QUERY)
    assert first.percentage_points == 100
    assert first.relative_drop == 1
    assert second.percentage_points == 0
    assert second.relative_drop is None
    assert "undefined" in second.reason


@pytest.mark.parametrize("baseline", [0, 0.5])
def test_unusable_starting_cohort_withholds_all_calculations(baseline):
    drops = calculate_dropoffs(rows_for(baseline, 0, 0), QUERY)
    assert all(d.percentage_points is None and d.relative_drop is None for d in drops)
    assert all("baseline" in d.reason for d in drops)


def test_missing_baseline_withholds_later_pair_too():
    drops = calculate_dropoffs(rows_for(1, 0.8, 0.6)[1:], QUERY)
    assert all(d.relative_drop is None and "Step 1 is missing" in d.reason for d in drops)


def test_missing_middle_step_does_not_bridge_the_gap():
    rows = rows_for(1, 0.8, 0.6)
    drops = calculate_dropoffs([rows[0], rows[2]], QUERY)
    assert [(d.from_step, d.to_step) for d in drops] == [("1", "2"), ("2", "3")]
    assert all(d.percentage_points is None and "missing" in d.reason for d in drops)


def test_missing_final_step_preserves_the_available_pair():
    drops = calculate_dropoffs(rows_for(1, 0.8), QUERY)
    assert drops[0].percentage_points == pytest.approx(20)
    assert drops[1].percentage_points is None


def test_empty_response_produces_unavailable_results_not_zeroes():
    drops = calculate_dropoffs([], QUERY)
    assert len(drops) == 2
    assert all(d.percentage_points is None and d.relative_drop is None for d in drops)


@pytest.mark.parametrize("last_rate", [0.9, 0.8000000001])
def test_any_increase_withholds_cohort_rather_than_clipping_negative_drop(last_rate):
    drops = calculate_dropoffs(rows_for(1, 0.8, last_rate), QUERY)
    assert all(d.percentage_points is None and "increase" in d.reason for d in drops)


@pytest.mark.parametrize("step", [0, 1])
def test_nonvalid_baseline_or_shared_endpoint_status_withholds_results(step):
    rows = rows_for(1, 0.8, 0.6)
    rows[step] = replace(rows[step], status="Projected")
    drops = calculate_dropoffs(rows, QUERY)
    assert all(d.relative_drop is None and "status" in d.reason for d in drops)


def test_valid_status_is_usable_and_bad_final_status_only_blocks_its_pair():
    rows = [replace(row, status="Valid") for row in rows_for(1, 0.8, 0.6)]
    assert all(d.reason is None for d in calculate_dropoffs(rows, QUERY))
    rows[2] = replace(rows[2], status="Unknown")
    drops = calculate_dropoffs(rows, QUERY)
    assert drops[0].relative_drop == pytest.approx(0.2)
    assert drops[1].relative_drop is None


def test_unselected_steps_are_not_presented_as_adjacent():
    query = replace(QUERY, step_ids=("1", "3"))
    rows = [rows_for(1, 0.8, 0.6)[i] for i in (0, 2)]
    drop = calculate_dropoffs(rows, query)[0]
    assert drop.relative_drop is None
    assert "not consecutive" in drop.reason


def test_numeric_order_and_single_step():
    query = replace(QUERY, step_ids=("10", "2", "1", "9"))
    rows = [FunnelRow(step, step, DAY, rate) for step, rate in [("10", 0.4), ("2", 0.9), ("1", 1), ("9", 0.5)]]
    drops = calculate_dropoffs(rows, query)
    assert [(d.from_step, d.to_step) for d in drops] == [("1", "2"), ("2", "9"), ("9", "10")]
    assert drops[2].relative_drop == pytest.approx(0.2)
    assert calculate_dropoffs(rows_for(1), replace(QUERY, step_ids=("1",))) == []


def test_days_are_independent_and_missing_days_still_appear():
    query = replace(QUERY, end_exclusive=date(2026, 9, 22))
    rows = rows_for(1, 0.8, 0.6) + [replace(row, cohort_date=date(2026, 9, 21)) for row in rows_for(0, 0, 0)]
    drops = calculate_dropoffs(list(reversed(rows)), query)
    assert len(drops) == 6
    assert drops[0].relative_drop == pytest.approx(0.2)
    assert drops[2].cohort_date == date(2026, 9, 20)
    assert all(d.relative_drop is None for d in drops[2:])


def test_real_reveal_to_normal_rounds_drop_and_daily_telescoping():
    root = Path(__file__).resolve().parents[1]
    saved = json.loads((root / "examples/matchcompletion.json").read_text(encoding="utf-8"))
    context = saved["query"]
    query = FunnelQuery(context["universe_id"], context["funnel_name"], date.fromisoformat(context["start"]), date.fromisoformat(context["end_exclusive"]), tuple(context["step_ids"]))
    rows = parse_rates(saved["result"], query)
    drops = calculate_dropoffs(rows, query)
    assert len(drops) == 12
    assert drops[2].percentage_points == pytest.approx(47.826087474823)
    assert drops[2].relative_drop == pytest.approx(0.5)
    for day in {row.cohort_date for row in rows}:
        final_rate = next(row.completion_rate for row in rows if row.cohort_date == day and row.step_id == "5")
        assert sum(d.percentage_points for d in drops if d.cohort_date == day) == pytest.approx((1 - final_rate) * 100)


def test_demo_displays_both_units(capsys):
    assert main(["demo"]) == 0
    output = capsys.readouterr().out
    assert "47.83 pp" in output and "50.00%" in output
    assert "Starter drop" in output and "Relative drop" in output


def test_cli_explains_unavailable_results(monkeypatch, capsys):
    monkeypatch.setattr("funnelcheck.__main__.parse_rates", lambda *_: [])
    assert main(["demo"]) == 0
    output = capsys.readouterr().out
    assert "N/A" in output
    assert "Step 1 is missing" in output
