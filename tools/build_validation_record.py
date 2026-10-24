"""Summarize the four completed CI reports without claiming manual validation."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.check_test_report import check


def build(reports: Path, destination: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    version = json.loads((root / "holdup" / "manifest.json").read_text(encoding="utf-8"))["human_version"]
    cases = []
    expected = {f"validation-{system}-anki-{anki}" for system in ("ubuntu-24.04", "windows-2025")
                for anki in ("26.9", "26.9.3")}
    actual = {path.name for path in reports.iterdir() if path.is_dir()}
    if actual != expected:
        raise ValueError("Validation requires reports from all four platform/version jobs")
    for name in sorted(expected):
        folder = reports / name
        report, = folder.rglob("ci-results.xml")
        benchmark, = folder.rglob("queue-benchmark.json")
        measurements = json.loads(benchmark.read_text(encoding="utf-8"))
        if measurements.get("holdup") != version or measurements.get("undo_redo") != "passed":
            raise ValueError("Queue benchmark does not match the candidate")
        expected_platform = "Windows" if name.startswith("validation-windows") else "Linux"
        expected_python = "3.13." if expected_platform == "Windows" else "3.12."
        if (measurements.get("platform") != expected_platform
                or measurements.get("anki_package") != name.split("-anki-")[1]
                or not measurements.get("python", "").startswith(expected_python)):
            raise ValueError("Reported platform/Anki/Python does not match the CI job")
        cases.append({"job": name, "passed": check(str(report)), "packaged_gui_cases": 4,
                      "queue_benchmark": measurements})
    record = {"candidate": version,
              "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "recorded_utc": datetime.now(timezone.utc).isoformat(), "automated": cases,
              "windows_11_manual": "not yet reported", "real_windows_study_day_crossing": "not yet reported"}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.reports, args.output)
