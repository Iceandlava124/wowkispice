"""
gpio_model.py - Digital GPIO behaviour for mixed-signal co-simulation.

An MCU pin becomes a real independent voltage source in the SPICE netlist, so
the analog solver sees real switching voltages instead of a comment line. What
that voltage does is declared by a *pin profile* (JSON), not extracted by
executing the binary - see bridge/firmware.py for why we say so plainly.

Profile spec (per pin):
    {"mode": "static", "level": 1,                 "vhigh": 3.3}
    {"mode": "square", "freq_hz": 1000, "duty": 0.5, "vhigh": 3.3}
    {"mode": "square", "freq_hz": 10,  "duty": 0.02, "vhigh": 5.0, "phase_s": 0.001}

Everything downstream (netlist generation, the GPIO inspector, tests) works off
the same spec, so the UI can never show a behaviour the solver did not get.
"""

from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_VHIGH = 3.3
DEFAULT_THRESHOLD = 1.65      # logic midpoint of a 3.3 V pin


def normalize_profile(spec: Optional[Dict[str, object]]) -> Dict[str, object]:
    """Fill in defaults and reject nonsense, so callers never guard twice."""
    spec = dict(spec or {})
    mode = str(spec.get("mode", "static")).lower()
    if mode not in ("static", "square"):
        raise ValueError(f"unsupported GPIO mode '{mode}' (use 'static' or 'square')")

    vhigh = float(spec.get("vhigh", DEFAULT_VHIGH))
    if not 0 < vhigh <= 24:
        raise ValueError(f"vhigh must be 0..24 V, got {vhigh}")

    out: Dict[str, object] = {"mode": mode, "vhigh": vhigh}
    if mode == "static":
        out["level"] = 1 if int(spec.get("level", 0)) else 0
    else:
        freq = float(spec.get("freq_hz", 1.0))
        duty = float(spec.get("duty", 0.5))
        if freq <= 0:
            raise ValueError(f"freq_hz must be > 0, got {freq}")
        if not 0.0 < duty <= 1.0:
            raise ValueError(f"duty must be in (0, 1], got {duty}")
        out["freq_hz"] = freq
        out["duty"] = duty
        out["phase_s"] = float(spec.get("phase_s", 0.0))
    return out


def spice_card(spec: Optional[Dict[str, object]], edge_time: float = 1e-7) -> str:
    """
    SPICE source card for a GPIO pin.

    static -> "DC 3.3"
    square -> "PULSE(0 3.3 0 100n 100n 500u 1m)"  (tr, tf, on-time, period)
    """
    s = normalize_profile(spec)
    vhigh = s["vhigh"]
    if s["mode"] == "static":
        return f"DC {vhigh:g}" if s["level"] else "DC 0"

    period = 1.0 / float(s["freq_hz"])
    on_time = period * float(s["duty"])
    # Keep edges fast relative to the period but sane on CPU ngspice
    tr = min(edge_time, period / 20.0)
    return f"PULSE(0 {vhigh:g} {float(s['phase_s']):g} {tr:g} {tr:g} {on_time:g} {period:g})"


def is_output_pin(profile: Optional[Dict[str, object]]) -> bool:
    return True      # every declared pin drives its net


def logic_levels(times: Sequence[float], values: Sequence[float],
                 threshold: float = DEFAULT_THRESHOLD) -> List[Tuple[float, bool]]:
    """
    Reduce a sampled pin waveform to (time, level) transitions.

    Returns only transitions plus the initial state, which is what a GPIO
    inspector should show rather than 10k samples.
    """
    if len(times) != len(values) or not times:
        return []
    level = values[0] >= threshold
    transitions = [(float(times[0]), level)]
    for t, v in zip(times[1:], values[1:]):
        new_level = v >= threshold
        if new_level != level:
            transitions.append((float(t), new_level))
            level = new_level
    return transitions


def analyze_pin(times: Sequence[float], values: Sequence[float],
                threshold: float = DEFAULT_THRESHOLD) -> Dict[str, object]:
    """
    Per-pin summary: logic levels, transition count, duty cycle, min/max level.

    Duty is the fraction of the observed window spent above the threshold.
    """
    if len(times) != len(values) or len(times) < 2:
        return {"points": len(values), "transitions": 0, "duty": 0.0,
                "v_min": None, "v_max": None, "levels": []}

    transitions = logic_levels(times, values, threshold)
    high_time = 0.0
    for i in range(len(transitions) - 1):
        if transitions[i][1]:
            high_time += transitions[i + 1][0] - transitions[i][0]
    window = float(times[-1]) - float(times[0])
    duty = (high_time / window) if window > 0 else 0.0

    return {
        "points": len(values),
        "transitions": max(0, len(transitions) - 1),
        "duty": duty,
        "v_min": float(min(values)),
        "v_max": float(max(values)),
        "levels": transitions,
    }


def measured_frequency(times: Sequence[float], values: Sequence[float],
                       threshold: float = DEFAULT_THRESHOLD) -> Optional[float]:
    """Frequency in Hz from rising edges, or None if fewer than two."""
    transitions = logic_levels(times, values, threshold)
    rises = [t for i, (t, level) in enumerate(transitions)
             if level and (i == 0 or not transitions[i - 1][1])]
    if len(rises) < 2:
        return None
    period = sum(b - a for a, b in zip(rises, rises[1:])) / (len(rises) - 1)
    return 1.0 / period if period > 0 else None


def describe_pin(pin: str, spec: Dict[str, object]) -> str:
    """One-line human description of a pin's declared behaviour."""
    s = normalize_profile(spec)
    if s["mode"] == "static":
        return f"{pin}: {'HIGH' if s['level'] else 'LOW'} @ {s['vhigh']:g} V"
    return (f"{pin}: square {float(s['freq_hz']):g} Hz, "
            f"{float(s['duty']) * 100:.0f}% duty @ {s['vhigh']:g} V")


# Pins that are supply or ground rather than signal.
_POWER_PINS = frozenset({"GND", "0", "gnd", "VCC", "5V", "3V3", "VIN", "VCC3V3",
                        "AREF", "NRST", "EN"})
_ANALOG_PINS = ("A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7")


def pin_direction(pin: str) -> str:
    """
    Best-effort pin direction from its name.

    Heuristic, and labelled as such: only the device datasheet knows for sure.
    Anything ambiguous is reported as "bidirectional" rather than guessed
    confidently, because a wrong 'output' on an input pin makes a pin-mapping
    view actively misleading.
    """
    p = str(pin or "").upper()
    if p in _POWER_PINS:
        return "power"
    if p.startswith("A") and p[1:].isdigit():          # Arduino analog pins
        return "analog"
    if p.startswith("ADC"):
        return "analog"
    if p.startswith(("D", "GPIO", "PA", "PB", "PC", "PD", "PE", "PF", "PG", "PH",
                     "LED", "SCL", "SDA", "TX", "RX", "SCK", "MOSI", "MISO")):
        return "bidirectional"
    return "bidirectional"


def pin_map(model, comp_id: str,
            gpio_profiles: Dict[str, Dict[str, object]],
            control_laws: Optional[Dict[str, object]] = None) -> List[Dict[str, object]]:
    """
    Per-pin view of an MCU: what it is, what drives it, what it reads.

    This is the panel behind "pin mapping shown visually". It reports only what
    the document actually declares - an unwired pin is listed as such rather
    than omitted, so a missing wire is visible instead of invisible.
    """
    comp = model.components.get(comp_id)
    if comp is None:
        return []
    from bridge.cad_engine import is_mcu
    if not is_mcu(comp.comp_type):
        return []

    profile = (gpio_profiles or {}).get(comp_id, {})
    law = (control_laws or {}).get(comp_id, {})
    law_pin = law.get("pin") if isinstance(law, dict) else None
    net_of, _ground = model._resolve_nets()

    rows: List[Dict[str, object]] = []
    for pin in sorted(comp.pins):
        net = net_of.get((comp_id, pin))
        direction = pin_direction(pin)
        spec = profile.get(pin)
        if pin == law_pin:
            role = "closed-loop control output"
            behaviour = f"control law reading '{law.get('sense_net')}'"
        elif direction == "power":
            role = "power"
            behaviour = "ground / supply rail" if net == "0" else f"rail on net {net}"
        elif spec:
            role = "output"
            behaviour = describe_pin(pin, spec)
        else:
            role = "declared but undriven"
            behaviour = "no GPIO profile - idles LOW in simulation"
        rows.append({
            "pin": pin,
            "net": net,
            "direction": direction,
            "role": role,
            "behaviour": behaviour,
            "wired": net is not None,
        })
    return rows