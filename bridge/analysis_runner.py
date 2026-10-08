"""
analysis_runner.py - Post-simulation analysis: FFT, Bode, noise, Monte Carlo.

The transient path lives in bridge/cosim_runner.py. This module covers the
analyses that need their own run:

    run_fft()         replays the solved transient through a windowed FFT
    run_bode()        compiles the schematic with analysis="ac", solves the
                      sweep, and returns gain/phase plus margins
    run_noise()       compiles with analysis="noise" and returns the output
                      noise spectral density plus the integrated total
    run_monte_carlo() perturbs every R/C/L by +/-tol, recompiles and re-solves
                      the USER's schematic per sample, and returns yield stats

All return plain dicts, so the UI only has to draw them and the tests only
have to assert on numbers.
"""

import os
import math
import random
import statistics
import sys
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import measurements
from bridge.ngspice_wrapper import NgSpiceEngine


class AnalysisError(RuntimeError):
    """Raised when an analysis cannot produce the data it was asked for."""


def run_fft(
    engine: NgSpiceEngine,
    net: str,
    window: str = "hann",
    fundamental_hz: Optional[float] = None,
) -> Dict[str, object]:
    """
    FFT of an already-solved transient trace.

    The engine must have run a transient analysis; this reads the plot it left
    behind rather than solving anything again.
    """
    times = engine.get_vector_array("time")
    if not times:
        raise AnalysisError(
            "no transient data to analyse - run a transient simulation first")
    values = engine.get_vector_array(net)
    if not values:
        raise AnalysisError(f"no vector named '{net}' in the current plot")

    out = measurements.fft_spectrum(times, values, window=window)
    if not out["freqs"]:
        raise AnalysisError(f"trace on '{net}' is too short to FFT ({len(values)} points)")
    out["net"] = net
    out["window"] = window
    if fundamental_hz is None:
        fundamental_hz = out.get("dominant_hz")
    out["fundamental_hz"] = fundamental_hz
    out["thd"] = measurements.thd(out["freqs"], out["magnitude"], fundamental_hz)
    return out


def run_bode(
    model,
    output_net: str,
    input_net: Optional[str] = None,
    start_hz: float = 1.0,
    stop_hz: float = 1e6,
    points_per_decade: int = 20,
    engine: Optional[NgSpiceEngine] = None,
) -> Dict[str, object]:
    """
    AC sweep of a compiled schematic, returned as a Bode plot plus margins.

    `output_net` is the node whose transfer function you want (the classic case
    is the output node of an RC or a feedback loop). `input_net` is optional:
    when omitted the gain is referenced to the stamped 1 V AC source, which is
    what ngspice's own .ac gives you.
    """
    lines, nets, warns = model.compile_netlist(
        analysis="ac", ac_start_hz=start_hz, ac_stop_hz=stop_hz,
        ac_points_per_decade=points_per_decade)
    if not any(".ac" in l for l in lines):
        raise AnalysisError(
            "the netlist contains no .ac card; nothing to sweep. "
            + (" ".join(warns)))

    owns = engine is None
    if engine is None:
        try:
            engine = NgSpiceEngine(verbose=False)
        except Exception as exc:
            raise AnalysisError(f"cannot start ngspice: {exc}") from exc
    engine.load_circuit(lines)
    engine.cmd("run")
    freqs = engine.get_vector_array("frequency")
    if not freqs:
        # Older ngspice names the sweep vector "frequency"; be tolerant.
        freqs = engine.get_vector_array("freq")
    if not freqs:
        raise AnalysisError(
            "ngspice produced no frequency vector - the sweep did not run")
    re, im = engine.get_vector_complex(output_net)
    if not re:
        raise AnalysisError(
            f"no vector named '{output_net}' in the AC plot; "
            f"available nets: {', '.join(nets) or '(none)'}")
    if input_net:
        in_re, in_im = engine.get_vector_complex(input_net)
        if in_re:
            re = _divide(re, im, in_re, in_im)
    # Deliberately no `quit`: sharedspice is a process-wide singleton, so
    # quitting it here would break every later NgSpiceEngine in this process
    # (observed as a hang, not an error). Process exit tears it down.

    out = measurements.bode_from_ac(freqs, re, im)
    if not out["freqs"]:
        raise AnalysisError("AC sweep returned an empty Bode result")
    out["net"] = output_net
    out["input_net"] = input_net
    out["margins"] = measurements.phase_margin(
        out["freqs"], out["gain_db"], out["phase_deg"])
    out["netlist"] = lines
    out["warnings"] = warns
    return out


def spice_value(text: str) -> float:
    """
    Parse a SPICE component value ('1k', '4.7u', '0.1meg', '10') into a plain
    number. Raises ValueError for strings that are not numbers (PULSE(...),
    empty, mixed units) - callers skip those rather than guess.
    """
    s = str(text or "").strip().lower()
    if not s:
        raise ValueError("empty value")
    for suffix, mult in (("meg", 1e6), ("mil", 2.54e-5), ("k", 1e3),
                         ("m", 1e-3), ("u", 1e-6), ("n", 1e-9),
                         ("p", 1e-12), ("f", 1e-15)):
        if s.endswith(suffix) and len(s) > len(suffix):
            try:
                return float(s[:-len(suffix)]) * mult
            except ValueError:
                break
    return float(s)


def run_noise(
    model,
    output_net: str,
    start_hz: float = 1.0,
    stop_hz: float = 1e6,
    points_per_decade: int = 10,
    engine: Optional[NgSpiceEngine] = None,
) -> Dict[str, object]:
    """
    Small-signal noise analysis of a compiled schematic.

    Compiles with analysis="noise" (ngspice's `.noise V(out) src dec ...`
    card), solves, and returns the output/input noise spectral density
    (V/sqrt(Hz)) versus frequency plus the integrated totals. ngspice puts
    the spectrum in its `noise1` plot and the integrated totals in the
    `noise2` plot that is current when `run` returns - hence the setplot.
    """
    lines, nets, warns = model.compile_netlist(
        analysis="noise", noise_output_net=output_net,
        ac_start_hz=start_hz, ac_stop_hz=stop_hz,
        ac_points_per_decade=points_per_decade)
    if output_net not in nets:
        raise AnalysisError(
            f"'{output_net}' is not a probeable net of this schematic")
    if not any(l.lower().startswith(".noise") for l in lines):
        raise AnalysisError(
            "the netlist contains no .noise card; nothing to analyse. "
            + (" ".join(warns)))

    owns = engine is None
    if engine is None:
        try:
            engine = NgSpiceEngine(verbose=False)
        except Exception as exc:
            raise AnalysisError(f"cannot start ngspice: {exc}") from exc
    engine.load_circuit(lines)
    rc = engine.cmd("run")
    if rc != 0:
        raise AnalysisError(f"ngspice noise run failed (rc {rc})")

    # After `run` the current plot is this run's Integrated Noise plot; the
    # spectrum sits in the noise plot numbered one below it.  Locate by
    # description + numbering, never by the literal name "noise1": the
    # numbers keep incrementing inside one shared ngspice session.
    plots = _plot_list(engine)
    int_plot = next((n for n, _d, cur in plots
                     if cur and "Integrated Noise" in _d), None)
    if int_plot is None:
        int_plot = next((n for n, d, _c in plots
                         if "Integrated Noise" in d), None)
    spec_plot = None
    if int_plot and int_plot.startswith("noise") \
            and int_plot[len("noise"):].isdigit():
        want = "noise" + str(int(int_plot[len("noise"):]) - 1)
        if any(n == want for n, _d, _c in plots):
            spec_plot = want
    if spec_plot is None:
        spec_plot = next((n for n, d, _c in plots
                          if "Noise Spectral Density Curves" in d), None)
    if int_plot is None or spec_plot is None:
        raise AnalysisError(
            "ngspice produced no noise plots - the .noise run did not "
            "complete (ngspice has: "
            + (", ".join(n for n, _d, _c in plots) or "nothing") + ")")

    engine.cmd(f"setplot {int_plot}")
    total_out = engine.get_vector_array("onoise_total")
    total_in = engine.get_vector_array("inoise_total")
    engine.cmd(f"setplot {spec_plot}")   # the spectral-density plot
    freqs = engine.get_vector_array("frequency")
    onoise = engine.get_vector_array("onoise_spectrum")
    inoise = engine.get_vector_array("inoise_spectrum")
    if not freqs or not onoise or len(freqs) != len(onoise):
        raise AnalysisError(
            "ngspice produced no noise spectrum - the .noise run did not "
            "complete")

    out: Dict[str, object] = {
        "net": output_net,
        "freqs": list(freqs),
        "onoise_density": list(onoise),
        "inoise_density": list(inoise) if inoise else [],
        "total_output": total_out[0] if total_out else None,
        "total_input": total_in[0] if total_in else None,
        "netlist": lines,
        "warnings": warns,
    }
    return out


def run_monte_carlo(
    model,
    output_net: str,
    iterations: int = 40,
    tol_pct: float = 5.0,
    yield_pct: float = 5.0,
    seed: Optional[int] = None,
    engine: Optional[NgSpiceEngine] = None,
    perturb: Sequence[str] = ("R", "C", "L"),
) -> Dict[str, object]:
    """
    Per-schematic tolerance / yield analysis.

    Perturbs every R/C/L value by +/- tol_pct (uniform, seeded RNG), then
    recompiles and re-solves the USER's schematic once per sample and records
    the settled (final) value of `output_net`. The component values are
    always restored, even on failure.

    This is deliberately per-schematic: unlike
    studio_engine.run_monte_carlo, which is a parametric model of one fixed
    buck converter, every sample here is a real solve of the drawn circuit.
    Source (V/I) values are NOT perturbed - supply tolerance is a different
    analysis (line regulation), and mixing it into component yield would
    misreport both.
    """
    if iterations < 2:
        raise AnalysisError("monte carlo needs at least 2 iterations")
    lines, nets, warns = model.compile_netlist()
    if output_net not in nets:
        raise AnalysisError(
            f"'{output_net}' is not a probeable net of this schematic")

    comps = []
    for comp in model.components.values():
        if (comp.comp_type or "").upper() not in perturb:
            continue
        try:
            base = spice_value(comp.value)
        except (TypeError, ValueError):
            continue                # PULSE(...) etc.: not a tolerance part
        comps.append((comp, base))
    if not comps:
        raise AnalysisError(
            "no sweepable R/C/L parts with numeric values - nothing to "
            "tolerate")

    owns = engine is None
    if engine is None:
        try:
            engine = NgSpiceEngine(verbose=False)
        except Exception as exc:
            raise AnalysisError(f"cannot start ngspice: {exc}") from exc

    def metric() -> float:
        run_lines, _nets, _warns = model.compile_netlist()
        engine.load_circuit(run_lines)
        rc = engine.cmd("run")
        trace = engine.get_vector_array(output_net)
        if rc != 0 or not trace:
            raise AnalysisError(
                f"monte carlo sample failed to solve on '{output_net}' "
                f"(rc {rc})")
        return float(trace[-1])

    originals = [(comp, comp.value) for comp, _base in comps]
    rng = random.Random(seed)
    samples: List[float] = []
    try:
        nominal = metric()
        for _ in range(iterations):
            for comp, base in comps:
                u = rng.uniform(-1.0, 1.0)
                comp.value = f"{base * (1.0 + u * tol_pct / 100.0):.6g}"
            samples.append(metric())
    finally:
        for comp, value in originals:
            comp.value = value

    mean = statistics.fmean(samples)
    std = statistics.pstdev(samples)
    band = abs(nominal) * (yield_pct / 100.0)
    within = sum(1 for s in samples if abs(s - nominal) <= band)
    return {
        "net": output_net,
        "iterations": iterations,
        "tol_pct": tol_pct,
        "yield_pct_spec": yield_pct,
        "yield_actual_pct": 100.0 * within / len(samples),
        "nominal": nominal,
        "samples": samples,
        "mean": mean,
        "std": std,
        "min": min(samples),
        "max": max(samples),
        "cv": (std / mean) if mean else None,
        "parts": [comp.name or comp.comp_id for comp, _b in comps],
        "netlist": lines,
        "warnings": warns,
    }


def _plot_list(engine) -> List[tuple]:
    """
    (name, description, is_current) for every plot ngspice has open.

    Reads the listing a bare `setplot` prints. Plots are located by their
    DESCRIPTION rather than by name because the numbers in ac1/disto1/disto2
    increment across runs inside one shared session.
    """
    start = len(engine.output_logs)
    engine.cmd("setplot")
    plots: List[tuple] = []
    listing = False
    for raw in engine.output_logs[start:]:
        line = raw
        for prefix in ("stdout ", "stderr "):
            if line.startswith(prefix):
                line = line[len(prefix):]
        line = line.rstrip()
        if "List of plots available" in line:
            listing = True
            continue
        if not listing:
            continue
        tokens = line.split()
        current = False
        if tokens and tokens[0] == "Current":
            current = True
            tokens = tokens[1:]
        if len(tokens) >= 2:
            plots.append((tokens[0], " ".join(tokens[1:]), current))
    return plots


def run_disto(
    model,
    output_net: str,
    start_hz: float = 100.0,
    stop_hz: float = 1e5,
    points_per_decade: int = 4,
    engine: Optional[NgSpiceEngine] = None,
) -> Dict[str, object]:
    """
    Harmonic distortion (`.disto`) with the `.ac` reference run: HD2/HD3
    versus frequency.

    ngspice executes three analyses for this deck and leaves three plots
    open (AC reference at f1, distortion at 2f1, distortion at 3f1). They
    are located by description, then HD = |V_harmonic| / |V_f1| per the
    ngspice manual - the raw .disto output is an AC voltage, not a ratio.
    """
    lines, nets, warns = model.compile_netlist(
        analysis="disto", ac_start_hz=start_hz, ac_stop_hz=stop_hz,
        ac_points_per_decade=points_per_decade)
    if output_net not in nets:
        raise AnalysisError(
            f"'{output_net}' is not a probeable net of this schematic")
    if not any(l.lower().startswith(".disto") for l in lines):
        raise AnalysisError(
            "the netlist contains no .disto card; nothing to analyse. "
            + (" ".join(warns)))

    owns = engine is None
    if engine is None:
        try:
            engine = NgSpiceEngine(verbose=False)
        except Exception as exc:
            raise AnalysisError(f"cannot start ngspice: {exc}") from exc
    engine.load_circuit(lines)
    rc = engine.cmd("run")
    if rc != 0:
        raise AnalysisError(f"ngspice distortion run failed (rc {rc})")

    plots = _plot_list(engine)

    def find(marker: str):
        for name, desc, _cur in plots:
            if marker in desc:
                return name
        return None

    ac_plot = find("(AC Analysis)")
    d2_plot = find("DISTORTION - 2nd harmonic")
    d3_plot = find("DISTORTION - 3rd harmonic")
    missing = [m for m, p in (("AC reference", ac_plot),
                              ("2nd harmonic", d2_plot),
                              ("3rd harmonic", d3_plot)) if p is None]
    if missing:
        raise AnalysisError(
            "distortion plots missing: " + ", ".join(missing)
            + " (ngspice has: "
            + (", ".join(n for n, _d, _c in plots) or "nothing") + ")")

    engine.cmd(f"setplot {ac_plot}")
    freqs = engine.get_vector_array("frequency")
    re1, im1 = engine.get_vector_complex(output_net)
    engine.cmd(f"setplot {d2_plot}")
    re2, im2 = engine.get_vector_complex(output_net)
    engine.cmd(f"setplot {d3_plot}")
    re3, im3 = engine.get_vector_complex(output_net)
    if not freqs or not re1:
        raise AnalysisError(
            "distortion run produced no frequency/fundamental data")
    mag1 = [math.hypot(a, b) for a, b in zip(re1, im1)]
    if not any(m > 0 for m in mag1):
        raise AnalysisError(
            "the AC reference is all zeros - no excitation at f1 "
            "(did the source get its AC magnitude?)")
    mag2 = [math.hypot(a, b) for a, b in zip(re2, im2)]
    mag3 = [math.hypot(a, b) for a, b in zip(re3, im3)]
    hd2 = [(m2 / m1 if m1 > 0 else 0.0) for m1, m2 in zip(mag1, mag2)]
    hd3 = [(m3 / m1 if m1 > 0 else 0.0) for m1, m3 in zip(mag1, mag3)]
    return {
        "net": output_net,
        "freqs": list(freqs),
        "hd2": hd2,
        "hd3": hd3,
        "fundamental": mag1,
        "netlist": lines,
        "warnings": warns,
    }


def _divide(nre, nim, dre, dim) -> List[float]:
    """Complex division H = N / D, used to reference gain to a real input node."""
    out = []
    for a, b, c, d in zip(nre, nim, dre, dim):
        denom = c * c + d * d
        if denom <= 0:
            out.append(0.0)
        else:
            out.append((a * c + b * d) / denom)
    return out