"""Independent extra appearances of one card, including old saved data and Undo."""

from contextlib import closing
import json
import time

import pytest

pytest.importorskip("anki")

from anki.collection import Collection
from anki.scheduler.v3 import CardAnswer
from holdup.practice import CONFIG_KEY, PracticeQueue, PracticeStateChanged
from test_anki_contracts import scheduling_snapshot, review_logs
from test_practice_anki import col

pytestmark = pytest.mark.anki_contract


def test_second_native_appearance_adds_an_item_and_undo_redo_keeps_both_histories(col):
    queue = PracticeQueue(col)
    first_head = col.sched.get_queued_cards().cards[0]
    card = col.get_card(first_head.card.id)
    before = scheduling_snapshot(card)
    queue.enqueue(card.id, 3600, 1000)
    first = queue.get(card.id)
    card.start_timer()
    col.sched.answer_card(col.sched.build_answer(card=card, states=first_head.states, rating=CardAnswer.GOOD))
    learning = scheduling_snapshot(col.get_card(card.id))
    second_head = col.sched.get_queued_cards().cards[0]
    assert second_head.card.id == card.id
    changes = queue.enqueue(card.id, 7200, 2000)
    second = queue.get(card.id)
    assert first.request_id != second.request_id
    assert queue.for_card(card.id) == [first, second]
    assert not changes.study_queues and not changes.card
    assert scheduling_snapshot(col.get_card(card.id)) == learning
    current = col.get_card(card.id)
    current.start_timer()
    col.sched.answer_card(col.sched.build_answer(card=current, states=second_head.states, rating=CardAnswer.EASY))
    assert len(review_logs(col, card.id)) == 2
    col.undo()
    assert scheduling_snapshot(col.get_card(card.id)) == learning
    assert queue.for_card(card.id) == [first, second]
    col.undo()
    assert queue.for_card(card.id) == [first]
    assert len(review_logs(col, card.id)) == 1
    col.undo()
    assert scheduling_snapshot(col.get_card(card.id)) == before
    assert queue.for_card(card.id) == [first] and not review_logs(col, card.id)
    col.undo()
    assert queue.for_card(card.id) == []
    for _ in range(4):
        col.redo()
    assert queue.for_card(card.id) == [first, second]
    assert len(review_logs(col, card.id)) == 2


@pytest.mark.parametrize("next_study_day", [False, True])
def test_equal_deadlines_have_distinct_identities_and_done_affects_only_one(col, next_study_day):
    cid = col.find_cards("")[0]
    queue = PracticeQueue(col)
    clock = time.time_ns() // 1_000_000
    for _ in range(2):
        queue.enqueue(cid, 1, clock, next_study_day=next_study_day)
    first, second = queue.for_card(cid)
    assert first.due_ms == second.due_ms and first != second
    before = scheduling_snapshot(col.get_card(cid))
    queue.release(first)
    assert queue.for_card(cid) == [second]
    with pytest.raises(PracticeStateChanged):
        queue.release(first)
    assert queue.for_card(cid) == [second]
    col.undo()
    assert queue.for_card(cid) == [first, second]
    col.redo()
    assert queue.for_card(cid) == [second]
    assert scheduling_snapshot(col.get_card(cid)) == before
    assert not review_logs(col, cid)


def test_repeat_preserves_identity_and_other_appearance_including_stale_commands(col):
    cid = col.find_cards("")[0]
    queue = PracticeQueue(col)
    for _ in range(2):
        queue.enqueue(cid, 1, 1000)
    first, second = queue.for_card(cid)
    queue.repeat(first, 7200, 3000)
    repeated = queue.get(cid, first.request_id)
    assert repeated.request_id == first.request_id and repeated.due_ms == 7203000
    assert queue.get(cid, second.request_id) == second
    assert queue.all() == [second, repeated]
    for operation in (lambda: queue.release(first), lambda: queue.repeat(first, 1, 4000)):
        step = col.undo_status().last_step
        with pytest.raises(PracticeStateChanged):
            operation()
        assert col.undo_status().last_step == step
        assert queue.all() == [second, repeated]
    col.undo()
    assert queue.for_card(cid) == [first, second]
    col.redo()
    assert queue.all() == [second, repeated]
    queue.release(second)
    assert queue.all() == [repeated]


@pytest.mark.parametrize("storage", ["config", "metadata", "cleared"])
def test_adding_to_old_storage_preserves_appointments_and_undo_restores_exact_format(col, storage):
    cid = col.find_cards("")[0]
    card = col.get_card(cid)
    card.custom_data = json.dumps({"odbv": 2, "odbat": 2000, "odbsecs": 1, "other": 7})
    col.update_card(card)
    if storage != "metadata":
        col.set_config(CONFIG_KEY, {"v": 1, "cards": {str(cid): None if storage == "cleared" else [3000, 2, False]}})
    raw = col.get_config(CONFIG_KEY)
    queue = PracticeQueue(col)
    old = queue.for_card(cid)
    before = scheduling_snapshot(card)
    step = col.undo_status().last_step
    assert col.get_config(CONFIG_KEY) == raw and col.undo_status().last_step == step
    queue.enqueue(cid, 3600, 4000)
    added = queue.get(cid)
    assert queue.for_card(cid) == old + [added]
    assert col.get_config(CONFIG_KEY)["v"] == 2
    assert col.get_card(cid).custom_data == card.custom_data
    col.undo()
    assert col.get_config(CONFIG_KEY) == raw and queue.for_card(cid) == old
    col.redo()
    assert queue.for_card(cid) == old + [added]
    queue.release_all(queue.all())
    assert not queue.all()  # Cleared metadata must not silently reappear.
    col.undo()
    assert queue.for_card(cid) == old + [added]
    assert scheduling_snapshot(col.get_card(cid)) == before and not review_logs(col, cid)


def test_clear_all_handles_multiple_items_of_one_card_in_one_undo_with_stale_preflight(col):
    cid = col.find_cards("")[0]
    queue = PracticeQueue(col)
    for _ in range(3):
        queue.enqueue(cid, 1, 1000)
    original = queue.all()
    queue.repeat(original[1], 7200, 3000)
    current = queue.all()
    step = col.undo_status().last_step
    with pytest.raises(PracticeStateChanged):
        queue.release_all(original)
    assert col.undo_status().last_step == step and queue.all() == current
    with pytest.raises(ValueError):
        queue.release_all([current[0], current[0]])
    queue.release_all(current)
    assert not queue.all()
    col.undo()
    assert queue.all() == current
    col.redo()
    assert not queue.all() and not review_logs(col, cid)


def test_multiple_appearances_survive_reopen_with_ids_and_deadlines(tmp_path):
    path = str(tmp_path / "multiple.anki2")
    with closing(Collection(path)) as collection:
        note = collection.new_note(collection.models.by_name("Basic"))
        note["Front"] = "One original"
        collection.add_note(note, 1)
        cid = note.card_ids()[0]
        queue = PracticeQueue(collection)
        for seconds in (3600, 1, 7200):
            queue.enqueue(cid, seconds, 1000)
        expected = queue.all()
    with closing(Collection(path)) as collection:
        queue = PracticeQueue(collection)
        assert queue.all() == expected
        queue.release(expected[1])
        assert queue.all() == [expected[0], expected[2]]
        assert not review_logs(collection, cid)
