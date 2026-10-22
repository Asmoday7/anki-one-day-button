"""Failure cases that a valid Anki collection cannot normally contain."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from holdup.request_store import (
    InvalidRequestData,
    PracticeRequest,
    RequestStore,
    UnsupportedRequestVersion,
)


@pytest.mark.parametrize(
    "card_id,day", [(0, 1), (-1, 1), (True, 1), (1, -1), (1, True), (1, 1.5)]
)
def test_request_rejects_invalid_identifiers_and_days(card_id, day):
    with pytest.raises(ValueError):
        PracticeRequest(card_id, day)


@pytest.mark.parametrize(
    "raw",
    [
        "{", "[]", "null", '{"other":1,"other":2}',
        '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}',
        '{"x":0.1234567890123456789}',
        '{"x":{"a":1,"a":2}}', '{"toolongkey":1}',
        '{"日本語":1}', '{"x":"\\ud800"}',
        '{"odbday":1}', '{"odbv":1}', '{"odbday":true,"odbv":1}',
        '{"odbday":-1,"odbv":1}', '{"odbday":1.5,"odbv":1}',
        '{"odbday":1,"odbv":true}',
    ],
)
def test_invalid_metadata_are_never_overwritten_or_removed(raw):
    card = SimpleNamespace(custom_data=raw)
    collection = Mock()
    collection.get_card.return_value = card
    store = RequestStore(collection)

    for action in (
        lambda: store.get(123),
        lambda: store.put(PracticeRequest(123, 2)),
        lambda: store.remove(123),
    ):
        with pytest.raises(InvalidRequestData):
            action()
        assert card.custom_data == raw
    collection.update_card.assert_not_called()


def test_unknown_schema_is_distinct_from_malformed_data():
    collection = Mock()
    collection.get_card.return_value.custom_data = '{"odbday":1,"odbv":2}'
    with pytest.raises(UnsupportedRequestVersion):
        RequestStore(collection).put(PracticeRequest(123, 2))
    collection.update_card.assert_not_called()


def test_invalid_search_day_does_not_reach_collection():
    collection = Mock()
    with pytest.raises(ValueError):
        RequestStore(collection).find_due("1 OR anything")
    collection.find_cards.assert_not_called()


def test_backend_failure_is_not_reported_as_a_success():
    collection = Mock()
    collection.get_card.return_value.custom_data = ""
    collection.update_card.side_effect = RuntimeError("backend unavailable")
    with pytest.raises(RuntimeError, match="backend unavailable"):
        RequestStore(collection).put(PracticeRequest(123, 1))
