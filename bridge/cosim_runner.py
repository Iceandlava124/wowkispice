"""
cosim_runner.py - Closed-loop mixed-signal co-simulation run harness.

Runs a schematic in ngspice while one or more MCU control laws drive `external`
voltage sources in lockstep with the solver. The law reads its sense net out of
the live plot on every callback, so the pin reacts to the circuit instead of
playing back a declared waveform.

Sequence per callback (ngspice GetVSRCData):
    1. read the sense net's most recently accepted sample
    2. hand it to the law (ADC quantisation + decision)
    3. return the pin voltage for this instant

Everything reported here comes out of the solver that actually ran. If a law
never fired, or a sense net was missing, the run says so in `warnings` rather
than reporting a tidy-looking zero.
"""

import os
import re
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import control_law
from bridge.control_law import ControlLaw, ControlLawError, make_law
from bridge.ngspice_wrapper import NgSpiceEngine


def _safe(name: str) -> str:
    """Identifier scrubber, matching SchematicNetlistEngine._safe."""
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


class CosimRun:
    """Result of one co-simulation run."""

    def __init__(self):
        self.time: List[float] = []
        self.traces: Dict[str, List[float]] = {}
        self.laws: Dict[str, ControlLaw] = {}        # pin -> executed law
        self.netlist: List[str] = []
        self.nets: List[str] = []
        self.warnings: List[str] = []
        self.callback_hits: int = 0
        self.aborted: bool = False

    # -- convenience views for the UI / tests --------------------------
    def pin_trace(self, pin: str) -> List[float]:
        law = self.laws.get(pin)
        return list(law.history_pin) if law else []

    def regulation(self, pin: str) -> Dict[str, Optional[float]]:
        """Steady-state error of a pin's loop, in ADC counts and volts."""
        law = self.laws.get(pin)
        if law is None or not law.history_counts:
            return {"mean_error_counts": None, "max_error_counts": None,
                    "mean_error_v": None, "final_error_counts": None}
        target = _midpoint_counts(law)
        return control_law.regulation_error(
            law.history_counts, target,
            vref=float(law.spec["vref"]), adc_bits=law.adc_bits)

    def stats(self) -> List[Dict[str, object]]:
        return [law.stats() for law in self.laws.values()]

    def summary_lines(self) -> List[str]:
        """Human report, one block per pin plus an overall verdict."""
        out: List[str] = []
        for pin, law in self.laws.items():
            s = law.stats()
            reg = self.regulation(pin)
            out.append(
                f"{pin} <- {law.sense_net}: {s['samples']} samples, "
                f"{s['switches']} switch events, duty {float(s['duty']) * 100:.1f}%, "
                f"ADC {s['counts_min']}..{s['counts_max']} counts, "
                f"final {s['final_level']}")
            mean = reg["mean_error_counts"]
            if mean is not None:
                out.append(
                    f"    regulation error: mean {mean:+.1f} counts "
                    f"({float(reg['mean_error_v']):+.4f} V), "
                    f"max |{float(reg['max_error_counts']):.0f}| counts")
        for w in self.warnings:
            out.append("warning: " + w)
        return out


def _midpoint_counts(law: ControlLaw) -> int:
    """Target count for a law, from whichever spec form it carries."""
    if "low_counts" in law.spec and "high_counts" in law.spec:
        return (int(law.spec["low_counts"]) + int(law.spec["high_counts"])) // 2
    from bridge.control_law import _to_counts
    return _to_counts(float(law.spec["target_v"]) * law.divider,
                      float(law.spec["vref"]), law.adc_bits)


def run_cosim(
    model,
    laws: Dict[str, Dict[str, object]],
    vin: float = 12.0,
    tstep_us: float = 0.5,
    duration_ms: float = 5.0,
    engine: Optional[NgSpiceEngine] = None,
    probe_nets: Optional[List[str]] = None,
    progress_callback=None,
    stop_flag=None,
) -> CosimRun:
    """
    Compile `model`, execute the netlist, and drive each entry of `laws`.

    `laws` maps an MCU pin name to a control-law spec. Every pin in it must be a
    wired MCU output pin that the netlist emitted as an `external` source;
    anything else is reported in `run.warnings`.

    `progress_callback(sim_time_s, steps)` is called on every accepted timestep.
    `stop_flag()` is polled the same way; returning True ends the run early and
    the partial result is still returned.
    """
    run = CosimRun()

    lines, nets, netlist_warnings = model.compile_netlist(
        vin=vin, tstep_us=tstep_us, duration_ms=duration_ms)
    run.netlist = list(lines)
    run.nets = list(probe_nets if probe_nets is not None else nets)
    run.warnings.extend(netlist_warnings)

    # Build the laws first: a bad spec must fail before we spend time solving.
    executables: Dict[str, ControlLaw] = {}
    for pin, spec in laws.items():
        try:
            executables[pin] = make_law(spec)
        except ControlLawError as exc:
            run.warnings.append(f"control law for {pin} rejected: {exc}")
    run.laws = executables

    if not executables:
        run.warnings.append("no executable control law; nothing was closed-loop")
        return run

    _check_laws_against_netlist(model, executables, run)

    if engine is None:
        try:
            engine = NgSpiceEngine(verbose=False)
        except Exception as exc:
            run.warnings.append(f"cannot start ngspice: {exc}")
            return run

    # No `quit` here: sharedspice is a process-wide singleton and quitting it
    # breaks every later NgSpiceEngine in this process.
    try:
        state = {"hits": 0}
        sense_map = {pin: law.sense_net for pin, law in executables.items()}

        def sense(net: str) -> float:
            """
            Latest accepted sample of a node, 0.0 before it exists.

            Reads the single element straight out of ngspice's C buffer. Going
            through get_vector_array() would copy the entire vector on every
            one of the tens of thousands of callbacks a transient run makes,
            turning the loop into O(n^2).
            """
            ptr = engine.lib.ngGet_Vec_Info(net.encode("utf-8"))
            if not ptr:
                ptr = engine.lib.ngGet_Vec_Info(f"v({net})".encode("utf-8"))
            if not ptr:
                return 0.0
            info = ptr.contents
            if info.v_length <= 0 or not info.v_realdata:
                return 0.0
            return float(info.v_realdata[info.v_length - 1])

        def callback(time_s: float, source_name: str) -> float:
            """
            ngspice GetVSRCData. `source_name` is the SPICE designator of the
            `external` source being evaluated; map it back to the pin that owns
            it so several MCUs can co-simulate in one run.
            """
            state["hits"] += 1
            pin = _pin_for_source(model, source_name)
            law = executables.get(pin)
            if law is None:                       # unknown external source
                return 0.0
            return law.update(sense(sense_map[pin]), time_s)

        engine.set_vsrc_callback(callback)
        # Progress and abort are combined into one hook: passing both
        # separately used to silently drop the progress callback.
        if progress_callback is not None or stop_flag is not None:
            def hook(t, n):
                if progress_callback is not None:
                    progress_callback(t, n)
                if stop_flag is not None and stop_flag():
                    engine.request_stop()
            engine.progress_callback = hook
        engine.load_circuit(run.netlist)
        engine.cmd("run")
        run.callback_hits = state["hits"]
        run.aborted = bool(getattr(engine, "_stop_requested", False))

        run.time = engine.get_vector_array("time")
        for net in run.nets:
            values = engine.get_vector_array(net)
            if values:
                run.traces[net] = values

        for pin, law in executables.items():
            if not law.history_counts:
                run.warnings.append(
                    f"{pin}: control law never ran (no `external` source matched); "
                    f"check the pin is wired and the MCU emits it")
            if not run.time:
                run.warnings.append("ngspice produced no time vector")
    except Exception as exc:
        run.warnings.append(f"closed-loop run failed: {exc}")

    return run


def _check_laws_against_netlist(model, laws: Dict[str, ControlLaw], run: CosimRun):
    """Warn when a declared law has no matching `external` source card."""
    external_cards = set()
    for line in run.netlist:
        stripped = line.strip()
        if stripped and not stripped.startswith("*") and "external" in stripped.lower():
            external_cards.add(stripped.split()[0].upper())
    if not external_cards:
        run.warnings.append(
            "netlist has no `external` source, so no law can be driven; "
            "attach a control law to a wired MCU pin")
        return
    for pin in laws:
        designator = designator_for_pin(model, pin)
        # A pin may be part of a joint wire (e.g. "GPIO18,S1:CTRL"), in which
        # case the netlister emits the joint label as the source designator
        # ("VU1_GPIO18_S1_CTRL") while designator_for_pin returns only the
        # individual pin ("VU1_GPIO18"). Match a declared law against the
        # designator when it is a strict prefix of an external card.
        matched = any(
            designator.upper() == card or card.startswith(designator.upper() + "_")
            for card in external_cards
        )
        if designator and not matched:
            run.warnings.append(
                f"{pin}: netlist has no `external` source for {designator}; "
                f"the pin is probably unwired")


def designator_for_pin(model, pin: str) -> str:
    """
    The SPICE source designator the netlister assigns to an MCU pin.

    Mirrors SchematicNetlistEngine._emit_mcu: "V<safe(comp_id)>_<safe(pin)>".
    Returns "" when no MCU owns a pin with that name.
    """
    from bridge.cad_engine import is_mcu
    for comp in model.components.values():
        if not is_mcu(comp.comp_type):
            continue
        if pin in comp.pins:
            return f"V{_safe(comp.comp_id)}_{_safe(pin)}"
    return ""


def _pin_for_source(model, source_name: str) -> str:
    """
    Map an SPICE designator back to the MCU pin that emitted it.

    ngspice hands the designator to GetVSRCData lowercased ('vu1_gpio18'), so
    every comparison here is case-insensitive.
    """
    from bridge.cad_engine import is_mcu
    name = (source_name or "").strip().lstrip("v")   # strip the type letter only
    if not name:
        return ""
    body = name.upper()
    for comp in model.components.values():
        if not is_mcu(comp.comp_type):
            continue
        prefix = _safe(comp.comp_id).upper()
        if body.startswith(prefix + "_"):
            pin = body[len(prefix) + 1:]
            for declared in comp.pins:
                if _safe(declared).upper() == pin:
                    return declared
    return ""


def describe_run(run: CosimRun) -> str:
    """Multi-line console report for a co-simulation run."""
    header = (f"Closed-loop run: {len(run.time)} points, "
              f"{run.callback_hits} control callbacks, "
              f"{len(run.laws)} law(s)")
    return "\n".join([header] + run.summary_lines())


def run_firmware_cosim(
    model,
    firmware_source: str,
    sense_net: str,
    pin: Optional[str] = None,
    **kwargs,
) -> CosimRun:
    """
    Convenience wrapper: import the control law from a firmware C source, then
    co-simulate. The law is derived from the file's real constants.
    """
    spec = control_law.law_from_firmware_source_exact(
        firmware_source, sense_net, divider=kwargs.pop("divider", 1.0))
    if pin:
        spec["pin"] = pin
    return run_cosim(model, {str(spec["pin"]): spec}, **kwargs)