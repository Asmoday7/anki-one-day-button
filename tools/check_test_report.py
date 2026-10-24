"""Reject skipped integration checks before publishing a release candidate."""

import sys
import xml.etree.ElementTree as ET


def check(path: str) -> int:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    count = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    if count < 231 or any(int(suite.attrib.get(key, 0)) for suite in suites
                          for key in ("errors", "failures", "skipped")):
        raise ValueError("Release requires the full suite with no errors, failures or skips")
    gui = [case for case in root.iter("testcase")
           if case.attrib.get("name", "").startswith("test_packaged_button_in_desktop_anki[")]
    if len(gui) != 4:
        raise ValueError("All four packaged desktop scenarios must run")
    return count


if __name__ == "__main__":
    print(f"Release test report: {check(sys.argv[1])} passed, including four desktop scenarios")
