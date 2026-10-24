"""Merge policy against real native queue heads; no Qt window is needed here."""

from types import SimpleNamespace

import pytest
import time

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
    collection.set_config("rollover", (time.localtime().tm_hour + 12) % 24)
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
    flow.mw = SimpleNamespace(col=col, reviewer=reviewer, state="review")
    flow.runtime = SimpleNamespace(mw=flow.mw, busy=False)
    flow.active = flow.collection = flow.token = None
    flow._requests, flow._native_counts = [], [0, 0, 0]
    flow._answer_collection = None
    flow._native_answers = {}
    flow._undo_card_id = None
    flow._undo_info = None
    flow._redo_stack = []
    flow._undo_pending = False
    flow._last_step = None
    flow._defer_native_advance = False
    flow._native_advance = None
    flow._practice_refresh = False

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


@pytest.mark.parametrize("other_practice", [False, True])
def test_native_answer_undo_takes_priority_over_ready_practice(col, monkeypatch, other_practice):
    clock = 100000
    flow = flow_for(col, monkeypatch, clock)
    flow.select()
    original = flow.reviewer.card
    before = scheduling_snapshot(original)
    queue = PracticeQueue(col)
    queue.enqueue(original.id, 1, clock)
    if other_practice:
        other_id = next(cid for cid in col.find_cards("") if cid != original.id)
        queue.enqueue(other_id, 1, clock - 1)
    requests = queue.all()
    col.sched.get_queued_cards()  # Read the unchanged native head before the answer.
    original.start_timer()
    col.sched.answer_card(col.sched.build_answer(
        card=original, states=flow.reviewer._v3.states, rating=CardAnswer.EASY,
    ))
    flow.native_answered(flow.reviewer, original, CardAnswer.EASY)
    monkeypatch.setattr("holdup.gui.now_ms", lambda: clock + 2000)
    flow.select()
    assert flow.active == requests[0] and flow.reviewer._v3 is None

    flow.on_undo(col.undo())
    for _redraw in range(2):
        flow.select()
        assert flow.active is None
        assert flow.reviewer.card.id == original.id
        assert flow.reviewer._v3 is not None
        assert not flow.reviewer._holdup_practice
        assert flow.guard_rating((True, 3), flow.reviewer, flow.reviewer.card) == (True, 3)
    assert scheduling_snapshot(col.get_card(original.id)) == before
    assert not review_logs(col, original.id)
    assert queue.all() == requests

    # A new explicit rating ends Undo's temporary native priority. The extra
    # appearance is still ready and can resume through the ordinary merge.
    card = flow.reviewer.card
    card.start_timer()
    col.sched.answer_card(col.sched.build_answer(
        card=card, states=flow.reviewer._v3.states, rating=CardAnswer.EASY,
    ))
    flow.native_answered(flow.reviewer, card, CardAnswer.EASY)
    flow.select()
    assert flow.active == requests[0] and flow.reviewer._v3 is None
    assert queue.all() == requests
    assert len(review_logs(col, original.id)) == 1


@pytest.mark.parametrize("action", ["repeat", "release"])
def test_practice_undo_still_restores_practice_after_a_native_answer(col, monkeypatch, action):
    clock = 100000
    flow = flow_for(col, monkeypatch, clock)
    flow.select()
    card = flow.reviewer.card
    queue = PracticeQueue(col)
    queue.enqueue(card.id, 1, clock)
    request = queue.get(card.id)
    col.sched.get_queued_cards()  # Read the unchanged native head before the answer.
    card.start_timer()
    col.sched.answer_card(col.sched.build_answer(
        card=card, states=flow.reviewer._v3.states, rating=CardAnswer.EASY,
    ))
    flow.native_answered(flow.reviewer, card, CardAnswer.EASY)
    native_state = scheduling_snapshot(col.get_card(card.id))
    logs = review_logs(col, card.id)
    monkeypatch.setattr("holdup.gui.now_ms", lambda: clock + 2000)
    flow.select()
    assert flow.active == request

    if action == "repeat":
        queue.repeat(request, 7200, clock + 2000)
    else:
        queue.release(request)
    flow.active = None  # Successful practice completion advances the reviewer.
    flow.select()
    assert flow.active is None
    flow.on_undo(col.undo())
    flow.select()
    assert flow.active == request and flow.reviewer._v3 is None
    assert flow._undo_card_id is None
    assert queue.get(card.id) == request
    assert scheduling_snapshot(col.get_card(card.id)) == native_state
    assert review_logs(col, card.id) == logs


@pytest.mark.parametrize("rating", [CardAnswer.GOOD, CardAnswer.EASY])
def test_undo_can_restore_displayed_original_when_learning_became_due(col, monkeypatch, rating):
    col.set_config("collapseTime", 0)
    learning = answer_next(col, CardAnswer.GOOD)
    learning.due = int(time.time()) + 3600
    col.update_card(learning)
    clock = time.time_ns() // 1_000_000
    flow = flow_for(col, monkeypatch, clock)
    flow.select()
    original = flow.reviewer.card
    assert original.queue == 0 and original.id != learning.id
    before = scheduling_snapshot(original)
    original.start_timer()

    # Fixture only: an intraday deadline passes while the new card is open.
    # Use Anki's public update API instead of sleeping or changing system time.
    learning.due = int(time.time()) - 1
    col.update_card(learning)
    queue = PracticeQueue(col)
    queue.enqueue(original.id, 7200, clock)
    request = queue.get(original.id)
    rebuilt = col.sched.get_queued_cards()
    assert rebuilt.cards[0].card.id == learning.id
    col.sched.answer_card(col.sched.build_answer(
        card=original, states=flow.reviewer._v3.states, rating=CardAnswer.EASY,
    ))
    flow.native_answered(flow.reviewer, original, CardAnswer.EASY)
    flow.select()
    assert flow.reviewer.card.id == learning.id

    undone = col.undo()
    flow.on_undo(undone)
    flow.select()
    flow.on_operation(undone.changes, None)
    assert flow.reviewer.card.id == original.id and flow.reviewer._v3 is not None
    assert flow.active is None and not flow.reviewer._holdup_practice
    assert scheduling_snapshot(col.get_card(original.id)) == before
    assert not review_logs(col, original.id)
    assert queue.get(original.id) == request
    # Restoring the display must not reorder Anki's own queue or alter the
    # unrelated learning card. Anki accepts the original's restored states.
    assert col.sched.get_queued_cards().cards[0].card.id == learning.id
    card = flow.reviewer.card
    card.start_timer()
    col.sched.answer_card(col.sched.build_answer(
        card=card, states=flow.reviewer._v3.states, rating=rating,
    ))
    flow.native_answered(flow.reviewer, card, rating)
    flow.select()
    assert flow.reviewer.card.id == learning.id
    assert len(review_logs(col, original.id)) == 1
    assert col.get_card(original.id).memory_state is not None
    assert queue.get(original.id) == request
    assert col.sched.counts()[0] == 1


@pytest.mark.parametrize("redo_mark_too", [False, True])
def test_native_undo_redo_then_undo_still_returns_original(col, monkeypatch, redo_mark_too):
    clock = 100000
    flow = flow_for(col, monkeypatch, clock)
    flow.select()
    original = flow.reviewer.card
    before = scheduling_snapshot(original)
    queue = PracticeQueue(col)
    queue.enqueue(original.id, 1, clock)
    request = queue.get(original.id)
    col.sched.get_queued_cards()
    original.start_timer()
    col.sched.answer_card(col.sched.build_answer(
        card=original, states=flow.reviewer._v3.states, rating=CardAnswer.EASY,
    ))
    flow.native_answered(flow.reviewer, original, CardAnswer.EASY)
    monkeypatch.setattr("holdup.gui.now_ms", lambda: clock + 2000)
    flow.select()
    assert flow.active == request

    def undo():
        out = col.undo()
        flow.on_undo(out)
        flow.select()  # Anki's main-window listener refreshes the screen first.
        flow.on_operation(out.changes, None)

    def redo():
        out = col.redo()
        flow.select()
        flow.on_operation(out.changes, None)

    undo()
    assert flow.reviewer.card.id == original.id and flow.active is None
    if redo_mark_too:
        undo()
        assert queue.get(original.id) is None
        redo()
        assert queue.get(original.id) == request
    redo()
    assert len(review_logs(col, original.id)) == 1
    flow.select()
    assert flow.active == request
    undo()
    assert flow.active is None and flow.reviewer.card.id == original.id
    assert flow.reviewer._v3 is not None and not flow.reviewer._holdup_practice
    assert scheduling_snapshot(col.get_card(original.id)) == before
    assert not review_logs(col, original.id)
    assert queue.get(original.id) == request


def test_deleting_restored_original_clears_undo_pin_and_continues(col, monkeypatch):
    clock = 100000
    flow = flow_for(col, monkeypatch, clock)
    flow.select()
    original = flow.reviewer.card
    queue = PracticeQueue(col)
    queue.enqueue(original.id, 7200, clock)
    col.sched.get_queued_cards()
    original.start_timer()
    col.sched.answer_card(col.sched.build_answer(
        card=original, states=flow.reviewer._v3.states, rating=CardAnswer.EASY,
    ))
    flow.native_answered(flow.reviewer, original, CardAnswer.EASY)
    flow.select()
    undone = col.undo()
    flow.on_undo(undone)
    flow.select()
    flow.on_operation(undone.changes, None)
    assert flow.reviewer.card.id == original.id and flow._undo_info is not None

    col.remove_notes([original.nid])
    delete_step = col.undo_status().last_step
    flow.select()
    assert flow._undo_info is None and flow._undo_card_id is None
    assert flow.active is None and not flow.reviewer._holdup_practice
    assert flow.reviewer.card.id != original.id and flow.reviewer._v3 is not None
    assert flow.reviewer.card.id == col.sched.get_queued_cards().cards[0].card.id
    assert not queue.all()
    assert col.undo_status().last_step == delete_step  # The redraw is read-only.


def test_practice_undo_redo_refreshes_without_any_native_answer_in_session(col, monkeypatch):
    flow = flow_for(col, monkeypatch, clock=100000)
    cid = col.find_cards("")[0]
    queue = PracticeQueue(col)
    queue.enqueue(cid, 1, 1000)
    request = queue.get(cid)
    flow.select()
    assert flow.active == request and flow._answer_collection is None
    queue.release(request)
    flow.active = None
    flow.select()
    refreshed = []
    monkeypatch.setattr(flow, "refresh_practice", lambda: refreshed.append(True))
    undone = col.undo()
    flow.on_undo(undone)
    flow.on_operation(undone.changes, None)
    assert refreshed == [True] and queue.get(cid) == request
    redone = col.redo()
    flow.on_operation(redone.changes, None)
    assert refreshed == [True, True] and queue.get(cid) is None
    assert not flow._native_answers and not col.get_review_logs(cid)


@pytest.mark.parametrize("state", ["review", "overview", "deckBrowser"])
def test_practice_history_refresh_returns_from_finished_overview_only(col, monkeypatch, state):
    flow = flow_for(col, monkeypatch, clock=100000)
    flow.mw.state = state
    calls = []
    flow.reviewer.nextCard = lambda: calls.append("next")
    flow.runtime.open_practice = lambda: calls.append("open")
    monkeypatch.setattr("holdup.review_flow.QTimer.singleShot", lambda _delay, callback: callback())
    flow.refresh_practice()
    assert calls == {"review": ["next"], "overview": ["open"], "deckBrowser": []}[state]


@pytest.mark.parametrize("ready", [True, False])
def test_switching_decks_excludes_previous_practice_before_native_queue_rebuild(col, monkeypatch, ready):
    flow = flow_for(col, monkeypatch, clock=100000)
    queue = PracticeQueue(col)
    cid = col.find_cards("")[0]
    queue.enqueue(cid, 1 if ready else 7200, 1000)
    flow.select()
    flow.clear()
    other_deck = col.decks.id("Newly selected deck")
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "Another deck's original"
    col.add_note(note, other_deck)
    col.decks.select(other_deck)
    # Anki's cached active_decks still belongs to the preceding queue until
    # the next native fetch. Practice scope must already follow the selection.
    assert 1 in col.decks.active()
    assert flow.requests() == []
    flow.select()
    assert flow.active is None and flow.reviewer.card.id == note.card_ids()[0]
    assert flow.reviewer._v3 is not None and not flow.reviewer._holdup_practice
    assert queue.get(cid) is not None


def test_native_overview_render_records_counts_to_avoid_an_immediate_poll_redraw(col, monkeypatch):
    from aqt.overview import OverviewBottomBar

    flow = flow_for(col, monkeypatch, clock=100000)
    flow.mw.overview = object()
    queue = PracticeQueue(col)
    cid = col.find_cards("")[0]
    queue.enqueue(cid, 7200, 1000)
    content = SimpleNamespace(body="")
    flow.overview_content(content, OverviewBottomBar(flow.mw.overview))
    assert flow.runtime._overview_count == (0, 1)
    queue.enqueue(cid, 1, 1000)
    flow.overview_content(SimpleNamespace(body=""), OverviewBottomBar(flow.mw.overview))
    assert flow.runtime._overview_count == (1, 2)
