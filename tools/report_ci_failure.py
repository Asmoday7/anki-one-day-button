"""Surface synthetic-test failures as public GitHub check annotations."""

from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


path = Path(sys.argv[1])
if not path.exists():
    print("::error::No JUnit report was produced; inspect the preceding setup/test step.")
else:
    for case in ET.parse(path).getroot().iter("testcase"):
        for kind in ("failure", "error"):
            for result in case.findall(kind):
                detail = (result.text or result.attrib.get("message", ""))[-4000:]
                title = escape(case.attrib.get("name", "Test failure"))
                print(f"::error title={title}::{escape(detail)}")
