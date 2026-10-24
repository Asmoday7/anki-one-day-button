"""Capture the installed candidate in Anki using a disposable English demo profile."""

from pathlib import Path
import sys
import time


def main(archive: Path, base: Path, output: Path) -> None:
    import anki.lang
    import aqt
    from aqt.addons import InstallOk
    from aqt.profiles import ProfileManager, VideoDriver
    from aqt.qt import QEvent, QTimer

    if base.exists():
        raise ValueError("Choose a new disposable profile directory")
    output.mkdir(parents=True, exist_ok=True)
    base.mkdir(parents=True)
    anki.lang.set_lang("en")
    pm = ProfileManager(base)
    pm.setupMeta()
    pm.create("HoldUp demo")
    pm.load("HoldUp demo")
    pm.meta.update(firstRun=False, defaultLang="en")
    pm.profile["autoSync"] = False
    pm.set_update_check(False)
    pm.set_check_for_addon_updates(False)
    pm.set_video_driver(VideoDriver.Software)
    pm.save()
    pm.db.close()
    app = aqt._run(["holdup-demo", "-b", str(base), "-p", "HoldUp demo", "-l", "en"], exec=False)
    assert app is not None
    mw = aqt.mw

    def wait(predicate, label):
        end = time.monotonic() + 25
        while time.monotonic() < end:
            app.processEvents()
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            if predicate():
                return
            time.sleep(0.01)
        raise RuntimeError("Screenshot timeout: " + label)

    def js(expression, web=None):
        results = []
        (web or mw.bottomWeb).evalWithCallback(expression, results.append)
        wait(lambda: bool(results), "JavaScript")
        return results[0]

    def loaded():
        return (not mw._background_op_count and mw.web._domDone and mw.bottomWeb._domDone
                and not mw.web.page().isLoading() and not mw.bottomWeb.page().isLoading())

    def capture(name):
        wait(loaded, name)
        # Let Qt paint the settled webviews before grabbing the actual widget.
        end = time.monotonic() + 0.2
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
        assert mw.grab().save(str(output / name))

    try:
        wait(lambda: mw.col is not None and loaded(), "Anki startup")
        assert isinstance(mw.addonManager.install(str(archive.resolve())), InstallOk)
        mw.addonManager.writeConfig("holdup", {"interval_seconds": 120, "interval_mode": "seconds"})
        mw.addonManager.loadAddons()
        from holdup.reviewer_adapter import _controller
        from holdup.practice import PracticeQueue

        assert Path(sys.modules["holdup"].__file__).resolve().is_relative_to(base.resolve())
        runtime = _controller.runtime
        col = mw.col
        col.set_config("fsrs", True)
        col.decks.rename(1, "Vocabulary")
        model = col.models.by_name("Basic")
        model["css"] = ".card {font-family:Arial,sans-serif;font-size:32px;text-align:center;}"
        col.models.save(model)
        note = col.new_note(model)
        note["Front"], note["Back"] = "recall", "To remember something again."
        col.add_note(note, 1)
        cid = note.card_ids()[0]
        mw.resize(960, 650)
        mw.moveToState("review")
        wait(lambda: mw.reviewer.state == "question" and loaded(), "question")
        js("document.getElementById('ansbut').click(); true")
        wait(lambda: js("document.querySelector('#holdup-button:not(:disabled)') !== null"), "HoldUp")
        capture("01-normal-review.png")

        def capture_dialog():
            dialog = app.activeModalWidget()
            if dialog is None:
                QTimer.singleShot(25, capture_dialog)
            else:
                assert dialog.grab().save(str(output / "02-interval.png"))
                dialog.reject()

        QTimer.singleShot(100, capture_dialog)
        runtime.configure()
        js("document.getElementById('holdup-button').click(); true")
        wait(lambda: not runtime.busy and PracticeQueue(col).get(cid) is not None, "appointment")
        js("document.querySelector('button[data-ease=\"4\"]').click(); true")
        wait(lambda: mw.state == "overview" and loaded(), "normal Easy")
        wait(lambda: js("document.querySelector('.congrats') !== null", mw.web), "finished overview")

        # Demo fixture: two overdue appearances of the same already-answered
        # original. Native scheduling and the system clock remain unchanged.
        def ready(queue):
            queue.release_all(queue.all())
            queue.enqueue(cid, 120, time.time_ns() // 1_000_000 - 121000)
            return queue.enqueue(cid, 120, time.time_ns() // 1_000_000 - 121000)

        runtime.perform(ready)
        wait(lambda: not runtime.busy and len(PracticeQueue(col).all()) == 2, "two demo appearances")
        wait(loaded, "overview before practice")
        runtime.open_practice()
        wait(lambda: runtime.flow.active is not None and loaded(), "extra practice")
        js("document.getElementById('ansbut').click(); true")
        wait(lambda: js("document.getElementById('holdup-practice-release') !== null"), "extra controls")
        capture("03-extra-practice.png")
        mw.moveToState("deckBrowser")
        wait(lambda: loaded() and js("document.querySelector('.holdup-deck-badge')?.dataset.count === '2'", mw.web), "deck badge")
        capture("04-deck-indicator.png")
        print("Captured four real Anki screenshots in", output)
    finally:
        if mw.col is not None:
            mw.unloadProfileAndExit()
            wait(lambda: mw.col is None, "profile cleanup")
        app.quit()


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
