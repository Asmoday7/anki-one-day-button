"""Present two independent schedules through the existing desktop reviewer.

Only GUI methods are adapted. The scheduler and its queue are left intact.
Private reviewer methods are version-sensitive: see the desktop contract tests.
"""

import json
import secrets
from html import escape
from typing import Any

from aqt import gui_hooks
from aqt.overview import OverviewBottomBar
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
        self.reviewer._holdup_practice = False
        self._original = {}
        for name, replacement in (
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
        gui_hooks.reviewer_will_end.append(self.clear)
        gui_hooks.profile_will_close.append(self.clear)
        gui_hooks.card_will_show.append(self.decorate)
        gui_hooks.webview_did_receive_js_message.append(self.message)
        gui_hooks.overview_will_render_bottom.append(self.overview_bottom)
        gui_hooks.webview_will_set_content.append(self.overview_content)

    def clear(self, *_args):
        self.active = self.collection = self.token = None
        self._requests = []
        self._native_counts = [0, 0, 0]
        self.reviewer._holdup_practice = False

    def requests(self):
        col = self.mw.col
        if col is None or col.decks.current()["dyn"]:
            return []
        decks = set(col.decks.active())
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
            decks = set(col.decks.active())
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
        # Merge deadlines with the real native head, never scan past it: Anki
        # rejects native answers that aren't at the top of its own queue.
        clock = now_ms()
        sched = self.mw.col.sched
        insert_practice = ready and (r.card is None or ready[0].due_ms <= native_due_ms(
            r.card, clock, sched.today, sched.day_cutoff))
        request = current or (ready[0] if insert_practice else None)
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
