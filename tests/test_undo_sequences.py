"""Long mixed histories must restore both schedules, not just the last write."""

import random

import pytest

pytest.importorskip("aqt")

from anki.scheduler.v3 import CardAnswer

from holdup.practice import PracticeQueue
from test_anki_contracts import answer_next, review_logs, scheduling_snapshot
from test_review_flow import col, flow_for

pytestmark = pytest.mark.anki_contract


@pytest.mark.parametrize("kind", ["new", "learning", "review", "relearning"])
@pytest.mark.parametrize("seed", [17, 83, 291])
def test_mixed_history_full_undo_redo_and_new_branch(col, monkeypatch, kind, seed):
    ids = col.find_cards("")
    if kind in ("review", "relearning"):
        col.sched.set_due_date(ids, "0")  # Fixture only, never add-on behavior.
    if kind in ("learning", "relearning"):
        for _ in ids:
            answer_next(col, CardAnswer.AGAIN)
    expected_type = {"new": 0, "learning": 1, "review": 2, "relearning": 3}[kind]
    assert all(col.get_card(cid).type == expected_type for cid in ids)

    clock = 100000
    flow = flow_for(col, monkeypatch, clock)
    # Unit host renders synchronously. Collection, queues and history are real.
    flow.refresh_practice = lambda: None
    queue = PracticeQueue(col)
    rng = random.Random(seed)

    def snapshot():
        return (
            {cid: scheduling_snapshot(col.get_card(cid)) for cid in ids},
            {cid: review_logs(col, cid) for cid in ids},
            queue.all(),
            tuple(col.sched.counts()),
        )

    def changed():
        flow.on_operation(None, flow.reviewer)
        flow.active = None
        flow.select()

    def rate(rating):
        card = flow.reviewer.card
        assert card is not None and flow.reviewer._v3 is not None
        card.start_timer()
        col.sched.answer_card(col.sched.build_answer(
            card=card, states=flow.reviewer._v3.states, rating=rating,
        ))
        flow.native_answered(flow.reviewer, card, rating)

    history = [snapshot()]
    native_steps = {}
    flow.select()
    # Native grades, independent appointment replacements and removals,
    # including multiple consecutive actions with identical Undo labels.
    for index in range(16):
        if index % 4 == 0 and flow.reviewer._v3 is not None:
            original = flow.reviewer.card.id
            rate(rng.choice((CardAnswer.HARD, CardAnswer.GOOD, CardAnswer.EASY)))
            native_steps[col.undo_status().last_step] = original
        else:
            cid = rng.choice(ids)
            request = queue.get(cid)
            if request and index % 3 == 0:
                queue.release(request)
            elif request and request.due_ms <= clock:
                queue.repeat(request, rng.choice((1, 120, 7200)), clock)
            else:
                queue.enqueue(cid, rng.choice((1, 120, 7200)), clock)
        changed()
        clock += 2000
        monkeypatch.setattr("holdup.gui.now_ms", lambda: clock)
        history.append(snapshot())

    for expected in reversed(history[:-1]):
        out = col.undo()
        flow.on_undo(out)
        flow.select()  # Native UI refresh precedes the add-on operation hook.
        flow.on_operation(out.changes, None)
        assert snapshot() == expected
        if out.counter in native_steps:
            assert flow.reviewer.card.id == native_steps[out.counter]
            assert flow.active is None and flow.reviewer._v3 is not None
        flow.select()  # A second redraw must not change either schedule.
        assert snapshot() == expected

    for expected in history[1:]:
        out = col.redo()
        flow.select()
        flow.on_operation(out.changes, None)
        assert snapshot() == expected

    # Undo everything once more, then answer with a different rating. The new
    # branch discards Redo and remains answerable; no old virtual copy returns.
    for expected in reversed(history[:-1]):
        out = col.undo()
        flow.on_undo(out)
        flow.select()
        flow.on_operation(out.changes, None)
        assert snapshot() == expected
    assert not queue.all()
    flow.select()
    cid = flow.reviewer.card.id
    logs = review_logs(col, cid)
    rate(CardAnswer.GOOD)
    changed()
    assert not col.undo_status().redo and not flow._redo_stack
    assert len(review_logs(col, cid)) == len(logs) + 1
    assert not queue.all()
