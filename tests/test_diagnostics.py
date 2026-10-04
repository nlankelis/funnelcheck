"""Synthetic direction/quality checks plus the real example through HTTP."""
import copy
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from funnelcheck.diagnostics import Expectation, Hypothesis, evaluate_hypothesis
from funnelcheck.funnel import DataError, FunnelQuery, FunnelRow
from funnelcheck.server import EXAMPLE, app
from funnelcheck.updates import RecordedUpdate

BEFORE, TRANSITION, AFTER = date(2026, 9, 19), date(2026, 9, 20), date(2026, 9, 21)
QUERY = FunnelQuery("1", "Test_v1", BEFORE, date(2026, 9, 22), ("1", "2", "3"))
UPDATE = RecordedUpdate("Tutorial added", "2026-09-20T04:00", "Europe/London", True)


def rows_for(day, *rates):
    return [FunnelRow(str(i), f"Event {i}", day, rate) for i, rate in enumerate(rates, 1)]


def evaluate(expectations=(("2", "increase"),), rows=None, comparison=(BEFORE, AFTER), update=UPDATE):
    hypothesis = Hypothesis("A user-defined expected behaviour", tuple(Expectation(*item) for item in expectations))
    rows = rows_for(BEFORE, 1, .8, .6) + rows_for(AFTER, 1, .9, .5) if rows is None else rows
    return evaluate_hypothesis(hypothesis, rows, QUERY, comparison, update)


@pytest.mark.parametrize("step,direction,status", [
    ("2", "increase", "supporting"), ("2", "decrease", "conflicting"),
    ("3", "decrease", "supporting"), ("3", "increase", "conflicting"),
    ("1", "unchanged", "supporting"), ("1", "increase", "unchanged"),
    ("2", "unchanged", "conflicting"),
])
def test_explicit_direction_and_exact_unchanged(step, direction, status):
    result = evaluate(((step, direction),))
    assert result.status == result.observations[0].status == status
    item = result.observations[0]
    assert item.before_date == BEFORE and item.after_date == AFTER
    assert item.question and "starters" in item.measurement
    assert result.update_name == "Tutorial added"
    assert any("not proof" in limit for limit in result.limitations)


def test_mixed_results_do_not_vote_or_weight_observations():
    result = evaluate((("2", "increase"), ("3", "increase")))
    assert result.status == "mixed"
    assert [item.status for item in result.observations] == ["supporting", "conflicting"]


def test_partial_evidence_retains_support_but_withholds_complete_summary():
    rows = rows_for(BEFORE, 1, .8, .6) + rows_for(AFTER, 1, .9)
    result = evaluate((("2", "increase"), ("3", "increase")), rows=rows)
    assert result.status == "insufficient_evidence"
    assert [item.status for item in result.observations] == ["supporting", "missing"]
    assert result.observations[1].after_rate is None
    assert result.observations[1].change_pp is None
    assert "missing" in result.observations[1].reason


@pytest.mark.parametrize("mutation", ["baseline", "increase", "status", "missing_baseline"])
def test_unusable_cohorts_and_statuses_do_not_become_verdicts(mutation):
    rows = rows_for(BEFORE, 1, .8, .6) + rows_for(AFTER, 1, .9, .5)
    if mutation == "baseline": rows[3] = replace(rows[3], completion_rate=0)
    elif mutation == "increase": rows[5] = replace(rows[5], completion_rate=.95)
    elif mutation == "status": rows[4] = replace(rows[4], status="Projected")
    else: rows.pop(3)
    item = evaluate(rows=rows).observations[0]
    assert item.status == "missing" and item.reason
    assert item.change_pp is None and item.observed_direction is None


@pytest.mark.parametrize("comparison,update,fragment", [
    (None, UPDATE, "Apply comparison"), ((BEFORE, AFTER), None, "Record an update"),
    ((BEFORE, TRANSITION), UPDATE, "full before"),
    ((TRANSITION, AFTER), UPDATE, "full before"),
    ((BEFORE, AFTER), replace(UPDATE, local_time="2026-09-22T04:00"), "full before"),
    ((BEFORE, AFTER), replace(UPDATE, local_time="2026-09-18T04:00"), "full before"),
])
def test_missing_or_unsuitable_update_context(comparison, update, fragment):
    result = evaluate(comparison=comparison, update=update)
    assert result.status == "insufficient_evidence"
    assert fragment in result.observations[0].reason


def test_blocked_context_preserves_descriptive_difference_but_not_verdict():
    result = evaluate(update=None)
    assert result.observations[0].change_pp == pytest.approx(10)
    assert result.observations[0].observed_direction == "increase"
    assert result.observations[0].status == "missing"


def test_midnight_update_allows_full_after_day():
    assert evaluate(update=replace(UPDATE, local_time="2026-09-21T00:00", time_zone="UTC")).status == "supporting"


def test_zero_and_tiny_nonzero_change_are_not_missing_or_rounded():
    rows = rows_for(BEFORE, 1, .8, .6) + rows_for(AFTER, 1, .800000000001, 0)
    result = evaluate((("2", "increase"), ("3", "decrease")), rows=rows)
    assert result.status == "supporting"
    assert 0 < result.observations[0].change_pp < 1e-8
    assert result.observations[1].after_rate == 0


def test_row_order_does_not_infer_mapping_and_inputs_are_unchanged():
    rows = rows_for(BEFORE, 1, .8, .6) + rows_for(AFTER, 1, .9, .5)
    original = copy.deepcopy(rows)
    assert evaluate(rows=list(reversed(rows))) == evaluate(rows=rows)
    assert rows == original


@pytest.mark.parametrize("step,direction", [(True, "increase"), ("0", "increase"), ("02", "increase"), ("2", "up"), ("2", True)])
def test_invalid_domain_mapping(step, direction):
    with pytest.raises(DataError): Expectation(step, direction)


@pytest.mark.parametrize("statement,expectations", [
    (" ", (Expectation("2", "increase"),)), ("x" * 501, (Expectation("2", "increase"),)),
    (True, (Expectation("2", "increase"),)), ("Test", ()),
    ("Test", (Expectation("2", "increase"),) * 2),
    ("Test", tuple(Expectation(str(i), "increase") for i in range(1, 12))),
])
def test_invalid_domain_hypothesis(statement, expectations):
    with pytest.raises(DataError): Hypothesis(statement, expectations)


def test_unselected_step_and_invalid_comparison_fail():
    with pytest.raises(DataError, match="selected"): evaluate((("4", "increase"),))
    with pytest.raises(DataError, match="earlier"): evaluate(comparison=(AFTER, BEFORE))


def mapped_payload():
    payload = copy.deepcopy(EXAMPLE)
    payload["compare"] = {"before": "2026-09-19", "after": "2026-09-21"}
    # Synthetic hypothesis chosen by this test; not inferred from the real tutorial.
    payload["hypothesis"] = {"statement": "More attempts reach match completion", "expectations": [{"step_id": "5", "expected_direction": "increase"}]}
    return payload


def test_http_demo_and_saved_analysis_recalculate_hypothesis():
    with TestClient(app) as client:
        payload = mapped_payload()
        response = client.post("/analyze", json=payload)
        assert response.status_code == 200
        report = response.json()
        assert report["diagnostics"]["status"] == "supporting"
        assert report["diagnostics"]["observations"][0]["change_pp"] == pytest.approx(37.68116235733032)
        assert client.post("/analyze", json=report["snapshot"]).json() == report
        options = {key: payload[key] for key in ("compare", "update", "hypothesis")}
        assert client.post("/demo", json=options).json() == report
        saved = report["snapshot"]
        saved["result"]["response"]["values"][4]["dataPoints"][2]["value"] = .1
        assert client.post("/analyze", json=saved).json()["diagnostics"]["status"] == "conflicting"
        saved["hypothesis"] = None
        cleared = client.post("/analyze", json=saved).json()
        assert cleared["diagnostics"] is None and cleared["snapshot"]["hypothesis"] is None
        assert client.get("/demo").json()["diagnostics"] is None


@pytest.mark.parametrize("hypothesis", [
    {"statement": " ", "expectations": [{"step_id": "5", "expected_direction": "increase"}]},
    {"statement": "Test", "expectations": []},
    {"statement": "Test", "expectations": [{"step_id": 5, "expected_direction": "increase"}]},
    {"statement": "Test", "expectations": [{"step_id": "5", "expected_direction": "up"}]},
    {"statement": "Test", "expectations": [{"step_id": "9", "expected_direction": "increase"}]},
    {"statement": "Test", "expectations": [{"step_id": "5", "expected_direction": "increase"}] * 2},
    {"statement": "Test", "expectations": [{"step_id": "5", "expected_direction": "increase", "cause": True}]},
    {"statement": "Test", "expectations": [{"step_id": "5", "expected_direction": "increase"}], "prediction": 20},
])
def test_http_mapping_validation(hypothesis):
    payload = mapped_payload()
    payload["hypothesis"] = hypothesis
    with TestClient(app) as client:
        assert client.post("/analyze", json=payload).status_code == 422


def test_http_missing_evidence_and_old_snapshots():
    with TestClient(app) as client:
        payload = mapped_payload()
        payload["result"]["response"]["values"][4]["dataPoints"].pop()
        report = client.post("/analyze", json=payload).json()
        assert report["diagnostics"]["status"] == "insufficient_evidence"
        assert report["diagnostics"]["observations"][0]["after_rate"] is None
        assert client.post("/analyze", json=report["snapshot"]).json() == report
        del payload["hypothesis"]
        assert client.post("/analyze", json=payload).json()["diagnostics"] is None
