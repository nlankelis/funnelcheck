"""Calendar boundaries and user-supplied timing are not measured effects."""

from datetime import date, datetime, timezone

import pytest

from funnelcheck.funnel import DataError, FunnelQuery
from funnelcheck.updates import RecordedUpdate, build_update_context, update_in_utc


def recorded(local="2026-09-20T04:00", zone="Europe/London", approximate=True):
    return RecordedUpdate("Tutorial explanation update", local, zone, approximate)


def query(start="2026-09-19", end="2026-09-22"):
    return FunnelQuery("10765553159", "MatchCompletion_v2", date.fromisoformat(start), date.fromisoformat(end), ("1", "2"))


def test_reported_tutorial_time_and_surrounding_full_days():
    result = build_update_context(recorded(), query())
    assert result.occurred_at_utc == datetime(2026, 9, 20, 3, tzinfo=timezone.utc)
    assert [item.phase for item in result.cohorts] == ["before", "transition", "after"]
    assert result.suggested_comparison.before == date(2026, 9, 19)
    assert result.suggested_comparison.after == date(2026, 9, 21)
    assert result.update.approximate is True
    assert any("no uncertainty range" in note for note in result.notes)


@pytest.mark.parametrize("local, zone, utc", [
    ("2026-01-20T04:00", "Europe/London", "2026-01-20T04:00:00+00:00"),
    ("2026-09-20T00:30", "Europe/London", "2026-09-19T23:30:00+00:00"),
    ("2026-09-20T04:00", "UTC", "2026-09-20T04:00:00+00:00"),
])
def test_winter_and_local_date_rollover(local, zone, utc):
    assert update_in_utc(recorded(local, zone)).isoformat() == utc


@pytest.mark.parametrize("local, message", [
    ("2026-03-29T01:30", "does not exist"),
    ("2026-10-25T01:30", "occurs twice"),
    ("2026-02-30T04:00", "invalid"),
    ("2026-09-20T04:00Z", "format"),
    ("2026-09-20", "format"),
])
def test_bad_or_ambiguous_local_times_are_not_guessed(local, message):
    with pytest.raises(DataError, match=message):
        update_in_utc(recorded(local))


def test_midnight_is_after_with_no_transition_day():
    result = build_update_context(recorded("2026-09-20T01:00", approximate=False), query())
    assert [item.phase for item in result.cohorts] == ["before", "after", "after"]
    assert result.suggested_comparison.after == date(2026, 9, 20)
    assert not any("approximate" in note for note in result.notes)


@pytest.mark.parametrize("time, phase", [("2026-09-18T03:00", "after"), ("2026-09-23T03:00", "before")])
def test_window_on_one_side_has_no_invented_comparison(time, phase):
    result = build_update_context(recorded(time), query())
    assert result.suggested_comparison is None
    assert all(item.phase == phase for item in result.cohorts)
    assert any("does not span" in note for note in result.notes)


def test_transition_comparison_is_descriptive_and_explicitly_labelled():
    result = build_update_context(recorded(), query(), (date(2026, 9, 19), date(2026, 9, 20)))
    assert any("selected comparison does not pair" in note for note in result.notes)
