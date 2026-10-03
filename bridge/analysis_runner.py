"""
analysis_runner.py - Post-simulation analysis: FFT and Bode.

The transient path lives in bridge/cosim_runner.py. This module covers the
analyses that need their own run:

    run_fft()   replays the solved transient through a windowed FFT
    run_bode()  compiles the schematic with analysis="ac", solves the sweep,
                and returns gain/phase plus phase and gain margin

Both return plain dicts, so the UI only has to draw them and the tests only
have to assert on numbers.
"""

import os
import sys
from typing import Dict, List, Optional

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