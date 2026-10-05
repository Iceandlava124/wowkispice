"""
control_law.py - Executable MCU firmware behaviour for mixed-signal co-simulation.

The gap this module closes: a *declared* GPIO profile (bridge/gpio_model.py) tells
the solver "this pin is a 1 kHz square wave". That is open-loop. The pin has no
idea what the analog circuit is doing, so a regulator schematic built from
declared profiles cannot actually regulate anything - it just switches into a
divider.

A control law is different. ngspice calls back into Python at every timestep
(GetVSRCData) for any source declared `external`; the law reads the *simulated*
feedback node out of the running plot and returns the pin voltage for that
instant. The analog solver therefore sees a pin that reacts to the circuit,
which is what closed-loop co-simulation means.

What is still not claimed: the compiled .hex/.elf binary is not executed (see
bridge/firmware.py for why). What *is* real is the decision logic and its
constants - `law_from_firmware_source()` reads the ADC thresholds and gate pin
out of the actual C source, so the simulated behaviour tracks the firmware file
rather than a guess. bridge/cosim_runner.py runs the resulting loop.

Law kinds:
    hysteretic  bang-bang with hysteresis, quantised to a real ADC bit width.
                This is the classic buck/boost peak-current-mode shape and
                matches firmware/esp32_buck_controller/src/main.c.
    pwm         duty cycle proportional to regulation error, on a fixed carrier.

WHAT THIS DOES NOT MODEL, AND WHY IT IS NOT A BUG

firmware/esp32_buck_controller/src/main.c does four things this law does not.
They are listed here, loudly, because the alternative is a simulation that
stays plausible and green while being quietly wrong.

  1. ADC_OVERSAMPLE_N = 16. It averages 16 reads per decision to suppress
     noise comparable to the hysteresis band. Deliberately NOT modelled: those
     16 reads are microseconds apart in real time, while solver timesteps here
     are sub-microsecond, so "average the last 16 samples" has no defensible
     analogue in this loop. Modelling it as a filter would be a guess dressed
     as physics. What it means in practice: the modelled loop switches more
     often than the firmware would.
  2. adc_cali line-fitting calibration. The firmware converts raw counts to
     millivolts through eFuse calibration, and configures ADC_ATTEN_DB_12
     (about 0-3.1 V usable, not 3.3 V). This law assumes a flat
     counts = volts/vref*full_scale mapping with vref = 3.3 V. On real silicon
     the calibration curve is neither flat nor exactly 3.3 V, so the modelled
     thresholds are a good first approximation and nothing more.
  3. The attenuation setting itself is not read from the source.
  4. ESP_ERROR_CHECK guards on init failure have no counterpart.

tests/test_cosim_control.py pins this gap deliberately: TestFidelityGap asserts
that main.c still declares ADC_OVERSAMPLE_N and still calls adc_cali. If someone
removers oversampling or calibration from the firmware, that test fails and
forces this section to be revisited - which is the point. A fidelity gap nobody
can notice is how a model rots.

Spec (JSON, per MCU):
    {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
     "target_v": 3.3, "hysteresis_v": 0.04, "divider": 0.5,
     "vhigh": 3.3, "vref": 3.3, "adc_bits": 12}

`divider` is the attenuation from the **sense net to the ADC pin**, so
`v_pin = sense_net * divider`. `adc_bits`/`vref` quantise the read exactly as a
real ADC would, so the modelled thresholds are counts, not float volts.

WHICH NET IS `sense_net`? THIS IS THE WHOLE BALLGAME.

The firmware's `#define ADC_LOW_THRESHOLD 1995` / `ADC_HIGH_THRESHOLD 2030`
are **raw counts measured at the ADC pin**, and its own comment says so:
"these are RAW counts, not millivolts ... the decision below is still made on
the raw value". The divider is already reflected in them, because the pin only
ever sees the divided voltage. Arithmetic, for the 2:1 divider in
circuits/buck_converter.cir:

    mid count 2012.5 / 4095 * 3.3 V = 1.6218 V at the pin
    1.6218 V * 2                    = 3.2436 V at vout   (firmware says 3.24 V)

So the correct `divider` is 1.0 **when `sense_net` is the divider output**
(the node the ADC pin is wired to). Passing the undivided output node as
`sense_net` and leaving `divider=1.0` is not a rounding error, it regulates to
1.62 V instead of 3.24 V: exactly the divider ratio, silently. `implied_
output_voltages()` exists so a caller can check before trusting a run.
"""

import math
import os
import re
from typing import Dict, List, Optional, Tuple

DEFAULT_VHIGH = 3.3
DEFAULT_VREF = 3.3
DEFAULT_ADC_BITS = 12
LAW_KINDS = ("hysteretic", "pwm")


class ControlLawError(ValueError):
    """Raised when a control law spec or firmware source cannot be used."""


# ----------------------------------------------------------------------
# Spec normalisation
# ----------------------------------------------------------------------
def normalize_law(spec: Optional[Dict[str, object]]) -> Dict[str, object]:
    """
    Fill defaults and reject nonsense so callers never guard twice.

    Returns a new dict; never mutates the input.
    """
    spec = dict(spec or {})
    kind = str(spec.get("kind", "hysteretic")).lower()
    if kind not in LAW_KINDS:
        raise ControlLawError(
            f"unsupported law kind '{kind}' (use {' or '.join(LAW_KINDS)})")

    pin = str(spec.get("pin", "")).strip()
    if not pin:
        raise ControlLawError("law needs a 'pin' naming the MCU output pin")
    sense_net = str(spec.get("sense_net", "")).strip()
    if not sense_net:
        raise ControlLawError(
            f"law for {pin} needs a 'sense_net' - the analog net the firmware "
            f"reads back (e.g. 'vout')")

    vhigh = float(spec.get("vhigh", DEFAULT_VHIGH))
    if not 0 < vhigh <= 24:
        raise ControlLawError(f"vhigh must be 0..24 V, got {vhigh}")
    vref = float(spec.get("vref", DEFAULT_VREF))
    if not 0 < vref <= 24:
        raise ControlLawError(f"vref must be 0..24 V, got {vref}")

    adc_bits = int(spec.get("adc_bits", DEFAULT_ADC_BITS))
    if not 8 <= adc_bits <= 24:
        raise ControlLawError(f"adc_bits must be 8..24, got {adc_bits}")

    divider = float(spec.get("divider", 1.0))
    if not 0 < divider <= 1:
        raise ControlLawError(f"divider must be in (0, 1], got {divider}")

    target_v = float(spec.get("target_v", 3.3))
    if target_v <= 0:
        raise ControlLawError(f"target_v must be > 0, got {target_v}")

    out: Dict[str, object] = {
        "kind": kind, "pin": pin, "sense_net": sense_net,
        "target_v": target_v, "vhigh": vhigh, "vref": vref,
        "adc_bits": adc_bits, "divider": divider,
    }

    if kind == "hysteretic":
        hyst = float(spec.get("hysteresis_v", 0.04))
        if hyst <= 0:
            raise ControlLawError(f"hysteresis_v must be > 0, got {hyst}")
        if hyst >= target_v:
            raise ControlLawError(
                f"hysteresis_v ({hyst}) must be smaller than target_v ({target_v})")
        out["hysteresis_v"] = hyst
        # Counts the firmware actually compares against, so the law and the
        # netlist comment agree with the solver's own quantisation. Explicit
        # counts win: that is how a spec imported from firmware source keeps
        # the file's exact decision boundary.
        low = spec.get("low_counts")
        high = spec.get("high_counts")
        if low is None or high is None:
            low = _to_counts((target_v - hyst) * divider, vref, adc_bits)
            high = _to_counts((target_v + hyst) * divider, vref, adc_bits)
        low, high = int(low), int(high)
        if low >= high:
            raise ControlLawError(
                f"threshold counts must increase, got low={low} high={high}")
        out["low_counts"] = low
        out["high_counts"] = high
    else:
        freq = float(spec.get("carrier_hz", 20000.0))
        if freq <= 0:
            raise ControlLawError(f"carrier_hz must be > 0, got {freq}")
        gain = float(spec.get("duty_gain", 0.25))
        if gain <= 0:
            raise ControlLawError(f"duty_gain must be > 0, got {gain}")
        out["carrier_hz"] = freq
        out["duty_gain"] = gain

    if spec.get("source") is not None:
        out["source"] = str(spec["source"])
    return out


def _to_counts(volts: float, vref: float, bits: int) -> int:
    """Volts -> ADC counts, clipped to the converter's full scale."""
    full = (1 << bits) - 1
    return max(0, min(full, int(round(volts / vref * full))))


# ----------------------------------------------------------------------
# The executable law
# ----------------------------------------------------------------------
class ControlLaw:
    """
    Base law. Subclasses implement `decide()`, which maps one simulated
    feedback sample to a logic level; this class owns the ADC front end, the
    telemetry, and the state a caller needs to report a run honestly.
    """

    def __init__(self, spec: Optional[Dict[str, object]]):
        self.spec = normalize_law(spec)
        self.pin: str = str(self.spec["pin"])
        self.sense_net: str = str(self.spec["sense_net"])
        self.vhigh: float = float(self.spec["vhigh"])
        self.divider: float = float(self.spec["divider"])
        self.vref: float = float(self.spec["vref"])
        self.adc_bits: int = int(self.spec["adc_bits"])
        self.level: bool = False
        self.switch_count: int = 0
        self.history_time: List[float] = []
        self.history_pin: List[float] = []
        self.history_counts: List[int] = []

    # -- front end ----------------------------------------------------
    @property
    def full_scale(self) -> int:
        return (1 << self.adc_bits) - 1

    def to_counts(self, sense_v: float) -> int:
        """Sense node -> ADC counts, including the divider and clipping."""
        feedback = sense_v * self.divider
        return _to_counts(feedback, self.vref, self.adc_bits)

    # -- to be provided by subclasses ---------------------------------
    def decide(self, counts: int) -> bool:
        raise NotImplementedError

    # -- the callback ngspice calls ------------------------------------
    def update(self, sense_v: float, time_s: float = 0.0) -> float:
        """
        One solver timestep. Returns the pin voltage for this instant and
        records telemetry for the run report.
        """
        counts = self.to_counts(sense_v)
        previous = self.level
        self.level = bool(self.decide(counts))
        if self.level != previous:
            self.switch_count += 1
        self.history_time.append(float(time_s))
        self.history_counts.append(int(counts))
        self.history_pin.append(self.vhigh if self.level else 0.0)
        return self.history_pin[-1]

    # -- reporting ----------------------------------------------------
    def describe(self) -> str:
        raise NotImplementedError

    def stats(self) -> Dict[str, object]:
        """Run summary; identical shape for every law kind so callers can print it."""
        samples = len(self.history_pin)
        midpoint = self.vhigh / 2.0
        high = sum(1 for v in self.history_pin if v > midpoint)
        return {
            "kind": self.spec["kind"],
            "pin": self.pin,
            "sense_net": self.sense_net,
            "samples": samples,
            "switches": self.switch_count,
            "duty": (high / samples) if samples else 0.0,
            "counts_min": min(self.history_counts) if samples else None,
            "counts_max": max(self.history_counts) if samples else None,
            "counts_last": self.history_counts[-1] if samples else None,
            "final_level": "HIGH" if self.level else "LOW",
        }


class HystereticLaw(ControlLaw):
    """
    Bang-bang with hysteresis, compared in ADC counts.

        if counts <  low_counts:  drive HIGH   (charge the inductor)
        if counts >  high_counts: drive LOW    (freewheel through the diode)
        otherwise:                 hold previous state

    Holding the previous state inside the band is what makes it hysteretic
    rather than chattering, and it is literally the structure of the firmware
    in firmware/esp32_buck_controller/src/main.c.
    """

    def __init__(self, spec: Optional[Dict[str, object]]):
        super().__init__(spec)
        self.low_counts = int(self.spec["low_counts"])
        self.high_counts = int(self.spec["high_counts"])

    def decide(self, counts: int) -> bool:
        if counts < self.low_counts:
            return True
        if counts > self.high_counts:
            return False
        return self.level

    def describe(self) -> str:
        return (f"hysteretic on {self.sense_net}: HIGH below {self.low_counts} counts, "
                f"LOW above {self.high_counts} counts, hold in between "
                f"(target {self.spec['target_v']:g} V via {self.divider:g}x divider)")


class PwmLaw(ControlLaw):
    """
    Duty proportional to regulation error on a fixed carrier.

    Saturates to 0% or 100% outside the error band, so an out-of-range feedback
    reading produces a definite output rather than a small wiggle.
    """

    def __init__(self, spec: Optional[Dict[str, object]]):
        super().__init__(spec)
        self.carrier_hz = float(self.spec["carrier_hz"])
        self.duty_gain = float(self.spec["duty_gain"])
        self.target_counts = _to_counts(
            float(self.spec["target_v"]) * self.divider, self.vref, self.adc_bits)
        self.duty = 0.0

    def decide(self, counts: int) -> bool:
        error = (self.target_counts - counts) / max(1, self.target_counts)
        self.duty = max(0.0, min(1.0, error * self.duty_gain))
        period = 1.0 / self.carrier_hz
        phase = (self.history_time[-1] if self.history_time else 0.0) % period
        return phase < self.duty * period

    def describe(self) -> str:
        return (f"PWM on {self.sense_net}: {self.carrier_hz:g} Hz carrier, "
                f"duty = min(1, gain {self.duty_gain:g} x error toward "
                f"{self.spec['target_v']:g} V)")


def make_law(spec: Optional[Dict[str, object]]) -> ControlLaw:
    """Build the right ControlLaw subclass for a (raw or normalized) spec."""
    normalized = normalize_law(spec)
    if normalized["kind"] == "hysteretic":
        return HystereticLaw(normalized)
    return PwmLaw(normalized)


# ----------------------------------------------------------------------
# Firmware import
# ----------------------------------------------------------------------
# Constants of the form `#define ADC_HIGH_THRESHOLD 2030` and
# `#define GATE_PIN            GPIO_NUM_18`.
_DEFINE_RE = re.compile(
    r"^\s*#define\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+(?P<value>[^\r\n/]+)",
    re.MULTILINE)

_ALIASES = {
    "ADC_LOW_THRESHOLD": "low",
    "ADC_HIGH_THRESHOLD": "high",
    "GATE_PIN": "pin",
}


def _parse_int(text: str) -> Optional[int]:
    """Accept plain decimals and the GPIO_NUM_n / ADC1_CHANNEL_n spellings."""
    m = re.search(r"(\d+)\s*$", text)
    return int(m.group(1)) if m else None


def read_firmware_constants(path: str) -> Dict[str, object]:
    """
    Pull the ADC thresholds and gate pin out of a C firmware source.

    Returns {"low": int, "high": int, "pin": "GPIO18"} for whatever was found.
    Raises ControlLawError if the file is missing or holds none of the names -
    we would rather say so than silently simulate a made-up controller.
    """
    if not os.path.exists(path):
        raise ControlLawError(f"firmware source not found: {path}")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as exc:
        raise ControlLawError(f"cannot read firmware source {path}: {exc}")

    found: Dict[str, object] = {}
    for match in _DEFINE_RE.finditer(text):
        slot = _ALIASES.get(match.group("name"))
        if slot is None:
            continue
        value = _parse_int(match.group("value"))
        if value is None:
            continue
        found[slot] = f"GPIO{value}" if slot == "pin" else value

    missing = [k for k in ("low", "high", "pin") if k not in found]
    if missing:
        raise ControlLawError(
            f"{os.path.basename(path)} has no {'/'.join(missing)} constant; "
            f"expected #define ADC_LOW_THRESHOLD / ADC_HIGH_THRESHOLD / GATE_PIN")
    if found["low"] >= found["high"]:
        raise ControlLawError(
            f"nonsense thresholds in {os.path.basename(path)}: "
            f"ADC_LOW_THRESHOLD ({found['low']}) >= ADC_HIGH_THRESHOLD ({found['high']})")
    return found


def law_from_firmware_source(
    path: str,
    sense_net: str,
    divider: float = 1.0,
    vhigh: float = DEFAULT_VHIGH,
    vref: float = DEFAULT_VREF,
    adc_bits: int = DEFAULT_ADC_BITS,
) -> Dict[str, object]:
    """
    Build a control-law spec from a real firmware C source.

    The thresholds in that firmware are already *scaled* counts (its comments
    state the divider is folded in), so the returned spec uses divider=1.0 by
    default: the counts are compared directly, exactly as the firmware does.

    Pass `divider` only when `sense_net` is NOT the net the ADC pin samples —
    i.e. when it is the undivided output and the pin sees it attenuated. The
    derived target and hysteresis are then reported in that net's units, and
    dividing `sense_net="fb"` by 1.0 must reproduce the firmware's own counts.
    """
    consts = read_firmware_constants(path)
    full = (1 << adc_bits) - 1
    low, high = int(consts["low"]), int(consts["high"])

    # Recover the output-target scale factor from the source's own numbers so
    # the reported target is the real one, not a round-number guess.
    midpoint = (low + high) / 2.0 / full * vref
    half_band = abs(high - low) / 2.0 / full * vref
    # A non-unit divider means the caller pointed us at an undivided net, so
    # BOTH the target and the band move to that net's scale. Scaling only the
    # target left hysteresis_v in pin volts; normalize_law then multiplies both
    # by divider again, so the target survived and the band was halved.
    target_v = midpoint / divider if divider else midpoint
    hysteresis_v = half_band / divider if divider else half_band

    return {
        "kind": "hysteretic",
        "pin": str(consts["pin"]),
        "sense_net": sense_net,
        "target_v": round(target_v, 4),
        "hysteresis_v": round(hysteresis_v, 4),
        "vhigh": vhigh,
        "vref": vref,
        "adc_bits": adc_bits,
        "divider": divider,
        # Preserve the source numbers verbatim; normalize_law recomputes
        # low/high counts from target/hysteresis, and the recovered target is a
        # rational fraction that must not drift.
        "source": os.path.basename(path),
        "source_counts": {"low": low, "high": high},
    }


def law_from_firmware_source_exact(
    path: str,
    sense_net: str,
    divider: float = 1.0,
    vhigh: float = DEFAULT_VHIGH,
    vref: float = DEFAULT_VREF,
    adc_bits: int = DEFAULT_ADC_BITS,
) -> Dict[str, object]:
    """
    As law_from_firmware_source(), but pins the counts to the file's own
    integers instead of a round-trip through volts, so what the solver sees is
    bit-for-bit the firmware's decision boundary.

    `divider` stays 1.0 for a pin-referenced sense net. Pass the attenuation
    from sense_net to the ADC pin (0.5 for a 100k/100k divider) ONLY when
    sense_net is the undivided output node.
    """
    spec = law_from_firmware_source(path, sense_net, divider, vhigh, vref, adc_bits)
    spec["low_counts"] = int(spec["source_counts"]["low"])
    spec["high_counts"] = int(spec["source_counts"]["high"])
    return spec


# ----------------------------------------------------------------------
# Divider sanity check
# ----------------------------------------------------------------------
def implied_pin_voltages(spec: Dict[str, object]) -> Tuple[float, float]:
    """Voltages the ADC pin must see to cross the low and high thresholds.

    Inverts the same pin-referenced mapping the firmware uses, so this is the
    direct statement of what the constants in the C file mean physically.
    """
    normalized = normalize_law(spec)
    vref = float(normalized["vref"])
    full = float((1 << int(normalized["adc_bits"])) - 1)
    return (float(normalized["low_counts"]) / full * vref,
            float(normalized["high_counts"]) / full * vref)


def implied_output_voltages(spec: Dict[str, object],
                            pin_divider: float = 1.0) -> Tuple[float, float]:
    """What the schematic's output node will be regulated to.

    `pin_divider` is the schematic's pin-to-output attenuation (0.5 for the
    100k/100k divider in circuits/buck_converter.cir). Call this before
    trusting a run: if `spec["sense_net"]` is the undivided output node rather
    than the divider output, the returned numbers are half what you expect, and
    that is the signature of a mis-wired sense net rather than a bad circuit.
    """
    lo, hi = implied_pin_voltages(spec)
    if pin_divider <= 0:
        raise ControlLawError(f"pin_divider must be > 0, got {pin_divider}")
    return (lo / pin_divider, hi / pin_divider)


def describe_law(spec: Optional[Dict[str, object]]) -> str:
    """One-line human description; never raises, for console display."""
    try:
        return make_law(spec).describe()
    except (ControlLawError, KeyError, TypeError, ValueError) as exc:
        return f"<invalid control law: {exc}>"


# ----------------------------------------------------------------------
# Per-run performance metric
# ----------------------------------------------------------------------
def regulation_error(
    count_samples: List[int],
    target_counts: int,
    vref: float = DEFAULT_VREF,
    adc_bits: int = DEFAULT_ADC_BITS,
) -> Dict[str, Optional[float]]:
    """
    Steady-state regulation error of a run, in ADC counts and in volts.

    Operates on the samples already in counts space (the law's own ADC view),
    so no volts<->counts round trip can smear the measurement. Ignores the first
    fifth of the samples: an inductor charging from zero is start-up, not
    regulation error.
    """
    if not count_samples:
        return {"mean_error_counts": None, "max_error_counts": None,
                "mean_error_v": None, "final_error_counts": None}
    tail = count_samples[max(1, len(count_samples) // 5):]
    errors = [c - target_counts for c in tail]
    lsb_v = vref / max(1, (1 << adc_bits) - 1)
    return {
        "mean_error_counts": sum(errors) / len(errors),
        "max_error_counts": max(abs(e) for e in errors),
        "mean_error_v": sum(errors) / len(errors) * lsb_v,
        "final_error_counts": tail[-1] - target_counts,
    }