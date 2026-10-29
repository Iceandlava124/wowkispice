#!/usr/bin/env python3
"""check_traceability.py - FAILS unless every requirement has a test.

The expectation is that the file runs under this repo's Python and pytest.
It parses the requirement entries in docs/requirements.md (a '| ID |' table
with 4 or more columns, Tests in the last-but-one-or-last cell), finds the
@pytest.mark.req("ID") markers - both in the test sources and in the junit
xml's <mark> elements - and fails (exit 1) if:

- a requirement has no test referencing it,
- a test (or source marker) references an unknown requirement ID,
- a requirement has no test that actually EXECUTED (ran, not skipped or
  xfailed) in the junit xml produced by pytest.

Zero requirements parsed or zero marked tests is never a pass: parsing
nothing means the checker saw no input, which is exactly the false green
this guard exists to stop.

Usage:
    # 1. Produce a junit xml that lists the real markers per test.
    python -m pytest tests -m "req or qemu or ngspice or integration or system" \
        --junit-xml=tests/junit.xml -q

    # 2. Run this checker.
    python tools/check_traceability.py tests/junit.xml
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REQUIREMENTS = os.path.join(ROOT, "docs", "requirements.md")
JUNIT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    ROOT, "tests", "junit.xml"
)

REQ_RE = re.compile(r"@pytest\.mark\.req\(\"([A-Za-z0-9-]+)\"\)")  # hyphen: CO-01
# test refs in a Tests cell: 'test_a::test_one', 'test_a.py' or
# 'test_a.py::Class::test_one' (the old pattern required '::' right after the
# name, so the repo's own 'test_x.py' cells never matched).
TEST_REF_RE = re.compile(r"test_[A-Za-z0-9_]+(?:\.py)?(?:::[^\s\]`,]+)?")

# requirement ids that are deliberately NOT IMPLEMENTED. They live in the
# second table of docs/requirements.md (## Not-yet-implemented), which the
# parser stops at, so they are never demanded here.
NOT_IMPLEMENTED_IDS = set()


def parse_requirements(path):
    """Return {req_id: set(test_refs)} parsed from the markdown table."""
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
            # A later heading starts a different table (the Not-yet-
            # implemented one): requirements there are not demanded.
            if stripped.startswith("## "):
                break
            if not stripped.startswith("|") or stripped.startswith("| ---"):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) < 4:
                continue
            rid = cells[0]
            if not rid or set(rid) <= set("-: "):
                continue  # separator row (|----|... form)
            # 4-column table: | ID | Requirement | Source | Tests |
            # 5-column table: | ID | Requirement | Source | Design | Tests |
            tests_cell = cells[4] if len(cells) >= 5 else cells[3]
            refs = set(TEST_REF_RE.findall(tests_cell))
            table[rid] = refs
    return table


def parse_source_markers():
    """Return {req_id: set((test_file, func_name))} from tests/test_*.py."""
    mapping = {}
    tests_dir = os.path.join(ROOT, "tests")
    if not os.path.isdir(tests_dir):
        return mapping
    for fname in sorted(os.listdir(tests_dir)):
        if not (fname.startswith("test_") and fname.endswith(".py")):
            continue
        try:
            with open(os.path.join(tests_dir, fname), encoding="utf-8") as fh:
                src = fh.read()
        except OSError:
            continue
        for m in REQ_RE.finditer(src):
            # The next `def` after the decorator is the marked test.
            dm = re.search(r"\bdef\s+([A-Za-z0-9_]+)\s*\(", src[m.end():])
            if dm:
                mapping.setdefault(m.group(1), set()).add((fname, dm.group(1)))
    return mapping


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


def junit_cases():
    """Return {name: (skipped_bool, classname)} for every junit testcase."""
    import xml.etree.ElementTree as ET

    cases = {}
    if not os.path.exists(JUNIT):
        return cases
    tree = ET.parse(JUNIT)
    for suite in tree.getroot().iter("testsuite"):
        for case in suite.iter("testcase"):
            name = case.get("name") or ""
            skipped = False
            for child in case:
                if child.tag == "skipped":
                    skipped = True
                elif child.tag in ("failure", "error") and \
                        child.get("type") == "XFAIL":
                    skipped = True
            cases[name] = (skipped, case.get("classname") or "")
    return cases


def executed(candidates, cases):
    """Which candidates ran for real in the junit xml?

    candidates: iterable of (func_name, file_stem) pairs, where file_stem is
    empty for junit-mark (legacy) candidates. A candidate counts as executed
    when a junit testcase of that name ran and was not skipped/xfailed; when
    the candidate came from a source file, the classname must contain the
    file stem so same-name functions in other modules do not vouch for it.
    """
    done = []
    for cand in candidates:
        func, stem = cand
        for name, (skipped, classname) in cases.items():
            if not (name == func or name.startswith(func + "[")):
                continue
            if stem and stem not in classname and stem not in name:
                continue
            if not skipped:
                done.append(name)
                break
    return done


def main():
    try:
        reqs = parse_requirements(REQUIREMENTS)
    except OSError as exc:
        # A missing requirements file must not read as "0 requirements, OK".
        print("\nTRACEABILITY FAIL")
        print("  - cannot read %s: %s" % (REQUIREMENTS, exc))
        sys.exit(1)
    print("Requirements parsed from docs/requirements.md:", len(reqs))
    for rid in sorted(reqs):
        print("  %s -> %d test references" % (rid, len(reqs[rid])))

    junit = parse_junit(reqs)
    source = parse_source_markers()
    marked = set(junit) | {(f + "::" + n) for pairs in source.values()
                           for (f, n) in pairs}
    print("\nTests carrying @pytest.mark.req: %d" % len(marked))

    problems = []

    # 0 is never a pass: parsing nothing means the checker saw no input,
    # which is exactly the false green this guard exists to stop.
    if not reqs:
        problems.append(
            "parsed 0 requirements from %s (missing file or no '| ID |' table)"
            % REQUIREMENTS
        )
    if not marked:
        problems.append(
            "0 tests carrying @pytest.mark.req in %s "
            "(junit xml missing or no marked tests ran)" % JUNIT
        )

    # 1. requirements with no test
    for rid, tests in reqs.items():
        if not tests:
            problems.append("Requirement %s has no test references" % rid)

    # 2. tests referencing unknown requirement ids (junit marks and source
    #    markers both)
    for test_name, ids in junit.items():
        for rid in ids:
            if rid not in reqs:
                problems.append(
                    "Test %s references unknown requirement %s"
                    % (test_name, rid)
                )
    for rid, pairs in source.items():
        if rid not in reqs:
            problems.append(
                "Test %s references unknown requirement %s"
                % (", ".join("%s::%s" % p for p in sorted(pairs)), rid)
            )

    # 3. requirements whose tests never actually ran (or all skipped/xfailed)
    cases = junit_cases()
    for rid in sorted(reqs):
        if rid in NOT_IMPLEMENTED_IDS:
            continue
        candidates = [(func, os.path.splitext(f)[0])
                      for (f, func) in source.get(rid, set())]
        candidates += [(name, "") for name in junit
                       if rid in junit[name]]
        if not candidates:
            problems.append(
                "Requirement %s has no executed test "
                "(junit missing or test not run)" % rid
            )
            continue
        ran = executed(candidates, cases)
        if not ran:
            src_names = sorted("%s::%s" % (f, n)
                               for f, n in source.get(rid, set()))
            if not src_names:
                src_names = sorted(name for name in junit
                                   if rid in junit[name])
            problems.append(
                "Requirement %s: all mapped tests skipped/xfail or not in "
                "junit: %s" % (rid, ", ".join(src_names))
            )

    if problems:
        print("\nTRACEABILITY FAIL")
        for p in problems:
            print("  - %s" % p)
        print("Requirements: %d, Executed requirement tests: %d"
              % (len(reqs), len(marked)))
        sys.exit(1)

    print("\nTRACEABILITY OK: %d requirements, %d tests"
          % (len(reqs), len(marked)))


if __name__ == "__main__":
    main()
