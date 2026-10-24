"""An overview poll must respect native page navigation and retry when ready."""

from types import SimpleNamespace

import pytest

pytest.importorskip("aqt")

from holdup.gui import PracticeRuntime

pytestmark = pytest.mark.anki_contract


@pytest.mark.parametrize("busy", ["background", "main", "footer", "context", "none"])
def test_overview_count_update_waits_for_native_navigation_without_losing_change(busy):
    rendered = []
    overview = SimpleNamespace(_renderBottom=lambda: rendered.append(True))

    def view(loading=False):
        return SimpleNamespace(_domDone=not loading, page=lambda: SimpleNamespace(isLoading=lambda: loading))

    runtime = PracticeRuntime.__new__(PracticeRuntime)
    runtime._overview_count = (0, 0)
    runtime.mw = SimpleNamespace(state="overview", overview=overview,
                                 _background_op_count=int(busy == "background"),
                                 web=view(busy == "main"), bottomWeb=view(busy == "footer"))
    runtime.mw.bottomWeb._bridge_context = SimpleNamespace(overview=None if busy == "context" else overview)
    runtime.update_overview(1, 2)
    assert rendered == ([True] if busy == "none" else [])
    assert runtime._overview_count == ((1, 2) if busy == "none" else (0, 0))
    runtime.mw._background_op_count = 0
    runtime.mw.web = view()
    runtime.mw.bottomWeb = view()
    runtime.mw.bottomWeb._bridge_context = SimpleNamespace(overview=overview)
    runtime.update_overview(1, 2)
    runtime.update_overview(1, 2)
    assert rendered == [True] and runtime._overview_count == (1, 2)
