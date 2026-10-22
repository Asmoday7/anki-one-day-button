"""Read-only ready-practice badges on Anki's existing deck list."""

import json
from pathlib import Path

from .i18n import localize_script


def deck_paths(decks):
    """Resolve existing ancestors by name without creating missing decks."""
    names = {deck.name: int(deck.id) for deck in decks}
    return {
        did: tuple(names[prefix] for prefix in (
            "::".join(name.split("::")[:level])
            for level in range(1, len(name.split("::")) + 1)
        ) if prefix in names)
        for name, did in names.items()
    }


def ready_counts(rows, clock):
    counts = {}
    for row in rows:
        if not row.available or row.request.due_ms > clock:
            continue
        for did in set(row.deck_ids):
            counts[did] = counts.get(did, 0) + 1
    return counts


class DeckIndicator:
    def __init__(self, runtime):
        from aqt import gui_hooks

        self.runtime = runtime
        self.mw = runtime.mw
        self.collection = None
        self.counts = {}
        self.script = (Path(__file__).parent / "web" / "deckbrowser.js").read_text(encoding="utf-8")
        gui_hooks.webview_will_set_content.append(self.content)
        gui_hooks.deck_browser_did_render.append(self.rendered)

    def content(self, content, context):
        if context is self.mw.deckBrowser:
            counts = self.counts if self.collection is self.mw.col else {}
            content.body += ("<script>" + localize_script(self.script) + "</script><script>"
                             f"window.HoldUpDecks.update({json.dumps(counts)});</script>")

    def rendered(self, browser):
        if browser is self.mw.deckBrowser:
            self.runtime.refresh()

    def update(self, rows):
        from .gui import now_ms

        counts = ready_counts(rows, now_ms())
        changed = self.collection is not self.mw.col or counts != self.counts
        self.collection = self.mw.col
        self.counts = counts
        if changed:
            self.paint()

    def paint(self):
        if (self.mw.state == "deckBrowser"
                and self.mw.web._bridge_context is self.mw.deckBrowser):
            self.mw.web.eval(f"window.HoldUpDecks?.update({json.dumps(self.counts)});")

    def clear(self):
        self.collection = None
        self.counts = {}
        self.paint()
