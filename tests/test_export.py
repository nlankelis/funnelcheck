import copy
from datetime import date
import json

from fastapi.testclient import TestClient
import pytest

from funnelcheck.__main__ import main
from funnelcheck.export import save_response
from funnelcheck.funnel import DataError, FunnelQuery, parse_rates
from funnelcheck.server import EXAMPLE, app


@pytest.fixture
def query():
    context = EXAMPLE["query"]
    return FunnelQuery(context["universe_id"], context["funnel_name"], date.fromisoformat(context["start"]), date.fromisoformat(context["end_exclusive"]), tuple(context["step_ids"]))


def test_export_round_trips_all_measurements_and_is_accepted_by_http_api(tmp_path, query):
    path = tmp_path / "nested" / "snapshot.json"
    envelope = copy.deepcopy(EXAMPLE["result"])
    original = copy.deepcopy(envelope)
    assert save_response(path, query, envelope) == path.resolve()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert parse_rates(saved["result"], query) == parse_rates(envelope, query)
    assert envelope == original
    assert saved["query"] == EXAMPLE["query"]
    with TestClient(app) as client:
        response = client.post("/analyze", json=saved)
    assert response.status_code == 200 and len(response.json()["rows"]) == 15
    assert response.json()["rows"][4]["completion_rate"] == 0.2753623127937317


def test_export_drops_unneeded_metadata_and_preserves_statuses_and_gaps(tmp_path, query):
    envelope = copy.deepcopy(EXAMPLE["result"])
    envelope["headers"] = {"x-api-key": "fake-secret-that-must-not-be-saved"}
    envelope["metadata"] = {"secret": "fake-secret-that-must-not-be-saved"}
    envelope["path"] = "irrelevant operation path"
    point = envelope["response"]["values"][0]["dataPoints"][0]
    point["extra"] = "fake-secret-that-must-not-be-saved"
    point["status"] = "Projected"
    envelope["response"]["values"][4]["dataPoints"].pop()
    path = tmp_path / "snapshot.json"
    save_response(path, query, envelope)
    text = path.read_text(encoding="utf-8")
    assert "fake-secret" not in text and "irrelevant operation" not in text
    rows = parse_rates(json.loads(text)["result"], query)
    assert len(rows) == 14 and rows[0].status == "Projected"
    with TestClient(app) as client:
        report = client.post("/analyze", json=json.loads(text)).json()
    assert report["validation_notes"]


@pytest.mark.parametrize("envelope", [{"done": False}, {"done": True, "error": {"code": 1}}])
def test_failed_or_pending_responses_create_no_file(tmp_path, query, envelope):
    path = tmp_path / "nested" / "snapshot.json"
    with pytest.raises(DataError):
        save_response(path, query, envelope)
    assert not path.parent.exists()


def test_never_overwrites_existing_file(tmp_path, query):
    path = tmp_path / "snapshot.json"
    path.write_text("existing snapshot", encoding="utf-8")
    with pytest.raises(DataError, match="already exists"):
        save_response(path, query, EXAMPLE["result"])
    assert path.read_text(encoding="utf-8") == "existing snapshot"


def test_demo_output_is_importable_without_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ROBLOX_API_KEY", raising=False)
    path = tmp_path / "demo.json"
    assert main(["demo", "--output", str(path)]) == 0
    assert "Saved snapshot:" in capsys.readouterr().out
    with TestClient(app) as client:
        assert client.post("/analyze", json=json.loads(path.read_text(encoding="utf-8"))).status_code == 200


@pytest.mark.parametrize("existing", [True, False])
def test_bad_output_path_fails_before_asking_for_key_or_fetching(tmp_path, monkeypatch, capsys, existing):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid output path must fail before credentials or HTTP")
    monkeypatch.setattr("funnelcheck.__main__.getpass.getpass", unexpected)
    monkeypatch.setattr("funnelcheck.__main__.fetch_rates", unexpected)
    path = tmp_path / ("taken.json" if existing else "wrong.csv")
    if existing:
        path.write_text("original", encoding="utf-8")
    assert main(["fetch", "--universe", "1", "--funnel", "Test", "--start", "2026-09-19", "--end-exclusive", "2026-09-22", "--steps", "1", "--output", str(path)]) == 1
    assert "Error:" in capsys.readouterr().out


def test_fetch_output_does_not_save_key(tmp_path, monkeypatch, capsys):
    key = "fake-test-key-never-save"
    monkeypatch.setenv("ROBLOX_API_KEY", key)
    def fake_fetch(query, received_key):
        assert received_key == key
        return copy.deepcopy(EXAMPLE["result"])
    monkeypatch.setattr("funnelcheck.__main__.fetch_rates", fake_fetch)
    path = tmp_path / "fetched.json"
    assert main(["fetch", "--universe", "10765553159", "--funnel", "MatchCompletion_v2", "--start", "2026-09-19", "--end-exclusive", "2026-09-22", "--steps", "1", "2", "3", "4", "5", "--output", str(path)]) == 0
    assert key not in path.read_text(encoding="utf-8")
    assert key not in capsys.readouterr().out
