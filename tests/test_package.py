"""Packaging checks; these do not launch Anki or exercise its add-on manager."""

import json
import subprocess
import sys
from zipfile import ZipFile

from tools.package_addon import build_addon


def test_archive_has_anki_layout_and_manifest(tmp_path):
    path = build_addon(tmp_path / "holdup.ankiaddon")
    with ZipFile(path) as archive:
        assert set(archive.namelist()) == {
            "__init__.py", "manifest.json", "request_store.py",
            "reviewer_adapter.py", "web/reviewer.js",
            "practice.py", "gui.py", "review_flow.py", "config.json",
            "deck_indicator.py", "web/deckbrowser.js", "i18n.py",
            "LICENSE", "NOTICE",
        }
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["package"] == "holdup"
        assert manifest["name"] == "HoldUp - Отправь карточку и в FSRS, и отдельную очередь!"
        assert isinstance(manifest["human_version"], str)
        assert "GNU AFFERO GENERAL PUBLIC LICENSE" in archive.read("LICENSE").decode()
        assert "AGPL-3.0-or-later" in archive.read("NOTICE").decode()
        for name in ("__init__.py", "request_store.py", "reviewer_adapter.py", "practice.py", "gui.py", "review_flow.py", "deck_indicator.py", "i18n.py"):
            compile(archive.read(name), name, "exec")


def test_packaged_entry_loads_under_numeric_name_without_anki(tmp_path):
    # AnkiWeb can install add-ons under numeric module names. Disable site-packages
    # so this check also catches accidental runtime dependencies in the skeleton.
    path = build_addon(tmp_path / "holdup.ankiaddon")
    with ZipFile(path) as archive:
        archive.extractall(tmp_path / "1234567890")
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            "import importlib, sys; sys.path.insert(0, sys.argv[1]); "
            "importlib.import_module('1234567890'); "
            "store = importlib.import_module('1234567890.request_store'); "
            "assert store.PracticeRequest(1, 1).due_day == 1; "
            "importlib.import_module('1234567890.reviewer_adapter'); "
            "importlib.import_module('1234567890.practice'); "
            "importlib.import_module('1234567890.deck_indicator'); "
            "assert 'aqt' not in sys.modules and 'anki' not in sys.modules",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ""
    assert result.stderr == ""


def test_release_archive_is_reproducible_after_checkout_timestamps_change(tmp_path, monkeypatch):
    import os
    from shutil import copytree, copyfile
    import tools.package_addon as package

    source = tmp_path / "source"
    copytree(package.ADDON, source / "holdup")
    for name in package.LEGAL_FILES:
        copyfile(package.REPOSITORY / name, source / name)
    monkeypatch.setattr(package, "ADDON", source / "holdup")
    monkeypatch.setattr(package, "REPOSITORY", source)
    first = package.build_addon(tmp_path / "first.ankiaddon").read_bytes()
    for path in source.rglob("*"):
        if path.is_file():
            os.utime(path, (1700000000, 1700000000))
    second = package.build_addon(tmp_path / "second.ankiaddon").read_bytes()
    assert first == second
