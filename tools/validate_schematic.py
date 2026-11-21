#!/usr/bin/env python3
"""
validate_schematic.py - READ-ONLY structural validation of a KiCad .kicad_sch.

Applies the same structural gates the WOWKISPICE project uses for its own
KiCad exports (tests/test_kicad_export.py) to an EXTERNAL schematic:
  - balanced s-expressions (quotes respected)
  - required top-level sections
  - component instances vs lib_symbols definitions
  - wire / junction / label / no_connect presence
  - duplicate references
  - power/global label sanity

Never writes to the input file. Prints a JSON report to stdout.
"""
import json
import re
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8", errors="replace").read()
report = {"file": path, "bytes": len(text), "checks": []}


def check(name, ok, detail=""):
    report["checks"].append({"name": name, "pass": bool(ok), "detail": detail})


# 1. balanced s-expressions respecting double-quoted strings
def balanced(s):
    depth = 0
    in_str = False
    for c in s:
        if c == '"':
            in_str = not in_str
        elif not in_str:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth < 0:
                    return False
    return depth == 0 and not in_str


check("balanced_s_expressions", balanced(text))

# 2. top-level sections
for sec in ("kicad_sch", "lib_symbols", "paper", "title_block"):
    check(f"has_{sec}", f"({sec}" in text)

# 3. counts
counts = {
    "components": len(re.findall(r"\(lib_id\s+\"", text)),
    "wires": len(re.findall(r"\(wire", text)),
    "junctions": len(re.findall(r"\(junction", text)),
    "no_connects": len(re.findall(r"\(no_connect", text)),
    "global_labels": len(re.findall(r"\(global_label", text)),
    "labels": len(re.findall(r"(?<!global_)\(label", text)),
    "lib_symbol_defs": len(re.findall(r'\(symbol\s+"[^"]+:[^"]+"', text)),
}
report["counts"] = counts
check("has_components", counts["components"] > 0, str(counts["components"]))
check("has_wires", counts["wires"] > 0, str(counts["wires"]))

# 4. refs (instances only: exclude the lib_symbols definition block)
idx = text.find("(lib_symbols")
d = 0
end = idx
for i in range(idx, len(text)):
    if text[i] == "(":
        d += 1
    elif text[i] == ")":
        d -= 1
        if d == 0:
            end = i + 1
            break
body = text[end:]
refs = re.findall(r'\(property\s+"Reference"\s+"([^"]+)"', body)
report["refs"] = sorted(set(refs))
# Multi-unit parts (e.g. a dual op-amp U2 units A/B) share one reference
# legitimately; count duplicate *distinct* refs across instances.
dupes = sorted({r for r in refs if refs.count(r) > 1 and not r.startswith("#PWR")})
# A ref repeated only as a multi-unit IC (has distinct (unit N) fields) is OK.
if dupes:
    blocks = re.split(r'(?=\(lib_id\s+")', body)
    multi_ok = []
    for r in dupes:
        unit_numbers = set()
        for b in blocks:
            mref = re.search(r'\(property\s+"Reference"\s+"' + re.escape(r) + r'"', b)
            if mref:
                u = re.search(r'\(unit\s+(\d+)', b)
                if u:
                    unit_numbers.add(u.group(1))
        if len(unit_numbers) > 1:
            multi_ok.append(r)
    dupes = [d for d in dupes if d not in multi_ok]
check("no_duplicate_refs", not dupes, ", ".join(dupes))

# 5. lib_ids used vs defined
used_ids = set(re.findall(r'\(lib_id\s+"([^"]+)"', text))
defined_ids = set(re.findall(r'\(symbol\s+"([^"]+:[^"]+)"', text))
missing = sorted(used_ids - defined_ids)
report["lib_ids_used"] = sorted(used_ids)
check("all_lib_ids_defined", not missing, ", ".join(missing))

# 6. global labels non-empty and sane names
glabels = re.findall(r'\(global_label\s+"([^"]+)"', text)
bad_glabels = [g for g in glabels if not g or any(c in g for c in " \t")]
check("global_labels_sane", not bad_glabels, ", ".join(bad_glabels))

# 7. no obvious placeholder junk
junk = re.findall(r"(?i)\b(TODO|FIXME|XXX|TBD)\b", text)
check("no_todo_markers", not junk, ", ".join(sorted(set(junk))))

passed = sum(1 for c in report["checks"] if c["pass"])
report["summary"] = f"{passed}/{len(report['checks'])} checks passed"
report["all_passed"] = passed == len(report["checks"])
print(json.dumps(report, indent=2))
sys.exit(0 if report["all_passed"] else 1)
