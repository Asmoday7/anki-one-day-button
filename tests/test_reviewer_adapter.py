"""Controller boundaries without Qt; desktop integration is tested separately."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from holdup.reviewer_adapter import COMMAND_PREFIX, INTERVAL_PREFIX, ReviewerController


class BottomContext:
    def __init__(self, reviewer):
        self.reviewer = reviewer


@pytest.fixture
def setup_controller(monkeypatch):
    from holdup import i18n
    monkeypatch.setattr(i18n, "language", lambda: "en")
    reviewer = SimpleNamespace(
        state="answer", card=SimpleNamespace(id=123, odid=0, queue=2),
        bottom=SimpleNamespace(web=Mock()),
    )
    reviewer._answerCard = Mock(side_effect=lambda _ease: setattr(reviewer, "state", "transition"))
    mw = SimpleNamespace(state="review", col=object(), reviewer=reviewer)
    report = Mock()
    defer = Mock()
    configure = Mock()
    controller = ReviewerController(mw, BottomContext, report, defer, configure,
                                    lambda: {"interval_seconds": 2, "pause_native": False})
    controller.on_answer(reviewer.card)
    return controller, mw, report


def current_command(mw):
    script = mw.reviewer.bottom.web.eval.call_args.args[0]
    assert script.startswith("window.HoldUpButton?.show(")
    payload = json.loads(script.removeprefix("window.HoldUpButton?.show(")[:-2])
    assert payload["label"] == "2 s" and payload["pause"] is False
    return COMMAND_PREFIX + payload["token"]


def test_valid_command_enqueues_once_and_never_calls_good(setup_controller):
    controller, mw, _report = setup_controller
    message = current_command(mw)
    context = BottomContext(mw.reviewer)
    assert controller.on_message((False, None), message, context) == (True, None)
    controller.on_message((False, None), message, context)
    controller._defer.assert_called_once_with(123)
    mw.reviewer._answerCard.assert_not_called()


def test_study_day_caption_and_mode_are_sent_to_reviewer(setup_controller):
    controller, mw, _report = setup_controller
    controller._settings = lambda: {"interval_seconds": 2, "interval_mode": "next_study_day", "pause_native": False}
    controller.on_answer(mw.reviewer.card)
    script = mw.reviewer.bottom.web.eval.call_args.args[0]
    payload = json.loads(script.removeprefix("window.HoldUpButton?.show(")[:-2])
    assert payload["label"] == "Study day" and payload["study_day"] is True
    mw.reviewer._answerCard.assert_not_called()


def test_undo_rearms_same_answer_with_fresh_token_after_background_work(setup_controller):
    controller, mw, _report = setup_controller
    stale = current_command(mw)
    controller.on_message((False, None), stale, BottomContext(mw.reviewer))
    controller.on_deferred(123)
    mw._background_op_count = 1
    controller.on_undo(None)
    assert controller._token is None
    mw._background_op_count = 0
    controller.on_idle()
    fresh = current_command(mw)
    assert fresh != stale
    controller.on_message((False, None), stale, BottomContext(mw.reviewer))
    assert controller._defer.call_count == 1
    controller.on_message((False, None), fresh, BottomContext(mw.reviewer))
    assert controller._defer.call_count == 2
    mw.reviewer._answerCard.assert_not_called()


@pytest.mark.parametrize("change", ["question", "window", "collection", "card", "filtered", "suspended", "practice", "native_answer_in_flight"])
def test_stale_or_ineligible_context_never_answers(setup_controller, change):
    controller, mw, _report = setup_controller
    message = current_command(mw)
    context = BottomContext(mw.reviewer)
    if change == "question":
        mw.reviewer.state = "question"
    elif change == "window":
        mw.state = "deckBrowser"
    elif change == "collection":
        mw.col = object()
    elif change == "card":
        mw.reviewer.card.id += 1
    elif change == "filtered":
        mw.reviewer.card.odid = 1
    elif change == "suspended":
        mw.reviewer.card.queue = -1
    elif change == "practice":
        mw.reviewer._holdup_practice = True
    elif change == "native_answer_in_flight":
        mw._background_op_count = 1
        mw.reviewer.state = "transition"
    controller.on_message((False, None), message, context)
    controller._defer.assert_not_called()
    mw.reviewer._answerCard.assert_not_called()


def test_other_handlers_contexts_and_commands_are_preserved(setup_controller):
    controller, mw, _report = setup_controller
    message = current_command(mw)
    handled = (True, "another add-on's result")
    assert controller.on_message(handled, message, BottomContext(mw.reviewer)) == handled
    assert controller.on_message((False, None), "ease3", BottomContext(mw.reviewer)) == (False, None)
    assert controller.on_message((False, None), message, mw.reviewer) == (False, None)
    controller.on_message((False, None), COMMAND_PREFIX + "wrong-token", BottomContext(mw.reviewer))
    mw.reviewer._answerCard.assert_not_called()


def test_settings_dialog_rearms_with_a_fresh_token_without_practice_or_answer(setup_controller):
    controller, mw, _report = setup_controller
    message = current_command(mw).replace(COMMAND_PREFIX, INTERVAL_PREFIX)
    context = BottomContext(mw.reviewer)
    controller.on_message((False, None), message, context)
    fresh = current_command(mw).replace(COMMAND_PREFIX, INTERVAL_PREFIX)
    assert fresh != message
    controller.on_message((False, None), message, context)
    controller._configure.assert_called_once_with()
    controller.on_message((False, None), fresh, context)
    assert controller._configure.call_count == 2
    controller._defer.assert_not_called()
    mw.reviewer._answerCard.assert_not_called()


@pytest.mark.parametrize("event", ["clear", "state"])
def test_lifecycle_events_invalidate_tokens(setup_controller, event):
    controller, mw, _report = setup_controller
    message = current_command(mw)
    if event == "state":
        controller.on_state_change("deckBrowser", "review")
    else:
        controller.clear()  # All three hooks register this same handler.
    controller.on_message((False, None), message, BottomContext(mw.reviewer))
    controller._defer.assert_not_called()
    mw.reviewer._answerCard.assert_not_called()


def test_uncertain_failure_is_reported_without_retry(setup_controller):
    controller, mw, report = setup_controller
    message = current_command(mw)
    error = RuntimeError("answer failed")
    controller._defer.side_effect = error
    context = BottomContext(mw.reviewer)
    controller.on_message((False, None), message, context)
    controller.on_message((False, None), message, context)
    report.assert_called_once_with(error)
    controller._defer.assert_called_once_with(123)
    mw.reviewer._answerCard.assert_not_called()


def test_button_appears_after_read_that_overlapped_show_answer(setup_controller):
    controller, mw, _report = setup_controller
    mw._background_op_count = 1
    controller.on_answer(mw.reviewer.card)
    assert controller._token is None
    mw._background_op_count = 0
    controller.on_idle()
    command = current_command(mw)
    controller.on_message((False, None), command, BottomContext(mw.reviewer))
    controller._defer.assert_called_once_with(123)
    mw.reviewer._answerCard.assert_not_called()


def test_click_during_read_dispatches_once_to_the_serialized_operation(setup_controller):
    controller, mw, _report = setup_controller
    old = current_command(mw)
    mw._background_op_count = 1
    controller.on_message((False, None), old, BottomContext(mw.reviewer))
    controller._defer.assert_called_once_with(123)
    mw._background_op_count = 0
    controller.on_idle()
    controller.on_message((False, None), old, BottomContext(mw.reviewer))
    controller._defer.assert_called_once_with(123)
    mw.reviewer._answerCard.assert_not_called()
