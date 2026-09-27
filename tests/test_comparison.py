"""Daily comparison contracts, synthetic edge cases and the real demo."""

from dataclasses import replace
from datetime import date

import pytest

from funnelcheck.__main__ import main
from funnelcheck.comparison import compare_daily_cohorts
from funnelcheck.funnel import DataError, FunnelQuery, FunnelRow


BEFORE = date(2026, 9, 19)
AFTER = date(2026, 9, 20)
QUERY = FunnelQuery("1", "Test_v1", BEFORE, date(2026, 9, 22), ("1", "2", "3"))


def rows_for(day, *rates):
    return [FunnelRow(str(i), f"Step {i}", day, rate) for i, rate in enumerate(rates, 1)]


def compare(before=None, after=None, before_query=QUERY, after_query=QUERY,
            before_date=BEFORE, after_date=AFTER):
    return compare_daily_cohorts(
        rows_for(BEFORE, 1, 0.8, 0.6) if before is None else before, before_query, before_date,
        rows_for(AFTER, 1, 0.9, 0.5) if after is None else after, after_query, after_date,
    )


def test_signed_change_includes_positive_negative_and_zero_without_rounding():
    results = compare()
    assert [item.change_pp for item in results] == pytest.approx([0, 10, -10])
    assert results[2].change_pp == (0.5 - 0.6) * 100
    assert results[2].before_rate == 0.6 and results[2].after_rate == 0.5
    assert results[2].before_date == BEFORE and results[2].after_date == AFTER
    assert all(item.reason is None for item in results)


@pytest.mark.parametrize("change,message", [
    ({"universe_id": "2"}, "experiences"),
    ({"funnel_name": "Test_v2"}, "versions"),
    ({"funnel_name": "Other_v1"}, "funnel names"),
    ({"step_ids": ("1", "2")}, "step sets"),
])
def test_incompatible_queries_fail_before_calculating(change, message):
    with pytest.raises(DataError, match=message):
        compare(after_query=replace(QUERY, **change))


def test_order_of_rows_and_requested_steps_does_not_change_matches_or_mutate_input():
    before = list(reversed(rows_for(BEFORE, 1, 0.8, 0.6)))
    after = list(reversed(rows_for(AFTER, 1, 0.9, 0.5)))
    original = (before.copy(), after.copy())
    result = compare(before, after, after_query=replace(QUERY, step_ids=("3", "1", "2")))
    assert result == compare()
    assert (before, after) == original


def test_separate_compatible_query_windows_are_allowed():
    before_query = replace(QUERY, end_exclusive=AFTER)
    after_query = replace(QUERY, start=AFTER)
    assert compare(before_query=before_query, after_query=after_query) == compare()


def test_changed_label_blocks_comparison():
    after = rows_for(AFTER, 1, 0.9, 0.5)
    after[2] = replace(after[2], step_name="New meaning")
    with pytest.raises(DataError, match="different labels"):
        compare(after=after)


@pytest.mark.parametrize("earlier,later,message", [
    (BEFORE, BEFORE, "earlier"),
    (AFTER, BEFORE, "earlier"),
    (date(2026, 9, 18), AFTER, "Before date"),
    (BEFORE, date(2026, 9, 22), "After date"),
])
def test_date_order_and_exclusive_boundaries(earlier, later, message):
    with pytest.raises(DataError, match=message):
        compare(before_date=earlier, after_date=later)


def test_missing_step_is_not_zero_and_does_not_hide_other_valid_steps():
    after = rows_for(AFTER, 1, 0.9, 0.5)
    results = compare(after=[after[0], after[2]])
    assert results[1].before_rate == 0.8
    assert results[1].after_rate is None and results[1].change_pp is None
    assert "missing" in results[1].reason
    assert results[2].change_pp == pytest.approx(-10)


def test_step_missing_on_both_dates_stays_in_report():
    result = compare(before=rows_for(BEFORE, 1, 0.8), after=rows_for(AFTER, 1, 0.9))[2]
    assert result.step_id == "3"
    assert result.before_rate is None and result.after_rate is None and result.change_pp is None


@pytest.mark.parametrize("side", ["before", "after"])
def test_missing_day_withholds_changes_but_preserves_other_days_rates(side):
    results = compare(**{side: []})
    assert all(item.change_pp is None for item in results)
    assert all("Step 1 is missing" in item.reason for item in results)
    assert results[2].after_rate == (0.5 if side == "before" else None)
    assert results[2].before_rate == (0.6 if side == "after" else None)


@pytest.mark.parametrize("rates", [(0, 0, 0), (0.9, 0.8, 0.6), (1, 0.4, 0.6)])
def test_unusable_baseline_or_increase_withholds_all_changes(rates):
    results = compare(after=rows_for(AFTER, *rates))
    assert all(item.change_pp is None and item.reason.startswith("After:") for item in results)
    assert results[2].after_rate == rates[2]


def test_status_blocks_only_affected_step_unless_baseline_is_flagged():
    after = rows_for(AFTER, 1, 0.9, 0.5)
    after[2] = replace(after[2], status="Projected")
    results = compare(after=after)
    assert results[1].change_pp == pytest.approx(10)
    assert results[2].change_pp is None and "Projected" in results[2].reason
    after[0] = replace(after[0], status="Projected")
    assert all(item.change_pp is None for item in compare(after=after))


def test_valid_status_and_measured_zero_are_usable():
    before = [replace(row, status="Valid") for row in rows_for(BEFORE, 1, 0.8, 0)]
    result = compare(before=before)[2]
    assert result.before_rate == 0
    assert result.change_pp == 50


def test_unselected_dates_do_not_affect_the_selected_days():
    after = rows_for(AFTER, 1, 0.9, 0.5) + rows_for(date(2026, 9, 21), 0, 0, 0)
    assert compare(after=after) == compare()


def test_real_demo_comparison_is_offline_and_has_expected_change(monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        pytest.fail("Offline comparison must not fetch data or ask for a key")
    monkeypatch.setattr("funnelcheck.__main__.fetch_rates", unexpected)
    monkeypatch.setattr("funnelcheck.__main__.getpass.getpass", unexpected)
    assert main(["demo", "--compare", "2026-09-19", "2026-09-20"]) == 0
    output = capsys.readouterr().out
    assert "Daily cohort comparison: 2026-09-19 -> 2026-09-20" in output
    line = next(line for line in output.splitlines() if "Match completed" in line and "+21.11 pp" in line)
    assert "27.54%" in line and "48.65%" in line
    assert "do not establish an update's effect" in output


def test_bad_live_comparison_dates_fail_before_credentials_or_network(monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid dates must be checked before fetching")
    monkeypatch.delenv("ROBLOX_API_KEY", raising=False)
    monkeypatch.setattr("funnelcheck.__main__.fetch_rates", unexpected)
    monkeypatch.setattr("funnelcheck.__main__.getpass.getpass", unexpected)
    assert main([
        "fetch", "--universe", "1", "--funnel", "Test_v1",
        "--start", "2026-09-19", "--end-exclusive", "2026-09-21", "--steps", "1", "2",
        "--compare", "2026-09-19", "2026-09-21",
    ]) == 1
    assert "end is exclusive" in capsys.readouterr().out


def test_cli_comparison_displays_missing_values_and_explanation(monkeypatch, capsys):
    monkeypatch.setattr("funnelcheck.__main__.parse_rates", lambda *_: [])
    assert main(["demo", "--compare", "2026-09-19", "2026-09-20"]) == 0
    comparison = capsys.readouterr().out.split("Daily cohort comparison:")[1]
    assert "N/A" in comparison and "Step 1 is missing" in comparison
