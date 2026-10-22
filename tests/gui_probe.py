"""Drive a packaged add-on in real desktop Anki and a disposable profile."""

from pathlib import Path
import sys
import time
import json


def main(base: Path, archive: Path, steps: str, language: str) -> None:
    import anki.lang
    import aqt
    from aqt import gui_hooks
    from aqt.addons import InstallOk
    from aqt.profiles import ProfileManager, VideoDriver
    from aqt.qt import QDialog, QEvent, QLabel, QPushButton, QRadioButton, QSpinBox, QTimer, Qt

    anki.lang.set_lang(language)
    base.mkdir(parents=True, exist_ok=True)
    pm = ProfileManager(base)
    pm.setupMeta()
    pm.create("HoldUpGUI")
    pm.load("HoldUpGUI")
    pm.meta.update(firstRun=False, defaultLang=language)
    pm.profile["autoSync"] = False
    pm.set_update_check(False)
    pm.set_check_for_addon_updates(False)
    pm.set_video_driver(VideoDriver.Software)
    pm.save()
    pm.db.close()
    app = aqt._run(["holdup-gui-test", "-b", str(base), "-p", "HoldUpGUI", "-l", language], exec=False)
    assert app is not None
    mw = aqt.mw
    assert mw is not None
    # Report unexpected JavaScript alerts as test failures instead of leaving
    # an unattended modal dialog open until the subprocess timeout.
    alerts = []
    import aqt.webview
    aqt.webview.showInfo = lambda message, **_kwargs: alerts.append(message)

    def wait_for(predicate, description, seconds=20):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            # This probe drives Qt without app.exec(); processEvents alone
            # leaves deleteLater() notifications (including Undo tooltips) alive.
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert not alerts, "Unexpected JavaScript alert: " + repr(alerts)
            if predicate():
                return
            time.sleep(0.01)
        mw.grab().save(str(base / "timeout.png"))
        print("TIMEOUT", description, "state", mw.state, mw.reviewer.state, "busy", mw._background_op_count, flush=True)
        raise AssertionError("Timed out: " + description)

    def js(expression, web=None):
        values = []
        (web or mw.bottomWeb).evalWithCallback(expression, values.append)
        wait_for(lambda: bool(values), "JavaScript result")
        return values[0]

    def button_ready():
        return js("""(() => {
            const b = document.querySelector('#holdup-button:not(:disabled)');
            if (!b) return false;
            const r = b.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.bottom <= innerHeight
                && r.left >= 0 && r.right <= innerWidth;
        })()""")

    def show_answer():
        # Drive the real Show Answer bridge after native question rendering,
        # rather than invoking _showAnswer during an outstanding focus redraw.
        wait_for(lambda: mw.reviewer.state == "question" and js("document.getElementById('ansbut') !== null"), "native Show Answer button")
        js("document.getElementById('ansbut').click(); true")
        wait_for(button_ready, "HoldUp after native Show Answer")

    def check_layout(mode):
        # Inspect real QtWebEngine geometry, including captions/text rather
        # than only button boxes (which missed the clipped footer in 0.2.0).
        if language == "ru" and mode in ("normal", "scheduled"):
            js("""document.querySelectorAll('#middle button[data-ease]').forEach(b => {
                const labels = {1:'Снова', 2:'Трудно', 3:'Хорошо', 4:'Легко'};
                b.firstChild.replaceWith(document.createTextNode(labels[b.dataset.ease]));
            }); true""")
        expression = """(() => {
            const buttons = Array.from(document.querySelectorAll('#middle button'));
            const visible = r => r.width > 0 && r.height > 0 && r.left >= -1
                && r.right <= innerWidth + 1 && r.top >= -1 && r.bottom <= innerHeight + 1;
            if (!buttons.length || !buttons.every(b => visible(b.getBoundingClientRect()))) return false;
            for (const b of buttons) {
                const r = b.getBoundingClientRect();
                const range = document.createRange();
                range.selectNode(b.firstChild);
                const text = range.getBoundingClientRect();
                if (!visible(text) || text.left < r.left || text.right > r.right) return false;
            }
            const captions = Array.from(document.querySelectorAll('#middle .nobold, #middle .stattxt, #holdup-queue-counts span, #holdup-waiting')).filter(c => c.getClientRects().length);
            if (!captions.every(c => visible(c.getBoundingClientRect()))) return false;
            const one = document.getElementById('holdup-button');
            if (one) {
                const native = Array.from(document.querySelectorAll('#middle button[data-ease]'));
                if (native.length !== 4 || native.some(b =>
                    Math.abs(b.offsetWidth - one.offsetWidth) > 1 ||
                    Math.abs(b.offsetHeight - one.offsetHeight) > 1 ||
                    getComputedStyle(b).fontSize !== getComputedStyle(one).fontSize)) return false;
                const settings = document.getElementById('holdup-interval');
                if (Math.abs(settings.offsetHeight - one.offsetHeight) > 1 ||
                    Math.abs(settings.offsetWidth - one.offsetHeight) > 1) return false;
            }
            return document.documentElement.scrollWidth <= innerWidth + 1;
        })()"""
        # CSS zoom is Anki's ANKI_WEBSCALE mechanism; font size also simulates
        # larger UI fonts. This exercises wrapping and footer height changes.
        for width, zoom, font in ((667, 1, 15), (1100, 1, 20), (667, 1.5, 20), (667, 2, 15)):
            mw.resize(width, 800)
            js(f"document.body.style.zoom = {zoom}; document.documentElement.style.fontSize = '{font}px'; true")
            wait_for(lambda: js(expression), f"{mode} layout at {width}px, zoom {zoom}, font {font}")
            if mode == "normal" and zoom == 1.5:
                from PyQt6.QtTest import QTest
                QTest.qWait(200)
                mw.grab().save(str(base / "holdup-layout-large.png"))
        js("document.body.style.zoom = 1; document.documentElement.style.removeProperty('font-size'); true")
        mw.resize(900, 800)
        wait_for(lambda: js(expression), mode + " layout after restore")
        from PyQt6.QtTest import QTest
        QTest.qWait(200)

    def visible_counts():
        return js("Array.from(document.querySelectorAll('#holdup-queue-counts > span')).map(s=>Number(s.textContent))")

    def expect_counts(total, ready=None):
        def matches():
            if len(visible_counts()) != 3:
                return False
            state = js("""(() => {
                const s = document.getElementById('holdup-waiting');
                return s ? [Number(s.dataset.ready), Number(s.dataset.waiting)] : null;
            })()""")
            return state and sum(state) == total and (ready is None or state[0] == ready)
        wait_for(matches, "three counters and passive HoldUp status")
        assert js("document.querySelectorAll('#holdup-queue-counts').length") == 1
        assert js("document.querySelectorAll('.holdup-count').length") == 0
        assert js("""(() => {
            const s = document.getElementById('holdup-waiting');
            return s.tagName === 'DIV' && !s.onclick && !s.closest('button, a')
                && !s.hasAttribute('tabindex');
        })()""")
        return visible_counts()

    def plus_practice(native, ready):
        return [native[0], native[1], native[2] + ready]

    def deck_badges():
        return js("""Object.fromEntries(Array.from(document.querySelectorAll('tr.deck[id] .holdup-deck-badge'))
            .map(b=>[b.closest('tr').id, Number(b.dataset.count)]))""", mw.web)

    def expect_deck_badges(expected):
        wait_for(lambda: mw.web._domDone and not mw.web.page().isLoading()
                 and deck_badges() == {str(key): value for key, value in expected.items()}, "deck-list ready indicators")
        for count, title in js("Array.from(document.querySelectorAll('.holdup-deck-badge')).map(b=>[b.dataset.count,b.title])", mw.web):
            assert title == (f"HoldUp: к повторению {count} (включая подколоды)" if language == "ru"
                             else f"HoldUp: ready {count} (including subdecks)")

    def snapshot(card):
        result = {name: getattr(card, name) for name in (
            "due", "odue", "did", "odid", "type", "queue", "ivl", "factor", "reps", "lapses", "left",
            "original_position", "last_review_time", "desired_retention", "decay",
        )}
        result["memory"] = card.memory_state.SerializeToString() if card.memory_state else None
        return result

    def wait_page():
        wait_for(lambda: mw._background_op_count == 0 and mw.web._domDone
                 and not mw.web.page().isLoading() and mw.bottomWeb._domDone
                 and not mw.bottomWeb.page().isLoading(), "native page loaded")
        if mw.web.page().url().path().rstrip("/").endswith("/congrats"):
            wait_for(lambda: js("document.querySelector('.congrats') !== null", mw.web), "native congrats data loaded")

    try:
        wait_for(lambda: mw.col is not None and mw.state == "deckBrowser" and mw._background_op_count == 0
                 and mw.web._domDone and mw.bottomWeb._domDone, "profile before saved-data fixture")
        # Public Card API prepares a persisted paused request before startup.
        # Recovery must restore native eligibility and retain its practice deadline.
        col = mw.col
        # Built-in model, field and default deck names are translated by Anki.
        col.decks.rename(1, "Default")
        model = next(m for m in col.models.all() if m["type"] == 0 and len(m["flds"]) == 2 and len(m["tmpls"]) == 1)
        saved_deck = col.decks.id("Saved practice")
        paused_note = col.new_note(model)
        paused_note.fields[0], paused_note.fields[1] = "Paused practice card", "Saved answer"
        col.add_note(paused_note, saved_deck)
        paused_id = paused_note.card_ids()[0]
        paused_card = col.get_card(paused_id)
        paused_before = snapshot(paused_card)
        paused_due = time.time_ns() // 1_000_000 - 1000
        paused_card.custom_data = json.dumps({"odbv": 2, "odbat": paused_due, "odbsecs": 86400, "odbq": 0})
        paused_card.queue = -1
        col.update_card(paused_card)
        # Reinstall the package without loading its hooks twice.
        assert isinstance(mw.addonManager.install(str(archive)), InstallOk)
        mw.addonManager.writeConfig("holdup", {"interval_seconds": 120, "interval_mode": "seconds"})
        saved_note = col.new_note(model)
        saved_note.fields[0], saved_note.fields[1] = "Saved calendar practice", "Saved answer"
        col.add_note(saved_note, saved_deck)
        saved_id = saved_note.card_ids()[0]
        saved_card = col.get_card(saved_id)
        saved_before = snapshot(saved_card)
        saved_due = col.sched.day_cutoff * 1000
        saved_card.custom_data = json.dumps({"odbv": 3, "odbat": saved_due, "odbsecs": 86400, "odbnext": 1})
        col.update_card(saved_card)
        assert isinstance(mw.addonManager.install(str(archive)), InstallOk)
        mw.addonManager.loadAddons()
        assert Path(sys.modules["holdup"].__file__).resolve().is_relative_to(base.resolve())
        wait_for(lambda: mw.col is not None and mw.state == "deckBrowser" and mw._background_op_count == 0
                 and mw.web._domDone and mw.bottomWeb._domDone, "profile startup")
        from holdup.practice import PracticeQueue
        from holdup.reviewer_adapter import _controller

        runtime = _controller.runtime
        from holdup.i18n import language as detected_language
        assert detected_language() == language
        assert runtime.restore_action.text() == ("HoldUp: убрать всю практику" if language == "ru" else "HoldUp: clear all practice")
        col = mw.col
        queue = PracticeQueue(col)
        assert runtime.settings() == {"interval_seconds": 120, "interval_mode": "seconds", "pause_native": False}
        saved = queue.get(saved_id)
        assert saved.next_study_day and saved.due_ms == saved_due
        assert snapshot(col.get_card(saved_id)) == saved_before and not col.get_review_logs(saved_id)
        wait_for(lambda: not runtime.busy and queue.get(paused_id).original_queue is None, "saved pause recovery")
        assert queue.get(paused_id).due_ms == paused_due
        assert snapshot(col.get_card(paused_id)) == paused_before and not col.get_review_logs(paused_id)
        assert runtime._resume_checked
        expect_deck_badges({saved_deck: 1})  # Existing ready practice is visible on startup.
        queue.release(queue.get(paused_id))
        queue.release(saved)
        print("PASS native install, saved settings, appointments and pause recovery", flush=True)
        col.set_config("fsrs", True)
        config = col.decks.config_dict_for_deck_id(1)
        config["new"]["delays"] = [1, 10] if steps == "minutes" else []
        config["autoplay"] = False
        config["new"]["perDay"] = 2  # Three cards exist, only two may be introduced.
        col.decks.update_config(config)
        for index in range(3):
            note = col.new_note(model)
            note.fields[0], note.fields[1] = f"Practice question {index}", f"Practice answer {index}"
            col.add_note(note, 1)
        default_ids = set(col.find_cards("deck:Default"))
        assert len(default_ids) == 3
        answered, undone = [], []
        gui_hooks.reviewer_did_answer_card.append(lambda reviewer, card, ease: answered.append((card.id, ease)))
        gui_hooks.state_did_undo.append(undone.append)

        def focus_main():
            app.setActiveWindow(mw)
            mw.web.setFocus()
            app.processEvents()

        def undo():
            focus_main()
            wait_page()
            count = len(undone)
            assert mw.form.actionUndo.isEnabled()
            mw.form.actionUndo.trigger()
            wait_for(lambda: len(undone) == count + 1 and mw._background_op_count == 0, "native Undo")

        mw.moveToState("review")
        wait_for(lambda: mw.reviewer.state == "question" and mw.bottomWeb._domDone, "question")
        wait_for(lambda: js("typeof HoldUpButton === 'object'") and js("typeof _showAnswer === 'function'", mw.web), "web assets")
        assert js("document.getElementById('holdup-button') === null")
        first_id = mw.reviewer.card.id
        assert expect_counts(0) == [2, 0, 0]
        before = snapshot(col.get_card(first_id))
        show_answer()
        assert expect_counts(0) == [2, 0, 0]
        assert js("Array.from(document.querySelectorAll('#middle button[data-ease]')).map(b => b.dataset.ease)") == ["1", "2", "3", "4"]
        assert js("document.querySelector('#holdup-button .nobold').textContent") == ("2 мин" if language == "ru" else "2 min")
        assert js("document.getElementById('holdup-button').firstChild.textContent") == "HoldUp"
        assert js("document.getElementById('holdup-interval').title") == ("Изменить интервал отдельной практики" if language == "ru" else "Change the extra practice interval")

        def choose_study_day():
            dialog = app.activeModalWidget()
            mode = dialog.findChild(QRadioButton, "holdup-mode-next-study-day") if dialog else None
            if mode is None:
                QTimer.singleShot(25, choose_study_day)
                return
            mode.setChecked(True)
            assert dialog.windowTitle() == ("HoldUp — интервал практики" if language == "ru" else "HoldUp — practice interval")
            assert mode.text() == ("Следующий учебный день Anki" if language == "ru" else "Next Anki study day")
            if language == "en":
                assert all(not any("\u0400" <= ch <= "\u04ff" for ch in label.text()) for label in dialog.findChildren(QLabel))
            assert not dialog.findChild(QSpinBox, "holdup-interval-seconds").isEnabled()
            dialog.grab().save(str(base / "holdup-study-day-settings.png"))
            dialog.accept()

        QTimer.singleShot(25, choose_study_day)
        js("document.getElementById('holdup-interval').click(); true")
        wait_for(lambda: runtime.settings()["interval_mode"] == "next_study_day" and button_ready(), "study-day setting saved")
        assert mw.addonManager.getConfig("holdup")["interval_mode"] == "next_study_day"
        assert js("document.querySelector('#holdup-button .nobold').textContent") == ("Учебный день" if language == "ru" else "Study day")
        check_layout("normal")
        js("document.getElementById('holdup-button').click(); true")
        wait_for(lambda: not runtime.busy and queue.get(first_id) is not None, "calendar request")
        calendar = queue.get(first_id)
        assert calendar.next_study_day and calendar.due_ms == col.sched.day_cutoff * 1000
        assert snapshot(col.get_card(first_id)) == before and not col.get_review_logs(first_id)
        assert mw.reviewer.state == "answer"
        assert js("Array.from(document.querySelectorAll('#middle button[data-ease]')).every(b => !b.disabled)")
        undo()
        wait_for(lambda: queue.get(first_id) is None, "Undo calendar request")
        if mw.reviewer.state == "question":
            show_answer()
        else:
            wait_for(button_ready, "HoldUp available after Undo on answer")

        def cancel_saved_study_day():
            dialog = app.activeModalWidget()
            mode = dialog.findChild(QRadioButton, "holdup-mode-next-study-day") if dialog else None
            if mode is None:
                QTimer.singleShot(25, cancel_saved_study_day)
                return
            assert mode.isChecked()
            dialog.findChild(QRadioButton, "holdup-mode-seconds").setChecked(True)
            dialog.reject()

        QTimer.singleShot(25, cancel_saved_study_day)
        js("document.getElementById('holdup-interval').click(); true")
        wait_for(button_ready, "calendar mode after cancelled dialog")
        assert runtime.settings()["interval_mode"] == "next_study_day"

        configured = []
        def set_interval():
            dialog = app.activeModalWidget()
            spin = dialog.findChild(QSpinBox, "holdup-interval-seconds") if dialog else None
            if spin is None:
                QTimer.singleShot(25, set_interval)
                return
            assert spin.minimum() == 1 and spin.maximum() == 86400
            next(b for b in dialog.findChildren(QPushButton) if b.text() == ("2 секунды" if language == "ru" else "2 seconds")).click()
            assert dialog.findChild(QRadioButton, "holdup-mode-seconds").isChecked()
            assert spin.isEnabled() and spin.value() == 2
            configured.append(True)
            dialog.accept()

        QTimer.singleShot(25, set_interval)
        js("document.getElementById('holdup-interval').click(); true")
        wait_for(lambda: bool(configured) and runtime.settings()["interval_seconds"] == 2, "interval dialog")
        wait_for(button_ready, "button after settings")
        focus_main()
        assert js("document.querySelector('#holdup-button .nobold').textContent") == ("2 с" if language == "ru" else "2 s")
        mw.reviewer._showEaseButtons()
        wait_for(button_ready, "native redraw")
        assert js("document.querySelectorAll('#holdup-button').length") == 1
        assert js("document.documentElement.scrollWidth <= innerWidth"), js("""JSON.stringify({
            width:innerWidth,scroll:document.documentElement.scrollWidth,
            buttons:Array.from(document.querySelectorAll('button')).map(b=>({text:b.textContent,
                width:b.offsetWidth,left:b.getBoundingClientRect().left,margin:getComputedStyle(b).margin}))})""")
        assert js("""Array.from(document.querySelectorAll('#middle button')).every(b => {
            const r = b.getBoundingClientRect();
            return r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth;
        })"""), js("document.body.innerHTML")
        check_layout("normal")
        from PyQt6.QtTest import QTest
        QTest.qWait(100)
        mw.grab().save(str(base / "holdup-button.png"))
        print("PASS interval dialog, fifth button and native redraw", flush=True)

        old_token = js("document.getElementById('holdup-button').dataset.token")
        # Exclude the earlier native Undo notification from the window baseline.
        from aqt.utils import closeTooltip
        closeTooltip()
        wait_for(lambda: not any(w.isVisible() and w.windowType() == Qt.WindowType.ToolTip
                                 for w in app.topLevelWidgets()), "native Undo notification closes")
        windows = {w for w in app.topLevelWidgets() if w.isVisible()}
        js("document.getElementById('holdup-button').click(); document.getElementById('holdup-button')?.click(); true")
        wait_for(lambda: not runtime.busy and queue.get(first_id) is not None, "virtual extra request")
        request = queue.get(first_id)
        assert request.original_queue is None
        assert mw.reviewer.card.id == first_id and mw.reviewer.state == "answer"
        assert snapshot(col.get_card(first_id)) == before
        assert expect_counts(1, ready=0) == [2, 0, 0]
        assert js("document.querySelector('#holdup-button .nobold').textContent") == ("✓ 2 с" if language == "ru" else "✓ 2 s")
        assert js("Array.from(document.querySelectorAll('#middle button[data-ease]')).every(b=>!b.disabled)")
        assert col.sched.get_queued_cards().cards[0].card.id == first_id
        count_step = col.undo_status().last_step
        assert not col.get_review_logs(first_id) and answered == []
        assert len(queue.all()) == 1
        check_layout("scheduled")
        # Read-only deadline updates must not advance/replenish the new queue.
        wait_for(lambda: time.time_ns() // 1_000_000 > request.due_ms + 1100, "real deadline without interruption")
        assert mw.reviewer.card.id == first_id and mw.reviewer.state == "answer"
        assert not runtime.flow.active
        assert expect_counts(1, ready=1) == [2, 0, 1]
        assert js("document.getElementById('holdup-waiting').textContent") == ("HoldUp: ожидают 0" if language == "ru" else "HoldUp: waiting 0")
        assert col.undo_status().last_step == count_step
        assert {w for w in app.topLevelWidgets() if w.isVisible()} == windows
        js("pycmd('holdup-button:' + " + repr(old_token) + "); true")
        assert queue.get(first_id) == request
        # The original is still on screen: its explicit Good consumes the native
        # new-card allowance and records exactly one FSRS answer, not a duplicate.
        js("document.querySelector('#middle button[data-ease=\"3\"]').click(); true")
        wait_for(lambda: len(answered) == 1 and runtime.flow.active == request and mw.reviewer.state == "question", "native Good then independent practice")
        assert mw.reviewer.card.id == first_id and mw.reviewer._v3 is None
        logs = col.get_review_logs(first_id)
        assert len(logs) == 1 and logs[0].button_chosen == 3
        assert col.get_card(first_id).memory_state is not None
        assert col.get_card(first_id).queue == (1 if steps == "minutes" else 2)
        after_good = snapshot(col.get_card(first_id))
        practice_native_counts = list(col.sched.counts())
        assert practice_native_counts[0] == 1
        assert expect_counts(1, ready=1) == plus_practice(practice_native_counts, 1)
        assert js("document.querySelector('#holdup-queue-counts .review-count').getAttribute('aria-current')") == "true"
        print("PASS virtual request, native Good, new limit and green grouping", flush=True)

        def show_practice_answer():
            wait_for(lambda: mw.reviewer.state == "question" and js("document.getElementById('ansbut') !== null"), "practice Show Answer")
            assert js("document.querySelector('.holdup-practice-label') !== null", mw.web)
            assert js("document.querySelector('#ansbut .stattxt') === null")
            js("document.getElementById('ansbut').click(); true")
            wait_for(lambda: js("document.querySelector('#holdup-practice-repeat:not(:disabled)') !== null"), "practice answer controls")
            assert js("document.querySelectorAll('#middle button[data-ease]').length") == 0
            assert js("document.getElementById('holdup-button') === null")

        check_layout("practice-question")
        mw.grab().save(str(base / "holdup-practice-question.png"))
        show_practice_answer()
        assert expect_counts(1, ready=1) == plus_practice(practice_native_counts, 1)
        check_layout("practice-answer")
        mw.reviewer.auto_advance_enabled = True
        runtime.flow.auto_answer()
        runtime.flow.auto_question()
        assert mw.reviewer._show_question_timer is None
        assert mw.reviewer._show_answer_timer is None
        mw.reviewer.auto_advance_enabled = False
        old_customizer = mw.reviewer._state_mutation_js
        mw.reviewer._state_mutation_js = "throw new Error('must not run in practice')"
        runtime.flow.mutation()
        assert mw.reviewer._states_mutated
        mw.reviewer._state_mutation_js = old_customizer
        def cancel_interval():
            dialog = app.activeModalWidget()
            if dialog is None:
                QTimer.singleShot(25, cancel_interval)
            else:
                dialog.reject()
        QTimer.singleShot(25, cancel_interval)
        js("document.getElementById('holdup-practice-interval').click(); true")
        wait_for(lambda: js("document.querySelector('#holdup-practice-repeat:not(:disabled)') !== null"), "practice controls after settings")
        focus_main()
        assert queue.get(first_id) == request
        for rating in (1, 2, 3, 4):
            mw.reviewer._answerCard(rating)
        assert snapshot(col.get_card(first_id)) == after_good
        assert len(col.get_review_logs(first_id)) == 1 and answered == [(first_id, 3)]
        assert js("document.body.innerText.includes('Practice answer 0')", mw.web)
        QTest.qWait(100)
        mw.grab().save(str(base / "holdup-inline-practice.png"))
        # Calendar mode is available from practice too; no native rating occurs.
        QTimer.singleShot(25, choose_study_day)
        js("document.getElementById('holdup-practice-interval').click(); true")
        wait_for(lambda: js("document.getElementById('holdup-practice-repeat')?.textContent") == ("Следующий учебный день" if language == "ru" else "Next study day"), "calendar repeat caption")
        check_layout("practice-answer")
        stale_repeat = runtime.flow.token
        js("document.getElementById('holdup-practice-repeat').click(); document.getElementById('holdup-practice-repeat')?.click(); true")
        wait_for(lambda: not runtime.busy and queue.get(first_id).due_ms > request.due_ms
                 and not runtime.flow.active and mw.reviewer.state == "question", "repeat then native card")
        assert expect_counts(1, ready=0) == practice_native_counts
        assert queue.get(first_id).next_study_day and queue.get(first_id).due_ms == col.sched.day_cutoff * 1000
        assert snapshot(col.get_card(first_id)) == after_good and len(col.get_review_logs(first_id)) == 1
        js("pycmd('holdup-practice:repeat:' + " + repr(stale_repeat) + "); true")
        undo()
        wait_for(lambda: queue.get(first_id) == request and mw.reviewer.state == "question", "Undo repeat")
        mw.addonManager.writeConfig("holdup", {"interval_seconds": 86400, "interval_mode": "seconds"})
        if not runtime.flow.active:
            mw.reviewer.nextCard()
        wait_for(lambda: runtime.flow.active == request, "restored practice")
        assert expect_counts(1, ready=1) == plus_practice(practice_native_counts, 1)
        show_practice_answer()
        js("document.getElementById('holdup-practice-release').click(); true")
        wait_for(lambda: not runtime.busy and queue.get(first_id) is None
                 and not runtime.flow.active and mw.reviewer.state == "question", "Done removes only the extra request")
        assert snapshot(col.get_card(first_id)) == after_good and len(col.get_review_logs(first_id)) == 1
        assert expect_counts(0, ready=0) == list(col.sched.counts())
        undo()
        wait_for(lambda: runtime.flow.active == request and mw.reviewer.state == "question", "Undo Done restores only the extra request")
        assert snapshot(col.get_card(first_id)) == after_good
        assert expect_counts(1, ready=1) == plus_practice(practice_native_counts, 1)
        show_practice_answer()
        js("document.getElementById('holdup-practice-release').click(); true")
        wait_for(lambda: not runtime.busy and queue.get(first_id) is None
                 and not runtime.flow.active and mw.reviewer.state == "question", "finish restored practice")
        assert snapshot(col.get_card(first_id)) == after_good
        print("PASS inline controls, rating guard, repeat, Undo and unchanged native state", flush=True)

        # Scope excludes another deck; no migration of old active requests occurs.
        other_deck = col.decks.id("Other deck")
        note = col.new_note(model)
        note.fields[0], note.fields[1] = "Other deck practice", "Other answer"
        col.add_note(note, other_deck)
        other_id = note.card_ids()[0]
        queue.enqueue(other_id, 1, time.time_ns() // 1_000_000)
        wait_for(lambda: time.time_ns() // 1_000_000 > queue.get(other_id).due_ms, "other deck deadline")
        assert other_id not in [r.card_id for r in runtime.flow.due()]
        expect_counts(0)
        queue.release(queue.get(other_id))
        col.decks.select(1)
        mw.reviewer.nextCard()
        wait_for(lambda: mw.reviewer.state == "question", "normal flow resumes")
        second_id = mw.reviewer.card.id
        assert second_id != first_id
        show_answer()
        previous = len(answered)
        js("document.querySelector('#middle button[data-ease=\"3\"]').click(); true")
        wait_for(lambda: len(answered) == previous + 1, "explicit Good on second native card")
        assert len(col.get_review_logs(second_id)) == 1

        # Defer a red learning card too, then verify future deadlines are excluded
        # from green and all ordinary ratings still go through the real scheduler.
        pending_id = None
        future = None
        pending_before = None
        for _ in range(10):
            wait_for(lambda: mw._background_op_count == 0, "native operation")
            if mw.state != "review":
                break
            cid = mw.reviewer.card.id
            show_answer()
            if steps == "minutes" and pending_id is None and mw.reviewer.card.queue == 1:
                pending_id = cid
                pending_before = snapshot(col.get_card(cid))
                js("document.getElementById('holdup-button').click(); true")
                wait_for(lambda: not runtime.busy and queue.get(cid) is not None, "HoldUp on red learning queue")
                future = queue.get(cid)
                assert future.original_queue is None
                assert snapshot(col.get_card(cid)) == pending_before
                assert mw.reviewer.card.id == cid and mw.reviewer.state == "answer"
                assert js("Array.from(document.querySelectorAll('#middle button[data-ease]')).every(b=>!b.disabled)")
                previous = len(answered)
                js("document.querySelector('#middle button[data-ease=\"4\"]').click(); true")
                wait_for(lambda: len(answered) == previous + 1, "native Easy after HoldUp on learning card")
                assert queue.get(cid) == future
                pending_before = snapshot(col.get_card(cid))
            else:
                previous = len(answered)
                js("document.querySelector('#middle button[data-ease=\"4\"]').click(); true")
                wait_for(lambda: len(answered) == previous + 1, "native Easy")
        wait_for(lambda: mw.state == "overview" and mw._background_op_count == 0, "native queue complete")
        wait_page()
        if steps == "none":
            pending_id = first_id
            pending_before = snapshot(col.get_card(first_id))
            runtime.perform(lambda q: q.enqueue(first_id, 86400, time.time_ns() // 1_000_000), initiator=mw.reviewer)
            wait_for(lambda: not runtime.busy and queue.get(first_id) is not None, "future practice on review card")
            future = queue.get(first_id)
        assert future and future.due_ms > time.time_ns() // 1_000_000
        assert set(col.find_cards("deck:Default")) == default_ids
        introduced = {cid for cid, _ease in answered}
        assert len(introduced) == 2
        unseen = default_ids - introduced
        assert len(unseen) == 1 and set(col.find_cards("deck:Default is:new")) == unseen
        assert all(not col.get_review_logs(cid) and queue.get(cid) is None for cid in unseen)
        assert not col.sched.get_queued_cards().cards  # The third word stays behind the daily limit.
        wait_for(lambda: runtime._overview_count == (0, 1) and mw.bottomWeb._domDone
                 and not mw.bottomWeb.page().isLoading(), "waiting footer loaded")
        wait_for(lambda: js("document.querySelector('#holdup-overview-status')?.textContent.includes(" + json.dumps("ожидают 1" if language == "ru" else "waiting 1") + ")"), "passive overview waiting status")
        assert js("document.getElementById('holdup-overview-status').tagName") == "DIV"
        assert not js("document.querySelector('button[onclick*=holdup-continue]') !== null")
        # Removing practice works before the deadline; Undo restores metadata only.
        wait_page()
        runtime.restore_action.trigger()
        wait_for(lambda: not runtime.busy and not queue.all(), "restore all before deadline")
        assert snapshot(col.get_card(pending_id)) == pending_before
        # A CollectionOp schedules an overview redraw after its success callback.
        # Wait for that page before invoking Undo, rather than aborting Anki's
        # own in-flight congrats fetch with another immediate navigation.
        wait_for(lambda: mw.web._domDone and mw.bottomWeb._domDone
                 and not mw.web.page().isLoading() and not mw.bottomWeb.page().isLoading()
                 and mw._background_op_count == 0, "restore-all overview loaded")
        QTest.qWait(200)
        undo()
        wait_for(lambda: queue.get(pending_id) == future and mw._background_op_count == 0, "Undo removing all practice")
        assert snapshot(col.get_card(pending_id)) == pending_before
        wait_for(lambda: mw.web._domDone and mw.bottomWeb._domDone
                 and not mw.web.page().isLoading() and not mw.bottomWeb.page().isLoading(), "overview after restoration Undo")
        QTest.qWait(200)
        print("PASS blue/red native ratings, daily limit, deck scope and practice removal", flush=True)

        # On the home screen future practice stays quiet; ready practice gets a
        # passive badge, even when all three native counts are zero.
        if mw.web.page().url().path().rstrip("/").endswith("/congrats"):
            wait_for(lambda: js("document.querySelector('.congrats') !== null", mw.web), "congrats before deck list")
        mw.moveToState("deckBrowser")
        expect_deck_badges({})
        parent_deck = col.decks.id("Ready parent")
        child_deck = col.decks.id("Ready parent::Child")
        leaf_deck = col.decks.id("Ready parent::Child::Leaf")
        child_ids = []
        for did in (child_deck, leaf_deck):
            note = col.new_note(model)
            note.fields[0], note.fields[1] = "Subdeck practice", "Answer"
            col.add_note(note, did)
            child_ids.append(note.card_ids()[0])
        # Fixture writes bypass the Add window's normal operation notification.
        mw.deckBrowser.refresh()
        wait_page()
        wait_for(lambda: js(f"document.getElementById('{parent_deck}') !== null", mw.web), "fixture deck tree rendered")

        # Practice alone resumes in this same reviewer; no normal Default card is due.
        ready_id = next(cid for cid in col.find_cards("deck:Default is:review") if cid != pending_id)
        ready_before = snapshot(col.get_card(ready_id))
        assert ready_before["queue"] == 2 and ready_before["due"] > col.sched.today
        def enqueue_home(q):
            for cid in [ready_id, *child_ids]:
                changes = q.enqueue(cid, 2, time.time_ns() // 1_000_000)
            return changes
        runtime.perform(enqueue_home, initiator=mw.deckBrowser)
        wait_for(lambda: not runtime.busy and queue.get(ready_id) is not None, "practice-only request")
        due = queue.get(ready_id)
        native_state = snapshot(col.get_card(ready_id))
        native_logs = len(col.get_review_logs(ready_id))
        expected_badges = {1: 1, parent_deck: 2, child_deck: 2, leaf_deck: 1}
        expect_deck_badges({1: 1, parent_deck: 2})  # New Anki decks start collapsed.
        mw.web.eval(f"document.getElementById('{parent_deck}').querySelector('a.collapse').click()")
        expect_deck_badges({1: 1, parent_deck: 2, child_deck: 2})
        mw.web.eval(f"document.getElementById('{child_deck}').querySelector('a.collapse').click()")
        expect_deck_badges(expected_badges)  # Same deadline, expanded hierarchy.
        assert mw.state == "deckBrowser"
        assert js("""Array.from(document.getElementById('1').querySelectorAll('td:not(.decktd) span'))
            .map(s=>Number(s.textContent))""", mw.web) == [0, 0, 0]
        assert js("""Array.from(document.querySelectorAll('.holdup-deck-badge')).every(b=>
            b.tagName === 'SPAN' && !b.closest('a, button') && !b.onclick && !b.hasAttribute('tabindex'))""", mw.web)
        step = col.undo_status().last_step
        runtime.refresh()
        wait_for(lambda: not runtime._query_running and mw._background_op_count == 0, "read-only badge poll")
        assert col.undo_status().last_step == step and snapshot(col.get_card(ready_id)) == native_state
        assert len(col.get_review_logs(ready_id)) == native_logs

        for night in (False, True):
            js(f"document.documentElement.classList.toggle('night-mode', {str(night).lower()}); true", mw.web)
            for width, zoom in ((1100, 1), (667, 1.5), (667, 2)):
                mw.resize(width, 800)
                js(f"document.body.style.zoom = {zoom}; true", mw.web)
                wait_for(lambda: js("""Array.from(document.querySelectorAll('.holdup-deck-badge')).every(b=>{
                    const r=b.getBoundingClientRect(); const t=b.lastChild.getBoundingClientRect();
                    return r.width>0 && r.left>=0 && r.right<=innerWidth+1 && r.top>=0
                        && r.bottom<=innerHeight && t.left>=r.left && t.right<=r.right;
                })""", mw.web), "badge geometry at zoom/theme")
            js("document.body.style.zoom = 1; true", mw.web)
            mw.resize(900, 800)
            QTest.qWait(150)
            mw.grab().save(str(base / ("holdup-decks-dark.png" if night else "holdup-decks.png")))
        js("document.documentElement.classList.remove('night-mode'); true", mw.web)

        mw.web.eval(f"document.getElementById('{parent_deck}').querySelector('a.collapse').click()")
        expect_deck_badges({1: 1, parent_deck: 2})
        mw.web.eval(f"document.getElementById('{parent_deck}').querySelector('a.collapse').click()")
        expect_deck_badges(expected_badges)
        runtime.perform(lambda q: q.release_all([q.get(cid) for cid in child_ids]), initiator=mw.deckBrowser)
        wait_for(lambda: not runtime.busy and all(queue.get(cid) is None for cid in child_ids), "finish subdeck practice")
        expect_deck_badges({1: 1})
        undo()
        expect_deck_badges(expected_badges)
        mw.form.actionRedo.trigger()
        wait_for(lambda: all(queue.get(cid) is None for cid in child_ids) and mw._background_op_count == 0, "redo subdeck practice removal")
        expect_deck_badges({1: 1})

        # The existing native deck link still opens overview normally.
        mw.web.eval("document.getElementById('1').querySelector('a.deck').click()")
        wait_for(lambda: mw.state == "overview" and mw._background_op_count == 0, "native deck link")
        wait_for(lambda: runtime._overview_count == (1, 2) and mw.bottomWeb._domDone
                 and not mw.bottomWeb.page().isLoading(), "ready footer loaded")
        wait_for(lambda: js("document.querySelector('#holdup-overview-status')?.textContent.includes(" + json.dumps("к повторению 1" if language == "ru" else "ready 1") + ")"), "overview ready status")
        wait_for(lambda: {w for w in app.topLevelWidgets() if w.isVisible()} == windows,
                 "native Undo tooltip closes, no practice popup")
        mw.bottomWeb.eval("document.querySelector('button[onclick*=holdup-continue]').click()")
        wait_for(lambda: mw.state == "review" and runtime.flow.active == due and mw.reviewer.state == "question", "practice-only reviewer")
        base_counts = list(col.sched.counts())
        assert expect_counts(2, ready=1) == plus_practice(base_counts, 1)
        show_practice_answer()
        assert expect_counts(2, ready=1) == plus_practice(base_counts, 1)
        mw.reviewer.onEnterKey()
        wait_for(lambda: not runtime.busy and queue.get(ready_id).due_ms > due.due_ms
                 and mw.state == "overview", "Space repeats then overview")
        assert snapshot(col.get_card(ready_id)) == native_state
        assert len(col.get_review_logs(ready_id)) == native_logs
        wait_page()
        mw.moveToState("deckBrowser")
        expect_deck_badges({})  # Only future Default practice remains.
        undo()
        wait_for(lambda: queue.get(ready_id) == due and mw._background_op_count == 0, "Undo practice-only repeat")
        runtime.open_practice()
        wait_for(lambda: runtime.flow.active == due and mw.state == "review", "resume restored practice")
        show_practice_answer()
        js("document.getElementById('holdup-practice-release').click(); true")
        wait_for(lambda: not runtime.busy and queue.get(ready_id) is None, "finish practice-only")
        assert snapshot(col.get_card(ready_id)) == ready_before
        assert len(col.get_review_logs(ready_id)) == native_logs
        wait_page()
        mw.moveToState("deckBrowser")
        expect_deck_badges({})
        wait_for(lambda: {w for w in app.topLevelWidgets() if w.isVisible()} == windows,
                 "no extra windows after operation")
        print("PASS practice-only flow, Space, passive status and Undo without windows", flush=True)
    except BaseException:
        import traceback
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        raise
    finally:
        if mw.col is not None:
            mw.unloadProfileAndExit()
            wait_for(lambda: mw.col is None, "profile cleanup")
        app.quit()


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4])
