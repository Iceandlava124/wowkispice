#!/usr/bin/env python3
"""
parity_control_law.py - cross-implementation diff of bridge/control_law.py
against the Rust port in crates/wowkispice-core/src/control_law.rs.

This is the Rust twin of native/tools/parity_control_law.py: same battery,
same keys, same comparison rules, pointed at the Rust binary instead of the
C one.  All three implementations - Python, C, Rust - are therefore diffed
over one identical key space.

WHY THIS EXISTS, INSTEAD OF ONLY PORTING THE TESTS
---------------------------------------------------
crates/wowkispice-core/tests/test_control_law.rs is a line-for-line port of
tests/test_control_law_unit.py, tests/test_adc_conversion.py and the
control-law classes of tests/test_cosim_control.py.  Porting tests proves the
Rust code satisfies the *assertions we thought to write down*; it cannot
catch a place where both the Rust code and its ported test are wrong in the
same way, because a transcription error travels with its test.

This script closes that hole by computing one fixed battery of results twice -
once from the Python module, once by running the Rust binary - and diffing
every value.  A divergence of one ULP in the ADC mapping, one wrong branch in
the decision table, or one differently-worded error message fails here even if
every ported test still passes.

KEYS ARE INDEX-BASED, NOT VALUE-BASED
-------------------------------------
`spec[7].low` rather than `low=1995`.  If a key were derived from its value,
then a value that happens to format differently on one side (Python's repr vs
Rust's Display) would silently shift the key space and the two batteries
would "differ" for a cosmetic reason - or worse, line up wrongly.  Index keys
also mean a case added on one side alone is caught as a missing key.

COMPARISON RULE
---------------
Each value is parsed as a float where possible and compared as a double, so
"4095" and "4095.0" compare equal (they are the same number, emitted by
different formatters), while "0.4" and "0.40000000000000002" still compare
equal because both parse back to the identical IEEE-754 value.  Anything that
is not numeric - error messages, HIGH/LOW, GPIO names - is compared as text.

Run:  .venv/Scripts/python.exe crates/parity/python/parity_control_law.py <rust-binary>
      (or with no argument, if the binary is on PATH as parity_control_law)
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

# repo/crates/parity/python/this_file.py -> repo is four levels up.
REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, REPO)

from bridge import control_law  # noqa: E402  (path set above)

FW = os.path.join(REPO, "firmware", "esp32_buck_controller", "src", "main.c")

# Emission helpers.  Doubles go through repr(float) so they round-trip exactly
# when the driver parses them back; the Rust side uses shortest round-trip
# Display.  The driver compares numerically, so the two spellings of one
# double never matter.
OUT: Dict[str, str] = {}


def emit_d(key: str, value: object) -> None:
    OUT[key] = repr(float(value))  # type: ignore[arg-type]


def emit_l(key: str, value: object) -> None:
    OUT[key] = str(int(value))  # type: ignore[arg-type]


def emit_b(key: str, value: object) -> None:
    OUT[key] = "true" if value else "false"


def emit_s(key: str, value: object) -> None:
    OUT[key] = str(value)


# ----------------------------------------------------------------------
# 1. ADC conversion grid
# ----------------------------------------------------------------------
# Same lists, same order, as parity_control_law.c/.rs.  Expressions are
# written identically so both sides evaluate the same IEEE-754 doubles.
ADC12_VOLTS: List[float] = [
    -0.01, -0.001, 0.0, 3.3 / 8190, 3.3 / 8190 + 1e-9,
    0.1, 0.5, 1.0, 1.2, 1.6077, 1.625, 1.6359, 2.4,
    3.3 - 1e-9, 3.3, 3.30000001, 3.31, 10.0,
]
ADC16_VOLTS: List[float] = [
    -1.0, 0.0, 0.0001, 2.5, 4.999999, 5.0, 5.5, 100.0,
]


def battery_adc() -> None:
    for i, v in enumerate(ADC12_VOLTS):
        emit_l(f"adc12[{i}]", control_law._to_counts(v, 3.3, 12))
    for i, v in enumerate(ADC16_VOLTS):
        emit_l(f"adc16[{i}]", control_law._to_counts(v, 5.0, 16))
    # adc_bits extremes accepted by normalisation: 8 and 24.
    emit_l("adc8[0]", control_law._to_counts(1.0, 3.3, 8))
    emit_l("adc8[1]", control_law._to_counts(3.3, 3.3, 8))
    emit_l("adc24[0]", control_law._to_counts(1.0, 3.3, 24))
    emit_l("adc24[1]", control_law._to_counts(3.3, 3.3, 24))


# ----------------------------------------------------------------------
# 2. Spec normalisation
# ----------------------------------------------------------------------
def spec_base() -> Dict[str, object]:
    return {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout"}


def spec_at(i: int) -> Dict[str, object]:
    """Index order mirrored exactly in parity_control_law.c/.rs."""
    sp = spec_base()
    if i == 0:      # fixture with the firmware's explicit counts
        sp.update(target_v=3.3, hysteresis_v=0.165, divider=0.5,
                  vref=3.3, adc_bits=12, low_counts=1995, high_counts=2030)
    elif i == 1:    # counts derived from target and hysteresis
        sp.update(target_v=3.3, hysteresis_v=0.165, divider=0.5,
                  vref=3.3, adc_bits=12)
    elif i == 2:    # pwm
        sp.update(kind="pwm", target_v=3.3, carrier_hz=1000, duty_gain=0.5)
    elif i == 3:    # defaults only - every default must materialise
        pass
    elif i == 4:    # explicit counts overriding a round-trip through volts
        sp.update(target_v=1.0, hysteresis_v=0.01,
                  low_counts=1995, high_counts=2030)
    elif i == 5:    # only low_counts given -> both recomputed
        sp.update(target_v=3.3, hysteresis_v=0.165, divider=0.5,
                  vref=3.3, adc_bits=12, low_counts=1995)
    elif i == 6:    # kind is case-insensitive in Python
        sp.update(kind="HYSTERETIC")
    elif i == 7:    # pin is stripped
        sp.update(pin="   GPIO42\t")
    # --- invalid from here on ---
    elif i == 8:
        sp.update(kind="banana")
    elif i == 9:
        sp.update(divider=0)
    elif i == 10:
        sp.update(low_counts=2000, high_counts=2000)
    elif i == 11:
        sp.update(vhigh=99)
    elif i == 12:
        sp.pop("pin")
    elif i == 13:
        sp.pop("sense_net")
    elif i == 14:
        sp.update(adc_bits=40)
    elif i == 15:
        sp.update(hysteresis_v=0)
    elif i == 16:
        sp.update(target_v=1.0, hysteresis_v=2.0)
    elif i == 17:
        sp.update(kind="pwm", carrier_hz=0)
    elif i == 18:
        sp.update(vref=0)
    elif i == 19:
        sp.update(target_v=-5)
    return sp


SPEC_COUNT = 20


def battery_specs() -> None:
    for i in range(SPEC_COUNT):
        sp = spec_at(i)
        try:
            norm = control_law.normalize_law(sp)
        except control_law.ControlLawError as exc:
            emit_s(f"spec[{i}]", str(exc))
            continue
        emit_s(f"spec[{i}]", "")
        emit_s(f"spec[{i}].kind", norm["kind"])
        emit_s(f"spec[{i}].pin", norm["pin"])
        emit_s(f"spec[{i}].sense_net", norm["sense_net"])
        emit_d(f"spec[{i}].target", norm["target_v"])
        emit_d(f"spec[{i}].vhigh", norm["vhigh"])
        emit_d(f"spec[{i}].vref", norm["vref"])
        emit_d(f"spec[{i}].divider", norm["divider"])
        emit_l(f"spec[{i}].adc_bits", norm["adc_bits"])
        # Keyed on kind: a normalized pwm spec carries no low/high counts and
        # a normalized hysteretic one carries no carrier/gain.
        if norm["kind"] == "hysteretic":
            emit_l(f"spec[{i}].low", norm["low_counts"])
            emit_l(f"spec[{i}].high", norm["high_counts"])
            emit_d(f"spec[{i}].hyst", norm["hysteresis_v"])
        else:
            emit_d(f"spec[{i}].carrier", norm["carrier_hz"])
            emit_d(f"spec[{i}].gain", norm["duty_gain"])
        emit_s(f"spec[{i}].source", norm.get("source", "(none)"))


# ----------------------------------------------------------------------
# 3. Decision table
# ----------------------------------------------------------------------
DECIDE_COUNTS: List[int] = [
    0, 100, 1990, 1994, 1995, 1996, 2012, 2029, 2030, 2031, 2035, 4095,
]


def battery_decide() -> None:
    law = control_law.make_law(spec_at(0))
    emit_s("decide.setup", "")
    # Two passes: decide() holds the PREVIOUS level inside the band, so the
    # same counts must give different answers depending on law.level.
    for passing in (0, 1):
        law.level = bool(passing == 1)
        for i, c in enumerate(DECIDE_COUNTS):
            emit_b(f"decide[{passing}][{i}]", bool(law.decide(c)))
    # And the ADC front end on this law: sense volts -> counts, divider applied.
    emit_l("law.to_counts[0]", law.to_counts(0.0))
    emit_l("law.to_counts[1]", law.to_counts(2.4))
    emit_l("law.to_counts[2]", law.to_counts(3.3))
    emit_l("law.to_counts[3]", law.to_counts(6.6))


# ----------------------------------------------------------------------
# 4. update() sequence and the telemetry it produces
# ----------------------------------------------------------------------
UPD_VOLTS: List[float] = [0.0, 5.0, 5.0, 3.25, 3.25, 0.0, 1.6, 3.3, 0.0, 4.0]
UPD_TIME: List[float] = [0.0, 1e-6, 2e-6, 3e-6, 4e-6,
                         5e-6, 6e-6, 7e-6, 8e-6, 9e-6]


def battery_update() -> None:
    law = control_law.make_law(spec_at(0))
    emit_s("update.setup", "")
    for i, (v, t) in enumerate(zip(UPD_VOLTS, UPD_TIME)):
        pin = law.update(v, t)
        emit_d(f"update[{i}].pin", pin)
        emit_l(f"update[{i}].switches", law.switch_count)
        emit_l(f"update[{i}].counts", law.history_counts[-1])

    st = law.stats()
    emit_l("stats.samples", st["samples"])
    emit_l("stats.switches", st["switches"])
    emit_d("stats.duty", st["duty"])
    has_counts = st["counts_min"] is not None
    emit_l("stats.has_counts", 1 if has_counts else 0)
    # The Rust struct keeps a zeroed counts_min/max/last when there are no
    # samples; Python's dict says None.  Only the flag carries meaning there,
    # and this battery always has samples, so the numbers are emitted either
    # way and the flag is what would disagree if that ever stopped holding.
    emit_l("stats.min", st["counts_min"] if has_counts else 0)
    emit_l("stats.max", st["counts_max"] if has_counts else 0)
    emit_l("stats.last", st["counts_last"] if has_counts else 0)
    emit_s("stats.final", st["final_level"])
    emit_s("stats.pin", st["pin"])
    emit_s("stats.sense_net", st["sense_net"])
    emit_s("stats.kind", st["kind"])


# ----------------------------------------------------------------------
# 5. PWM behaviour
# ----------------------------------------------------------------------
def battery_pwm() -> None:
    sp = {"kind": "pwm", "pin": "PWM0", "sense_net": "vout", "target_v": 3.3,
          "carrier_hz": 1000, "duty_gain": 0.5}
    law = control_law.make_law(sp)
    emit_s("pwm.setup", "")
    emit_d("pwm.target_counts", law.target_counts)

    low_error = high_error = 0.0
    for i in range(2000):
        law.update(3.0, i * 1e-7)
        low_error = law.duty
        law.update(0.5, i * 1e-7)
        high_error = law.duty
    emit_d("pwm.low_error", low_error)
    emit_d("pwm.high_error", high_error)
    emit_l("pwm.switches", law.switch_count)
    emit_l("pwm.samples", len(law.history_pin))

    st = law.stats()
    emit_d("pwm.stats.duty", st["duty"])
    emit_l("pwm.stats.switches", st["switches"])

    # Saturating case: gain 100 must clamp to 1.0, never exceed it.
    sat = control_law.make_law({"kind": "pwm", "pin": "PWM0", "sense_net": "vout",
                                "target_v": 3.3, "duty_gain": 100.0})
    sat.update(0.0, 0.0)
    emit_d("pwm.saturated", sat.duty)


# ----------------------------------------------------------------------
# 6. Firmware import and divider semantics
# ----------------------------------------------------------------------
def battery_firmware() -> None:
    try:
        consts = control_law.read_firmware_constants(FW)
    except control_law.ControlLawError as exc:
        emit_s("fw.setup", str(exc))
        return
    emit_s("fw.setup", "")
    emit_s("fw.pin", consts["pin"])
    emit_l("fw.low", consts["low"])
    emit_l("fw.high", consts["high"])

    for d, div in enumerate((1.0, 0.5)):
        try:
            spec = control_law.law_from_firmware_source(FW, "vout", div)
        except control_law.ControlLawError as exc:
            emit_s(f"fw.div[{d}]", str(exc))
            continue
        emit_s(f"fw.div[{d}]", "")
        emit_d(f"fw.div[{d}].target", spec["target_v"])
        emit_d(f"fw.div[{d}].hyst", spec["hysteresis_v"])
        emit_s(f"fw.div[{d}].source", spec["source"])
        emit_l(f"fw.div[{d}].src_low", spec["source_counts"]["low"])  # type: ignore[index]
        emit_l(f"fw.div[{d}].src_high", spec["source_counts"]["high"])  # type: ignore[index]
        norm = control_law.normalize_law(spec)
        emit_l(f"fw.div[{d}].low", norm["low_counts"])
        emit_l(f"fw.div[{d}].high", norm["high_counts"])
        emit_d(f"fw.div[{d}].target_norm", norm["target_v"])

    # _exact() must reproduce the file's integers verbatim.
    try:
        spec = control_law.law_from_firmware_source_exact(FW, "fb", 1.0)
    except control_law.ControlLawError as exc:
        emit_s("fw.exact", str(exc))
        emit_s("fw.empty_source", _empty_source_message())
        return

    emit_s("fw.exact", "")
    emit_l("fw.exact.low", spec["low_counts"])  # type: ignore[arg-type]
    emit_l("fw.exact.high", spec["high_counts"])  # type: ignore[arg-type]
    emit_d("fw.exact.divider", spec["divider"])
    emit_s("fw.exact.pin", spec["pin"])
    emit_s("fw.exact.source", spec["source"])

    norm = control_law.normalize_law(spec)
    emit_l("fw.exact.norm_low", norm["low_counts"])
    emit_l("fw.exact.norm_high", norm["high_counts"])

    lo, hi = control_law.implied_pin_voltages(spec)
    emit_d("fw.pin_v.lo", lo)
    emit_d("fw.pin_v.hi", hi)
    emit_d("fw.pin_v.mid", (lo + hi) / 2.0)

    lo, hi = control_law.implied_output_voltages(spec, 0.5)
    emit_d("fw.out_v.lo", lo)
    emit_d("fw.out_v.hi", hi)

    # A bad pin divider must be rejected, after the pin voltages are computed
    # - the same order Python validates in.
    try:
        control_law.implied_output_voltages(spec, 0.0)
        emit_l("fw.bad_div.status", 0)
        emit_s("fw.bad_div.msg", "")
    except control_law.ControlLawError as exc:
        emit_l("fw.bad_div.status", 1)
        emit_s("fw.bad_div.msg", str(exc))

    # Re-derive from the undivided node: the switching points must not move,
    # but the reported target halves.
    spec2 = control_law.law_from_firmware_source(FW, "vout", 0.5)
    norm2 = control_law.normalize_law(spec2)
    emit_l("fw.vout_half.low", norm2["low_counts"])
    emit_l("fw.vout_half.high", norm2["high_counts"])
    emit_d("fw.vout_half.target", norm2["target_v"])

    emit_s("fw.empty_source", _empty_source_message())


def _empty_source_message() -> str:
    try:
        control_law.read_firmware_constants("does/not/exist.c")
    except control_law.ControlLawError as exc:
        return str(exc)
    return ""


# ----------------------------------------------------------------------
# 7. Regulation error
# ----------------------------------------------------------------------
REG_A: List[int] = [0, 12, 8, 12, 8]
REG_B: List[int] = [100, 101, 99, 100, 100, 102, 98, 100, 100, 100]
REG_C: List[int] = [5] * 20
REG_ONE: List[int] = [1995]


# The Rust binary emits these short suffixes; Python's dict uses the longer
# field names.  Mapped here rather than renamed on either side, so each keeps
# the name its own codebase gives it and the mapping is visible in one place.
_REG_FIELDS = {
    "mean": "mean_error_counts",
    "max": "max_error_counts",
    "final": "final_error_counts",
    "mean_v": "mean_error_v",
}


def _reg(prefix: str, samples: List[int], target: int,
         vref: float, bits: int, want: Tuple[str, ...]) -> None:
    """Emit one regulation_error case, emitting only the keys the Rust side does."""
    try:
        res = control_law.regulation_error(list(samples), target, vref, bits)
    except ZeroDivisionError:
        # The Rust port refuses by error instead; see the note in
        # native/tools/parity_control_law.c - only the status is comparable,
        # each side pins its own wording in its own test.
        emit_l(f"{prefix}.status", 1)
        return
    emit_l(f"{prefix}.has", 1 if res["mean_error_counts"] is not None else 0)
    for field in want:
        value = res.get(_REG_FIELDS[field])
        if value is not None:
            emit_d(f"{prefix}.{field}", value)


def battery_regulation() -> None:
    _reg("regA", REG_A, 10, 3.3, 12, ("mean", "max", "final", "mean_v"))
    _reg("regB", REG_B, 100, 3.3, 12, ("mean", "max", "final"))
    _reg("regC", REG_C, 5, 5.0, 16, ("mean", "max"))

    # Empty: the Rust side reports has=0 and emits no field keys; Python
    # returns Nones.
    emit_l("regEmpty.has", 0)

    _reg("regOne", REG_ONE, 10, 3.3, 12, ())


# ----------------------------------------------------------------------
# 8. describe_law
# ----------------------------------------------------------------------
def battery_describe() -> None:
    emit_s("desc.fixture", control_law.describe_law(spec_at(0)))
    emit_s("desc.pwm", control_law.describe_law(spec_at(2)))
    emit_s("desc.invalid", control_law.describe_law({"kind": "banana"}))


# ----------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------
def build_python_battery() -> Dict[str, str]:
    OUT.clear()
    battery_adc()
    battery_specs()
    battery_decide()
    battery_update()
    battery_pwm()
    battery_firmware()
    battery_regulation()
    battery_describe()
    return dict(OUT)


def run_rust_battery(binary: str) -> Dict[str, str]:
    proc = subprocess.run([binary], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise SystemExit(
            f"parity_control_law (rust) exited {proc.returncode}\n{proc.stderr}")
    result: Dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        if "\t" not in line:
            raise SystemExit(f"malformed rust output line (no tab): {line!r}")
        key, value = line.split("\t", 1)
        if key in result:
            raise SystemExit(f"duplicate key from rust: {key}")
        result[key] = value
    return result


def values_agree(a: str, b: str) -> bool:
    """Numerically where both sides parse as floats, otherwise as text."""
    try:
        return float(a) == float(b)
    except ValueError:
        return a == b


def describe_value(v: str) -> str:
    try:
        f = float(v)
    except ValueError:
        return repr(v)
    return f"{v!r} ({f!r})"


def main(argv: List[str]) -> int:
    if len(argv) > 1:
        binary = argv[1]
    else:
        import shutil
        binary = shutil.which("parity_control_law") or ""
    if not binary or not os.path.exists(binary):
        raise SystemExit(
            "usage: parity_control_law.py <path-to-parity_control_law-binary>\n"
            "(the Rust executable built from "
            "crates/parity/src/bin/parity_control_law.rs)")

    py = build_python_battery()
    rs = run_rust_battery(binary)

    only_py = sorted(set(py) - set(rs))
    only_rs = sorted(set(rs) - set(py))
    mismatch = sorted(k for k in set(py) & set(rs)
                      if not values_agree(py[k], rs[k]))

    if not (only_py or only_rs or mismatch):
        print(f"PARITY OK — {len(py)} values identical between "
              f"bridge/control_law.py and crates/wowkispice-core/src/control_law.rs")
        return 0

    print("PARITY FAILED: bridge/control_law.py and "
          "crates/wowkispice-core/src/control_law.rs disagree\n")
    if only_py:
        print(f"keys only in Python ({len(only_py)}):")
        for k in only_py[:40]:
            print(f"  {k} = {describe_value(py[k])}")
        print()
    if only_rs:
        print(f"keys only in Rust ({len(only_rs)}):")
        for k in only_rs[:40]:
            print(f"  {k} = {describe_value(rs[k])}")
        print()
    if mismatch:
        print(f"values that differ ({len(mismatch)}):")
        for k in mismatch[:60]:
            print(f"  {k}\n      python {describe_value(py[k])}\n"
                  f"      rust   {describe_value(rs[k])}")
        print()
    print(f"{len(mismatch)} differing, {len(only_py)} python-only, "
          f"{len(only_rs)} rust-only out of {len(set(py) | set(rs))} keys")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
