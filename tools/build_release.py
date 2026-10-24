"""Build versioned installer/upload archives and checksums from one source tree."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.package_addon import REPOSITORY, build_addon


def build_release(destination: Path, tag: str | None = None) -> list[Path]:
    version = json.loads((REPOSITORY / "holdup" / "manifest.json").read_text(encoding="utf-8"))["human_version"]
    if re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\.\d+)?", version) is None:
        raise ValueError("Release version must be X.Y.Z or X.Y.Z-rc.N")
    if tag is not None and tag != "v" + version:
        raise ValueError("Tag must match manifest human_version")
    installer = build_addon(destination / f"holdup-{version}.ankiaddon")
    upload = destination / f"holdup-{version}.zip"
    upload.write_bytes(installer.read_bytes())
    archives = [installer, upload]
    checksums = destination / "SHA256SUMS"
    checksums.write_text("".join(f"{sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                                 for path in archives), encoding="utf-8", newline="\n")
    return archives + [checksums]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, default=REPOSITORY / "dist")
    parser.add_argument("--tag")
    args = parser.parse_args()
    for path in build_release(args.output_directory, args.tag):
        print(path)
