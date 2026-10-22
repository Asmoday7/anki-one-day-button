"""Merge policy against real native queue heads; no Qt window is needed here."""

from types import SimpleNamespace

import pytest

pytest.importorskip("aqt", reason="Install requirements-gui-26.09.txt for reviewer contracts")

from anki.collection import Collection
from anki.scheduler.v3 import CardAnswer
from aqt.reviewer import V3CardInfo

from holdup.practice import PracticeQueue
from holdup.review_flow import ReviewFlow
from test_anki_contracts import answer_next, review_logs, scheduling_snapshot

pytestmark = pytest.mark.anki_contract


@pytest.fixture
def col(tmp_path):
    collection = Collection(str(tmp_path / "merge.anki2"))
    collection.set_config("fsrs", True)
    config = collection.decks.config_dict_for_deck_id(1)
    config["new"]["delays"] = [1, 10]
    collection.decks.update_config(config)
    for index in range(3):
        note = collection.new_note(collection.models.by_name("Basic"))
        note["Front"], note["Back"] = f"Merge {index}", "Answer"
        collection.add_note(note, 1)
    try:
        yield collection
    finally:
        collection.close()


def flow_for(col, monkeypatch, clock):
    # Only the GUI clock/host is isolated; queue selection/states come from Anki.
    monkeypatch.setattr("holdup.gui.now_ms", lambda: clock)
    reviewer = SimpleNamespace(card=None, _v3=None, _clear_auto_advance_timers=lambda: None)
    flow = ReviewFlow.__new__(ReviewFlow)
    flow.reviewer = reviewer
    flow.mw = SimpleNamespace(col=col, reviewer=reviewer)
    flow.runtime = SimpleNamespace(mw=flow.mw, busy=False)
    flow.active = flow.collection = flow.token = None
    flow._requests, flow._native_counts = [], [0, 0, 0]

    def native_head():
        reviewer.card = reviewer._v3 = None
        output = col.sched.get_queued_cards()
        if output.cards:
            reviewer._v3 = V3CardInfo.from_queue(output)
            reviewer.card = col.get_card(output.cards[0].card.id)

    flow._original = {"_get_next_v3_card": native_head}
    return flow


def test_due_practice_is_sorted_and_not_forced_to_alternate_with_new(col, monkeypatch):
    ids = col.find_cards("")
    q = PracticeQueue(col)
    q.enqueue(ids[0], 1, 1000, pause=True)
    q.enqueue(ids[1], 1, 2000, pause=True)
    flow = flow_for(col, monkeypatch, clock=10000)
    assert col.sched.get_queued_cards().cards[0].card.id == ids[2]
    flow.select()
    assert flow.active == q.get(ids[0])
    assert flow.reviewer._v3 is None
    flow.select()  # A redraw doesn't silently complete an unfinished practice.
    assert flow.active == q.get(ids[0])
    q.release(flow.active)
    flow.active = None
    flow.select()
    assert flow.active == q.get(ids[1])  # Still before new; no 1:1 alternation.
    assert all(not review_logs(col, cid) for cid in ids)


@pytest.mark.parametrize("native_earlier", [True, False])
def test_merge_uses_learning_time_and_preserves_an_answerable_native_head(col, monkeypatch, native_earlier):
    native = answer_next(col, CardAnswer.GOOD)
    assert native.queue == 1
    clock = native.due * 1000 + (60000 if native_earlier else -60000)
    q = PracticeQueue(col)
    practice_ids = [cid for cid in col.find_cards("") if cid != native.id]
    for offset, cid in enumerate(practice_ids):
        q.enqueue(cid, 1, clock - 4000 + offset * 1000, pause=True)
    before = scheduling_snapshot(col.get_card(native.id))
    logs = review_logs(col, native.id)
    flow = flow_for(col, monkeypatch, clock)
    flow.select()
    if native_earlier:
        assert flow.active is None and flow.reviewer.card.id == native.id
        assert flow.reviewer._v3 is not None
        # The selected native card really is answerable: no non-head bypass.
        card = flow.reviewer.card
        card.start_timer()
        answer = col.sched.build_answer(card=card, states=flow.reviewer._v3.states, rating=CardAnswer.GOOD)
        col.sched.answer_card(answer)
        assert len(review_logs(col, native.id)) == len(logs) + 1
    else:
        assert flow.active.card_id == practice_ids[0]
        assert flow.reviewer._v3 is None
        assert scheduling_snapshot(col.get_card(native.id)) == before
        assert review_logs(col, native.id) == logs
    assert all(not review_logs(col, cid) for cid in practice_ids)


def test_native_review_day_precedes_later_practice_without_changing_fsrs(col, monkeypatch):
    native = answer_next(col, CardAnswer.EASY)
    # Test fixture only: public manual rescheduling supplies a due review card.
    # Runtime HoldUp never calls set_due_date or changes due/type.
    col.sched.set_due_date([native.id], "0")
    clock = col.sched.day_cutoff * 1000 - 60000
    q = PracticeQueue(col)
    for cid in col.find_cards(""):
        if cid != native.id:
            q.enqueue(cid, 1, clock - 5000, pause=True)
    before = scheduling_snapshot(col.get_card(native.id))
    logs = review_logs(col, native.id)
    flow = flow_for(col, monkeypatch, clock)
    flow.select()
    assert flow.active is None and flow.reviewer.card.id == native.id
    assert flow.reviewer._v3 is not None
    assert scheduling_snapshot(col.get_card(native.id)) == before
    assert review_logs(col, native.id) == logs


def test_native_rating_is_blocked_during_pause_write(col, monkeypatch):
    flow = flow_for(col, monkeypatch, clock=10000)
    flow.select()
    card = flow.reviewer.card
    assert flow.guard_rating((True, 3), flow.reviewer, card) == (True, 3)
    flow.runtime.busy = True
    assert flow.guard_rating((True, 3), flow.reviewer, card) == (False, 3)
    assert not review_logs(col, card.id)
