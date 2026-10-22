"""One pending practice request per card, stored through public Anki APIs.

The caller supplies the study day and serializes collection access (CollectionOp
in the GUI). This module never answers cards or merges unrelated undo entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anki.collection import Collection, OpChanges


DAY_KEY = "odbday"
VERSION_KEY = "odbv"
SCHEMA_VERSION = 1
# Anki 26.09.3: rslib/src/storage/card/data.rs (UTF-8 bytes, inclusive).
MAX_CUSTOM_DATA_BYTES = 100
MAX_KEY_BYTES = 8


class InvalidRequestData(ValueError):
    """Existing metadata cannot be interpreted safely; nothing was written."""


class UnsupportedRequestVersion(InvalidRequestData):
    """A different schema owns these keys; do not overwrite or remove it."""


class CustomDataLimitExceeded(InvalidRequestData):
    """The complete JSON object would exceed Anki's custom-data budget."""


def _check_integer(value: int, name: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


@dataclass(frozen=True)
class PracticeRequest:
    card_id: int
    due_day: int

    def __post_init__(self) -> None:
        _check_integer(self.card_id, "card_id", minimum=1)
        _check_integer(self.due_day, "due_day")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise InvalidRequestData("Duplicate JSON keys in custom data")
        data[key] = value
    return data


def _reject_constant(value: str) -> None:
    raise InvalidRequestData("Non-finite JSON numbers in custom data")


def _encode(data: dict[str, Any]) -> str:
    try:
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        for key in data:
            if len(key.encode("utf-8")) > MAX_KEY_BYTES:
                raise InvalidRequestData("Custom data keys must fit in 8 UTF-8 bytes")
        size = len(raw.encode("utf-8"))
    except (ValueError, UnicodeError) as error:
        if isinstance(error, InvalidRequestData):
            raise
        raise InvalidRequestData("Custom data cannot be encoded safely") from error
    if size > MAX_CUSTOM_DATA_BYTES:
        raise CustomDataLimitExceeded("Custom data would exceed 100 UTF-8 bytes")
    return raw


def _decode(raw: str) -> dict[str, Any]:
    if raw == "":
        return {}
    try:
        if len(raw.encode("utf-8")) > MAX_CUSTOM_DATA_BYTES:
            raise CustomDataLimitExceeded("Existing custom data exceed 100 UTF-8 bytes")
        data = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        if not isinstance(data, dict):
            raise InvalidRequestData("Custom data must be a JSON object")
        encoded = _encode(data)
        # Do not round another add-on's high-precision JSON numbers on a rewrite.
        if json.loads(raw, parse_float=Decimal) != json.loads(encoded, parse_float=Decimal):
            raise InvalidRequestData("Custom data numbers cannot round-trip without loss")
    except (ValueError, UnicodeError) as error:
        if isinstance(error, InvalidRequestData):
            raise
        raise InvalidRequestData("Malformed custom data JSON") from error
    return data


def _request(card_id: int, data: dict[str, Any]) -> PracticeRequest | None:
    if DAY_KEY not in data and VERSION_KEY not in data:
        return None
    if DAY_KEY not in data or VERSION_KEY not in data:
        raise InvalidRequestData("Practice request is missing a day or schema version")
    version = data[VERSION_KEY]
    if type(version) is not int:
        raise InvalidRequestData("Practice request version must be an integer")
    if version != SCHEMA_VERSION:
        raise UnsupportedRequestVersion("Unsupported practice request schema version")
    try:
        return PracticeRequest(card_id=card_id, due_day=data[DAY_KEY])
    except ValueError as error:
        raise InvalidRequestData("Practice request day must be a non-negative integer") from error


class RequestStore:
    """Metadata adapter bound to one open collection; no cache or UI hooks.

    Mutating methods return OpChanges, or None for a semantic no-op. Each change
    is a native undoable update; combining it with Good is the caller's job.
    """

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def get(self, card_id: int) -> PracticeRequest | None:
        _check_integer(card_id, "card_id", minimum=1)
        card = self._collection.get_card(card_id)
        return _request(card_id, _decode(card.custom_data))

    def put(self, request: PracticeRequest) -> OpChanges | None:
        """Create or replace one request, preserving all other JSON values."""
        card = self._collection.get_card(request.card_id)
        data = _decode(card.custom_data)
        if _request(request.card_id, data) == request:
            return None
        data[DAY_KEY] = request.due_day
        data[VERSION_KEY] = SCHEMA_VERSION
        card.custom_data = _encode(data)
        return self._collection.update_card(card)

    def remove(self, card_id: int) -> OpChanges | None:
        """Remove only a recognized request; absence does not create an undo step."""
        _check_integer(card_id, "card_id", minimum=1)
        card = self._collection.get_card(card_id)
        data = _decode(card.custom_data)
        if _request(card_id, data) is None:
            return None
        del data[DAY_KEY]
        del data[VERSION_KEY]
        card.custom_data = _encode(data) if data else ""
        return self._collection.update_card(card)

    def find_due(self, today: int) -> list[PracticeRequest]:
        """Find due/overdue metadata, not a runnable practice queue.

        Eligibility (suspended, buried, filtered, etc.) belongs to a later service.
        Invalid metadata among candidates raises an error instead of being erased.
        """
        _check_integer(today, "today")
        ids = self._collection.find_cards(f"prop:cdn:{DAY_KEY}<={today}")
        requests = []
        for card_id in ids:
            request = self.get(card_id)
            if request is not None and request.due_day <= today:
                requests.append(request)
        return sorted(requests, key=lambda request: (request.due_day, request.card_id))
