"""Timed queue tests on disposable real collections, without SQL or fake reviews."""

import json
import time
from contextlib import closing
from datetime import datetime

import pytest

pytest.importorskip("anki")

from anki.collection import Collection
from anki.scheduler.v3 import CardAnswer

from holdup.practice import PracticeQueue, PracticeStateChanged
from holdup.request_store import CustomDataLimitExceeded, InvalidRequestData
from test_anki_contracts import answer_next, review_logs, scheduling_snapshot

pytestmark = pytest.mark.anki_contract


@pytest.fixture
def col(tmp_path):
    collection = Collection(str(tmp_path / "timed.anki2"))
    collection.set_config("fsrs", True)
    note = collection.new_note(collection.models.by_name("Basic"))
    note["Front"], note["Back"] = "Timed question", "Timed answer"
    collection.add_note(note, 1)
    try:
        yield collection
    finally:
        collection.close()


def unchanged_except_pause(before, card):
    actual = scheduling_snapshot(card)
    assert actual.pop("queue") == -1
    assert actual == {key: value for key, value in before.items() if key != "queue"}


@pytest.mark.parametrize("kind", ["new", "learning", "review"])
def test_pause_repeat_release_preserve_schedule_fsrs_and_history_with_undo(col, kind):
    if kind != "new":
        config = col.decks.config_dict_for_deck_id(1)
        config["new"]["delays"] = [1, 10] if kind == "learning" else []
        col.decks.update_config(config)
        answer_next(col, CardAnswer.GOOD)
    card_id = col.find_cards("")[0]
    card = col.get_card(card_id)
    card.custom_data = '{"other":7}'
    col.update_card(card)
    before, logs = scheduling_snapshot(card), review_logs(col, card_id)
    queue = PracticeQueue(col)

    queue.enqueue(card_id, 2, 100000, pause=True)
    request = queue.get(card_id)
    assert request.due_ms == 102000 and request.original_queue == before["queue"]
    assert queue.all() == [request] and queue.available(request)
    unchanged_except_pause(before, col.get_card(card_id))
    assert review_logs(col, card_id) == logs
    assert not col.sched.get_queued_cards().cards
    assert json.loads(col.get_card(card_id).custom_data)["other"] == 7

    step = col.undo_status().last_step
    with pytest.raises(PracticeStateChanged):
        queue.repeat(request, 1, 101999)
    assert col.undo_status().last_step == step
    queue.repeat(request, 1, 102000)
    repeated = queue.get(card_id)
    assert repeated.due_ms == 103000
    assert review_logs(col, card_id) == logs
    unchanged_except_pause(before, col.get_card(card_id))
    with pytest.raises(PracticeStateChanged):
        queue.repeat(request, 1, 104000)  # Duplicate/stale submission.

    col.undo()
    assert queue.get(card_id) == request
    col.undo()
    assert queue.get(card_id) is None
    assert scheduling_snapshot(col.get_card(card_id)) == before
    col.redo()
    col.redo()
    assert queue.get(card_id) == repeated

    queue.release(repeated)
    assert queue.get(card_id) is None
    assert scheduling_snapshot(col.get_card(card_id)) == before
    assert json.loads(col.get_card(card_id).custom_data) == {"other": 7}
    assert review_logs(col, card_id) == logs
    col.undo()
    assert queue.get(card_id) == repeated
    unchanged_except_pause(before, col.get_card(card_id))
    col.redo()
    assert scheduling_snapshot(col.get_card(card_id)) == before
    if kind == "review":
        # A future native due date remains future after release.
        assert not col.sched.get_queued_cards().cards
    else:
        answered = answer_next(col, CardAnswer.GOOD)
        assert answered.reps == before["reps"] + 1
        assert answered.memory_state is not None
        assert len(col.get_review_logs(card_id)) == len(logs) + 1


def test_parallel_request_does_not_pause_or_modify_schedule(col):
    card = col.get_card(col.find_cards("")[0])
    before = scheduling_snapshot(card)
    queue = PracticeQueue(col)
    queue.enqueue(card.id, 86400, 1000)
    request = queue.get(card.id)
    assert request.original_queue is None and request.due_ms == 86401000
    assert scheduling_snapshot(col.get_card(card.id)) == before
    assert col.sched.get_queued_cards().cards
    queue.repeat(request, 1, request.due_ms)
    assert scheduling_snapshot(col.get_card(card.id)) == before
    queue.release(queue.get(card.id))
    assert scheduling_snapshot(col.get_card(card.id)) == before
    assert not col.get_review_logs(card.id)


@pytest.mark.parametrize("rollover", [0, 4, 16, 23])
def test_study_day_uses_anki_boundary_preserves_native_answer_and_undo(col, rollover):
    col.set_config("rollover", rollover)
    queue = PracticeQueue(col)
    queued = col.sched.get_queued_cards().cards[0]
    card = col.get_card(queued.card.id)
    before = scheduling_snapshot(card)
    clock = time.time_ns() // 1_000_000
    cutoff = col.sched.day_cutoff * 1000
    assert datetime.fromtimestamp(cutoff / 1000).hour == rollover
    queue.enqueue(card.id, 2, clock, next_study_day=True)
    request = queue.get(card.id)
    assert request.next_study_day and request.due_ms == cutoff > clock
    assert request.interval_seconds == 86400 and request.original_queue is None
    assert scheduling_snapshot(col.get_card(card.id)) == before
    assert not col.get_review_logs(card.id)
    assert json.loads(col.get_card(card.id).custom_data)["odbnext"] == 1
    col.undo()
    assert queue.get(card.id) is None
    col.redo()
    assert queue.get(card.id) == request
    # Cached native states and all normal FSRS handling remain usable.
    card.start_timer()
    col.sched.answer_card(col.sched.build_answer(card=card, states=queued.states, rating=CardAnswer.GOOD))
    assert queue.get(card.id) == request and len(col.get_review_logs(card.id)) == 1
    assert col.get_card(card.id).memory_state is not None


@pytest.mark.parametrize("remaining_ms", [1, 90000000])
def test_calendar_delay_can_be_shorter_than_second_or_longer_than_24_hours(col, monkeypatch, remaining_ms):
    queue = PracticeQueue(col)
    cid = col.find_cards("")[0]
    cutoff = col.sched.day_cutoff * 1000
    clock = cutoff - remaining_ms
    # Simulate the boundary supplied by Anki, including a 25-hour DST day.
    monkeypatch.setattr(type(col.sched), "day_cutoff", property(lambda _self: cutoff // 1000))
    queue.enqueue(cid, 86400, clock, next_study_day=True)
    assert queue.get(cid).due_ms == cutoff
    assert queue.get(cid).due_ms - clock == remaining_ms
    queue.enqueue(cid, 86400, clock)
    assert queue.get(cid).due_ms == clock + 86400000
    assert not queue.get(cid).next_study_day
    assert json.loads(col.get_card(cid).custom_data)["odbv"] == 2
    assert "odbnext" not in json.loads(col.get_card(cid).custom_data)


def test_calendar_repeat_and_release_preserve_other_data_and_history(col):
    cid = col.find_cards("")[0]
    card = col.get_card(cid)
    card.custom_data = '{"other":7}'
    col.update_card(card)
    before = scheduling_snapshot(card)
    queue = PracticeQueue(col)
    clock = time.time_ns() // 1_000_000
    queue.enqueue(cid, 1, clock - 2000)
    old = queue.get(cid)
    queue.repeat(old, 1, clock, next_study_day=True)
    request = queue.get(cid)
    assert request.next_study_day and request.due_ms == col.sched.day_cutoff * 1000
    col.undo()
    assert queue.get(cid) == old
    col.redo()
    assert queue.get(cid) == request
    # Changing the preference does not rewrite an existing deadline.
    col.set_config("rollover", (col.get_config("rollover", 4) + 1) % 24)
    assert queue.get(cid) == request
    queue.release(request)
    assert json.loads(col.get_card(cid).custom_data) == {"other": 7}
    assert scheduling_snapshot(col.get_card(cid)) == before and not col.get_review_logs(cid)


def test_calendar_request_survives_collection_reopen(tmp_path):
    path = str(tmp_path / "calendar-reopen.anki2")
    with closing(Collection(path)) as collection:
        note = collection.new_note(collection.models.by_name("Basic"))
        note["Front"], note["Back"] = "Calendar", "Persist"
        collection.add_note(note, 1)
        cid = note.card_ids()[0]
        PracticeQueue(collection).enqueue(cid, 2, time.time_ns() // 1_000_000, next_study_day=True)
        expected = PracticeQueue(collection).get(cid)
    with closing(Collection(path)) as reopened:
        assert PracticeQueue(reopened).get(cid) == expected
        assert not reopened.get_review_logs(cid)


@pytest.mark.parametrize("data", [
    {"odbv": 3, "odbat": 1000, "odbsecs": 86400},
    {"odbv": 3, "odbat": 1000, "odbsecs": 86400, "odbnext": True},
    {"odbv": 3, "odbat": 1000, "odbsecs": 2, "odbnext": 1},
    {"odbv": 2, "odbat": 1000, "odbsecs": 86400, "odbnext": 1},
])
def test_mixed_calendar_metadata_is_not_overwritten(col, data):
    card = col.get_card(col.find_cards("")[0])
    card.custom_data = json.dumps(data)
    col.update_card(card)
    step = col.undo_status().last_step
    with pytest.raises(InvalidRequestData):
        PracticeQueue(col).enqueue(card.id, 2, 1000)
    assert col.get_card(card.id).custom_data == card.custom_data
    assert col.undo_status().last_step == step


def test_calendar_budget_failure_and_stale_cutoff_write_nothing(col, monkeypatch):
    card = col.get_card(col.find_cards("")[0])
    card.custom_data = json.dumps({"other": "x" * 40})
    col.update_card(card)
    queue = PracticeQueue(col)
    step = col.undo_status().last_step
    clock = time.time_ns() // 1_000_000
    with pytest.raises(CustomDataLimitExceeded):
        queue.enqueue(card.id, 2, clock, next_study_day=True)
    monkeypatch.setattr(type(col.sched), "day_cutoff", property(lambda _self: clock // 1000))
    with pytest.raises(PracticeStateChanged):
        queue.enqueue(card.id, 2, clock, next_study_day=True)
    assert col.get_card(card.id).custom_data == card.custom_data
    assert col.undo_status().last_step == step and not col.get_review_logs(card.id)


def test_budget_failure_does_not_pause_card_or_add_undo(col):
    card = col.get_card(col.find_cards("")[0])
    card.custom_data = json.dumps({"other": "x" * 75})
    col.update_card(card)
    raw, before, undo = card.custom_data, scheduling_snapshot(card), col.undo_status().last_step
    with pytest.raises(CustomDataLimitExceeded):
        PracticeQueue(col).enqueue(card.id, 86400, 1792300000000)
    assert scheduling_snapshot(col.get_card(card.id)) == before
    assert col.get_card(card.id).custom_data == raw
    assert col.undo_status().last_step == undo
    assert not col.get_review_logs(card.id)


@pytest.mark.parametrize("data", [{"odbv": 1, "odbday": 5}, {"odbv": 9}, {"odbv": 2}, {"odbv": 2, "odbat": -1, "odbsecs": 2}])
def test_unknown_or_broken_metadata_is_not_overwritten(col, data):
    card = col.get_card(col.find_cards("")[0])
    card.custom_data = json.dumps(data)
    col.update_card(card)
    with pytest.raises(InvalidRequestData):
        PracticeQueue(col).enqueue(card.id, 2, 1000)
    assert col.get_card(card.id).custom_data == card.custom_data
    assert col.get_card(card.id).queue == card.queue


def test_external_queue_change_is_preserved_on_release(col):
    card_id = col.find_cards("")[0]
    queue = PracticeQueue(col)
    queue.enqueue(card_id, 2, 1000)
    request = queue.get(card_id)
    card = col.get_card(card_id)
    card.queue = -2  # An independent user action while a request exists.
    col.update_card(card)
    assert not queue.available(request)
    with pytest.raises(PracticeStateChanged):
        queue.repeat(request, 2, request.due_ms)
    queue.release(request)
    assert col.get_card(card_id).queue == -2
    assert queue.get(card_id) is None


def test_release_all_is_one_undoable_batch_and_stale_batch_writes_nothing(col):
    second = col.new_note(col.models.by_name("Basic"))
    second["Front"], second["Back"] = "Second", "Batch"
    col.add_note(second, 1)
    ids = col.find_cards("")
    queue = PracticeQueue(col)
    for cid in ids:
        queue.enqueue(cid, 2, 1000, pause=True)
    original = queue.all()
    queue.repeat(original[1], 2, 3000)
    step = col.undo_status().last_step
    with pytest.raises(PracticeStateChanged):
        queue.release_all(original)
    assert col.undo_status().last_step == step
    assert all(col.get_card(cid).queue == -1 for cid in ids)
    current = queue.all()
    queue.release_all(current)
    assert not queue.all()
    assert all(col.get_card(cid).queue == 0 for cid in ids)
    col.undo()
    assert queue.all() == current
    assert all(col.get_card(cid).queue == -1 and not col.get_review_logs(cid) for cid in ids)


def test_timed_request_survives_reopen(tmp_path):
    path = str(tmp_path / "reopen.anki2")
    with closing(Collection(path)) as col:
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"], note["Back"] = "Persist", "Request"
        col.add_note(note, 1)
        card_id = note.card_ids()[0]
        PracticeQueue(col).enqueue(card_id, 1, 1000, pause=True)
    with closing(Collection(path)) as reopened:
        request = PracticeQueue(reopened).get(card_id)
        assert request.due_ms == 2000 and request.original_queue == 0
        assert reopened.get_card(card_id).queue == -1
        assert not reopened.get_review_logs(card_id)


def test_native_answer_with_cached_states_preserves_request_and_removal(col):
    """Reviewer need not reset when only practice metadata changes."""
    queue = PracticeQueue(col)
    queued = col.sched.get_queued_cards().cards[0]
    card = col.get_card(queued.card.id)
    card.start_timer()
    queue.enqueue(card.id, 2, 1000)
    expected = queue.get(card.id)
    answer = col.sched.build_answer(card=card, states=queued.states, rating=CardAnswer.GOOD)
    col.sched.answer_card(answer)
    assert queue.get(card.id) == expected
    assert len(col.get_review_logs(card.id)) == 1
    assert col.get_card(card.id).memory_state is not None

    queued = col.sched.get_queued_cards().cards[0]
    cached = col.get_card(queued.card.id)
    cached.start_timer()
    queue.release(expected)
    answer = col.sched.build_answer(card=cached, states=queued.states, rating=CardAnswer.GOOD)
    col.sched.answer_card(answer)
    assert queue.get(card.id) is None
    assert len(col.get_review_logs(card.id)) == 2


@pytest.mark.parametrize("rating", [CardAnswer.AGAIN, CardAnswer.HARD, CardAnswer.GOOD, CardAnswer.EASY])
def test_all_native_ratings_after_holdup_preserve_virtual_request(col, rating):
    queue = PracticeQueue(col)
    queued = col.sched.get_queued_cards().cards[0]
    card = col.get_card(queued.card.id)
    before = scheduling_snapshot(card)
    ids = col.find_cards("")
    card.start_timer()
    queue.enqueue(card.id, 2, 1000)
    expected = queue.get(card.id)
    assert expected.original_queue is None
    assert scheduling_snapshot(col.get_card(card.id)) == before
    assert not col.get_review_logs(card.id)
    assert col.sched.get_queued_cards().cards[0].card.id == card.id
    answer = col.sched.build_answer(card=card, states=queued.states, rating=rating)
    col.sched.answer_card(answer)
    assert queue.get(card.id) == expected
    logs = col.get_review_logs(card.id)
    assert len(logs) == 1 and logs[0].button_chosen == rating + 1
    assert col.get_card(card.id).memory_state is not None
    assert col.find_cards("") == ids  # No physical card/note is duplicated.
    after = scheduling_snapshot(col.get_card(card.id))
    queue.repeat(expected, 1, expected.due_ms)
    assert scheduling_snapshot(col.get_card(card.id)) == after
    assert len(col.get_review_logs(card.id)) == 1
    queue.release(queue.get(card.id))
    assert scheduling_snapshot(col.get_card(card.id)) == after


def test_virtual_requests_do_not_refill_or_bypass_daily_new_limit(col):
    config = col.decks.config_dict_for_deck_id(1)
    config["new"]["perDay"] = 2
    config["new"]["delays"] = []
    col.decks.update_config(config)
    for index in range(9):
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"], note["Back"] = f"New limit {index}", "Answer"
        col.add_note(note, 1)
    all_ids = set(col.find_cards(""))
    assert len(all_ids) == 10
    queue = PracticeQueue(col)
    introduced = []
    for remaining in (2, 1):
        queued = col.sched.get_queued_cards()
        assert queued.new_count == remaining
        cid = queued.cards[0].card.id
        introduced.append(cid)
        before = scheduling_snapshot(col.get_card(cid))
        for clock in (1000, 2000, 3000):
            queue.enqueue(cid, 1, clock)
            current = col.sched.get_queued_cards()
            assert current.new_count == remaining
            assert current.cards[0].card.id == cid  # No replacement with a new word.
            assert scheduling_snapshot(col.get_card(cid)) == before
        answered = answer_next(col, CardAnswer.GOOD)
        assert answered.id == cid and len(col.get_review_logs(cid)) == 1
    assert len(set(introduced)) == 2
    assert not col.sched.get_queued_cards().cards
    assert col.sched.counts() == (0, 0, 0)
    assert set(col.find_cards("is:new")) == all_ids - set(introduced)
    assert len(queue.all()) == 2 and set(col.find_cards("")) == all_ids
    # Practice and its removal don't replenish the native daily allowance.
    for request in queue.all():
        queue.repeat(request, 1, request.due_ms)
        assert not col.sched.get_queued_cards().cards
        queue.release(queue.get(request.card_id))
        assert not col.sched.get_queued_cards().cards
    assert set(col.find_cards("is:new")) == all_ids - set(introduced)


@pytest.mark.parametrize("kind", ["new", "learning", "review"])
def test_upgrade_resumes_native_without_losing_practice_or_fsrs_with_undo(col, kind):
    if kind != "new":
        config = col.decks.config_dict_for_deck_id(1)
        config["new"]["delays"] = [1, 10] if kind == "learning" else []
        col.decks.update_config(config)
        answer_next(col, CardAnswer.GOOD)
    cid = col.find_cards("")[0]
    card = col.get_card(cid)
    card.custom_data = '{"other":7}'
    col.update_card(card)
    before, logs = scheduling_snapshot(card), review_logs(col, cid)
    queue = PracticeQueue(col)
    queue.enqueue(cid, 86400, 1000, pause=True)  # An existing paused request.
    paused = queue.get(cid)
    queue.resume_native([paused])
    resumed = queue.get(cid)
    assert resumed.original_queue is None
    assert resumed.due_ms == paused.due_ms and resumed.interval_seconds == paused.interval_seconds
    assert json.loads(col.get_card(cid).custom_data)["other"] == 7
    assert scheduling_snapshot(col.get_card(cid)) == before and review_logs(col, cid) == logs
    col.undo()
    assert queue.get(cid) == paused and col.get_card(cid).queue == -1
    col.redo()
    assert queue.get(cid) == resumed and scheduling_snapshot(col.get_card(cid)) == before
    queue.release(resumed)
    assert scheduling_snapshot(col.get_card(cid)) == before and review_logs(col, cid) == logs


def test_upgrade_batch_preflights_and_preserves_external_queue_changes(col):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"], note["Back"] = "Another old pause", "Answer"
    col.add_note(note, 1)
    queue = PracticeQueue(col)
    ids = col.find_cards("")
    for cid in ids:
        queue.enqueue(cid, 2, 1000, pause=True)
    stale = queue.all()
    queue.repeat(stale[1], 2, stale[1].due_ms)
    undo_step = col.undo_status().last_step
    with pytest.raises(PracticeStateChanged):
        queue.resume_native(stale)
    assert col.undo_status().last_step == undo_step
    assert all(col.get_card(cid).queue == -1 for cid in ids)
    card = col.get_card(ids[0])
    card.queue = -2  # A subsequent explicit user action must survive upgrade.
    col.update_card(card)
    queue.resume_native(queue.all())
    assert col.get_card(ids[0]).queue == -2 and col.get_card(ids[1]).queue == 0
    assert all(request.original_queue is None for request in queue.all())
    assert all(not col.get_review_logs(cid) for cid in ids)
    col.undo()
    assert col.get_card(ids[0]).queue == -2 and col.get_card(ids[1]).queue == -1
    assert all(request.original_queue is not None for request in queue.all())
