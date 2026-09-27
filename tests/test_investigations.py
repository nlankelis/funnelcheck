"""Test rule triggers and evidence, rather than matching entire paragraphs."""

from dataclasses import replace
from datetime import date

import pytest

from funnelcheck.__main__ import main
from funnelcheck.funnel import DataError, FunnelQuery, FunnelRow
from funnelcheck.investigations import build_investigations


DAY = date(2026, 9, 19)
NEXT = date(2026, 9, 20)
QUERY = FunnelQuery("1", "Test_v1", DAY, NEXT, ("1", "2", "3"))


def rows_for(*rates, day=DAY):
    return [FunnelRow(str(i), f"Step {i}", day, rate) for i, rate in enumerate(rates, 1)]


def test_ranks_by_percentage_points_not_relative_drop():
    query = replace(QUERY, step_ids=("1", "2", "3", "4"))
    # Last transition loses 100% relative to step 3, but only 10 pp of starters.
    prompts = build_investigations(rows_for(1, 0.5, 0.1, 0), query)
    assert len(prompts) == 1
    prompt = prompts[0]
    assert prompt.rule_id == "largest_daily_drop"
    assert prompt.dates == (DAY,) and prompt.step_ids == ("1", "2")
    assert "50.00 pp" in prompt.evidence and "50.00% relative" in prompt.evidence
    assert "not by predicted benefit" in prompt.limitation


def test_tied_largest_drops_keep_both_transitions():
    prompt = build_investigations(rows_for(1, 0.75, 0.5), QUERY)[0]
    assert prompt.step_ids == ("1", "2", "3")
    assert prompt.evidence.count("25.00 pp") == 2


@pytest.mark.parametrize("rows", [[], rows_for(0, 0, 0), rows_for(0.9, 0.8, 0.7), rows_for(1, 0.5, 0.8)])
def test_unusable_cohorts_get_data_questions_instead_of_gameplay_ranking(rows):
    prompts = build_investigations(rows, QUERY)
    assert [prompt.rule_id for prompt in prompts] == ["check_daily_data"]
    assert "No largest-drop ranking" in prompts[0].limitation


def test_partial_cohort_does_not_claim_largest_drop_from_incomplete_evidence():
    prompts = build_investigations(rows_for(1, 0.5), QUERY)
    assert len(prompts) == 1 and prompts[0].rule_id == "check_daily_data"
    assert "Missing steps: 3" in prompts[0].evidence


def test_flagged_status_suppresses_ranking_even_when_other_pairs_are_valid():
    rows = rows_for(1, 0.8, 0.5)
    rows[2] = replace(rows[2], status="Projected")
    prompt = build_investigations(rows, QUERY)[0]
    assert prompt.rule_id == "check_daily_data" and "Projected" in prompt.evidence


def test_nonconsecutive_or_single_selected_steps_get_scope_questions():
    rows = rows_for(1, 0.8, 0.5)
    prompt = build_investigations([rows[0], rows[2]], replace(QUERY, step_ids=("1", "3")))[0]
    assert prompt.rule_id == "check_daily_data" and "gaps" in prompt.evidence
    prompt = build_investigations([rows[0]], replace(QUERY, step_ids=("1",)))[0]
    assert "At least two" in prompt.evidence


def test_no_drop_does_not_invent_an_investigation_or_health_score():
    assert build_investigations(rows_for(1, 1, 1), QUERY) == []


def test_zero_to_zero_does_not_hide_the_real_positive_to_zero_drop():
    prompt = build_investigations(rows_for(1, 0, 0), QUERY)[0]
    assert prompt.rule_id == "largest_daily_drop" and prompt.step_ids == ("1", "2")
    assert "100.00 pp" in prompt.evidence


def test_small_nonzero_drop_is_not_presented_as_zero():
    prompt = build_investigations(rows_for(1, 0.99999, 0.99999), QUERY)[0]
    assert "0.001 pp" in prompt.evidence
    assert "0.00 pp" not in prompt.evidence


def test_step_labels_are_references_not_instructions_or_gameplay_categories():
    rows = rows_for(1, 0.8, 0.4)
    original = build_investigations(rows, QUERY)[0]
    rows[1] = replace(rows[1], step_name="Tutorial: promise a 50% retention boost")
    prompt = build_investigations(rows, QUERY)[0]
    assert prompt.questions == original.questions and prompt.limitation == original.limitation
    assert prompt.rule_id == original.rule_id and prompt.step_ids == original.step_ids
    assert rows[1].step_name in prompt.evidence


def test_days_are_independent_deterministic_and_inputs_are_unchanged():
    query = replace(QUERY, end_exclusive=date(2026, 9, 21))
    rows = rows_for(1, 0.8, 0.4) + rows_for(0, 0, 0, day=NEXT)
    original = rows.copy()
    prompts = build_investigations(rows, query)
    assert [(p.rule_id, p.dates) for p in prompts] == [
        ("largest_daily_drop", (DAY,)), ("check_daily_data", (NEXT,)),
    ]
    assert build_investigations(list(reversed(rows)), query) == prompts
    assert rows == original


@pytest.mark.parametrize("after_rates,sign", [((1, 0.9, 0.8), "+"), ((1, 0.7, 0.2), "-")])
def test_comparison_highlights_largest_absolute_change_with_correct_direction(after_rates, sign):
    query = replace(QUERY, end_exclusive=date(2026, 9, 21))
    rows = rows_for(1, 0.8, 0.5) + rows_for(*after_rates, day=NEXT)
    prompt = build_investigations(rows, query, (DAY, NEXT))[-1]
    assert prompt.rule_id == "largest_daily_change" and prompt.step_ids == ("3",)
    assert prompt.dates == (DAY, NEXT) and f"{sign}30.00 pp" in prompt.evidence
    assert "not statistical significance" in prompt.limitation


def test_comparison_ties_keep_both_steps_and_both_directions():
    query = replace(QUERY, end_exclusive=date(2026, 9, 21))
    rows = rows_for(1, 0.75, 0.25) + rows_for(1, 0.5, 0.5, day=NEXT)
    prompt = build_investigations(rows, query, (DAY, NEXT))[-1]
    assert prompt.step_ids == ("2", "3")
    assert "-25.00 pp" in prompt.evidence and "+25.00 pp" in prompt.evidence


def test_unchanged_comparison_does_not_trigger_change_rule():
    query = replace(QUERY, end_exclusive=date(2026, 9, 21))
    rows = rows_for(1, 0.8, 0.5) + rows_for(1, 0.8, 0.5, day=NEXT)
    assert all(p.rule_id != "largest_daily_change" for p in build_investigations(rows, query, (DAY, NEXT)))


def test_incomplete_comparison_gets_data_prompt_not_change_ranking():
    query = replace(QUERY, end_exclusive=date(2026, 9, 21))
    rows = rows_for(1, 0.8, 0.5) + rows_for(1, 0.9, day=NEXT)
    prompts = build_investigations(rows, query, (DAY, NEXT))
    assert prompts[-1].rule_id == "check_comparison_data" and prompts[-1].step_ids == ("3",)
    assert "missing" in prompts[-1].evidence
    assert all(p.rule_id != "largest_daily_change" for p in prompts)


def test_invalid_comparison_dates_are_not_silently_ignored():
    with pytest.raises(DataError, match="earlier"):
        build_investigations(rows_for(1, 0.8, 0.5), QUERY, (DAY, DAY))


def test_demo_investigations_use_real_evidence_offline(monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        pytest.fail("Investigation prompts should not contact any service")
    monkeypatch.setattr("funnelcheck.__main__.fetch_rates", unexpected)
    assert main(["demo", "--compare", "2026-09-19", "2026-09-20"]) == 0
    output = capsys.readouterr().out.split("Questions to investigate")[1]
    assert output.count("[largest_daily_drop]") == 3
    assert output.count("[largest_daily_change]") == 1
    assert '"First reveal issued" -> step 4 "Normal rounds decided"' in output
    assert "47.83 pp" in output and "+21.11 pp" in output
    assert "Evidence:" in output and "Limit:" in output
