"""Package HoldUp without caches, tests or local user data."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


REPOSITORY = Path(__file__).resolve().parents[1]
ADDON = REPOSITORY / "holdup"
# Extend this list deliberately when future milestones add runtime files.
RUNTIME_FILES = (
    "__init__.py", "manifest.json", "request_store.py",
    "reviewer_adapter.py", "web/reviewer.js",
    "practice.py", "gui.py", "review_flow.py", "config.json",
    "deck_indicator.py", "web/deckbrowser.js", "i18n.py",
)


def build_addon(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for name in RUNTIME_FILES:
            archive.write(ADDON / name, arcname=name)
    return destination


if __name__ == "__main__":
    print(build_addon(REPOSITORY / ".dev" / "dist" / "holdup.ankiaddon"))
