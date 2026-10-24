"""Measure a synthetic queue in a temporary collection; never opens user data."""

import argparse
import json
from pathlib import Path
import platform
import sys
from tempfile import TemporaryDirectory
from time import perf_counter, time_ns

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def benchmark(count: int) -> dict:
    from importlib.metadata import version
    from anki.collection import Collection
    from holdup.practice import CONFIG_KEY, PracticeQueue

    if not 1 <= count <= 10000:
        raise ValueError("Benchmark count must be between 1 and 10000")
    with TemporaryDirectory() as temporary:
        col = Collection(str(Path(temporary) / "synthetic.anki2"))
        try:
            note = col.new_note(col.models.by_name("Basic"))
            note["Front"] = "Synthetic release benchmark"
            col.add_note(note, 1)
            cid = note.card_ids()[0]
            clock = time_ns() // 1_000_000
            entries = [[f"{index + 1:032x}", clock - 1000, 1, False] for index in range(count)]
            col.set_config(CONFIG_KEY, {"v": 2, "cards": {str(cid): entries}})
            queue = PracticeQueue(col)
            manifest = Path(__file__).resolve().parents[1] / "holdup" / "manifest.json"
            result = {"appearances": count, "platform": platform.system(),
                      "python": platform.python_version(), "anki_package": version("anki"),
                      "holdup": json.loads(manifest.read_text(encoding="utf-8"))["human_version"]}
            start = perf_counter()
            requests = queue.all()
            result["read_seconds"] = perf_counter() - start
            start = perf_counter()
            queue.repeat(requests[0], 7200, clock)
            result["repeat_seconds"] = perf_counter() - start
            requests = queue.all()
            start = perf_counter()
            queue.release_all(requests)
            result["clear_seconds"] = perf_counter() - start
            assert not queue.all()
            col.undo()
            assert queue.all() == requests
            col.redo()
            assert not queue.all() and not col.get_review_logs(cid)
            result["undo_redo"] = "passed"
            return result
        finally:
            col.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(benchmark(args.count), indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8")
    print(result, end="")
