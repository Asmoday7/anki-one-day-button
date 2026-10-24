# HoldUp — Send a card to both FSRS and a separate queue!

**English** · [Русский](README.ru.md)

Not sure you will remember a card? **HoldUp** schedules another look at a time
you choose, alongside your normal Anki reviews.

**[Download 1.0.0-rc.2](https://github.com/Asmoday7/holdup-anki-addon/raw/refs/heads/main/dist/holdup-1.0.0-rc.2.ankiaddon)**

[User guide](USER_GUIDE.md) · [Руководство пользователя](USER_GUIDE.ru.md)

**Release candidate:** manual Windows 11 validation and a real study-day crossing
are still open. [Release checklist](RELEASE_CHECKLIST.md) ·
[Validation record](release/VALIDATION.md) ·
[GitHub checks](https://github.com/Asmoday7/holdup-anki-addon/actions/workflows/ci.yml).

## Install

If another copy of this add-on is installed, disable it in **Tools → Add-ons**
and restart Anki first. Then install the downloaded archive through
**Tools → Add-ons → Install from file** and restart Anki.

Existing cards and practice appointments remain in the collection. Choose your
preferred interval again if needed; local add-on preferences are not automatically
copied from another installation. Keep only one copy enabled.

Python does not need to be installed separately. Start with a separate test profile.

## How it works

1. Show the answer and press **HoldUp**. A checkmark confirms an extra practice
   appointment. The original answer stays open.
2. Choose **Again**, **Hard**, **Good**, or **Easy** for the original. This normal
   Anki answer updates its schedule and counts towards the daily new-card limit.
3. Extra practice keeps its own deadline independently of that rating. Good may
   schedule the original for eight days while practice becomes ready in two minutes.
4. Ready practice appears between cards in the same reviewer, labelled
   **HoldUp · practice without an FSRS rating**.
5. **Again in …** reschedules the current extra appearance; **Done** finishes only
   that appearance. These actions do not submit FSRS ratings.

Each HoldUp press adds an independent extra appearance. Earlier appointments keep
their deadlines; the waiting count includes every appearance, even of the same card.
No card or note is duplicated. Scheduling practice alone does not answer
Good or consume the daily new-card allowance; the normal rating does.

![HoldUp alongside Anki's normal answer buttons](release/assets/01-normal-review.png)

## Language and time

The interface follows Anki's language: Russian for Russian, English for other
languages. Both translations are included. Restart Anki after changing its language.

Choose time through **⋯** or **Tools → HoldUp: interval…**. Presets include
2 seconds, 2 minutes, 1 hour and 1 day; custom intervals range from 1 to 86400 seconds.

- **1 day** means exactly 24 hours after the action.
- **Next Anki study day** uses the next day-start boundary from Anki's preferences.
  With a 04:00 start, scheduling at 23:00 or 02:00 makes practice ready at the next
  04:00. Anki supplies the boundary, including local time and daylight saving.

Settings apply to subsequent actions. Existing appointments keep their stored
absolute deadlines, including after a change to Anki's day-start setting.

## Queue and indicators

During study, the green count includes ready practice. Its tooltip shows the Anki
and HoldUp portions. Blue and red remain Anki's counts. **HoldUp: waiting N**
shows future appointments as passive text.

On **Decks**, a small green clock badge **HoldUp · N** shows ready practice,
even when the three native deck counts are zero. Open the deck by its normal name.
Parents include their subdecks, including collapsed ones; parent and child counts
overlap. Future and unavailable appointments do not show ready badges.

Practice uses the selected deck and subdecks. A deadline is the earliest time it
can appear: the current answer and earlier native deadlines can delay it. When
Anki is closed, appointments wait for your next session. **Continue studying** on
the deck overview returns to the same reviewer when extra practice is ready.

Appointments, repeats, completion and clearing support **Undo/Redo**.
After **HoldUp → a normal rating → Undo**, only that normal rating is cancelled:
the original returns, and the HoldUp deadline remains. A second Undo cancels the
earlier HoldUp appointment if no other collection action intervened. Undoing a
practice repeat or **Done** affects only the practice appointment.
**Tools → HoldUp: clear all practice** removes extra appointments across the open
collection, including future ones. Cards and normal ratings remain.


Version 1.0.0-rc.2 prepares the first stable release: faster large-queue clearing,
AGPL-3.0-or-later licensing, reproducible packages and Windows/Linux CI. It retains
independent appearances of the same card, their existing deadlines and native Undo/Redo.

## Data and license

First-release support is one desktop installation per collection. Full collection
exports (`.colpkg`) and Anki backups preserve appointments; deck `.apkg` exports do
not carry the complete queue. Live multi-device sync/conflict resolution remains
unverified. See the [data contract](release/DATA_AND_COMPATIBILITY.md).

HoldUp is free software under [AGPL-3.0-or-later](LICENSE). The installer includes
the runtime source, full license and [project notice](NOTICE).

[Release notes](release/RELEASE_NOTES.md) · [AnkiWeb submission kit](release/ANKIWEB.md) ·
[GitHub releases](https://github.com/Asmoday7/holdup-anki-addon/releases).

## Development

Runtime has no dependencies beyond Anki. Source is in [`holdup/`](holdup/), and
[`i18n.py`](holdup/i18n.py) holds the English source strings and Russian translations.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
mkdir -p .dev
python -m pytest -m "not anki_contract and not anki_gui" --basetemp=.dev/pytest-unit
```

For backend tests, install `requirements-anki.txt`. For desktop checks, use separate
environments with `requirements-gui-26.09.txt` or `requirements-gui.txt`.
Do not install both Anki versions into one environment. Run GUI suites sequentially
because Anki uses a single-instance mechanism.

```bash
python -m pytest --basetemp=.dev/pytest-full
python tools/package_addon.py
python tools/build_release.py --tag v1.0.0-rc.2
```

The build is `.dev/dist/holdup.ankiaddon`. Published archives and checksums are in
[dist](dist/README.md). Tests use disposable collections and profiles without
AnkiWeb; pytest clears `--basetemp`. Skipped backend or GUI checks do not establish
integration support.

[Architecture](ARCHITECTURE.md) and [manual checks](TESTING.md) are maintained in Russian.
Windows/Python 3.13, cross-device sync, audio and complex templates require manual
validation. AnkiDroid does not run desktop Python add-ons. Extra practice does not
submit FSRS ratings, although it can affect what a person remembers on their next
normal review.

Verified on Linux: **231 passed** on each of Anki **26.09 (e62e7739)** and
**26.09.3 (29bb700b)**, including English/Russian GUI scenarios with and without
minute learning steps. Windows and cross-device sync still need manual checks.
