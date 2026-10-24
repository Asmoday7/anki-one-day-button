# HoldUp 1.0.0-rc.1

This is a **release candidate**, intended for final desktop testing before 1.0.0.
Manual Windows 11 validation and a real study-day crossing are still open gates.
The attached `validation-*.json` records the four actual CI jobs, their test
counts and queue benchmarks. It deliberately leaves the manual Windows gates open.

HoldUp adds extra practice alongside your normal Anki/FSRS reviews. Press HoldUp,
then choose a normal Anki rating for the original. Each new HoldUp press adds an
independent extra appearance; Repeat and Done affect only the appearance on screen.

Included:

- Extra appearances in the existing reviewer, with no separate practice window.
- Intervals from 1 second to 24 hours and Next Anki study day.
- Ready counts and passive deck-list badges.
- Native ratings, daily new-card limits and independent practice Undo/Redo.
- English and Russian interfaces in one package.
- Faster clearing of large queues and a 2000-appearance regression.
- Deferred overview-footer updates while Anki is loading its native pages.
- AGPL-3.0-or-later license, included in the archive with source and project notice.
- Reproducible installers and checksums; Windows/Linux CI for Anki 26.09 and 26.09.3.

Install `holdup-1.0.0-rc.1.ankiaddon` through Tools → Add-ons → Install from file,
then fully restart Anki. Keep one enabled copy. Existing appointments are retained.
The `.zip` upload archive contains identical bytes; use the `.ankiaddon` for installation.

First-release support is one desktop installation per collection. Full collection
exports and native backups preserve appointments; deck `.apkg` export does not
carry the complete queue. Live multi-device sync/conflict resolution is unverified.
AnkiDroid and AnkiMobile do not run this add-on.

[User guide](https://github.com/Asmoday7/holdup-anki-addon/blob/main/USER_GUIDE.md) ·
[Русская инструкция](https://github.com/Asmoday7/holdup-anki-addon/blob/main/USER_GUIDE.ru.md) ·
[Validation](https://github.com/Asmoday7/holdup-anki-addon/blob/main/release/VALIDATION.md) ·
[Report a bug](https://github.com/Asmoday7/holdup-anki-addon/issues/new?template=bug_report.yml)
