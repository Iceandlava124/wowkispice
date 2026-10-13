"""
measurements.py - Waveform analysis and post-simulation metrics.

Everything here is pure computation over arrays the solver produced. No Qt, no
solver dependency: it can be unit tested headlessly, and the UI is a thin shell
over it.

What it provides:
    cursors          LTspice-style two-cursor readout: dt, dv, slope, 1/dt
    traces           point lookup, RMS, mean, min/max, peak-to-peak ripple,
                     settling time, duty cycle, rise/fall time
    fft              magnitude spectrum, dominant frequency, THD
    bode             gain (dB) and phase (deg) from an AC sweep
    power            efficiency and loss from measured in/out series

Time is in seconds and values in volts throughout, matching ngspice, so nothing
has to be converted at the call site.
"""

import math
from typing import Dict, List, Optional, Sequence

EPS = 1e-15


# ----------------------------------------------------------------------
# Cursor / ruler measurement
# ----------------------------------------------------------------------
def sample_at(times: Sequence[float], values: Sequence[float],
              t: float, clamp: bool = True) -> Optional[float]:
    """
    Interpolated value of a trace at time `t`.

    Out-of-range queries return None unless clamp is set, in which case the
    nearest endpoint is returned - which is what a cursor dragged past the end
    of a waveform should show.
    """
    if not times or len(times) != len(values) or not times:
        return None
    if t <= times[0]:
        return float(values[0]) if clamp else None
    if t >= times[-1]:
        return float(values[-1]) if clamp else None
    # Binary search for the bracketing pair.
    lo, hi = 0, len(times) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if times[mid] <= t:
            lo = mid
        else:
            hi = mid
    span = times[hi] - times[lo]
    if span <= 0:
        return float(values[lo])
    frac = (t - times[lo]) / span
    return float(values[lo] + frac * (values[hi] - values[lo]))


def cursor_readout(times: Sequence[float], values: Sequence[float],
                   t1: Optional[float] = None, v1: Optional[float] = None,
                   t2: Optional[float] = None, v2: Optional[float] = None
                   ) -> Dict[str, Optional[float]]:
    """
    Everything an LTspice ruler shows between two points.

    Pass t2 to get a ruler measurement (dt, dv, slope, 1/dt); leave it None for
    a single cursor's coordinates only. Nothing is defaulted into existence -
    a delta the caller did not ask for is not reported.
    """
    if not times or len(times) != len(values):
        return {"t1": None, "v1": None, "t2": None, "v2": None,
                "dt": None, "dv": None, "slope": None, "inv_dt": None,
                "inv_dv": None}
    if t1 is None:
        t1 = times[0]
    if v1 is None:
        v1 = sample_at(times, values, t1)

    out: Dict[str, Optional[float]] = {
        "t1": float(t1), "v1": v1, "t2": None, "v2": None,
        "dt": None, "dv": None, "slope": None, "inv_dt": None, "inv_dv": None,
    }
    if t2 is None:
        return out

    if v2 is None:
        v2 = sample_at(times, values, t2)
    out["t2"] = float(t2)
    out["v2"] = v2
    dt = float(t2) - float(t1)
    dv = float(v2) - float(v1)
    out["dt"] = dt
    out["dv"] = dv
    if abs(dt) > EPS:
        out["inv_dt"] = 1.0 / dt            # frequency, if dt is a period
        if abs(dv) > EPS:
            out["slope"] = dv / dt          # V/s
    if abs(dv) > EPS:
        out["inv_dv"] = 1.0 / dv
    return out


def format_readout(readout: Dict[str, Optional[float]]) -> str:
    """One-line console form of a cursor readout."""
    def eng(v, unit):
        if v is None:
            return "-"
        if v == 0:
            return f"0 {unit}"
        a = abs(v)
        prefix = "m" if a < 1e-3 else ("k" if a >= 1e3 else "")
        return f"{v * {'m': 1e3, 'k': 1e-3, }.get(prefix, 1.0):g}{prefix}{unit}"

    if readout.get("t1") is None:
        return "no trace"
    left = f"t1={eng(readout['t1'], 's')} v1={eng(readout['v1'], 'V')}"
    if readout.get("t2") is None:
        return left
    right = (f"t2={eng(readout['t2'], 's')} v2={eng(readout['v2'], 'V')}")
    extra = []
    if readout.get("inv_dt") is not None:
        extra.append(f"1/dt={eng(readout['inv_dt'], 'Hz')}")
    if readout.get("slope") is not None:
        extra.append(f"slope={eng(readout['slope'], 'V/s')}")
    return "  ".join([left, right] + extra)


# ----------------------------------------------------------------------
# Trace statistics
# ----------------------------------------------------------------------
def trace_stats(times: Sequence[float], values: Sequence[float],
                threshold: Optional[float] = None) -> Dict[str, object]:
    """
    Summary statistics of one trace.

    `threshold` (when given) splits the samples into logic-high and logic-low
    and adds duty cycle plus rise/fall timing.
    """
    if not values:
        return {"points": 0, "mean": None, "rms": None, "min": None,
                "max": None, "p2p": None, "duty": None}
    vals = [float(v) for v in values]
    out: Dict[str, object] = {
        "points": len(vals),
        "mean": sum(vals) / len(vals),
        "rms": math.sqrt(sum(v * v for v in vals) / len(vals)),
        "min": min(vals),
        "max": max(vals),
        "p2p": max(vals) - min(vals),
        "duty": None,
    }
    if threshold is not None and len(times) == len(vals) and len(vals) > 1:
        high = sum(1 for v in vals if v >= threshold)
        out["duty"] = high / len(vals)
        edge = _crossing_time(times, vals, threshold)
        if edge is not None:
            out["first_crossing_s"] = edge
    return out


def settling_time(times: Sequence[float], values: Sequence[float],
                  target: float, tolerance: float = 0.02,
                  t_start: Optional[float] = None) -> Optional[float]:
    """
    Time after `t_start` at which the trace enters and stays inside
    +/- tolerance of `target`.

    Returns None if it never settles - a real answer, unlike a value invented
    from the last sample.
    """
    if len(times) != len(values) or len(times) < 2:
        return None
    band = abs(target) * tolerance
    lo = 0
    if t_start is not None:
        while lo < len(times) and times[lo] < t_start:
            lo += 1
    for i in range(lo, len(times)):
        if abs(values[i] - target) <= band:
            # Confirm it stays put for the rest of the window.
            if all(abs(v - target) <= band for v in values[i:]):
                return float(times[i] - (times[0] if t_start is None else t_start))
    return None


def rise_fall_time(times: Sequence[float], values: Sequence[float],
                   low: float, high: float, fraction: float = 0.5
                   ) -> Dict[str, Optional[float]]:
    """
    10-90 style edge timing between two levels.

    Uses `fraction` of the actual low->high span, so it works for any logic
    amplitude rather than assuming a 0..3.3 V pin.
    """
    span = high - low
    if span <= 0:
        return {"rise_s": None, "fall_s": None, "v_low": low, "v_high": high}
    lo_thr = low + span * fraction * 0.2
    hi_thr = low + span * fraction * 0.8

    rise = fall = None
    for i in range(1, len(times)):
        a, b = values[i - 1], values[i]
        if rise is None and a <= lo_thr <= b:
            rise = _interp_cross(times[i - 1], a, times[i], b, lo_thr)
        if rise is None and a >= hi_thr >= b:
            rise = _interp_cross(times[i - 1], a, times[i], b, hi_thr)
        if fall is None and a >= hi_thr >= b:
            fall = _interp_cross(times[i - 1], a, times[i], b, hi_thr)
    if fall is None and rise is not None:
        fall = rise
    return {"rise_s": rise, "fall_s": fall, "v_low": low, "v_high": high}


def step_metrics(times: Sequence[float], values: Sequence[float],
                 tolerance: float = 0.02) -> Dict[str, object]:
    """
    Step-response characterization of a transient trace.

    Reports the settled value, the 50% crossing (propagation delay from the
    start of the window), the 10-90% transition time, overshoot/undershoot
    past the settled value (as a percentage of the step), settling time into
    a +/-`tolerance` band, and the 10-90 slew rate.

    Anything the data cannot support comes back None - a missing crossing is
    an honest answer; a fabricated one is not.
    """
    out: Dict[str, object] = {
        "points": len(values), "v_start": None, "v_final": None,
        "step_v": None, "direction": None, "delay_s": None, "rise_s": None,
        "overshoot_pct": 0.0, "undershoot_pct": 0.0, "settling_s": None,
        "slew_v_ms": None,
    }
    if len(times) != len(values) or len(times) < 3:
        return out
    n = len(values)
    tail = values[max(0, n - max(2, n // 10)):]
    v_start = float(values[0])
    v_final = float(sum(tail) / len(tail))
    span = v_final - v_start
    out["v_start"] = v_start
    out["v_final"] = v_final
    out["step_v"] = span
    if abs(span) <= 1e-12:
        return out                      # flat trace: no step to measure
    rising = span > 0
    out["direction"] = "rising" if rising else "falling"

    l10 = v_start + 0.10 * span
    l50 = v_start + 0.50 * span
    l90 = v_start + 0.90 * span
    t10 = _crossing_time(times, values, l10, rising=rising)
    t50 = _crossing_time(times, values, l50, rising=rising)
    t90 = _crossing_time(times, values, l90, rising=rising)
    if t50 is not None:
        out["delay_s"] = t50 - float(times[0])
    if t10 is not None and t90 is not None and t90 >= t10:
        rise = t90 - t10
        out["rise_s"] = rise
        if rise > 0:
            out["slew_v_ms"] = 0.8 * abs(span) / (rise * 1000.0)

    # Overshoot only after the 50% crossing: before it, the step itself
    # would masquerade as overshoot. Undershoot is measured only after the
    # trace first reaches the settled level, so a monotonic rise does not
    # report its own approach as an undershoot.
    i_lo = 0
    if t50 is not None:
        for i in range(1, len(times)):
            if times[i] >= t50:
                i_lo = i
                break
    post = values[i_lo:]
    if post:
        if rising:
            out["overshoot_pct"] = max(
                0.0, (float(max(post)) - v_final) / abs(span) * 100.0)
        else:
            out["overshoot_pct"] = max(
                0.0, (v_final - float(min(post))) / abs(span) * 100.0)
        t_final = _crossing_time(times, values, v_final, rising=rising)
        if t_final is not None:
            i_fin = 0
            for i in range(1, len(times)):
                if times[i] >= t_final:
                    i_fin = i
                    break
            tail_post = values[i_fin:]
            if tail_post and rising:
                out["undershoot_pct"] = max(
                    0.0, (v_final - float(min(tail_post))) / abs(span) * 100.0)
            elif tail_post:
                out["undershoot_pct"] = max(
                    0.0, (float(max(tail_post)) - v_final) / abs(span) * 100.0)

    out["settling_s"] = settling_time(times, values, v_final,
                                       tolerance=tolerance)
    return out


def _interp_cross(t0, v0, t1, v1, level) -> float:
    if v1 == v0:
        return float(t0)
    return float(t0 + (level - v0) * (t1 - t0) / (v1 - v0))


def _crossing_time(times, values, threshold,
                   rising: bool = True) -> Optional[float]:
    """First interpolated crossing of `threshold`; `rising=False` asks for a
    falling crossing (a step that goes down never crosses upward)."""
    for i in range(1, len(times)):
        a, b = values[i - 1], values[i]
        if rising and a < threshold <= b:
            return _interp_cross(times[i - 1], a, times[i], b, threshold)
        if not rising and a >= threshold > b:
            return _interp_cross(times[i - 1], a, times[i], b, threshold)
    return None


# ----------------------------------------------------------------------
# FFT
# ----------------------------------------------------------------------
def fft_spectrum(times: Sequence[float], values: Sequence[float],
                 window: str = "blackman") -> Dict[str, object]:
    """
    Single-sided magnitude spectrum of a real trace.

    Returns freqs (Hz), magnitude (linear, peak-normalised to 1.0), the
    dominant frequency, the measured noise floor and the bin width.

    The default window is Blackman. A rectangular window smears every tone
    across the whole band, and even Hann leaks ~0.2% of a strong fundamental
    into the bins where its harmonics sit - enough to make a pure sine read as
    0.2% THD. Blackman's -58 dB sidelobes put that below the noise.
    """
    if len(times) != len(values) or len(values) < 4:
        return {"freqs": [], "magnitude": [], "dominant_hz": None, "n": 0}
    t0, t1 = float(times[0]), float(times[-1])
    duration = t1 - t0
    if duration <= 0:
        return {"freqs": [], "magnitude": [], "dominant_hz": None, "n": 0}

    n = len(values)
    step = duration / (n - 1) if n > 1 else duration
    # The radix-2 FFT needs a power-of-two length, and any incomplete final
    # cycle would smear energy across bins. Take the largest power of two that
    # fits entirely inside the solved window.
    whole_cycles = int(duration / step)
    usable = 1
    while usable * 2 <= min(whole_cycles, n):
        usable *= 2
    if usable < 8:
        return {"freqs": [], "magnitude": [], "dominant_hz": None, "n": 0}
    samples = [float(v) for v in values[:usable]]
    mean = sum(samples) / len(samples)
    samples = [v - mean for v in samples]

    if window == "hann":
        w = [0.5 * (1 - math.cos(2 * math.pi * i / (len(samples) - 1)))
             for i in range(len(samples))]
    elif window == "blackman":
        # -58 dB sidelobes. Wider main lobe than Hann, but leakage is what
        # limits a THD reading, so the trade is strongly in its favour.
        a0, a1, a2, a3 = 0.35875, 0.48829, 0.14128, 0.01168
        denom = len(samples) - 1
        w = [a0 - a1 * math.cos(2 * math.pi * i / denom)
             + a2 * math.cos(4 * math.pi * i / denom)
             - a3 * math.cos(6 * math.pi * i / denom)
             for i in range(len(samples))]
    elif window == "rect":
        w = [1.0] * len(samples)
    else:
        raise ValueError(
            f"unsupported window '{window}' (use 'blackman', 'hann' or 'rect')")
    samples = [s * wi for s, wi in zip(samples, w)]

    # Zero-pad to the next power of two: this interpolates the spectrum and
    # sharpens peak estimation without adding information, but it costs
    # nothing and makes the harmonic bins land closer to their true centres.
    n_fft = 1
    while n_fft < 4 * len(samples):
        n_fft *= 2
    samples = samples + [0.0] * (n_fft - len(samples))
    spec = _dft(samples)
    half = n_fft // 2
    mags = []
    freqs = []
    for k in range(half):
        re = spec[k].real
        im = spec[k].imag
        scale = 2.0 / (sum(w) or 1.0)
        mags.append(math.hypot(re, im) * scale)
        freqs.append(k / (n_fft * step))

    # Drop DC, then find the peak. The peak frequency is interpolated across
    # its neighbours: without that, a 1 kHz tone analysed with 122 Hz bins
    # reports 977 Hz, and every downstream harmonic lands on the wrong bin.
    body = mags[1:]
    dominant = None
    noise_floor = 0.0
    if body:
        peak = max(range(len(body)), key=lambda i: body[i])
        bin_hz = freqs[1] - freqs[0] if len(freqs) > 1 else 0.0
        dominant = _interp_peak(freqs, mags, peak + 1, bin_hz)
        others = [m for i, m in enumerate(mags) if i != peak + 1]
        noise_floor = _median(others)
        top = body[peak]
        if top > 0:
            mags = [m / top for m in mags]
    return {"freqs": freqs, "magnitude": mags, "dominant_hz": dominant,
            "n": n_fft, "sample_rate_hz": 1.0 / step,
            "noise_floor": noise_floor,
            "bin_width_hz": (freqs[1] - freqs[0]) if len(freqs) > 1 else 0.0}


def _interp_peak(freqs, mags, peak_index, bin_hz):
    """
    Sub-bin peak frequency from a parabolic fit through log-magnitude.

    A tone that falls between bins otherwise reports the nearest bin, which
    biases every harmonic derived from it.
    """
    n = len(mags)
    if not (1 <= peak_index < n - 1) or bin_hz <= 0:
        return float(freqs[peak_index])
    a, b, c = mags[peak_index - 1], mags[peak_index], mags[peak_index + 1]
    denom = a - 2.0 * b + c
    if abs(denom) < EPS:
        return float(freqs[peak_index])
    delta = 0.5 * (a - c) / denom
    if abs(delta) > 1.0:               # not a peak shape; trust the bin
        delta = 0.0
    return float(freqs[peak_index] + delta * bin_hz)


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


def _dft(samples: List[float]) -> List[complex]:
    """Radix-2 FFT; input length must be a power of two (caller pads)."""
    n = len(samples)
    if n & (n - 1):
        raise ValueError("FFT length must be a power of two")
    data = [complex(s, 0.0) for s in samples]
    # Bit-reversal permutation.
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            data[i], data[j] = data[j], data[i]
    length = 2
    while length <= n:
        ang = -2.0 * math.pi / length
        wlen = complex(math.cos(ang), math.sin(ang))
        for i in range(0, n, length):
            w = complex(1.0, 0.0)
            for k in range(i, i + length // 2):
                u = data[k]
                v = data[k + length // 2] * w
                data[k] = u + v
                data[k + length // 2] = u - v
                w *= wlen
        length <<= 1
    return data


def thd(freqs: Sequence[float], magnitude: Sequence[float],
        fundamental_hz: Optional[float] = None,
        max_harmonic: int = 20) -> Optional[float]:
    """
    Total harmonic distortion as a fraction (0.01 = 1%).

    Harmonics are matched in *frequency*, not in harmonic number: for each
    order n the energy inside the window around n*f0 is summed, and the
    harmonic amplitude is compared with the fundamental the same way. Matching
    in units of n instead would sweep in nearly every bin once n is large,
    because the bins get dense relative to the harmonic spacing - which
    reports a square wave at 118% THD instead of the correct 49%.

    Only the first `max_harmonic` orders count, as in a conventional THD meter.
    """
    if not freqs or len(freqs) < 3:
        return None
    bin_hz = freqs[1] - freqs[0]
    if bin_hz <= 0:
        return None
    if fundamental_hz is None or fundamental_hz <= 0:
        if len(magnitude) < 2:
            return None
        peak = max(range(1, len(magnitude)), key=lambda i: magnitude[i])
        fundamental_hz = freqs[peak]
    nyquist = freqs[-1]
    if fundamental_hz <= 0:
        return None

    # A Blackman-windowed tone occupies about +/-4 bins around its centre.
    half_width = 4.0 * bin_hz

    def lobe_amplitude(center_hz: float) -> float:
        total = 0.0
        for f, m in zip(freqs, magnitude):
            if abs(f - center_hz) <= half_width:
                total += m * m
        return math.sqrt(total)

    fundamental = lobe_amplitude(fundamental_hz)
    if fundamental <= 0:
        return None

    harmonics = 0.0
    counted = 0
    for n in range(2, int(max_harmonic) + 1):
        f_n = n * fundamental_hz
        if f_n > nyquist:
            break
        amp = lobe_amplitude(f_n)
        if amp > 0:
            harmonics += amp * amp
            counted += 1
    if counted == 0:
        return None
    return math.sqrt(harmonics) / fundamental


# ----------------------------------------------------------------------
# Bode
# ----------------------------------------------------------------------
def bode_from_ac(freqs: Sequence[float], re: Sequence[float],
                 im: Sequence[float], magnitude_ref: float = 1.0
                 ) -> Dict[str, object]:
    """
    Gain in dB and phase in degrees from a complex AC sweep.

    `magnitude_ref` is the input magnitude the sweep used, so the plotted gain
    is V(out)/V(in) rather than just V(out).
    """
    if not freqs or len(freqs) != len(re) or len(freqs) != len(im):
        return {"freqs": [], "gain_db": [], "phase_deg": [], "peak_db": None,
                "peak_hz": None}
    gain_db: List[float] = []
    phase: List[float] = []
    for a, b in zip(re, im):
        mag = math.hypot(a, b)
        gain_db.append(20.0 * math.log10(mag / magnitude_ref) if mag > EPS
                       else -300.0)
        phase.append(math.degrees(math.atan2(b, a)))
    # Unwrap phase so the curve reads continuously instead of sawtoothing
    # between +180 and -180 at every zero crossing.
    unwrapped: List[float] = []
    prev = None
    for p in phase:
        if prev is not None:
            while p - prev > 180.0:
                p -= 360.0
            while p - prev < -180.0:
                p += 360.0
        unwrapped.append(p)
        prev = p

    peak_db = max(gain_db) if gain_db else None
    peak_hz = freqs[gain_db.index(peak_db)] if peak_db is not None else None
    return {"freqs": list(freqs), "gain_db": gain_db, "phase_deg": unwrapped,
            "peak_db": peak_db, "peak_hz": peak_hz}


def phase_margin(freqs: Sequence[float], gain_db: Sequence[float],
                 phase_deg: Sequence[float]) -> Dict[str, Optional[float]]:
    """
    Gain and phase at the unity-gain crossover, then the phase margin.

    Returns None for whatever could not be located - an unstable or
    unconditional loop has no meaningful phase margin, and saying so is more
    useful than printing a number.
    """
    if not gain_db or len(gain_db) != len(phase_deg):
        return {"crossover_hz": None, "gain_at_crossover_db": None,
                "phase_margin_deg": None, "gain_margin_db": None}
    crossings = []
    for i in range(1, len(gain_db)):
        if gain_db[i - 1] >= 0 > gain_db[i]:
            frac = gain_db[i - 1] / (gain_db[i - 1] - gain_db[i])
            crossings.append((i - 1 + frac, freqs[i - 1] +
                              frac * (freqs[i] - freqs[i - 1])))
    if not crossings:
        return {"crossover_hz": None, "gain_at_crossover_db": None,
                "phase_margin_deg": None, "gain_margin_db": None}

    idx, f_cross = crossings[0]
    phase_at = phase_deg[int(idx)]
    # Unwrapped phase starts at some offset; measure margin from -180 degrees.
    margin = 180.0 + phase_at

    # Gain margin: where phase is -180 degrees.
    gain_margin = None
    for i in range(1, len(phase_deg)):
        if phase_deg[i - 1] > -180.0 >= phase_deg[i]:
            frac = (phase_deg[i - 1] + 180.0) / (phase_deg[i - 1] - phase_deg[i])
            g = gain_db[i - 1] + frac * (gain_db[i] - gain_db[i - 1])
            gain_margin = -g
            break
    return {
        "crossover_hz": f_cross,
        "gain_at_crossover_db": gain_db[int(idx)],
        "phase_margin_deg": margin,
        "gain_margin_db": gain_margin,
    }


# ----------------------------------------------------------------------
# Power
# ----------------------------------------------------------------------
def power_metrics(v_in: float, i_in: float,
                  v_out: float, i_out: float) -> Dict[str, Optional[float]]:
    """
    Efficiency and losses from mean in/out voltages and currents.

    Efficiency outside 0..100% is reported as None: a number outside that
    range means the measurement or the sign convention is wrong, and dividing
    anyway would print a confident lie.
    """
    p_in = v_in * i_in
    p_out = v_out * i_out
    out: Dict[str, Optional[float]] = {
        "p_in_w": p_in, "p_out_w": p_out,
        "loss_w": p_in - p_out, "efficiency": None,
    }
    if p_in > EPS:
        eff = p_out / p_in
        if 0.0 <= eff <= 1.0:
            out["efficiency"] = eff
    return out


def series_current(times: Sequence[float], voltages: Sequence[float],
                   resistance: float) -> List[float]:
    """Ohm's law over a trace - the honest way to get a current trace in SPICE."""
    if resistance <= 0:
        return [0.0] * len(voltages)
    return [float(v) / resistance for v in voltages]