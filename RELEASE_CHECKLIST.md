# HoldUp 1.0 release checklist

Candidate: **1.0.0-rc.3**. This file records work and open gates; unchecked items
must not be reported as completed.

## 1. Validation

- [x] Tests cover independent repeated appearances, normal ratings and native new-card limits.
- [x] Tests cover Undo/Redo, returning to the original, Repeat/Done and finished-overview return.
- [x] A 2000-appearance regression checks repeat, clear, Undo/Redo and unchanged native history.
- [x] A reproducible benchmark measures a temporary 1000-appearance queue.
- [x] Windows/Python 3.13 and Linux/Python 3.12 CI jobs are defined for both Anki versions.
- [x] Candidate's Linux matrix results recorded in [validation](release/VALIDATION.md).
- [x] Candidate's Windows CI matrix completed successfully: 231 tests on each Anki version.
- [ ] Actual Windows 11 test of the candidate completed by a tester.
- [ ] A real Anki study-day boundary observed in the Windows test installation.

## 2. Data support

- [x] First-release scope is one desktop installation per collection.
- [x] Full `.colpkg` export/restore and native-backup restoration have integration tests.
- [x] `.apkg` limitations and unverified/conflicting multi-device sync are documented.
- [x] Existing formats, exact Undo restoration and restart persistence have tests.
- [x] [Data and compatibility contract](release/DATA_AND_COMPATIBILITY.md) is ready.

## 3. License

- [x] AGPL-3.0-or-later selected; full license and project notice added.
- [x] License and notice included in installation/upload archives.
- [x] Source URL included in the notice and release materials.

## 4. Publication

- [x] Deterministic Windows/Linux packaging with checksums is implemented.
- [x] Candidate release notes and English AnkiWeb description are prepared.
- [x] Four actual Anki screenshots captured and reviewed.
- [x] Candidate archives and matching source tag pushed to GitHub.
- [x] [GitHub prerelease](https://github.com/Asmoday7/holdup-anki-addon/releases/tag/v1.0.0-rc.3) published after all four CI jobs pass.
- [ ] Final manual Windows results received before stable 1.0.0.
- [ ] Stable version/tag/archive prepared after the remaining validation gates pass.
- [ ] AnkiWeb listing uploaded through the owner's account.

## Short Windows test

Install the candidate over the existing HoldUp and fully restart Anki. Use a
separate test profile with FSRS enabled, one card and learning steps `1m 10m`.

1. On the answer, set HoldUp to two hours, press it, then choose normal Good.
2. When Anki offers the original learning card again, press HoldUp again.
   There must now be two future appearances. The first deadline stays unchanged.
3. Choose normal Easy, then Undo. The original returns with normal ratings;
   both extra appearances remain. The next Undo removes only the latest addition.
4. Redo restores that addition at its exact saved deadline. Test ordinary rating
   again; there must be one current normal review log per actual rating.
5. Use a short interval in another test run. Repeat/Done and their Undo/Redo must
   affect one extra appearance. Test Undo after the last Done reaches the finished page.
6. Restart Anki and confirm that future appearances remain. Check window scaling
   at the user's usual Windows setting.
7. Separately, choose Next Anki study day and observe the real configured boundary.
   Do not change the system clock. Record whether the appearance becomes ready.

Record Anki build, Python/Qt, Windows version, candidate version, date and results
in [validation](release/VALIDATION.md) or a GitHub issue. Linux/CI results do not
substitute for this manual result.
