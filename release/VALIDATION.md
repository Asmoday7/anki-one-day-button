# Candidate validation record

Candidate: **1.0.0-rc.3**. Automated reports use UTC; manual reports use the tester's local time zone.

[Tagged CI run](https://github.com/Asmoday7/holdup-anki-addon/actions/runs/40094640748)
completed successfully. The [published report](validation-1.0.0-rc.3.json) was downloaded
unchanged from the GitHub prerelease and records the exact source commit and all four jobs.

| Environment | Evidence | Status |
| --- | --- | --- |
| Linux / Anki 26.09 / Python 3.12 | Full candidate suite, four real packaged GUI scenarios | **231 passed**, four GUI cases |
| Linux / Anki 26.09.3 / Python 3.12 | Full candidate suite, four real packaged GUI scenarios | **231 passed**, four GUI cases |
| GitHub Windows runner / Python 3.13 / Anki 26.09 | Full tagged candidate suite and native application shutdown | **231 passed**, four GUI cases |
| GitHub Windows runner / Python 3.13 / Anki 26.09.3 | Same matrix | **231 passed**, four GUI cases |
| User's Windows 11 / Anki 26.09 | [Short manual test](../RELEASE_CHECKLIST.md#short-windows-test) | Not yet reported |
| Actual next Anki study-day boundary on Windows | Real configured day-start crossing | Not yet reported |
| macOS | No release evidence | Unverified |
| Live multi-device HoldUp sync | No live test / conflict resolution | Outside supported scope |

The previous 0.5.0 build passed 218 tests on each Linux Anki version. Those results
are not substituted for the candidate or for Windows.

Local machine-readable results for the preceding rc.1 runtime (unchanged in rc.3):
[local-validation.json](local-validation.json). The rc.3 tagged CI run tests its own
versioned package separately.

The desktop probe waits for Anki's complete native application cleanup and requires
a clean subprocess exit. Its stale-queue rejection case externally buries the displayed
card, guaranteeing a different native head without relying on random review sorting.
Assertions, JavaScript error checks and the requirement for all four GUI cases remain enabled.

All four CI installers are byte-identical. The public prerelease installer, upload ZIP
and checksums were downloaded and compared with the local release files.

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
