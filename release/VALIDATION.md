# Candidate validation record

Candidate: **1.0.0-rc.1**. Dates use the tester's local time zone.

| Environment | Evidence | Status |
| --- | --- | --- |
| Linux / Anki 26.09 / Python 3.12 | Full candidate suite, four real packaged GUI scenarios | **231 passed**, four GUI cases |
| Linux / Anki 26.09.3 / Python 3.12 | Full candidate suite, four real packaged GUI scenarios | **231 passed**, four GUI cases |
| GitHub Windows runner / Python 3.13 / Anki 26.09 | [CI workflow](https://github.com/Asmoday7/holdup-anki-addon/actions/workflows/ci.yml) | Configured; not yet verified |
| GitHub Windows runner / Python 3.13 / Anki 26.09.3 | Same matrix | Configured; not yet verified |
| User's Windows 11 / Anki 26.09 | [Short manual test](../RELEASE_CHECKLIST.md#short-windows-test) | Not yet reported |
| Actual next Anki study-day boundary on Windows | Real configured day-start crossing | Not yet reported |
| macOS | No release evidence | Unverified |
| Live multi-device HoldUp sync | No live test / conflict resolution | Outside supported scope |

The previous 0.5.0 build passed 218 tests on each Linux Anki version. Those results
are not substituted for the candidate or for Windows.

Local machine-readable results: [local-validation.json](local-validation.json).

## Storage and load

Integration tests restore full exports in modern and legacy formats and a native
Anki backup. A 2000-appearance regression checks selective repeat, clearing,
Undo/Redo and unchanged native schedule/history. APKG tests demonstrate the
documented lack of current collection appointments after deck import.

The initial synthetic 1000-item benchmark on Linux took 7.858 seconds to clear.
After validating one snapshot instead of re-reading the entire config per item,
the same benchmark took 0.014 seconds. These are observations from this environment,
not timing guarantees for other computers. Candidate benchmark JSON reports are
attached to CI validation artifacts and recorded locally for both Anki versions.

## Windows manual report

- Tester/date/time zone: not reported
- Windows / Anki / Python / Qt versions: not reported
- Install/upgrade and restart persistence: not reported
- Two independent appearances and counters: not reported
- Native rating → Undo → original → regrade: not reported
- Repeat/Done Undo/Redo, including finished overview: not reported
- Real next-study-day crossing: not reported
- Scaling / card audio and real templates: not reported

Do not change this section to passed without a tester's actual results.
