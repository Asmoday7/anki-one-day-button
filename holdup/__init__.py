"""HoldUp: timed practice independent of Anki answer ratings."""

import sys

# Anki imports add-ons after aqt.mw exists. Ordinary Python imports (tests/tools)
# must not initialize a GUI or require aqt to be installed.
if "aqt" in sys.modules:
    from aqt import mw

    if mw is not None:
        from .reviewer_adapter import install

        install(mw)
