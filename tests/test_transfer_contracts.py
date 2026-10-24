"""Release contracts for full-collection backup and the limits of deck export."""

from contextlib import closing
from pathlib import Path
import time

import pytest

pytest.importorskip("anki")

from anki._backend import RustBackend
from anki.collection import Collection, ExportAnkiPackageOptions, ImportAnkiPackageRequest
from anki.scheduler.v3 import CardAnswer
from holdup.practice import CONFIG_KEY, PracticeQueue
from test_anki_contracts import answer_next, review_logs, scheduling_snapshot

pytestmark = pytest.mark.anki_contract


def fixture_collection(path):
    col = Collection(str(path))
    col.set_config("fsrs", True)
    col.set_config("rollover", (time.localtime().tm_hour + 12) % 24)
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"], note["Back"] = "Release transfer fixture", "Answer"
    col.add_note(note, 1)
    card = answer_next(col, CardAnswer.EASY)
    queue = PracticeQueue(col)
    queue.enqueue(card.id, 1, 1000)
    queue.enqueue(card.id, 7200, time.time_ns() // 1_000_000)
    return col, card.id


def restore_colpkg(archive, destination):
    backend = RustBackend()
    backend.import_collection_package(
        col_path=str(destination), backup_path=str(archive),
        media_folder=str(destination.parent / "collection.media"),
        media_db=str(destination.parent / "collection.media.db2"),
    )
    return Collection(str(destination), backend=backend)


@pytest.mark.parametrize("legacy", [False, True])
def test_full_collection_export_preserves_both_appearances_and_original(tmp_path, legacy):
    source, cid = fixture_collection(tmp_path / "source.anki2")
    expected = PracticeQueue(source).all()
    schedule, logs = scheduling_snapshot(source.get_card(cid)), review_logs(source, cid)
    archive = tmp_path / "full.colpkg"
    try:
        source.export_collection_package(str(archive), include_media=False, legacy=legacy)
    finally:
        source.close()
    with closing(restore_colpkg(archive, tmp_path / "restored.anki2")) as restored:
        assert PracticeQueue(restored).all() == expected
        assert scheduling_snapshot(restored.get_card(cid)) == schedule
        assert review_logs(restored, cid) == logs


def test_native_backup_restores_appearances_after_the_live_queue_is_cleared(tmp_path):
    source, cid = fixture_collection(tmp_path / "source.anki2")
    try:
        queue = PracticeQueue(source)
        expected = queue.all()
        schedule, logs = scheduling_snapshot(source.get_card(cid)), review_logs(source, cid)
        backups = tmp_path / "backups"
        backups.mkdir()
        assert source.create_backup(backup_folder=str(backups), force=True, wait_for_completion=True)
        archive, = backups.glob("*.colpkg")
        queue.release_all(expected)
        assert not queue.all()
        with closing(restore_colpkg(archive, tmp_path / "restored.anki2")) as restored:
            assert PracticeQueue(restored).all() == expected
            assert scheduling_snapshot(restored.get_card(cid)) == schedule
            assert review_logs(restored, cid) == logs
    finally:
        source.close()


@pytest.mark.parametrize("legacy", [False, True])
def test_deck_export_does_not_transfer_collection_appointments(tmp_path, legacy):
    with closing(fixture_collection(tmp_path / "source.anki2")[0]) as source:
        archive = tmp_path / "deck.apkg"
        source.export_anki_package(
            out_path=str(archive), limit=None,
            options=ExportAnkiPackageOptions(with_scheduling=True, with_media=False,
                                           with_deck_configs=True, legacy=legacy),
        )
    with closing(Collection(str(tmp_path / "imported.anki2"))) as imported:
        imported.import_anki_package(ImportAnkiPackageRequest(package_path=str(archive)))
        assert len(imported.find_cards("")) == 1
        assert imported.get_config(CONFIG_KEY) is None
        assert PracticeQueue(imported).all() == []


def test_large_queue_repeat_clear_undo_and_redo_keep_the_native_schedule(tmp_path):
    with closing(fixture_collection(tmp_path / "large.anki2")[0]) as col:
        cid = col.find_cards("")[0]
        clock = time.time_ns() // 1_000_000
        entries = [[f"{index + 1:032x}", clock - 1000, 1, False] for index in range(2000)]
        col.set_config(CONFIG_KEY, {"v": 2, "cards": {str(cid): entries}})
        queue = PracticeQueue(col)
        original = queue.all()
        schedule, logs = scheduling_snapshot(col.get_card(cid)), review_logs(col, cid)
        queue.repeat(original[1000], 7200, clock)
        pending = queue.all()
        assert len(pending) == 2000 and pending[-1].request_id == original[1000].request_id
        changes = queue.release_all(pending)
        assert not changes.study_queues and not changes.card and not queue.all()
        col.undo()
        assert queue.all() == pending
        col.redo()
        assert not queue.all()
        assert scheduling_snapshot(col.get_card(cid)) == schedule
        assert review_logs(col, cid) == logs
