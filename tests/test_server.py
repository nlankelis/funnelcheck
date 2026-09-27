"""Exercise the HTTP boundary using the saved example, without a live server."""

import copy

from fastapi.testclient import TestClient
import pytest

from funnelcheck.server import EXAMPLE, app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("ROBLOX_API_KEY", raising=False)
    def unexpected_fetch(*args, **kwargs):
        pytest.fail("HTTP report endpoints must not fetch from Roblox")
    monkeypatch.setattr("funnelcheck.api.fetch_rates", unexpected_fetch)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def payload():
    return copy.deepcopy(EXAMPLE)


def test_health_and_interactive_contract(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {"/health", "/demo", "/analyze"}
    assert "AnalysisReport" in schema["components"]["schemas"]
    example = schema["paths"]["/analyze"]["post"]["requestBody"]["content"]["application/json"]["examples"]["size_it_up"]["value"]
    assert client.post("/analyze", json=example).status_code == 200


def test_demo_and_post_have_identical_full_precision_reports(client, payload):
    demo = client.get("/demo")
    post = client.post("/analyze", json=payload)
    assert demo.status_code == post.status_code == 200
    report = post.json()
    assert report == demo.json()
    assert len(report["rows"]) == 15 and len(report["dropoffs"]) == 12
    assert report["rows"][4]["completion_rate"] == 0.2753623127937317
    assert report["rows"][0]["cohort_date"] == "2026-09-19"
    assert report["dropoffs"][2]["relative_drop"] == pytest.approx(0.5)
    assert report["dropoffs"][2]["percentage_points"] == pytest.approx(47.826087474823)
    assert report["units"]["relative_drop"] == "fraction"
    assert report["validation_notes"] == [] and report["comparisons"] is None
    assert len(report["investigations"]) == 3 and report["limitations"]
    assert "result" not in report and "source" not in report


def test_post_and_demo_comparison_match(client, payload):
    payload["compare"] = {"before": "2026-09-19", "after": "2026-09-20"}
    response = client.post("/analyze", json=payload)
    assert response.status_code == 200
    report = response.json()
    assert report == client.get("/demo?before=2026-09-19&after=2026-09-20").json()
    assert report["comparisons"][4]["change_pp"] == pytest.approx(21.11241817474365)
    assert len(report["investigations"]) == 4


def test_missing_data_returns_200_notes_and_null_not_invented_zero(client, payload):
    payload["compare"] = {"before": "2026-09-19", "after": "2026-09-20"}
    payload["result"]["response"]["values"][4]["dataPoints"].pop(1)
    response = client.post("/analyze", json=payload)
    assert response.status_code == 200
    report = response.json()
    assert len(report["rows"]) == 14 and report["validation_notes"]
    assert report["comparisons"][4]["after_rate"] is None
    assert report["comparisons"][4]["change_pp"] is None
    assert report["comparisons"][4]["reason"]


def test_zero_denominator_survives_serialization_as_null(client, payload):
    for series in payload["result"]["response"]["values"][1:]:
        series["dataPoints"][0]["value"] = 0
    response = client.post("/analyze", json=payload)
    assert response.status_code == 200
    drops = response.json()["dropoffs"]
    assert drops[0]["relative_drop"] == 1
    assert drops[1]["percentage_points"] == 0
    assert drops[1]["relative_drop"] is None


@pytest.mark.parametrize("result", [
    {"done": False}, {"done": True, "error": {"code": 1}},
    {"done": True, "response": {"values": "bad"}},
])
def test_unusable_operation_is_422_not_polled_or_reported_as_success(client, payload, result):
    payload["result"] = result
    response = client.post("/analyze", json=payload)
    assert response.status_code == 422 and isinstance(response.json()["detail"], str)


@pytest.mark.parametrize("value", [True, "0.5", None, -0.1, 1.1])
def test_raw_measurements_reach_existing_parser_without_coercion(client, payload, value):
    payload["result"]["response"]["values"][1]["dataPoints"][0]["value"] = value
    response = client.post("/analyze", json=payload)
    assert response.status_code == 422 and "finite number" in response.json()["detail"]


@pytest.mark.parametrize("field,value", [
    ("metric", "FunnelStepTotalCount"), ("granularity", "None"),
    ("filters", {"platform": "Mobile"}), ("step_ids", [1, 2]),
    ("universe_id", True), ("start", 1790000000),
    ("start", "2026-09-19T00:00:00Z"), ("start", "2026-02-30"),
])
def test_wrong_or_unsupported_query_fields_are_rejected(client, payload, field, value):
    payload["query"][field] = value
    assert client.post("/analyze", json=payload).status_code == 422


def test_metric_is_required_and_extra_top_level_fields_are_rejected(client, payload):
    del payload["query"]["metric"]
    assert client.post("/analyze", json=payload).status_code == 422
    payload = copy.deepcopy(EXAMPLE)
    payload["unexpected_option"] = "should not be ignored"
    assert client.post("/analyze", json=payload).status_code == 422


@pytest.mark.parametrize("field,value", [
    ("step_ids", ["1", "1"]), ("funnel_name", "   "),
    ("end_exclusive", "2026-09-18"), ("end_exclusive", "2028-09-22"),
])
def test_domain_query_errors_are_422(client, payload, field, value):
    payload["query"][field] = value
    assert client.post("/analyze", json=payload).status_code == 422


@pytest.mark.parametrize("query", [
    "?before=2026-09-19", "?before=2026-09-20&after=2026-09-19",
    "?before=2026-09-19&after=2026-09-22", "?before=1790000000&after=2026-09-20",
])
def test_demo_comparison_dates_are_validated(client, query):
    assert client.get("/demo" + query).status_code == 422


def test_invalid_json_and_invalid_shape_are_rejected(client):
    assert client.post("/analyze", content="{", headers={"Content-Type": "application/json"}).status_code == 422
    assert client.post("/analyze", json=[]).status_code == 422


def test_requests_do_not_change_demo_data_or_leak_previous_comparison(client, payload):
    baseline = client.get("/demo").json()
    payload["result"]["response"]["values"][4]["dataPoints"][0]["value"] = 0
    payload["compare"] = {"before": "2026-09-19", "after": "2026-09-20"}
    changed = client.post("/analyze", json=payload)
    assert changed.status_code == 200 and changed.json()["rows"][4]["completion_rate"] == 0
    assert client.get("/demo").json() == baseline


def test_demo_context_and_comparison_preserve_real_measurements(client):
    baseline = client.get("/demo").json()
    context = baseline["update_context"]
    assert context["occurred_at_utc"] == "2026-09-20T03:00:00Z"
    assert context["update"]["approximate"] is True
    assert [day["phase"] for day in context["cohorts"]] == ["before", "transition", "after"]
    response = client.post("/demo", json={"compare": context["suggested_comparison"], "update": context["update"]})
    assert response.status_code == 200
    compared = response.json()
    assert compared["comparisons"][4]["change_pp"] == pytest.approx(37.68116235733032)
    cleared = client.post("/demo", json={"compare": context["suggested_comparison"], "update": None}).json()
    assert cleared["update_context"] is None
    assert cleared["rows"] == baseline["rows"] == compared["rows"]
    assert cleared["comparisons"] == compared["comparisons"]
    assert client.get("/demo").json() == baseline


@pytest.mark.parametrize("field, value", [
    ("name", "   "), ("name", True), ("time_zone", "GMT"),
    ("approximate", "true"), ("approximate", 1),
    ("local_time", "2026-03-29T01:30"), ("local_time", "2026-10-25T01:30"),
    ("local_time", "2026-02-30T04:00"), ("local_time", 1790000000),
])
def test_invalid_update_context_is_422(client, payload, field, value):
    payload["update"][field] = value
    response = client.post("/analyze", json=payload)
    assert response.status_code == 422


def test_old_snapshot_without_update_still_works_and_missing_is_not_filled(client, payload):
    payload.pop("update")
    response = client.post("/analyze", json=payload)
    assert response.status_code == 200
    assert response.json()["update_context"] is None
    payload["update"] = EXAMPLE["update"]
    payload["compare"] = {"before": "2026-09-19", "after": "2026-09-21"}
    payload["result"]["response"]["values"][4]["dataPoints"].pop()
    result = client.post("/analyze", json=payload).json()
    assert result["update_context"]["cohorts"][-1]["phase"] == "after"
    assert result["comparisons"][4]["after_rate"] is None
    assert result["comparisons"][4]["change_pp"] is None


def test_saved_analysis_reopens_same_report_with_full_precision_and_context(client, payload):
    payload["compare"] = {"before": "2026-09-19", "after": "2026-09-21"}
    payload["update"]["name"] = "Edited tutorial explanation"
    original = client.post("/analyze", json=payload).json()
    saved = original["snapshot"]
    assert set(saved) == {"query", "result", "compare", "update"}
    assert saved["compare"] == payload["compare"]
    assert saved["update"] == payload["update"]
    reopened = client.post("/analyze", json=saved)
    assert reopened.status_code == 200
    assert reopened.json() == original
    assert reopened.json()["comparisons"][4]["change_pp"] == pytest.approx(37.68116235733032)


def test_saved_demo_cleared_fields_stay_cleared(client):
    report = client.post("/demo", json={"compare": None, "update": None}).json()
    assert report["snapshot"]["compare"] is None
    assert report["snapshot"]["update"] is None
    assert client.post("/analyze", json=report["snapshot"]).json() == report


def test_saved_analysis_preserves_gaps_zero_and_status_without_arbitrary_metadata(client, payload):
    payload["compare"] = {"before": "2026-09-19", "after": "2026-09-21"}
    payload["source"] = "fake-private-source"
    payload["result"]["metadata"] = {"secret": "fake-private-metadata"}
    series = payload["result"]["response"]["values"]
    series[4]["dataPoints"][0]["value"] = 0
    series[4]["dataPoints"].pop()
    series[0]["dataPoints"][0]["status"] = "Projected"
    original = client.post("/analyze", json=payload).json()
    saved = original["snapshot"]
    assert "fake-private" not in str(saved)
    reopened = client.post("/analyze", json=saved).json()
    assert reopened == original
    assert reopened["rows"][4]["completion_rate"] == 0
    assert reopened["comparisons"][4]["after_rate"] is None
    assert reopened["comparisons"][4]["change_pp"] is None
    assert reopened["rows"][0]["status"] == "Projected"


@pytest.mark.parametrize("mutation", ["rate", "dates", "derived"])
def test_saved_analysis_is_revalidated_when_edited(client, mutation):
    saved = client.get("/demo").json()["snapshot"]
    if mutation == "rate":
        saved["result"]["response"]["values"][0]["dataPoints"][0]["value"] = True
    elif mutation == "dates":
        saved["compare"] = {"before": "2026-09-21", "after": "2026-09-19"}
    else:
        saved["comparisons"] = [{"change_pp": 999}]
    assert client.post("/analyze", json=saved).status_code == 422


def test_reopening_recalculates_from_measurements_not_previous_results(client):
    saved = client.get("/demo?before=2026-09-19&after=2026-09-21").json()["snapshot"]
    saved["result"]["response"]["values"][4]["dataPoints"][2]["value"] = 0.5
    report = client.post("/analyze", json=saved).json()
    assert report["comparisons"][4]["change_pp"] == pytest.approx((0.5 - 0.2753623127937317) * 100)
