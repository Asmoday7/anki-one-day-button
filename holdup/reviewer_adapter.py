"""Bind one-use reviewer commands to timed practice; never answer a card."""

from __future__ import annotations

import json
from pathlib import Path
import secrets
from typing import Any, Callable

from .i18n import localize_script, tr


COMMAND_PREFIX = "holdup-button:"
INTERVAL_PREFIX = "holdup-interval:"
_controller: ReviewerController | None = None


class ReviewerController:
    def __init__(self, mw: Any, context_type: type, report_error: Callable,
                 defer: Callable, configure: Callable, settings: Callable) -> None:
        self._mw = mw
        self._context_type = context_type
        self._report_error = report_error
        self._defer = defer
        self._configure = configure
        self._settings = settings
        self._reviewer: Any = None
        self._collection: Any = None
        self._card_id: int | None = None
        self._token: str | None = None
        self._waiting_card_id: int | None = None

    def _eligible(self, *, allow_background: bool = False) -> bool:
        reviewer = self._mw.reviewer
        card = reviewer.card
        return (
            self._mw.col is not None
            and self._mw.state == "review"
            and reviewer.state == "answer"
            and not getattr(reviewer, "_holdup_practice", False)
            and card is not None
            and card.odid == 0
            and card.queue in (0, 1, 2, 3)
            and (allow_background or not getattr(self._mw, "_background_op_count", 0))
        )

    def _hide(self) -> None:
        if self._reviewer is not None:
            try:
                self._reviewer.bottom.web.eval("window.HoldUpButton?.hide();")
            except RuntimeError:
                # The Qt object may already have been destroyed during shutdown.
                pass

    def clear(self, *_args: Any) -> None:
        self._hide()
        self._token = self._card_id = self._waiting_card_id = None
        self._reviewer = self._collection = None

    def on_state_change(self, new_state: str, _old_state: str) -> None:
        if new_state != "review":
            self.clear()

    def on_idle(self) -> None:
        # backend_did_block fires when the background-operation count reaches
        # zero. A read finishing must not leave the fifth button missing.
        if (self._waiting_card_id is not None and self._eligible()
                and self._mw.reviewer.card.id == self._waiting_card_id):
            self.on_answer(self._mw.reviewer.card)

    def on_undo(self, _changes: Any) -> None:
        # Undoing metadata does not redraw Anki's answer. Restore the action
        # with a fresh token instead of leaving the old scheduled checkmark.
        if self._eligible(allow_background=True):
            self.on_answer(self._mw.reviewer.card)

    def on_deferred(self, card_id: int) -> None:
        if (self._mw.col is self._collection and self._mw.reviewer is self._reviewer
                and self._eligible(allow_background=True) and self._mw.reviewer.card.id == card_id):
            self._waiting_card_id = None
            self._reviewer.bottom.web.eval("window.HoldUpButton?.scheduled();")

    def on_answer(self, card: Any) -> None:
        self.clear()
        reviewer = self._mw.reviewer
        if not self._eligible() or reviewer.card.id != card.id:
            if self._eligible(allow_background=True) and reviewer.card.id == card.id:
                self._waiting_card_id = card.id
            return
        self._reviewer = reviewer
        self._collection = self._mw.col
        self._card_id = card.id
        self._token = secrets.token_urlsafe(18)
        from .practice import MODE_STUDY_DAY, interval_label

        config = self._settings()
        study_day = config.get("interval_mode") == MODE_STUDY_DAY
        payload = {"token": self._token, "label": interval_label(config["interval_seconds"], next_study_day=study_day),
                   "study_day": study_day,
                   "pause": config["pause_native"]}
        reviewer.bottom.web.eval(
            f"window.HoldUpButton?.show({json.dumps(payload)});"
        )

    def on_message(
        self, handled: tuple[bool, Any], message: str, context: Any
    ) -> tuple[bool, Any]:
        if (not handled[0] and message == "holdup-layout"
                and isinstance(context, self._context_type)
                and context.reviewer is self._mw.reviewer):
            web = context.reviewer.bottom.web
            def fit(height):
                # Navigation can invalidate a queued JavaScript callback.
                # Ignore it instead of applying an old height to a new page.
                if (isinstance(height, (int, float)) and height > 0
                        and self._mw.state == "review"
                        and web._bridge_context is context and not web.hidden):
                    web.setFixedHeight(int(height))

            if self._mw.state == "review" and not web.hidden and web._domDone:
                web.evalWithCallback("document.documentElement?.offsetHeight || 0", fit)
            return (True, None)
        configure = message.startswith(INTERVAL_PREFIX)
        prefix = INTERVAL_PREFIX if configure else COMMAND_PREFIX
        if handled[0] or not message.startswith(prefix):
            return handled
        if not isinstance(context, self._context_type):
            return handled
        if (
            self._token is None
            or message != prefix + self._token
            or context.reviewer is not self._reviewer
            or self._mw.reviewer is not self._reviewer
            or self._mw.col is not self._collection
            or not self._eligible(allow_background=True)
            or self._mw.reviewer.card.id != self._card_id
        ):
            return (True, None)

        # CollectionOp serializes the write after outstanding collection reads.
        # Dropping this valid click during the one-second poll required a
        # second click even though the button had already acknowledged it.
        reviewer = self._reviewer
        card_id = self._card_id
        # Consume before dispatch: nested or queued second clicks are stale.
        self._token = None
        # Keep this cell in place while disabled: removing it could move a
        # native rating under the second physical click of a double click.
        reviewer.bottom.web.eval("window.HoldUpButton?.pending();")
        try:
            if configure:
                self._configure()
            else:
                self._defer(card_id)
        except Exception as error:
            # Never retry an uncertain operation automatically.
            self.clear()
            self._report_error(error)
        else:
            # Closing the settings dialog is not a practice action.
            if (
                configure and self._token is None and self._mw.col is self._collection
                and self._mw.reviewer is reviewer
                and self._eligible(allow_background=True)
                and reviewer.card.id == self._card_id
            ):
                self.on_answer(reviewer.card)
        return (True, None)


def install(mw: Any) -> bool:
    """Register once, after Anki has created its main window; no collection needed."""
    global _controller
    if _controller is not None:
        return True

    from aqt import gui_hooks
    from aqt import reviewer as reviewer_module
    from aqt.utils import show_warning

    names = (
        "webview_will_set_content", "webview_did_receive_js_message",
        "reviewer_did_show_answer", "reviewer_did_show_question",
        "reviewer_will_end", "profile_will_close", "state_did_change",
        "reviewer_will_answer_card", "card_will_show", "overview_will_render_bottom",
        "backend_did_block", "state_did_undo", "reviewer_did_answer_card",
    )
    context_type = getattr(reviewer_module, "ReviewerBottomBar", None)
    flow_methods = (
        "nextCard", "_get_next_v3_card", "_showAnswerButton", "_showEaseButtons",
        "_run_state_mutation_hook", "_auto_advance_to_answer_if_enabled",
        "_auto_advance_to_question_if_enabled", "_clear_auto_advance_timers",
        "onEnterKey",
    )
    reviewer = getattr(mw, "reviewer", None)
    if (context_type is None or not all(hasattr(gui_hooks, name) for name in names)
            or not all(callable(getattr(reviewer, name, None)) for name in flow_methods)):
        print("HoldUp: this reviewer API is not supported; button disabled.")
        return False

    def report_error(error: Exception) -> None:
        import traceback

        traceback.print_exception(error)
        show_warning(
            tr("HoldUp: the action could not be completed. It was not retried automatically.")
            + "\n\n" + str(error), parent=mw
        )

    from .gui import PracticeRuntime

    runtime = PracticeRuntime(mw)
    controller = ReviewerController(mw, context_type, report_error, runtime.defer,
                                    runtime.configure, runtime.settings)
    runtime.controller = controller
    # Keep an inspectable runtime for GUI tests and Anki's module lifecycle.
    controller.runtime = runtime
    script = (Path(__file__).parent / "web" / "reviewer.js").read_text(encoding="utf-8")

    def on_content(content: Any, context: Any) -> None:
        if isinstance(context, context_type) and context.reviewer is mw.reviewer:
            content.body += "<script>" + localize_script(script) + "</script>"

    gui_hooks.webview_will_set_content.append(on_content)
    gui_hooks.webview_did_receive_js_message.append(controller.on_message)
    gui_hooks.reviewer_did_show_answer.append(controller.on_answer)
    gui_hooks.backend_did_block.append(controller.on_idle)
    gui_hooks.state_did_undo.append(controller.on_undo)
    gui_hooks.reviewer_did_show_question.append(controller.clear)
    gui_hooks.reviewer_will_end.append(controller.clear)
    gui_hooks.profile_will_close.append(controller.clear)
    gui_hooks.state_did_change.append(controller.on_state_change)
    _controller = controller
    return True
