"""Practice must not rebuild a live native queue, even after time has passed."""

import json
import time

import pytest

pytest.importorskip("anki")

from test_practice_anki import col
from anki.scheduler.v3 import CardAnswer
from holdup.practice import CONFIG_KEY, PracticeQueue
from holdup.request_store import InvalidRequestData
from test_anki_contracts import scheduling_snapshot

pytestmark = pytest.mark.anki_contract


@pytest.mark.parametrize("rating", [CardAnswer.AGAIN, CardAnswer.HARD, CardAnswer.GOOD, CardAnswer.EASY])
def test_random_reviews_stay_answerable_after_reading_then_holdup(col, rating):
    for index in range(29):
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"] = f"Random review {index}"
        col.add_note(note, 1)
    # Fixture setup only: create due reviews with the public rescheduling API.
    col.sched.set_due_date(col.find_cards(""), "0")
    config = col.decks.config_dict_for_deck_id(1)
    config["reviewOrder"] = 8
    col.decks.update_config(config)
    queued = col.sched.get_queued_cards(fetch_limit=30)
    ids = [entry.card.id for entry in queued.cards]
    card = col.get_card(ids[0])
    card.start_timer()
    before = scheduling_snapshot(card)
    before_logs = col.get_review_logs(card.id)
    # Rebuilding random review order uses a new salt after the clock advances.
    # Immediate, one-review tests did not exercise this production failure.
    time.sleep(1.1)
    queue = PracticeQueue(col)
    changes = queue.enqueue(card.id, 7200, time.time_ns() // 1_000_000)
    request = queue.get(card.id)
    assert not changes.study_queues and not changes.card
    assert [entry.card.id for entry in col.sched.get_queued_cards(fetch_limit=30).cards] == ids
    assert scheduling_snapshot(col.get_card(card.id)) == before
    assert col.get_card(card.id).custom_data == card.custom_data
    col.sched.answer_card(col.sched.build_answer(card=card, states=queued.cards[0].states, rating=rating))
    assert len(col.get_review_logs(card.id)) == len(before_logs) + 1
    assert col.get_review_logs(card.id)[0].button_chosen == rating + 1
    col.sched.get_queued_cards()
    col.undo()
    assert scheduling_snapshot(col.get_card(card.id)) == before
    assert col.get_review_logs(card.id) == before_logs and queue.get(card.id) == request
    assert col.sched.get_queued_cards().cards[0].card.id == card.id
    col.undo()
    assert queue.get(card.id) is None


@pytest.mark.parametrize("raw", [
    {"v": True, "cards": {}}, {"v": 3, "cards": {}}, {"v": 1, "cards": []},
    {"v": 1, "cards": {"01": None}}, {"v": 1, "cards": {"0": None}},
    {"v": 1, "cards": {"1": [123, 0, False]}},
    {"v": 1, "cards": {"1": [123, 60, True]}},
    {"v": 2, "cards": {"1": None}},
    {"v": 2, "cards": {"1": [["bad-id", 123, 60, False]]}},
    {"v": 2, "cards": {"1": [["legacy", 123, 60, False], ["legacy", 124, 60, False]]}},
])
def test_unsupported_collection_practice_data_is_not_overwritten(col, raw):
    col.set_config(CONFIG_KEY, raw)
    before = col.undo_status().last_step
    with pytest.raises(InvalidRequestData):
        PracticeQueue(col).enqueue(col.find_cards("")[0], 3600, 1000)
    assert col.get_config(CONFIG_KEY) == raw and col.undo_status().last_step == before


def test_saved_card_appointment_can_be_repeated_cleared_and_undone_without_card_writes(col):
    card = col.get_card(col.find_cards("")[0])
    card.custom_data = json.dumps({"odbv": 2, "odbat": 2000, "odbsecs": 1, "other": 7})
    col.update_card(card)
    queue = PracticeQueue(col)
    original = queue.get(card.id)
    col.sched.get_queued_cards()
    changes = queue.repeat(original, 7200, 3000)
    repeated = queue.get(card.id)
    assert not changes.study_queues and not changes.card
    assert repeated.due_ms == 7203000 and queue.all() == [repeated]
    assert col.get_card(card.id).custom_data == card.custom_data
    queue.release(repeated)
    assert queue.get(card.id) is None and queue.all() == []
    col.undo()
    assert queue.get(card.id) == repeated
    col.undo()
    assert queue.get(card.id) == original
    assert col.get_card(card.id).custom_data == card.custom_data


def test_practice_does_not_consume_other_addons_card_custom_data_budget(col):
    card = col.get_card(col.find_cards("")[0])
    card.custom_data = json.dumps({"other": "x" * 75})
    col.update_card(card)
    before = scheduling_snapshot(card)
    queue = PracticeQueue(col)
    queue.enqueue(card.id, 3600, 1000)
    assert queue.get(card.id).interval_seconds == 3600
    assert scheduling_snapshot(col.get_card(card.id)) == before
    assert col.get_card(card.id).custom_data == card.custom_data


def test_clearing_mixed_saved_pause_and_new_appointment_is_one_undo(col):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "Another original"
    col.add_note(note, 1)
    first, second = col.find_cards("")
    queue = PracticeQueue(col)
    queue.enqueue(first, 1, 1000, pause=True)
    queue.enqueue(second, 3600, 1000)
    queue.enqueue(second, 7200, 1000)
    requests = queue.all()
    assert len(requests) == 3
    queue.release_all(requests)
    assert queue.all() == [] and col.get_card(first).queue == 0
    col.undo()
    assert queue.all() == requests and col.get_card(first).queue == -1
    col.redo()
    assert queue.all() == [] and col.get_card(first).queue == 0
