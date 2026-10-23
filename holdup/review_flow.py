"""Present two independent schedules through the existing desktop reviewer.

Only GUI methods are adapted. The scheduler and its queue are left intact.
Private reviewer methods are version-sensitive: see the desktop contract tests.
"""

from copy import deepcopy
import json
import secrets
from html import escape
from typing import Any

from anki.errors import NotFoundError
from aqt import gui_hooks
from aqt.overview import OverviewBottomBar
from aqt.qt import QTimer
from aqt.reviewer import ReviewerBottomBar

from .practice import MODE_STUDY_DAY, PracticeQueue, interval_label, native_due_ms
from .i18n import tr


PREFIX = "holdup-practice:"


class ReviewFlow:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.mw = runtime.mw
        self.reviewer = self.mw.reviewer
        self.active = None
        self.collection = None
        self.token = None
        self._requests = []
        self._native_counts = [0, 0, 0]
        self._answer_collection = None
        self._native_answers = {}
        self._undo_card_id = None
        self._undo_info = None
        self._redo_stack = []
        self._undo_pending = False
        self._last_step = None
        self._defer_native_advance = False
        self._native_advance = None
        self._practice_refresh = False
        self.reviewer._holdup_practice = False
        self._original = {}
        for name, replacement in (
            ("nextCard", self.next_card),
            ("_get_next_v3_card", self.select),
            ("_showAnswerButton", self.question_buttons),
            ("_showEaseButtons", self.answer_buttons),
            ("_run_state_mutation_hook", self.mutation),
            ("_auto_advance_to_answer_if_enabled", self.auto_answer),
            ("_auto_advance_to_question_if_enabled", self.auto_question),
            ("onEnterKey", self.enter),
        ):
            self._original[name] = getattr(self.reviewer, name)
            setattr(self.reviewer, name, replacement)
        gui_hooks.reviewer_will_answer_card.append(self.guard_rating)
        gui_hooks.reviewer_did_answer_card.append(self.native_answered)
        gui_hooks.state_did_undo.append(self.on_undo)
        gui_hooks.operation_did_execute.append(self.on_operation)
        gui_hooks.backend_did_block.append(self.on_backend_idle)
        gui_hooks.reviewer_will_end.append(self.clear)
        gui_hooks.profile_will_close.append(self.close)
        gui_hooks.card_will_show.append(self.decorate)
        gui_hooks.webview_did_receive_js_message.append(self.message)
        gui_hooks.overview_will_render_bottom.append(self.overview_bottom)
        gui_hooks.webview_will_set_content.append(self.overview_content)

    def clear(self, *_args):
        self.active = self.collection = self.token = None
        self._requests = []
        self._native_counts = [0, 0, 0]
        self._undo_card_id = None
        self._undo_info = None
        self._defer_native_advance = False
        self._native_advance = None
        self._practice_refresh = False
        self.reviewer._holdup_practice = False

    def close(self, *_args):
        self.clear()
        self._answer_collection = None
        self._native_answers.clear()
        self._redo_stack.clear()
        self._undo_pending = False
        self._last_step = None

    def native_answered(self, reviewer, card, _ease):
        if reviewer is not self.reviewer or reviewer._holdup_practice:
            return
        if self._answer_collection is not self.mw.col:
            self._native_answers.clear()
            self._answer_collection = self.mw.col
        self._last_step = self.mw.col.undo_status().last_step
        # Keep the exact states/context originally presented by Anki, including
        # custom scheduling. A newly-due learning card can head the rebuilt queue
        # when this answer is undone; returning the original is a GUI action.
        self._native_answers[self._last_step] = (card.id, deepcopy(reviewer._v3))
        self._redo_stack.clear()
        self._undo_card_id = None
        self._undo_info = None
        self._defer_native_advance = True

    def next_card(self):
        if not self._defer_native_advance:
            return self._original["nextCard"]()
        self._defer_native_advance = False
        collection, card = self.mw.col, self.reviewer.card

        def advance():
            if (self.mw.col is collection and self.mw.state == "review"
                    and self.reviewer.card is card and self.reviewer.state == "transition"):
                self._original["nextCard"]()

        # The answer is already recorded. Navigate after its operation hooks,
        # so the last native card cannot render the congrats page twice.
        self._native_advance = advance

    def on_undo(self, changes):
        self._practice_refresh = changes.operation in self.practice_undo_names()
        self._undo_card_id = None
        self._undo_info = None
        if self.mw.col is not self._answer_collection:
            self._native_answers.clear()
            self._redo_stack.clear()
            self._answer_collection = self.mw.col
        info = self._native_answers.get(changes.counter)
        self._redo_stack.append((changes.operation, info))
        self._last_step = changes.new_status.last_step
        self._undo_pending = True
        if info is None:
            return  # Metadata Undo retains the normal practice merge policy.
        self._undo_card_id, _ = info
        self._undo_info = info
        self.active = self.token = None
        if self.mw.state == "overview":
            self.runtime.open_undone_card()

    def on_operation(self, *_args):
        if self._practice_refresh:
            self._practice_refresh = False
            self.refresh_practice()
        if self._native_advance is not None:
            advance, self._native_advance = self._native_advance, None
            QTimer.singleShot(0, advance)
        if self.mw.col is not self._answer_collection:
            return
        if self._undo_pending:
            self._undo_pending = False
            return  # state_did_undo already recorded this operation.
        status = self.mw.col.undo_status()
        if status.last_step == self._last_step:
            return
        self._last_step = status.last_step
        # Redo has no state_did_redo hook. Match the operation name supplied by
        # Anki itself (in its current language), not a hard-coded translation.
        if self._redo_stack and status.undo == self._redo_stack[-1][0]:
            _operation, info = self._redo_stack.pop()
            if info is not None:
                self._native_answers[status.last_step] = info
            elif status.undo in self.practice_undo_names() and (len(_args) < 2 or _args[1] is None):
                self.refresh_practice()
            if self._redo_stack and status.redo != self._redo_stack[-1][0]:
                self._redo_stack.clear()
        else:
            self._redo_stack.clear()

    @staticmethod
    def practice_undo_names():
        return {tr("HoldUp: repeat practice"), tr("HoldUp: finish practice"), tr("HoldUp: clear all practice")}

    def refresh_practice(self):
        collection = self.mw.col

        def refresh():
            if self.mw.col is not collection:
                return
            if self.mw.state == "review":
                self.active = self.token = None
                self.reviewer.nextCard()
            elif self.mw.state == "overview":
                # Undo of the last Repeat/Done restores a ready appearance,
                # even though its successful action already left review.
                # Reuse the guarded overview navigation (including the async
                # congrats fetch); ordinary polling never enters review.
                self.runtime.open_practice()

        QTimer.singleShot(0, refresh)

    def on_backend_idle(self):
        # Anki leaves the reviewer in transition when a native answer fails.
        # Allow its success callback and our normal navigation to finish first;
        # an unsuccessful answer then recovers through the real native queue.
        if self.mw.state != "review" or self.reviewer.state != "transition":
            return
        collection, card = self.mw.col, self.reviewer.card

        def recover():
            if (self.mw.col is collection and self.mw.state == "review"
                    and self.reviewer.card is card and self.reviewer.state == "transition"
                    and not self.mw._background_op_count and not self.runtime.busy):
                self._defer_native_advance = False
                self._native_advance = None
                self._undo_info = self._undo_card_id = None
                self._original["nextCard"]()

        QTimer.singleShot(0, lambda: QTimer.singleShot(0, recover))

    def selected_decks(self):
        # decks.active() describes Anki's last built study queue. Immediately
        # after selecting a different deck it can still name the old one.
        col = self.mw.col
        return set(col.decks.deck_and_child_ids(col.decks.get_current_id()))

    def requests(self):
        col = self.mw.col
        if col is None or col.decks.current()["dyn"]:
            return []
        decks = self.selected_decks()
        queue = PracticeQueue(col)
        return [r for r in queue.all()
                if queue.available(r) and col.get_card(r.card_id).did in decks]

    def due(self):
        from .gui import now_ms

        return [r for r in self.requests() if r.due_ms <= now_ms()]

    def update_counts(self, rows=None):
        """Three visual groups: ready practice contributes to green, not FSRS."""
        from .gui import now_ms

        r, col = self.reviewer, self.mw.col
        if col is None or self.mw.state != "review" or not r.card or r.state not in ("question", "answer"):
            return
        if rows is not None:
            decks = self.selected_decks()
            self._requests = [row.request for row in rows if row.available and row.deck_id in decks]
        if col.decks.current()["dyn"] or not col.conf["dueCounts"]:
            payload = None
        else:
            if r._v3 is not None:
                active, native = r._v3.counts()
                self._native_counts = list(native)
            else:
                active = 2  # Practice is presented with the green repetitions.
            ready = sum(request.due_ms <= now_ms() for request in self._requests)
            payload = {"native": self._native_counts, "total": len(self._requests),
                       "ready": ready, "active": active, "phase": r.state}
        r.bottom.web.eval(f"window.HoldUpButton?.counts({json.dumps(payload)});")

    def select(self):
        r = self.reviewer
        self.token = None
        r._clear_auto_advance_timers()
        try:
            from .gui import now_ms

            self._requests = self.requests()
            ready = [request for request in self._requests if request.due_ms <= now_ms()]
        except (ValueError, TypeError):
            # The polling QueryOp reports corrupt/unsupported metadata. Keep
            # native study available without overwriting or guessing at it.
            self._requests = ready = []
        # An external operation/Undo may refresh an unfinished practice card.
        current = self.active if self.collection is self.mw.col and self.active in ready else None
        r._holdup_practice = False
        self._original["_get_next_v3_card"]()
        self._native_counts = (list(r._v3.counts()[1]) if r._v3 is not None
                               else list(self.mw.col.sched.counts()))
        # Anki restored a native answer. Keep its original on screen until it
        # is answered/left, even if a separate practice appearance is ready.
        # If another learning card became due while the original was open,
        # Anki's rebuilt head may differ. Restore its saved native presentation,
        # leaving the backend queue untouched. These are real scheduling states.
        if self._undo_info:
            try:
                card = self.mw.col.get_card(self._undo_card_id)
            except NotFoundError:
                # A normal delete action can remove the restored original.
                # Continue with Anki's available head instead of a stale pin.
                self._undo_info = self._undo_card_id = None
            else:
                expected = self._undo_info[1].top_card().card
                restored = (
                    (card.reps, card.queue, card.type, card.due, card.did)
                    == (expected.reps, expected.queue, expected.ctype, expected.due, expected.deck_id)
                    and card.odid == 0 and card.did in self.selected_decks()
                )
                if not restored:
                    # Redo/external operations can refresh before our operation
                    # hook runs. Never reuse pre-answer states for a changed card.
                    self._undo_info = self._undo_card_id = None
                elif r.card is None or r.card.id != self._undo_card_id:
                    r.card = card
                    r.card.start_timer()
                    r._v3 = deepcopy(self._undo_info[1])
                    for name, count in zip(("new_count", "learning_count", "review_count"), self._native_counts):
                        setattr(r._v3.queued_cards, name, count)
        undo_native = r.card is not None and r.card.id == self._undo_card_id
        if not undo_native:
            self._undo_card_id = None
            self._undo_info = None
        # Ordinary study merges with Anki's native head. Only Undo restores an
        # already-presented original ahead of the regular merge.
        clock = now_ms()
        sched = self.mw.col.sched
        insert_practice = ready and (r.card is None or ready[0].due_ms <= native_due_ms(
            r.card, clock, sched.today, sched.day_cutoff))
        request = None if undo_native else current or (ready[0] if insert_practice else None)
        self.active = request
        self.collection = self.mw.col
        if request is not None:
            r.card = self.mw.col.get_card(request.card_id)
            r.card.start_timer()
            r._v3 = None  # No scheduling states: this is not a native answer.
            r._holdup_practice = True

    def guard_rating(self, result, reviewer, _card):
        # Native _answerCard checks this hook BEFORE building an answer.
        # This also covers keyboard 1..4 and stray ease bridge messages.
        if reviewer is self.reviewer and (reviewer._holdup_practice or self.runtime.busy):
            return (False, result[1])
        return result

    def decorate(self, text, card, kind):
        if (self.active and self.reviewer._holdup_practice
                and card.id == self.active.card_id
                and kind in ("reviewQuestion", "reviewAnswer")):
            badge = (
                '<div class="holdup-practice-label" '
                'style="font:14px sans-serif;text-align:center;opacity:.75">'
                + escape(tr("HoldUp · practice without an FSRS rating")) + '</div>'
            )
            return badge + text
        return text

    def question_buttons(self):
        if not self.active:
            self._original["_showAnswerButton"]()
            self.update_counts()
            return
        self.token = None
        html = (
            '<table id="holdup-practice-question" cellpadding="0"><tr><td class="stat2" align="center">'
            '<button id="ansbut" onclick="pycmd(\'ans\')">'
            + escape(tr("Show Answer")) + '</button>'
            '</td></tr></table>'
        )
        self.reviewer.bottom.web.eval(f"showQuestion({json.dumps(html)}, 0);")
        self.update_counts()

    def answer_buttons(self):
        if not self.active:
            self._original["_showEaseButtons"]()
            self.update_counts()
            return
        self.token = secrets.token_urlsafe(18)
        config = self.runtime.settings()
        repeat_label = (tr("Next study day") if config["interval_mode"] == MODE_STUDY_DAY
                        else tr("Again in {interval}", interval=interval_label(config["interval_seconds"])))
        buttons = []
        actions = (("repeat", repeat_label), ("release", tr("Done")), ("interval", "⋯"))
        for action, title in actions:
            # Disable synchronously; a second click cannot act on the next card.
            command = PREFIX + action + ":" + self.token
            buttons.append(
                f'<button id="holdup-practice-{action}" '
                'onclick="this.parentNode.querySelectorAll(\'button\')'
                '.forEach(b=>b.disabled=true);'
                f'pycmd(\'{command}\')">{escape(title)}</button>'
            )
        html = '<div id="holdup-practice-actions">' + ''.join(buttons) + '</div>'
        self.reviewer.bottom.web.eval(f"showAnswer({json.dumps(html)}, true);")
        self.update_counts()

    def mutation(self):
        if self.active:
            self.reviewer._states_mutated = True
        else:
            return self._original["_run_state_mutation_hook"]()

    def auto_answer(self):
        if not self.active:
            return self._original["_auto_advance_to_answer_if_enabled"]()

    def auto_question(self):
        if not self.active:
            return self._original["_auto_advance_to_question_if_enabled"]()

    def enter(self):
        if self.active and self.reviewer.state == "answer":
            if self.mw.pm.spacebar_rates_card():
                self.act("repeat")
        else:
            return self._original["onEnterKey"]()

    def message(self, handled, message, context):
        if handled[0] or not message.startswith(PREFIX):
            return handled
        if not isinstance(context, ReviewerBottomBar) or context.reviewer is not self.reviewer:
            return handled
        parts = message[len(PREFIX):].split(":")
        if len(parts) == 2 and self.token and parts[1] == self.token:
            self.act(parts[0])
        return (True, None)

    def act(self, action):
        if (not self.token or not self.active or self.runtime.busy
                or self.mw.col is not self.collection or self.mw.state != "review"
                or self.reviewer.state != "answer" or not self.reviewer._holdup_practice
                or not self.reviewer.card or self.reviewer.card.id != self.active.card_id):
            return
        if action not in ("interval", "repeat", "release"):
            return
        self.token = None
        if action == "interval":
            self.runtime.configure()
        else:
            request = self.active
            if action == "repeat":
                self.runtime.repeat(request, self.finished)
            else:
                self.runtime.release(request, self.finished)

    def finished(self):
        self.active = self.token = None
        if self.mw.state == "review":
            self.reviewer.nextCard()

    def overview_bottom(self, handler, links):
        try:
            from .gui import now_ms

            requests = self.requests()
            count = sum(request.due_ms <= now_ms() for request in requests)
        except (ValueError, TypeError):
            count = 0  # The runtime reports the read error separately.
        if count:
            links.append(["", "holdup-continue", tr("Continue studying")])

        def link(message):
            if message == "holdup-continue":
                self.runtime.open_practice()
            else:
                return handler(message)
        return link

    def overview_content(self, content, context):
        if not isinstance(context, OverviewBottomBar) or context.overview is not self.mw.overview:
            return
        try:
            from .gui import now_ms

            requests = self.requests()
            ready = sum(request.due_ms <= now_ms() for request in requests)
        except (ValueError, TypeError):
            return
        if requests:
            content.body += (
                '<div id="holdup-overview-status" role="status" '
                'style="font:12px sans-serif;text-align:center;opacity:.8;margin:6px 0 4px;cursor:default">'
                + escape(tr("HoldUp: waiting {waiting} · ready {ready}", waiting=len(requests) - ready, ready=ready)) + '</div>'
            )
