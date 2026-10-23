"""Anki UI for timed practice. Imported only by the running desktop application."""

from dataclasses import dataclass
import time
from typing import Any, Callable

from aqt import gui_hooks
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import (
    QAction, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QPushButton, QRadioButton, QSpinBox, QTimer, QVBoxLayout,
)
from aqt.utils import show_warning

from .practice import MODE_STUDY_DAY, PracticeQueue, TimedRequest, validate_interval
from .deck_indicator import DeckIndicator, deck_paths
from .i18n import tr


def now_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(frozen=True)
class PracticeRow:
    request: TimedRequest
    available: bool
    deck_id: int
    deck_ids: tuple[int, ...]


class PracticeRuntime:
    def __init__(self, mw: Any) -> None:
        self.mw = mw
        self.controller = None
        self.rows: list[PracticeRow] = []
        self.busy = False
        self._query_running = False
        self._generation = 0
        self._read_version = 0
        self._last_error = None
        self._resume_checked = False
        self.indicator = DeckIndicator(self)
        from .review_flow import ReviewFlow

        self.flow = ReviewFlow(self)
        self._overview_count = None
        self.practice_action = QAction(tr("HoldUp: continue studying"), mw)
        self.practice_action.triggered.connect(self.open_practice)
        self.interval_action = QAction(tr("HoldUp: interval…"), mw)
        self.interval_action.triggered.connect(self.configure)
        self.restore_action = QAction(tr("HoldUp: clear all practice"), mw)
        self.restore_action.triggered.connect(self.restore_all)
        self.resume_action = QAction(tr("HoldUp: resume paused practice cards"), mw)
        self.resume_action.triggered.connect(self.resume_paused)
        mw.form.menuTools.addAction(self.practice_action)
        mw.form.menuTools.addAction(self.interval_action)
        mw.form.menuTools.addAction(self.restore_action)
        mw.form.menuTools.addAction(self.resume_action)
        self.timer = QTimer(mw)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        gui_hooks.profile_did_open.append(self.start)
        gui_hooks.profile_will_close.append(self.stop)
        gui_hooks.operation_did_execute.append(self.on_operation)
        if mw.col is not None:
            self.start()

    def settings(self) -> dict[str, Any]:
        config = self.mw.addonManager.getConfig(__name__) or {}
        seconds = config.get("interval_seconds", 86400)
        try:
            validate_interval(seconds)
        except ValueError:
            seconds = 86400
        mode = config.get("interval_mode", "seconds")
        if mode not in ("seconds", MODE_STUDY_DAY):
            mode = "seconds"
        return {"interval_seconds": seconds, "interval_mode": mode, "pause_native": False}

    def start(self, *_args: Any) -> None:
        self._last_error = None
        self._overview_count = None
        self._resume_checked = False
        self.timer.start()
        self.refresh()

    def stop(self, *_args: Any) -> None:
        self.timer.stop()
        self._generation += 1
        self._query_running = False
        self.flow.clear()
        self.rows = []
        self.indicator.clear()

    def on_operation(self, *_args: Any) -> None:
        self._read_version += 1
        self.refresh()

    def refresh(self) -> None:
        if self.mw.col is None or self.busy or self._query_running or self.mw._background_op_count:
            return
        collection, generation = self.mw.col, self._generation
        read_version = self._read_version
        self._query_running = True

        def read(col):
            queue = PracticeQueue(col)
            rows = []
            requests = queue.all()
            paths = deck_paths(col.decks.all_names_and_ids(include_filtered=False)) if requests else {}
            for request in requests:
                card = col.get_card(request.card_id)
                rows.append(PracticeRow(request, queue.available(request), card.did,
                                        paths.get(card.did, ())))
            return rows

        def done(rows):
            if generation != self._generation or self.mw.col is not collection:
                return
            self._query_running = False
            if read_version != self._read_version:
                self.refresh()
                return
            self._last_error = None
            self.rows = rows
            if not self._resume_checked:
                # Once per profile load, never on every poll: Undo must be able
                # to restore the previous pause without an automatic redo.
                self._resume_checked = True
                paused = [row.request for row in rows if row.request.original_queue is not None]
                if paused:
                    self.resume_paused(paused)
                    return
            self.resume_action.setEnabled(any(row.request.original_queue is not None for row in rows))
            self.indicator.update(rows)
            self.flow.update_counts(rows)
            decks = set(collection.decks.active())
            pending = sum(row.available and row.deck_id in decks for row in rows)
            count = sum(row.available and row.request.due_ms <= now_ms()
                        and row.deck_id in decks for row in rows)
            if collection.decks.current()["dyn"]:
                count = pending = 0
            self.practice_action.setText(tr("HoldUp: practice — ready {ready}, waiting {waiting}", ready=count, waiting=pending - count))
            # A poll only updates a count. It never changes the current card,
            # opens a window, or enters review without an explicit user action.
            if self.mw.state == "overview":
                if (count, pending) != self._overview_count:
                    self._overview_count = (count, pending)
                    self.mw.overview._renderBottom()

        def failed(error):
            if generation != self._generation:
                return
            self._query_running = False
            if read_version != self._read_version:
                self.refresh()
                return
            self.practice_action.setText(tr("HoldUp: practice — unable to read appointments"))
            self.indicator.clear()
            if str(error) != self._last_error:
                self._last_error = str(error)
                self.report(error)

        QueryOp(parent=self.mw, op=read, success=done).failure(failed).run_in_background()

    def report(self, error: Exception) -> None:
        show_warning(tr("HoldUp: the action could not be completed. It was not retried automatically.") + "\n\n" + str(error), parent=self.mw)

    def perform(self, operation: Callable, success: Callable | None = None, *, initiator: Any = None) -> None:
        if self.busy or self.mw.col is None:
            return
        collection, generation = self.mw.col, self._generation
        self._read_version += 1
        self.busy = True

        def run(col):
            if col is not collection:
                raise ValueError(tr("The open collection changed"))
            return operation(PracticeQueue(col))

        def done(_changes):
            # Anki dispatches operation_did_execute after this callback returns.
            # Navigating to overview here lets that hook refresh it a second
            # time, aborting its in-flight congrats fetch. Finish after the hook.
            def finish():
                self.busy = False
                if generation == self._generation and self.mw.col is collection:
                    if success is not None:
                        success()
                    self.refresh()

            QTimer.singleShot(0, finish)

        def failed(error):
            self.busy = False
            if generation == self._generation:
                self.report(error)
                if self.controller is not None and self.mw.state == "review" and self.mw.reviewer.card:
                    self.controller.on_answer(self.mw.reviewer.card)
                if self.flow.active and self.mw.state == "review":
                    self.mw.reviewer.nextCard()
                self.refresh()

        CollectionOp(parent=self.mw, op=run).success(done).failure(failed).run_in_background(initiator=initiator)

    def defer(self, card_id: int) -> None:
        config = self.settings()
        reviewer = self.mw.reviewer
        reviewer._clear_auto_advance_timers()

        self.perform(lambda queue: queue.enqueue(card_id, config["interval_seconds"], now_ms(),
                                               next_study_day=config["interval_mode"] == MODE_STUDY_DAY),
                     lambda: self.controller.on_deferred(card_id), initiator=reviewer)

    def repeat(self, request: TimedRequest, success: Callable | None = None) -> None:
        config = self.settings()
        self.perform(lambda q: q.repeat(request, config["interval_seconds"], now_ms(),
                                       next_study_day=config["interval_mode"] == MODE_STUDY_DAY),
                     success, initiator=self.mw.reviewer)

    def release(self, request: TimedRequest, success: Callable | None = None) -> None:
        self.perform(lambda q: q.release(request), success,
                     initiator=self.mw.reviewer)

    def restore_all(self) -> None:
        """Reversible escape hatch, including requests whose deadline is future.

        Scope is the open collection, not only the currently selected deck.
        The service preserves external queue changes and validates the batch.
        """
        def restore(queue):
            requests = queue.all()
            return queue.release_all(requests) if requests else queue.col.update_cards([])

        def refreshed():
            self.flow.clear()
            if self.mw.state == "review":
                self.mw.reviewer.nextCard()

        self.perform(restore, refreshed, initiator=self.mw.reviewer)

    def resume_paused(self, requests=None) -> None:
        # QAction passes a bool, while startup supplies its validated snapshot.
        expected = requests if isinstance(requests, list) else None

        def resume(queue):
            paused = expected if expected is not None else [r for r in queue.all() if r.original_queue is not None]
            return queue.resume_native(paused) if paused else queue.col.update_cards([])

        self.perform(resume)

    def configure(self) -> None:
        if self.busy:
            return
        dialog = QDialog(self.mw)
        dialog.setWindowTitle(tr("HoldUp — practice interval"))
        layout = QVBoxLayout(dialog)
        label = QLabel(tr("When should the next extra appearance be scheduled?"))
        label.setWordWrap(True)
        layout.addWidget(label)
        fixed = QRadioButton(tr("After an interval from 1 second to 24 hours"))
        fixed.setObjectName("holdup-mode-seconds")
        layout.addWidget(fixed)
        spin = QSpinBox()
        spin.setObjectName("holdup-interval-seconds")
        spin.setRange(1, 86400)
        spin.setSuffix(" " + tr("s"))
        spin.setValue(self.settings()["interval_seconds"])
        layout.addWidget(spin)
        fixed.toggled.connect(spin.setEnabled)
        presets = QHBoxLayout()

        def choose_seconds(value):
            fixed.setChecked(True)
            spin.setValue(value)

        for text, seconds in (("2 seconds", 2), ("2 minutes", 120), ("1 hour", 3600), ("1 day", 86400)):
            button = QPushButton(tr(text))
            button.clicked.connect(lambda _checked=False, value=seconds: choose_seconds(value))
            presets.addWidget(button)
        layout.addLayout(presets)
        study_day = QRadioButton(tr("Next Anki study day"))
        study_day.setObjectName("holdup-mode-next-study-day")
        layout.addWidget(study_day)
        if self.settings()["interval_mode"] == MODE_STUDY_DAY:
            study_day.setChecked(True)
            spin.setEnabled(False)
        else:
            fixed.setChecked(True)
        explanation = QLabel(tr("The study day starts at the time set in Anki's preferences. “1 day” above means exactly 24 hours."))
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        info = QLabel(tr("HoldUp adds an extra appearance of this card without an FSRS rating. The original stays in Anki: choose a normal rating after scheduling practice. This setting applies to subsequent actions."))
        info.setWordWrap(True)
        layout.addWidget(info)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            config = self.mw.addonManager.getConfig(__name__) or {}
            config.update(interval_seconds=spin.value(),
                          interval_mode=MODE_STUDY_DAY if study_day.isChecked() else "seconds")
            self.mw.addonManager.writeConfig(__name__, config)
        if self.flow.active and self.mw.state == "review" and self.mw.reviewer.state == "answer":
            self.flow.answer_buttons()
        if self.controller is not None and self.mw.state == "review" and self.mw.reviewer.card:
            self.controller.on_answer(self.mw.reviewer.card)

    def open_practice(self) -> None:
        self._open_review(lambda: bool(self.flow.due()))

    def open_undone_card(self) -> None:
        self._open_review(lambda: self.flow._undo_card_id is not None)

    def _open_review(self, should_enter: Callable[[], bool]) -> None:
        # Let the overview finish navigating before reusing its webviews.
        # Otherwise a late congrats-page load can replace the reviewer page.
        if self.mw.col is None or self.mw.state not in ("overview", "deckBrowser"):
            return
        collection, state = self.mw.col, self.mw.state
        deck_id = collection.decks.get_current_id()

        def enter():
            if (self.mw.col is not collection or self.mw.state != state
                    or collection.decks.get_current_id() != deck_id):
                return
            if (self.busy or self.mw._background_op_count
                    or not self.mw.web._domDone or not self.mw.bottomWeb._domDone
                    or self.mw.web.page().isLoading() or self.mw.bottomWeb.page().isLoading()):
                QTimer.singleShot(50, enter)
                return

            def proceed(ready=True):
                if (self.mw.col is not collection or self.mw.state != state
                        or collection.decks.get_current_id() != deck_id):
                    return
                if (not ready or self.busy or self.mw._background_op_count
                        or self.mw.web.page().isLoading() or self.mw.bottomWeb.page().isLoading()
                        or not self.mw.web._domDone or not self.mw.bottomWeb._domDone):
                    QTimer.singleShot(50, enter)
                elif should_enter():
                    self.mw.moveToState("review")

            if self.mw.web.page().url().path().rstrip("/").endswith("/congrats"):
                # Qt's loadFinished/DOM-ready precede Svelte's async info fetch.
                # Navigating before the rendered result can abort that fetch
                # and surface a native "Failed to fetch" alert after Undo.
                self.mw.web.evalWithCallback("document.querySelector('.congrats') !== null", proceed)
            else:
                proceed()

        QTimer.singleShot(0, enter)
