"""Package HoldUp without caches, tests or local user data."""

from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo


REPOSITORY = Path(__file__).resolve().parents[1]
ADDON = REPOSITORY / "holdup"
# Extend this list deliberately when future milestones add runtime files.
RUNTIME_FILES = (
    "__init__.py", "manifest.json", "request_store.py",
    "reviewer_adapter.py", "web/reviewer.js",
    "practice.py", "gui.py", "review_flow.py", "config.json",
    "deck_indicator.py", "web/deckbrowser.js", "i18n.py",
)
LEGAL_FILES = ("LICENSE", "NOTICE")


def build_addon(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_STORED) as archive:
        def include(name: str, path: Path) -> None:
            # Fixed metadata and no zlib dependency make release bytes identical
            # across Windows/Linux, Python versions and checkout timestamps.
            entry = ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, path.read_bytes())

        for name in RUNTIME_FILES:
            include(name, ADDON / name)
        for name in LEGAL_FILES:
            include(name, REPOSITORY / name)
    return destination


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPOSITORY / ".dev" / "dist" / "holdup.ankiaddon")
    print(build_addon(parser.parse_args().output))
