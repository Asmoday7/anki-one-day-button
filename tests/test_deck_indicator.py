"""Deck-list summaries are read-only and independent of the selected deck."""

from copy import deepcopy
from types import SimpleNamespace

from holdup.deck_indicator import deck_paths, ready_counts


def test_deck_paths_resolve_only_existing_ancestors_not_name_prefixes():
    decks = [SimpleNamespace(id=1, name="Японский"),
             SimpleNamespace(id=2, name="Японский::Слова"),
             SimpleNamespace(id=3, name="Японский::Слова::Глаголы"),
             SimpleNamespace(id=4, name="Японский 2"),
             SimpleNamespace(id=5, name="Missing::Leaf")]
    assert deck_paths(decks) == {1: (1,), 2: (1, 2), 3: (1, 2, 3), 4: (4,), 5: (5,)}
    assert len(decks) == 5


def test_ready_badges_include_due_subdecks_and_exclude_waiting_unavailable_and_filtered():
    row = lambda due, path, available=True: SimpleNamespace(
        request=SimpleNamespace(due_ms=due), deck_ids=path, available=available)
    rows = [row(999, (1,)), row(1000, (1, 2)), row(1001, (1, 2)),
            row(999, (1, 3), False), row(999, ()), row(999, (4,))]
    before = deepcopy(rows)
    assert ready_counts(rows, 1000) == {1: 2, 2: 1, 4: 1}
    assert ready_counts(rows, 1001) == {1: 3, 2: 2, 4: 1}
    assert rows == before


def test_finished_or_empty_practice_leaves_no_zero_badges_or_double_ancestors():
    assert ready_counts([], 1000) == {}
    row = SimpleNamespace(request=SimpleNamespace(due_ms=1000), deck_ids=(1, 1, 2), available=True)
    assert ready_counts([row], 1000) == {1: 1, 2: 1}
