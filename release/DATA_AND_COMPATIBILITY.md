# HoldUp 1.0 data and compatibility contract

## Supported use for the first release

Use HoldUp in **one desktop Anki installation per collection**. Compatibility
targets are Anki **26.09** and **26.09.3**. See [validation](VALIDATION.md) for
the platforms actually tested. A version listed as a target is not evidence
that a manual test has passed.

AnkiDroid and AnkiMobile do not run this desktop Python add-on. HoldUp does not
provide extra-practice controls on those clients.

## What is saved

Each HoldUp press adds an appearance with its own identity and absolute deadline.
Appearances are saved in the collection, independently of the original card's
schedule, FSRS memory state and review history. The local interval preference
belongs to the add-on installation.

Normal Anki ratings continue to update the original. Repeat and Done affect
only the displayed extra appearance. Undo/Redo uses Anki's session undo history;
it is not a permanent activity log that survives closing Anki.

## Backup and transfer

**A full collection export (`.colpkg`) or an Anki collection backup preserves the
extra queue.** Release tests restore both modern and legacy full exports through
Anki's own importer and compare appointment identities, deadlines, the original
schedule, FSRS memory state and review logs. A native-backup restoration is tested
after clearing the live queue.

For a move to another desktop installation:

1. Export the entire collection from the source Anki as `.colpkg`.
   Include media when moving card images or audio; the automated HoldUp contracts
   verify queue/scheduling data, while real media/templates remain a manual check.
2. Install the same HoldUp version on the destination.
3. Import the collection using Anki's normal full-collection restore/import flow.
4. Choose the local HoldUp interval again if needed.

Full-collection import replaces the destination collection. Use this flow when
moving/restoring the entire collection, not for combining two existing collections.

**A deck export (`.apkg`) does not transfer the complete HoldUp queue.** Current
appointments are collection data. An old appointment still stored in a card's
metadata may travel with scheduling data, so APKG is not a reliable HoldUp transfer
method. Tests explicitly verify that current appointments are absent after
importing a deck package with scheduling enabled.

## AnkiWeb sync

Anki includes the collection configuration in its own sync. HoldUp currently
stores its queue as one configuration value. Concurrent changes on two desktop
installations can overwrite one another. Live cross-device sync and conflict
resolution are **outside the first release's support guarantee**.

This contract does not claim that enabling sync merges HoldUp appointments.
Use full-collection transfer/backup for a verified copy of the complete queue.

## Upgrades

Saved appointments from the earlier card-metadata format and collection format 1
remain readable. Reading does not rewrite the collection. The next queue change
writes format 2 while preserving existing appointments; Undo restores the preceding
format and values. Updating from 0.5.0 uses the same queue format.

Keep one enabled copy of HoldUp. Older builds that cannot read format 2 are not
a downgrade path; restore the corresponding pre-upgrade collection backup when
returning to an older data format.
