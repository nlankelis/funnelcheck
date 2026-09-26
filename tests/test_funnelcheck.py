import copy
import csv
from datetime import date
import json
from pathlib import Path

import httpx
import pytest

from funnelcheck.__main__ import main
from funnelcheck.api import BASE_URL, RobloxAPIError, fetch_rates
from funnelcheck.funnel import DataError, FunnelQuery, parse_rates, validation_notes


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def query():
    return FunnelQuery("10765553159", "MatchCompletion_v2", date(2026, 9, 19), date(2026, 9, 22), ("1", "2", "3", "4", "5"))


@pytest.fixture
def envelope():
    return json.loads((ROOT / "examples/matchcompletion.json").read_text(encoding="utf-8"))["result"]


def test_api_example_matches_all_15_export_values(envelope, query):
    rows = parse_rates(envelope, query)
    with (ROOT / "tests/fixtures/matchcompletion_rates.csv").open(newline="", encoding="utf-8") as source:
        expected = {
            (date.fromisoformat(item["Date"][:10]), item["Step"].split(". ", 1)[0]):
            (item["Step"].split(". ", 1)[1], float(item["Session cohort completion rate"]))
            for item in csv.DictReader(source)
        }
    actual = {(row.cohort_date, row.step_id): (row.step_name, row.completion_rate) for row in rows}
    assert len(actual) == 15
    assert actual == expected
    assert validation_notes(rows, query) == []


def test_parser_sorts_and_does_not_modify_or_round_input(envelope, query):
    envelope["response"]["values"].reverse()
    for series in envelope["response"]["values"]:
        series["dataPoints"].reverse()
    original = copy.deepcopy(envelope)
    rows = parse_rates(envelope, query)
    assert [(row.cohort_date.day, row.step_id) for row in rows] == [
        (day, str(step)) for day in (19, 20, 21) for step in range(1, 6)
    ]
    assert rows[4].completion_rate == 0.2753623127937317
    assert envelope == original


@pytest.mark.parametrize("value", [None, "0.5", True, False, -0.01, 1.01, float("nan"), float("inf")])
def test_invalid_rates_are_rejected(envelope, query, value):
    envelope["response"]["values"][0]["dataPoints"][0]["value"] = value
    with pytest.raises(DataError, match="finite number"):
        parse_rates(envelope, query)


@pytest.mark.parametrize("timestamp", ["bad", "2026-09-19", "2026-09-19T00:00:00", "2026-09-19T12:00:00Z", "2026-09-22T00:00:00Z", "2026-09-18T00:00:00Z"])
def test_invalid_or_out_of_window_dates_are_rejected(envelope, query, timestamp):
    envelope["response"]["values"][0]["dataPoints"][0]["time"] = timestamp
    with pytest.raises(DataError):
        parse_rates(envelope, query)


@pytest.mark.parametrize("timestamp", ["2026-09-19T00:00:00.000Z", "2026-09-19T01:00:00+01:00"])
def test_equivalent_utc_timestamps_are_normalized(envelope, query, timestamp):
    envelope["response"]["values"][0]["dataPoints"][0]["time"] = timestamp
    assert parse_rates(envelope, query)[0].cohort_date == date(2026, 9, 19)


def test_duplicate_pairs_are_rejected(envelope, query):
    series = envelope["response"]["values"][0]
    series["dataPoints"].append(copy.deepcopy(series["dataPoints"][0]))
    with pytest.raises(DataError, match="Duplicate"):
        parse_rates(envelope, query)


def test_extra_segments_cannot_be_accidentally_pooled(envelope, query):
    envelope["response"]["values"][0]["breakdowns"].append({"dimension": "Platform", "value": "Phone"})
    with pytest.raises(DataError, match="segmented data"):
        parse_rates(envelope, query)


def test_unrequested_steps_are_rejected(envelope, query):
    envelope["response"]["values"][0]["breakdowns"][0]["value"] = "99"
    with pytest.raises(DataError, match="unrequested"):
        parse_rates(envelope, query)


def test_missing_rows_stay_missing_and_are_reported(envelope, query):
    envelope["response"]["values"][4]["dataPoints"].pop()
    rows = parse_rates(envelope, query)
    assert len(rows) == 14
    assert any("2026-09-21: missing steps 5" in note for note in validation_notes(rows, query))


def test_empty_response_is_not_zero_conversion(query):
    rows = parse_rates({"done": True, "response": {"values": []}}, query)
    assert rows == []
    assert sum("missing steps" in note for note in validation_notes(rows, query)) == 3


def test_all_zero_cohort_is_flagged_without_replacing_values(envelope, query):
    for series in envelope["response"]["values"]:
        series["dataPoints"][0]["value"] = 0
    rows = parse_rates(envelope, query)
    assert all(row.completion_rate == 0 for row in rows[:5])
    assert any("do not interpret as 100% abandonment" in note for note in validation_notes(rows, query))


def test_increasing_rates_are_flagged(envelope, query):
    envelope["response"]["values"][4]["dataPoints"][0]["value"] = 0.8
    assert any("increases from step 4 to 5" in note for note in validation_notes(parse_rates(envelope, query), query))


def test_roblox_status_is_preserved_and_flagged(envelope, query):
    envelope["response"]["values"][0]["dataPoints"][0]["status"] = "Projected"
    rows = parse_rates(envelope, query)
    assert rows[0].status == "Projected"
    assert any("Projected" in note for note in validation_notes(rows, query))


def test_incomplete_or_failed_responses_are_not_parsed(query):
    for payload in ({"done": False}, {"done": True, "error": {"code": 2001}}, {"done": True}, {"done": True, "response": {"values": None}}):
        with pytest.raises(DataError):
            parse_rates(payload, query)


def test_invalid_query_prevents_an_http_request():
    with pytest.raises(DataError, match="before"):
        FunnelQuery("1", "Test", date(2026, 9, 22), date(2026, 9, 19), ("1",))
    with pytest.raises(DataError, match="unique"):
        FunnelQuery("1", "Test", date(2026, 9, 19), date(2026, 9, 22), ("1", "1"))


def test_immediate_result_needs_only_post(query, envelope):
    calls = []
    def handle(request):
        calls.append(request)
        assert request.headers["x-api-key"] == "fake-test-key"
        payload = json.loads(request.content)
        assert payload["metric"] == "FunnelCohortSessionCompletionRate"
        assert payload["granularity"] == "OneDay"
        assert payload["endTime"] == "2026-09-22T00:00:00Z"
        assert payload["filter"][0]["values"] == ["MatchCompletion_v2"]
        return httpx.Response(200, json=envelope)
    result = fetch_rates(query, "fake-test-key", transport=httpx.MockTransport(handle))
    assert result == envelope
    assert len(calls) == 1 and calls[0].method == "POST"


def test_pending_operation_is_polled_without_resubmitting(query, envelope):
    calls = []
    sleeps = []
    path = f"v1/universes/{query.universe_id}/operations/metrics/test123"
    def handle(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(202, json={"done": False, "path": path})
        return httpx.Response(200, json=envelope)
    result = fetch_rates(query, "fake-test-key", transport=httpx.MockTransport(handle), sleep=sleeps.append)
    assert result == envelope
    assert [request.method for request in calls] == ["POST", "GET", "GET"]
    assert str(calls[1].url) == BASE_URL + path
    assert calls[1].content == b""
    assert sleeps == [2.0, 2.0]


@pytest.mark.parametrize("path", ["https://example.com/steal", "v1/universes/999/operations/metrics/a", "../metrics", "v1/universes/10765553159/operations/metrics/a?secret=1"])
def test_untrusted_poll_path_never_receives_a_key(query, path):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(202, json={"done": False, "path": path})
    with pytest.raises(RobloxAPIError, match="polling path"):
        fetch_rates(query, "fake-test-key", transport=httpx.MockTransport(handle))
    assert len(calls) == 1


def test_polling_stops_and_provides_resume_path(query):
    calls = []
    path = f"v1/universes/{query.universe_id}/operations/metrics/test123"
    def handle(request):
        calls.append(request.method)
        return httpx.Response(202, json={"done": False, "path": path})
    with pytest.raises(RobloxAPIError, match="Resume with GET"):
        fetch_rates(query, "fake-test-key", max_polls=2, sleep=lambda _: None, transport=httpx.MockTransport(handle))
    assert calls == ["POST", "GET", "GET"]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
def test_http_failures_are_readable_and_do_not_echo_server_body(query, status):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text="fake-test-key"))
    with pytest.raises(RobloxAPIError, match=f"HTTP {status}") as error:
        fetch_rates(query, "fake-test-key", transport=transport)
    assert "fake-test-key" not in str(error.value)


def test_operation_error_inside_http_200_is_still_a_failure(query):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "done": True, "error": {"code": 2001, "message": "Bad query fake-test-key"},
    }))
    with pytest.raises(RobloxAPIError, match="2001") as error:
        fetch_rates(query, "fake-test-key", transport=transport)
    assert "fake-test-key" not in str(error.value)


def test_timeout_has_a_clear_message(query):
    def handle(request):
        raise httpx.ReadTimeout("private details", request=request)
    with pytest.raises(RobloxAPIError, match="timed out"):
        fetch_rates(query, "fake-test-key", transport=httpx.MockTransport(handle))


def test_redirects_are_not_followed(query):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://example.com"})
    with pytest.raises(RobloxAPIError, match="HTTP 302"):
        fetch_rates(query, "fake-test-key", transport=httpx.MockTransport(handle))
    assert len(calls) == 1


def test_demo_runs_without_network_or_credentials(monkeypatch, capsys):
    monkeypatch.delenv("ROBLOX_API_KEY", raising=False)
    def unexpected_fetch(*args, **kwargs):
        pytest.fail("The demo must not use the network")
    monkeypatch.setattr("funnelcheck.__main__.fetch_rates", unexpected_fetch)
    assert main(["demo"]) == 0
    output = capsys.readouterr().out
    assert "15 records; 0 validation notes" in output
    assert "27.54%" in output and "65.22%" in output
