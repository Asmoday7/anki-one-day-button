"""Optional actual Anki/Qt run in a child process with disposable profile data."""

from importlib.util import find_spec
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.package_addon import build_addon


@pytest.mark.anki_gui
@pytest.mark.skipif(find_spec("aqt") is None, reason="Install requirements-gui.txt for desktop checks")
@pytest.mark.parametrize("steps", ["none", "minutes"])
@pytest.mark.parametrize("language", ["en", "ru"])
def test_packaged_button_in_desktop_anki(tmp_path, steps, language):
    archive = build_addon(tmp_path / "holdup.ankiaddon")
    base = tmp_path / "anki-profile"
    cache = tmp_path / "cache"
    cache.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    env = dict(os.environ)
    env.update(QT_QPA_PLATFORM="offscreen", XDG_CACHE_HOME=str(cache), XDG_DATA_HOME=str(data), PYTHONUNBUFFERED="1")
    log = tmp_path / "desktop.log"
    try:
        with log.open("w") as output:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("gui_probe.py")), str(base), str(archive), steps, language],
                env=env, stdout=output, stderr=subprocess.STDOUT, text=True, timeout=90,
            )
    except subprocess.TimeoutExpired:
        pytest.fail("Desktop probe timed out:\n" + log.read_text())
    output = log.read_text()
    assert result.returncode == 0, output
    assert output.count("PASS ") == 10, output
    assert "JS error" not in output, output
    print(output)
