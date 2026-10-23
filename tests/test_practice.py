"""Validation without Anki; collection invariants are checked against Anki below."""

import pytest

from holdup.practice import TimedRequest, interval_label, validate_interval
from holdup import i18n


@pytest.mark.parametrize("value", [0, -1, 86401, True, 1.5, "60", None])
def test_interval_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        validate_interval(value)


@pytest.mark.parametrize("language", ["en", "ru"])
@pytest.mark.parametrize("seconds,english,russian", [(1, "1 s", "1 с"), (2, "2 s", "2 с"), (60, "1 min", "1 мин"), (120, "2 min", "2 мин"), (3600, "1 h", "1 ч"), (86400, "1 d", "1 д")])
def test_interval_bounds_and_labels(seconds, english, russian, language, monkeypatch):
    monkeypatch.setattr(i18n, "language", lambda: language)
    assert interval_label(seconds) == (russian if language == "ru" else english)


def test_study_day_label_is_distinct_from_elapsed_day(monkeypatch):
    for language, label, day in (("en", "Study day", "1 d"), ("ru", "Учебный день", "1 д")):
        monkeypatch.setattr(i18n, "language", lambda: language)
        assert interval_label(86400, next_study_day=True) == label
        assert interval_label(86400) == day
    assert TimedRequest(1, 1000, 86400, next_study_day=True).next_study_day
    for seconds, mode in ((2, True), (86400, 1)):
        with pytest.raises(ValueError):
            TimedRequest(1, 1000, seconds, next_study_day=mode)


@pytest.mark.parametrize("args", [(0, 1, 1), (1, -1, 1), (1, True, 1), (1, 2**53, 1), (1, 1, 1, -1), (1, 1, 1, True)])
def test_request_rejects_invalid_identity_time_or_queue(args):
    with pytest.raises(ValueError):
        TimedRequest(*args)


@pytest.mark.parametrize("identity", [None, 1, True, "", "a" * 31, "z" * 32, "A" * 32])
def test_request_rejects_invalid_appearance_identity(identity):
    with pytest.raises(ValueError):
        TimedRequest(1, 1000, 1, request_id=identity)


def test_merge_deadlines_distinguishes_timestamps_days_and_new_positions():
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    from holdup.practice import native_due_ms

    cutoff = datetime(2026, 10, 19, 4)
    now = int(datetime(2026, 10, 18, 16).timestamp() * 1000)
    today = 100
    deadline = lambda queue, due: native_due_ms(SimpleNamespace(queue=queue, due=due), now, today, int(cutoff.timestamp()))
    assert deadline(0, 1) == deadline(0, 9000) == now
    assert deadline(1, now // 1000 - 60) == now - 60000
    assert deadline(1, now // 1000 + 60) == now + 60000
    assert deadline(2, today) == int((cutoff - timedelta(days=1)).timestamp() * 1000)
    assert deadline(3, today - 1) == int((cutoff - timedelta(days=2)).timestamp() * 1000)
    assert deadline(2, today - 1) < deadline(1, now // 1000 - 60) < now
