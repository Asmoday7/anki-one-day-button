"""Timed practice through undoable collection config, independent of card queues.

Card metadata remains readable for compatibility with saved appointments.
Only recovery of persisted pauses uses update_card(); normal practice never does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import secrets
from typing import Any

from .i18n import tr

from .request_store import (
    InvalidRequestData, UnsupportedRequestVersion, _check_integer, _decode, _encode,
)


MAX_INTERVAL_SECONDS = 86400
MODE_STUDY_DAY = "next_study_day"
KEYS = ("odbv", "odbat", "odbsecs", "odbq", "odbnext")
ACTIVE_QUEUES = (0, 1, 2, 3)
CONFIG_KEY = "holdupPractice"


class PracticeStateChanged(ValueError):
    """The card or request changed; reload instead of acting on a stale view."""


def validate_interval(seconds: int) -> int:
    _check_integer(seconds, "interval_seconds", 1)
    if seconds > MAX_INTERVAL_SECONDS:
        raise ValueError("Interval must be between 1 and 86400 seconds")
    return seconds


def interval_label(seconds: int, *, next_study_day: bool = False) -> str:
    validate_interval(seconds)
    if next_study_day:
        return tr("Study day")
    for divisor, unit in ((86400, "d"), (3600, "h"), (60, "min")):
        if seconds % divisor == 0:
            return f"{seconds // divisor} {tr(unit)}"
    return f"{seconds} {tr('s')}"


def native_due_ms(card: Any, now_ms: int, today: int, day_cutoff: int) -> int:
    """Comparable deadline for the native head, without reordering its queue.

    Learning has a Unix timestamp. Review/day-learning have only an Anki day:
    use that day's local rollover, preserving DST. New positions aren't times;
    a ready practice card takes precedence over a newly offered card.
    """
    if card.queue == 1:
        return card.due * 1000
    if card.queue in (2, 3):
        boundary = datetime.fromtimestamp(day_cutoff) - timedelta(days=today - card.due + 1)
        return int(boundary.timestamp() * 1000)
    return now_ms


@dataclass(frozen=True)
class TimedRequest:
    card_id: int
    due_ms: int
    interval_seconds: int
    original_queue: int | None = None
    next_study_day: bool = False
    request_id: str = "legacy"

    def __post_init__(self) -> None:
        _check_integer(self.card_id, "card_id", 1)
        _check_integer(self.due_ms, "due_ms")
        if self.due_ms > 2**53 - 1:
            raise ValueError("Deadline exceeds exact numeric search range")
        validate_interval(self.interval_seconds)
        if (not isinstance(self.request_id, str)
                or (self.request_id != "legacy" and (
                    len(self.request_id) != 32
                    or any(c not in "0123456789abcdef" for c in self.request_id)))):
            raise ValueError("Invalid practice appearance identity")
        if type(self.next_study_day) is not bool or (self.next_study_day and self.interval_seconds != 86400):
            raise ValueError("Invalid next-study-day interval")
        if self.original_queue is not None and (
            type(self.original_queue) is not int or self.original_queue not in ACTIVE_QUEUES
        ):
            raise ValueError("Unsupported original queue")


def _read(card_id: int, data: dict[str, Any]) -> TimedRequest | None:
    if "odbday" in data:
        raise UnsupportedRequestVersion("Day-based requests are not supported by this queue")
    if not any(key in data for key in KEYS):
        return None
    if type(data.get("odbv")) is not int or data["odbv"] not in (2, 3):
        raise UnsupportedRequestVersion("Unsupported HoldUp metadata version; not overwritten")
    if "odbat" not in data or "odbsecs" not in data or ("odbq" in data and data["odbq"] is None):
        raise InvalidRequestData("Incomplete or mixed HoldUp request")
    next_day = data["odbv"] == 3
    if ((next_day and (type(data.get("odbnext")) is not int or data["odbnext"] != 1))
            or (not next_day and "odbnext" in data)):
        raise InvalidRequestData("Invalid next-study-day metadata")
    try:
        return TimedRequest(card_id, data["odbat"], data["odbsecs"], data.get("odbq"), next_day)
    except ValueError as error:
        raise InvalidRequestData("Invalid timed practice request") from error


class PracticeQueue:
    """Collection-bound service; call writes through a serialized CollectionOp."""

    def __init__(self, collection: Any) -> None:
        self.col = collection

    def _overrides(self) -> dict[str, list[list]]:
        raw = self.col.get_config(CONFIG_KEY)
        if raw is None:
            return {}
        if not isinstance(raw, dict) or raw.get("v") not in (1, 2) or type(raw.get("v")) is not int:
            raise UnsupportedRequestVersion("Unsupported HoldUp collection data; not overwritten")
        cards = raw.get("cards")
        if not isinstance(cards, dict) or set(raw) != {"v", "cards"}:
            raise InvalidRequestData("Invalid HoldUp collection data")
        normalized = {}
        for key, value in cards.items():
            if (not isinstance(key, str) or not key.isdecimal()
                    or str(int(key)) != key or int(key) < 1):
                raise InvalidRequestData("Invalid HoldUp card identity")
            if raw["v"] == 1:
                request = self._from_override(int(key), value)
                normalized[key] = [self._entry(request)] if request else []
            else:
                if not isinstance(value, list):
                    raise InvalidRequestData("Invalid HoldUp appearance list")
                requests = [self._from_entry(int(key), entry) for entry in value]
                if len({r.request_id for r in requests}) != len(requests):
                    raise InvalidRequestData("Duplicate HoldUp appearance identity")
                normalized[key] = [self._entry(request) for request in requests]
        return normalized

    @staticmethod
    def _entry(request):
        return [request.request_id, request.due_ms, request.interval_seconds, request.next_study_day]

    @staticmethod
    def _from_entry(card_id, entry):
        if not isinstance(entry, list) or len(entry) != 4:
            raise InvalidRequestData("Invalid HoldUp appearance")
        try:
            return TimedRequest(card_id, entry[1], entry[2], next_study_day=entry[3], request_id=entry[0])
        except ValueError as error:
            raise InvalidRequestData("Invalid HoldUp appearance") from error

    @staticmethod
    def _from_override(card_id, value):
        if value is None:
            return None  # A cleared appointment from card metadata stays cleared.
        if not isinstance(value, list) or len(value) != 3:
            raise InvalidRequestData("Invalid HoldUp appointment")
        try:
            return TimedRequest(card_id, value[0], value[1], next_study_day=value[2])
        except ValueError as error:
            raise InvalidRequestData("Invalid HoldUp appointment") from error

    def _save_overrides(self, cards, name="HoldUp: schedule practice"):
        # A compact value: about 90 bytes per active appointment. Anki includes
        # collection config in sync; it is intended for a modest practice list.
        step = self.col.add_custom_undo_entry(tr(name))
        self.col.set_config(CONFIG_KEY, {"v": 2, "cards": cards}, undoable=True)
        return self.col.merge_undo_entries(step)

    def _card_requests(self, card, cards):
        key = str(card.id)
        if key in cards:
            return [self._from_entry(card.id, entry) for entry in cards[key]]
        saved = _read(card.id, _decode(card.custom_data))
        return [saved] if saved else []

    def _save_request(self, request, name, *, append=False):
        cards = self._overrides()
        previous = self._card_requests(self.col.get_card(request.card_id), cards)
        if append:
            if any(r.request_id == request.request_id for r in previous):
                raise PracticeStateChanged("Practice appearance identity already exists")
            previous.append(request)
        else:
            if not any(r.request_id == request.request_id for r in previous):
                raise PracticeStateChanged("Practice appearance no longer exists")
            previous = [request if r.request_id == request.request_id else r for r in previous]
        cards[str(request.card_id)] = [self._entry(r) for r in previous]
        return self._save_overrides(cards, name)

    def for_card(self, card_id: int) -> list[TimedRequest]:
        """Saved appearances in creation order, including an older saved request."""
        _check_integer(card_id, "card_id", 1)
        card = self.col.get_card(card_id)
        return self._card_requests(card, self._overrides())

    def get(self, card_id: int, request_id: str | None = None) -> TimedRequest | None:
        """Look up an identity; without one, return the most recently added item.

        Practice actions always supply the appearance identity. The shorthand
        is useful when inspecting a newly scheduled card, not for completion.
        """
        requests = self.for_card(card_id)
        if request_id is None:
            return requests[-1] if requests else None
        return next((r for r in requests if r.request_id == request_id), None)

    def all(self) -> list[TimedRequest]:
        from anki.errors import NotFoundError

        cards = self._overrides()
        ids = set(self.col.find_cards("prop:cdn:odbat>=0")) | {int(cid) for cid in cards}
        requests = []
        for cid in ids:
            try:
                requests.extend(self._card_requests(self.col.get_card(cid), cards))
            except NotFoundError:
                continue
        return sorted((r for r in requests if r is not None), key=lambda r: (r.due_ms, r.card_id))

    def available(self, request: TimedRequest) -> bool:
        card = self.col.get_card(request.card_id)
        return card.odid == 0 and (
            (request.original_queue is not None and card.queue == -1)
            or (request.original_queue is None and card.queue in ACTIVE_QUEUES)
        )

    def _write(self, card: Any, data: dict[str, Any], request: TimedRequest,
               name="HoldUp: schedule practice", *, append=False) -> Any:
        if request.original_queue is None:
            return self._save_request(request, name, append=append)
        data.update(odbv=3 if request.next_study_day else 2,
                    odbat=request.due_ms, odbsecs=request.interval_seconds)
        if request.next_study_day:
            data["odbnext"] = 1
        else:
            data.pop("odbnext", None)
        if request.original_queue is not None:
            data["odbq"] = request.original_queue
        else:
            data.pop("odbq", None)
        # Validate before changing the card, including shared custom-data budget.
        encoded = _encode(data)
        card.custom_data = encoded
        if request.original_queue is not None:
            card.queue = -1  # Persistent pause; unlike bury, does not expire daily.
        return self.col.update_card(card)

    def _request(self, card_id, seconds, clock, original_queue, next_study_day, *, request_id="legacy"):
        if type(next_study_day) is not bool:
            raise ValueError("Invalid next-study-day mode")
        due = self.col.sched.day_cutoff * 1000 if next_study_day else clock + seconds * 1000
        if due <= clock:
            raise PracticeStateChanged("Anki study-day boundary changed; try again")
        # For calendar mode 86400 is a nominal day, not the elapsed duration.
        # Schema 3 records that distinction; the exact cutoff is stored in due.
        return TimedRequest(card_id, due, 86400 if next_study_day else seconds,
                            original_queue, next_study_day, request_id)

    def enqueue(self, card_id: int, seconds: int, now_ms: int, *, pause: bool = False,
                next_study_day: bool = False) -> Any:
        _check_integer(card_id, "card_id", 1)
        validate_interval(seconds)
        _check_integer(now_ms, "now_ms")
        card = self.col.get_card(card_id)
        if card.odid or card.queue not in ACTIVE_QUEUES:
            raise PracticeStateChanged("Card is no longer available in ordinary review")
        data = _decode(card.custom_data)
        old = self.for_card(card_id)
        if any(r.original_queue is not None for r in old) or (pause and old):
            raise PracticeStateChanged("Existing paused request changed outside HoldUp")
        request = self._request(card_id, seconds, now_ms, card.queue if pause else None, next_study_day,
                                request_id="legacy" if pause else secrets.token_hex(16))
        return self._write(card, data, request, append=True)

    def repeat(self, expected: TimedRequest, seconds: int, now_ms: int, *, next_study_day: bool = False) -> Any:
        validate_interval(seconds)
        _check_integer(now_ms, "now_ms")
        card = self.col.get_card(expected.card_id)
        data = _decode(card.custom_data)
        if self.get(card.id, expected.request_id) != expected or not self.available(expected):
            raise PracticeStateChanged("Practice request changed; reload the list")
        if expected.due_ms > now_ms:
            raise PracticeStateChanged("Practice is not due yet")
        request = self._request(card.id, seconds, now_ms, expected.original_queue, next_study_day,
                                request_id=expected.request_id)
        return self._write(card, data, request, "HoldUp: repeat practice")

    def _release_card(self, expected: TimedRequest) -> Any:
        card = self.col.get_card(expected.card_id)
        data = _decode(card.custom_data)
        if _read(card.id, data) != expected:
            raise PracticeStateChanged("Practice request changed; reload the list")
        if expected.original_queue is not None and card.queue == -1:
            if card.odid:
                raise PracticeStateChanged("Card moved to a filtered deck; not resumed")
            card.queue = expected.original_queue
        # If the user changed the queue externally, preserve their choice.
        for key in KEYS:
            data.pop(key, None)
        card.custom_data = _encode(data) if data else ""
        return card

    def release(self, expected: TimedRequest) -> Any:
        """Return eligibility to Anki, without answering or moving its due date."""
        if expected.original_queue is None:
            return self.release_all([expected], name="HoldUp: finish practice")
        return self.col.update_card(self._release_card(expected))

    def resume_native(self, expected: list[TimedRequest]) -> Any:
        """Remove stored practice pauses, preserving practice deadlines, in one Undo.

        Preflight the whole batch. A changed external queue is preserved; a
        paused card moved to a filtered deck needs explicit manual recovery.
        """
        if not expected or len({(r.card_id, r.request_id) for r in expected}) != len(expected):
            raise ValueError("Expected a nonempty list of distinct requests")
        cards = []
        for request in expected:
            card = self.col.get_card(request.card_id)
            data = _decode(card.custom_data)
            if _read(card.id, data) != request or request.original_queue is None:
                raise PracticeStateChanged("Paused practice request changed; reload the list")
            if card.queue == -1:
                if card.odid:
                    raise PracticeStateChanged("Card moved to a filtered deck; not resumed")
                card.queue = request.original_queue
            data.pop("odbq")
            card.custom_data = _encode(data)
            cards.append(card)
        return self.col.update_cards(cards)

    def release_all(self, expected: list[TimedRequest], *, name="HoldUp: clear all practice") -> Any:
        """One native undoable batch; preflight every request before any write."""
        if not expected or len({(r.card_id, r.request_id) for r in expected}) != len(expected):
            raise ValueError("Expected a nonempty list of distinct requests")
        entries = self._overrides()
        source_cards = {cid: self.col.get_card(cid) for cid in {r.card_id for r in expected}}
        existing = {cid: self._card_requests(card, entries) for cid, card in source_cards.items()}
        by_identity = {(r.card_id, r.request_id): r for group in existing.values() for r in group}
        cards = []
        removed = {}
        for request in expected:
            if by_identity.get((request.card_id, request.request_id)) != request:
                raise PracticeStateChanged("Practice request changed; reload the list")
            if request.original_queue is not None:
                cards.append(self._release_card(request))
            else:
                removed.setdefault(request.card_id, set()).add(request.request_id)
        # Validate the original snapshot once. Re-reading and validating the
        # entire config for every appearance made clearing 1000 items take
        # several seconds even when they all belonged to a single card.
        for cid, identities in removed.items():
            remaining = [r for r in existing[cid] if r.request_id not in identities]
            data = _decode(source_cards[cid].custom_data)
            if remaining or any(key in data for key in KEYS):
                entries[str(cid)] = [self._entry(r) for r in remaining]
            else:
                entries.pop(str(cid), None)
        if not cards:
            return self._save_overrides(entries, name)
        if not removed:
            return self.col.update_cards(cards)
        # Only recovery can contain paused cards. Validate the whole batch
        # above, then group our two kinds of changes into one native Undo.
        step = self.col.add_custom_undo_entry(tr("HoldUp: clear all practice"))
        self.col.update_cards(cards)
        self._save_overrides(entries)
        return self.col.merge_undo_entries(step)
