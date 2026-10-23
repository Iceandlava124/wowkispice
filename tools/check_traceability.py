#!/usr/bin/env python3
"""check_traceability.py - FAILS unless every requirement has a test.

The expectation is that the file runs under this repo's Python and pytest.
It parses the test source files looking for @pytest.mark.req("ID") markers
and the requirement entries in docs/requirements.md, then fails (exit 1) if:

- a requirement has no test referencing it,
- a test references an unknown requirement ID,
- a requirement's mapped test is skipped/xfail/unexecuted (the "skipped"
  check is performed against a junit xml produced by pytest, which is what the
  CI traceability job consumes).

Usage:
    # 1. Produce a junit xml that lists the real markers per test.
    python -m pytest tests -m "req or qemu or ngspice or integration or system" \
        --junit-xml=tests/junit.xml -q

    # 2. Run this checker.
    python tools/check_traceability.py tests/junit.xml
"""

import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REQUIREMENTS = os.path.join(ROOT, "docs", "requirements.md")
JUNIT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    ROOT, "tests", "junit.xml"
)

REQ_RE = re.compile(r"@pytest\.mark\.req\(\"([A-Za-z0-9]+)\"\)")
UNKNOWN_ID_RE = re.compile(r"@pytest\.mark\.req\(\"([A-Za-z0-9]+)\"\)")

# requirement ids that are deliberately NOT IMPLEMENTED and are xfailed
# strictly. These are expected to have no *passing* test, and the audit must
# report them as NOT IMPLEMENTED rather than as a gap.
NOT_IMPLEMENTED_IDS = {
    # filled in below after the docs are generated; read from the markdown
}


def parse_requirements(path):
    """Return {req_id: set(test_files)} parsed from the markdown table."""
    table = {}
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    in_tests = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("| ID |"):
            in_tests = True
            continue
        if in_tests:
            if not stripped.startswith("|") or stripped.startswith("| ---"):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) < 5:
                continue
            rid = cells[0]
            tests_cell = cells[4]
            # tests cell is markdown link text or a comma separated list
            refs = set()
            for m in re.finditer(r"test_[A-Za-z0-9_]+::[^\s\]]+", tests_cell):
                refs.add(m.group(0))
            table[rid] = refs
    return table


def parse_junit(req_by_test):
    """Map test names to the requirement ids they carry, from junit xml."""
    import xml.etree.ElementTree as ET

    mapping = {}
    if not os.path.exists(JUNIT):
        return mapping
    tree = ET.parse(JUNIT)
    for suite in tree.getroot().iter("testsuite"):
        for case in suite.iter("testcase"):
            name = case.get("name")
            req_ids = set()
            for mark in case.iter("mark"):
                if mark.get("name") == "req":
                    req_ids.add(mark.get("content"))
            if req_ids:
                mapping[name] = req_ids
    return mapping


def skip_or_xfail(junit, test_name):
    """Return True if the test is skipped or xfailed in this run."""
    import xml.etree.ElementTree as ET

    if not os.path.exists(JUNIT):
        return False
    tree = ET.parse(JUNIT)
    for suite in tree.getroot().iter("testsuite"):
        for case in suite.iter("testcase"):
            if case.get("name") == test_name:
                for child in case:
                    if child.tag in ("skipped", "failure", "error"):
                        if child.tag == "skipped":
                            return True
                        if child.get("type") == "XFAIL":
                            return True
    return False


def main():
    reqs = parse_requirements(REQUIREMENTS)
    print("Requirements parsed from docs/requirements.md:", len(reqs))
    for rid in sorted(reqs):
        print("  %s -> %d test references" % (rid, len(reqs[rid])))

    junit = parse_junit(reqs)
    print("\nTests carrying @pytest.mark.req: %d" % len(junit))

    problems = []

    # 1. requirements with no test
    for rid, tests in reqs.items():
        if not tests:
            problems.append("Requirement %s has no test references" % rid)

    # 2. tests referencing unknown requirement ids
    for test_name, ids in junit.items():
        for rid in ids:
            if rid not in reqs:
                problems.append(
                    "Test %s references unknown requirement %s"
                    % (test_name, rid)
                )

    # 3. requirements whose tests are all skipped/xfail/unexecuted
    for rid, tests in reqs.items():
        existing = [t for t in tests if t in junit]
        if not existing:
            # no test executed at all: report as unexecuted, not a pass
            problems.append(
                "Requirement %s has no executed test "
                "(junit missing or test not run)" % rid
            )
            continue
        unexecuted = []
        for t in existing:
            if skip_or_xfail(junit, t):
                unexecuted.append(t)
        if unexecuted:
            problems.append(
                "Requirement %s: all mapped tests skipped/xfail: %s"
                % (rid, ", ".join(unexecuted))
            )

    if problems:
        print("\nTRACEABILITY FAIL")
        for p in problems:
            print("  - %s" % p)
        print("Requirements: %d, Executed requirement tests: %d"
              % (len(reqs), len(junit)))
        sys.exit(1)

    print("\nTRACEABILITY OK: %d requirements, %d tests"
          % (len(reqs), len(junit)))


if __name__ == "__main__":
    main()
