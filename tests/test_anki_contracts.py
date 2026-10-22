"""API research probes and request-storage tests against the real Anki backend.

All writes use collection APIs and disposable collections. No SQL is used.
"""

import json

import pytest

pytest.importorskip("anki", reason="Install requirements-anki.txt for backend probes")

from anki.collection import Collection
from anki.decks import DeckId
from anki.errors import InvalidInput
from anki.scheduler.v3 import CardAnswer

from holdup.request_store import (
    CustomDataLimitExceeded,
    PracticeRequest,
    RequestStore,
    UnsupportedRequestVersion,
)

pytestmark = pytest.mark.anki_contract


@pytest.fixture
def collection(tmp_path):
    col = Collection(str(tmp_path / "collection.anki2"))
    try:
        col.set_config("fsrs", True)
        # Graduate immediately so the probe exercises a review card with FSRS.
        config = col.decks.config_dict_for_deck_id(DeckId(1))
        config["new"]["delays"] = []
        col.decks.update_config(config)
        model = col.models.by_name("Basic")
        assert model is not None
        note = col.new_note(model)
        note["Front"] = "Backend probe question"
        note["Back"] = "Backend probe answer"
        col.add_note(note, DeckId(1))
        yield col
    finally:
        col.close()


def scheduling_snapshot(card):
    fields = (
        "did", "odid", "due", "odue", "type", "queue", "ivl", "factor",
        "reps", "lapses", "left", "original_position", "last_review_time",
        "desired_retention", "decay",
    )
    values = {field: getattr(card, field) for field in fields}
    memory = card.memory_state
    values["memory_state"] = (
        (memory.stability, memory.difficulty) if memory is not None else None
    )
    return values


def answer_next(col, rating):
    queued = col.sched.get_queued_cards().cards[0]
    card = col.get_card(queued.card.id)
    card.start_timer()
    answer = col.sched.build_answer(card=card, states=queued.states, rating=rating)
    col.sched.answer_card(answer)
    return col.get_card(card.id)


def review_logs(col, card_id):
    return [entry.SerializeToString() for entry in col.get_review_logs(card_id)]


def test_good_can_remain_in_learning_and_same_day_logs_cannot_train_fsrs(collection):
    """A recorded Good and FSRS memory do not imply optimizer training data."""
    col = collection
    config = col.decks.config_dict_for_deck_id(DeckId(1))
    config["new"]["delays"] = [1, 10]
    col.decks.update_config(config)

    learning = answer_next(col, CardAnswer.GOOD)
    assert learning.type == 1 and learning.queue == 1  # Native red learning queue.
    assert learning.reps == 1 and learning.memory_state is not None
    logs = col.get_review_logs(learning.id)
    assert len(logs) == 1 and logs[0].button_chosen == 3
    assert logs[0].interval == 600  # get_review_logs() exposes seconds.

    # Anki's learning-ahead queue permits the second native step without waiting
    # or editing dates/history. The second Good graduates the card normally.
    graduated = answer_next(col, CardAnswer.GOOD)
    assert graduated.type == 2 and graduated.queue == 2
    assert graduated.reps == 2 and graduated.memory_state is not None
    assert [log.button_chosen for log in col.get_review_logs(learning.id)] == [3, 3]

    # Research probe only: the add-on never calls the optimizer. With no
    # cross-day observations, the real backend returns zero training items.
    result = col._backend.compute_fsrs_params(
        search="", current_params=[], ignore_revlogs_before_ms=0,
        num_of_relearning_steps=1, health_check=False,
    )
    assert result.fsrs_items == 0
    assert len(col.get_review_logs(learning.id)) == 2


def test_good_metadata_and_merged_undo_redo(collection):
    col = collection
    card_id = col.find_cards("")[0]
    before = scheduling_snapshot(col.get_card(card_id))
    card = answer_next(col, CardAnswer.GOOD)
    assert card.memory_state is not None, "FSRS must actually be active"
    assert card.reps == 1
    logs = col.get_review_logs(card_id)
    assert len(logs) == 1 and logs[0].button_chosen == 3
    after_good = scheduling_snapshot(card)
    log_after_good = review_logs(col, card_id)
    answer_step = col.undo_status().last_step

    # An experimental metadata write, not the HoldUp command implementation.
    card.custom_data = json.dumps({"odbday": col.sched.today + 1})
    col.update_card(card)
    col.merge_undo_entries(answer_step)
    assert scheduling_snapshot(col.get_card(card_id)) == after_good
    assert review_logs(col, card_id) == log_after_good

    col.undo()
    assert scheduling_snapshot(col.get_card(card_id)) == before
    assert col.get_card(card_id).custom_data == ""
    assert not col.get_review_logs(card_id)
    col.redo()
    assert scheduling_snapshot(col.get_card(card_id)) == after_good
    assert json.loads(col.get_card(card_id).custom_data)["odbday"] == col.sched.today + 1
    assert review_logs(col, card_id) == log_after_good


def test_rendering_does_not_answer_card(collection):
    col = collection
    card = answer_next(col, CardAnswer.GOOD)
    before = scheduling_snapshot(card)
    logs = review_logs(col, card.id)
    assert "Backend probe question" in card.question()
    assert "Backend probe answer" in card.answer()
    assert scheduling_snapshot(col.get_card(card.id)) == before
    assert review_logs(col, card.id) == logs


@pytest.mark.parametrize("rating", [CardAnswer.GOOD, CardAnswer.EASY])
def test_filtered_preview_restores_schedule_but_writes_revlog(collection, rating):
    col = collection
    card = answer_next(col, CardAnswer.GOOD)
    before = scheduling_snapshot(card)
    previous_logs = review_logs(col, card.id)

    filtered = col.sched.get_or_create_filtered_deck(DeckId(0))
    filtered.name = "HoldUp backend probe"
    filtered.config.reschedule = False
    filtered.config.preview_good_secs = 0
    filtered.config.search_terms[0].search = f"cid:{card.id}"
    filtered.config.search_terms[0].limit = 1
    filtered_id = DeckId(col.sched.add_or_update_filtered_deck(filtered).id)
    col.decks.select(filtered_id)
    moved = col.get_card(card.id)
    assert moved.did == filtered_id and moved.odid == before["did"]

    answer_next(col, rating)
    assert scheduling_snapshot(col.get_card(card.id)) == before
    logs = col.get_review_logs(card.id)
    assert len(logs) == len(previous_logs) + 1
    preview = next(log for log in logs if log.review_kind == 3)
    # CardAnswer.Rating is zero-based; reviewer ease/revlog buttons are 1..4.
    assert preview.button_chosen == rating + 1
    assert preview.ease == 0  # Native cramming entry, not a normal FSRS review.


def test_custom_data_is_searchable_and_preserves_other_keys(collection):
    col = collection
    card = col.get_card(col.find_cards("")[0])
    tomorrow = col.sched.today + 1
    card.custom_data = json.dumps({"other": 7, "odbday": tomorrow})
    col.update_card(card)
    assert not col.find_cards(f"prop:cdn:odbday<={col.sched.today}")
    assert col.find_cards(f"prop:cdn:odbday<={tomorrow}") == [card.id]
    assert json.loads(col.get_card(card.id).custom_data)["other"] == 7


@pytest.mark.parametrize(
    "payload",
    [{"toolongkey": 1}, {"long": "x" * 10000}],
    ids=["key-longer-than-eight-bytes", "oversized-value"],
)
def test_backend_rejects_invalid_custom_data(collection, payload):
    col = collection
    card = col.get_card(col.find_cards("")[0])
    original = card.custom_data
    card.custom_data = json.dumps(payload)
    with pytest.raises(InvalidInput):
        col.update_card(card)
    assert col.get_card(card.id).custom_data == original


# The following checks exercise the actual RequestStore implementation.


def test_store_write_preserves_good_schedule_revlog_and_foreign_data(collection):
    col = collection
    card = answer_next(col, CardAnswer.GOOD)
    assert card.memory_state is not None
    foreign = {"other": {"n": 7}, "text": "тест", "ratio": 0.25}
    card.custom_data = json.dumps(foreign, ensure_ascii=False, separators=(",", ":"))
    col.update_card(card)
    before = scheduling_snapshot(card)
    logs = review_logs(col, card.id)
    store = RequestStore(col)
    request = PracticeRequest(card.id, col.sched.today + 1)

    assert store.get(card.id) is None
    assert store.put(request) is not None
    assert store.get(card.id) == request
    saved = col.get_card(card.id)
    data = json.loads(saved.custom_data)
    assert data.pop("odbday") == request.due_day
    assert data.pop("odbv") == 1
    assert data == foreign
    assert scheduling_snapshot(saved) == before
    assert review_logs(col, card.id) == logs


@pytest.mark.parametrize("foreign", [{}, {"other": 7}])
def test_store_replaces_one_request_and_removes_only_its_keys(collection, foreign):
    col = collection
    card = answer_next(col, CardAnswer.GOOD)
    before, logs = scheduling_snapshot(card), review_logs(col, card.id)
    card.custom_data = json.dumps(foreign)
    col.update_card(card)
    store = RequestStore(col)

    store.put(PracticeRequest(card.id, 1))
    store.put(PracticeRequest(card.id, 2))
    assert store.get(card.id) == PracticeRequest(card.id, 2)
    assert store.find_due(2) == [PracticeRequest(card.id, 2)]
    assert store.remove(card.id) is not None
    assert store.get(card.id) is None
    raw = col.get_card(card.id).custom_data
    assert (json.loads(raw) if raw else {}) == foreign

    step = col.undo_status().last_step
    assert store.remove(card.id) is None
    assert col.undo_status().last_step == step
    assert scheduling_snapshot(col.get_card(card.id)) == before
    assert review_logs(col, card.id) == logs


def test_same_request_is_noop_and_preserves_existing_json(collection):
    col = collection
    card = col.get_card(col.find_cards("")[0])
    card.custom_data = '{ "odbday": 1, "odbv": 1, "other": 7 }'
    col.update_card(card)
    step = col.undo_status().last_step
    assert RequestStore(col).put(PracticeRequest(card.id, 1)) is None
    assert col.get_card(card.id).custom_data == card.custom_data
    assert col.undo_status().last_step == step


def test_store_reloads_card_before_each_write(collection):
    col = collection
    card_id = col.find_cards("")[0]
    store = RequestStore(col)
    store.put(PracticeRequest(card_id, 1))
    changed = col.get_card(card_id)
    data = json.loads(changed.custom_data)
    data["other"] = "new"
    changed.custom_data = json.dumps(data)
    col.update_card(changed)

    store.put(PracticeRequest(card_id, 2))
    assert json.loads(col.get_card(card_id).custom_data)["other"] == "new"
    store.remove(card_id)
    assert json.loads(col.get_card(card_id).custom_data) == {"other": "new"}


def test_store_create_replace_remove_support_native_undo_redo(collection):
    col = collection
    card_id = col.find_cards("")[0]
    store = RequestStore(col)
    first, second = PracticeRequest(card_id, 1), PracticeRequest(card_id, 2)
    for action, previous, following in (
        (lambda: store.put(first), None, first),
        (lambda: store.put(second), first, second),
        (lambda: store.remove(card_id), second, None),
    ):
        action()
        assert store.get(card_id) == following
        col.undo()
        assert store.get(card_id) == previous
        col.redo()
        assert store.get(card_id) == following
    assert not col.get_review_logs(card_id)


def test_store_changes_can_merge_into_a_known_good_undo_step(collection):
    col = collection
    card_id = col.find_cards("")[0]
    before = scheduling_snapshot(col.get_card(card_id))
    card = answer_next(col, CardAnswer.GOOD)
    after = scheduling_snapshot(card)
    answer_step = col.undo_status().last_step
    store = RequestStore(col)
    request = PracticeRequest(card.id, 1)
    store.put(request)
    col.merge_undo_entries(answer_step)

    col.undo()
    assert store.get(card.id) is None
    assert scheduling_snapshot(col.get_card(card.id)) == before
    assert not col.get_review_logs(card.id)
    col.redo()
    assert store.get(card.id) == request
    assert scheduling_snapshot(col.get_card(card.id)) == after
    assert len(col.get_review_logs(card.id)) == 1


def test_request_survives_collection_reopen(collection):
    col = collection
    card_id = col.find_cards("")[0]
    request = PracticeRequest(card_id, 1)
    RequestStore(col).put(request)
    col.close()
    col.reopen()
    assert RequestStore(col).get(card_id) == request


def test_find_due_includes_overdue_and_omits_future_and_absent_requests(collection):
    col = collection
    model = col.models.by_name("Basic")
    for index in range(3):
        note = col.new_note(model)
        note["Front"] = f"Extra search card {index}"
        col.add_note(note, DeckId(1))
    ids = col.find_cards("")
    assert len(ids) == 4
    store = RequestStore(col)
    for card_id, due in zip(ids, (10, 9, 11)):
        store.put(PracticeRequest(card_id, due))
    assert store.find_due(10) == [PracticeRequest(ids[1], 9), PracticeRequest(ids[0], 10)]
    assert store.find_due(8) == []


@pytest.mark.parametrize("total_bytes", [100, 101])
@pytest.mark.parametrize("fill", ["a", "я"])
def test_store_respects_exact_backend_byte_budget(collection, total_bytes, fill):
    col = collection
    card = col.get_card(col.find_cards("")[0])
    base = json.dumps({"x": "", "odbday": 1, "odbv": 1}, separators=(",", ":"))
    available = total_bytes - len(base.encode("utf-8"))
    copies, remaining = divmod(available, len(fill.encode("utf-8")))
    foreign = {"x": fill * copies + "a" * remaining}
    card.custom_data = json.dumps(foreign, ensure_ascii=False, separators=(",", ":"))
    col.update_card(card)
    original, step = card.custom_data, col.undo_status().last_step
    store = RequestStore(col)

    if total_bytes == 100:
        store.put(PracticeRequest(card.id, 1))
        raw = col.get_card(card.id).custom_data
        assert len(raw.encode("utf-8")) == 100
        assert json.loads(raw)["x"] == foreign["x"]
    else:
        with pytest.raises(CustomDataLimitExceeded):
            store.put(PracticeRequest(card.id, 1))
        assert col.get_card(card.id).custom_data == original
        assert col.undo_status().last_step == step


def test_store_never_overwrites_unknown_schema_even_when_due(collection):
    col = collection
    card = col.get_card(col.find_cards("")[0])
    card.custom_data = '{"odbday":1,"odbv":2,"other":7}'
    col.update_card(card)
    original, step = card.custom_data, col.undo_status().last_step
    store = RequestStore(col)
    for action in (
        lambda: store.get(card.id),
        lambda: store.put(PracticeRequest(card.id, 2)),
        lambda: store.remove(card.id),
        lambda: store.find_due(2),
    ):
        with pytest.raises(UnsupportedRequestVersion):
            action()
    assert col.get_card(card.id).custom_data == original
    assert col.undo_status().last_step == step
