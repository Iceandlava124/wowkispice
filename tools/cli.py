"""wosp/cli.py - Headless CLI for WOWKISPICE bridge tools.

Provides command-line access to simulation, cosimulation, and diagnostic
commands without requiring the PyQt UI layer.
"""

import sys
import os
import json
import argparse
import hashlib
from datetime import datetime, timezone

# Add project root to path so bridge/ imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")


def main(args=None):
    """Entry point for the wosp CLI."""
    parser = argparse.ArgumentParser(
        prog="wosp",
        description="WOWKISPICE - Embedded breadboard cosimulation tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # === cosim-binary command ===
    cosim_parser = subparsers.add_parser(
        "cosim-binary", help="Run binary cosimulation with firmware in QEMU"
    )
    cosim_parser.add_argument(
        "--model", required=True, help="Path to circuit model file or module"
    )
    cosim_parser.add_argument(
        "--qemu",
        required=True,
        help="Path to qemu-system-xtensa binary",
    )
    cosim_parser.add_argument(
        "--firmware",
        required=True,
        help="Path to firmware qemu_flash.bin image",
    )
    cosim_parser.add_argument(
        "--duration-ms",
        type=float,
        default=5.0,
        help="Simulation duration in milliseconds (default: 5.0)",
    )
    cosim_parser.add_argument(
        "--tstep-us",
        type=float,
        default=0.5,
        help="NGSpice time step in microseconds (default: 0.5)",
    )
    cosim_parser.add_argument(
        "--output", help="Path to write JSON trace output"
    )

    # === test-gate-flip command ===
    gate_parser = subparsers.add_parser(
        "test-gate-flip", help="Test gate flipping against firmware"
    )
    gate_parser.add_argument(
        "--qemu", required=True, help="Path to qemu-system-xtensa binary"
    )
    gate_parser.add_argument(
        "--firmware",
        required=True,
        help="Path to firmware qemu_flash.bin image",
    )
    gate_parser.add_argument(
        "--low-adc", type=int, default=1500, help="Low ADC threshold (default: 1500)"
    )
    gate_parser.add_argument(
        "--high-adc", type=int, default=2500, help="High ADC threshold (default: 2500)"
    )
    gate_parser.add_argument(
        "--settle-delay", type=float, default=0.05, help="Settle delay in seconds (default: 0.05)"
    )

    # === doctor command ===
    doctor_parser = subparsers.add_parser(
        "doctor", help="Check environment and toolchain status"
    )
    doctor_parser.add_argument(
        "--verbose", action="store_true", help="Show detailed output"
    )

    # === golden-trace command ===
    golden_parser = subparsers.add_parser(
        "golden-trace", help="Capture or compare golden traces"
    )
    golden_sub = golden_parser.add_subparsers(dest="golden_cmd")

    capture_parser = golden_sub.add_parser(
        "capture", help="Capture a new golden trace"
    )
    capture_parser.add_argument(
        "--name", required=True, help="Trace name"
    )
    capture_parser.add_argument(
        "--model", required=True, help="Circuit model (JSON schematic)"
    )
    capture_parser.add_argument(
        "--qemu", required=True, help="QEMU binary path"
    )
    capture_parser.add_argument(
        "--firmware", help="Firmware qemu_flash.bin image"
    )
    capture_parser.add_argument(
        "--duration-ms", type=float, default=5.0, help="Duration in ms"
    )
    capture_parser.add_argument(
        "--tstep-us", type=float, default=0.5, help="Time step in microseconds"
    )

    compare_parser = golden_sub.add_parser(
        "compare", help="Compare traces against golden reference"
    )
    compare_parser.add_argument(
        "--name", required=True, help="Golden trace name"
    )
    compare_parser.add_argument(
        "--trace", required=True, help="Path to trace data (cosim-binary JSON)"
    )
    compare_parser.add_argument(
        "--tolerances", help="JSON tolerances dict, e.g. '{\"voltage\": 0.02}'"
    )

    # === version command ===
    subparsers.add_parser(
        "version", help="Show version information"
    )

    # Parse arguments
    args = parser.parse_args(args)

    if args.command is None:
        parser.print_help()
        return 1

    # Route to command handlers
    if args.command == "cosim-binary":
        return run_cosim_binary(args)
    elif args.command == "test-gate-flip":
        return run_gate_flip_test(args)
    elif args.command == "doctor":
        return run_doctor(args)
    elif args.command == "golden-trace":
        return run_golden_trace(args)
    elif args.command == "version":
        print_version()
        return 0

    return 1


def _load_model(path):
    """Load a JSON schematic produced by the editor's save action."""
    from bridge.cad_engine import SchematicNetlistEngine

    with open(path, "r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "model must be a wowki-schematic-v1 JSON file "
                "(a SPICE netlist is not a component graph): %s" % exc)
    if not isinstance(data, dict) or "components" not in data:
        raise ValueError(
            "model must be a wowki-schematic-v1 JSON file "
            "(netlists are not a component graph)")
    model = SchematicNetlistEngine()
    model.load_dict(data)
    return model


def _pin_specs_from_model(model):
    """One sense spec per declared control law, keyed by MCU pin."""
    specs = {}
    for spec in model.control_laws.values():
        pin = spec.get("pin")
        sense_net = spec.get("sense_net") or spec.get("sense")
        if pin and sense_net:
            specs[pin] = {"sense_net": sense_net}
    return specs


def _sha256(path):
    if not path or not os.path.exists(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_cosim_binary(args):
    """Run binary cosimulation command."""
    from bridge import binary_runner

    if not os.path.exists(args.model):
        print(f"Error: Model file not found: {args.model}", file=sys.stderr)
        return 1
    try:
        model = _load_model(args.model)
    except Exception as exc:
        print(f"Error: cannot load model {args.model}: {exc}", file=sys.stderr)
        return 1
    pin_specs = _pin_specs_from_model(model)
    if not pin_specs:
        print("Error: the model declares no control law with a pin and "
              "sense_net, so there is nothing to close the loop on.",
              file=sys.stderr)
        return 1

    run = binary_runner.run_binary_cosim(
        model,
        pin_specs,
        qemu=args.qemu,
        firmware_image=args.firmware,
        duration_ms=args.duration_ms,
        tstep_us=args.tstep_us,
    )

    print("Cosimulation complete")
    print(f"  Callback hits: {run.callback_hits}")
    print(f"  Warnings: {len(run.warnings)}")
    for w in run.warnings:
        print(f"  - {w}")

    if args.output:
        output_data = {
            "time": run.time,
            "traces": run.traces,
            "nets": run.nets,
            "warnings": run.warnings,
            "callback_hits": run.callback_hits,
            "aborted": run.aborted,
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)
        print(f"  Output written to {args.output}")

    return 0 if run.time else 1


def run_gate_flip_test(args):
    """Run gate flip test command through the tested binary runner."""
    from bridge import binary_runner

    if not os.path.exists(args.firmware):
        print(f"Error: Firmware image not found: {args.firmware}", file=sys.stderr)
        return 1
    if not os.path.exists(args.qemu):
        print(f"Error: QEMU binary not found: {args.qemu}", file=sys.stderr)
        return 1

    result = binary_runner.test_gate_flip(
        qemu=args.qemu,
        firmware_image=args.firmware,
        low_adc=args.low_adc,
        high_adc=args.high_adc,
        settle_delay=args.settle_delay,
    )
    for gate in result.get("gates", []):
        state = "HIGH" if gate["gate"] else "LOW"
        print(f"  ADC={gate['adc']}: gate={state}")
    for err in result.get("errors", []):
        print(f"  ERROR: {err}", file=sys.stderr)
    print(f"Gate flip test: {len(result.get('gates', []))} reads, "
          f"ok={bool(result.get('ok'))}")
    return 0 if result.get("ok") and not result.get("errors") else 1


def run_golden_trace(args):
    """Capture or compare a golden trace."""
    from tools.golden_trace import GoldenTrace

    if args.golden_cmd == "capture":
        return _capture_golden(args, GoldenTrace)
    if args.golden_cmd == "compare":
        return _compare_golden(args, GoldenTrace)
    print("Error: choose 'capture' or 'compare'", file=sys.stderr)
    return 1


def _capture_golden(args, golden_cls):
    from bridge import binary_runner

    if not os.path.exists(args.model):
        print(f"Error: Model file not found: {args.model}", file=sys.stderr)
        return 1
    try:
        model = _load_model(args.model)
    except Exception as exc:
        print(f"Error: cannot load model {args.model}: {exc}", file=sys.stderr)
        return 1
    pin_specs = _pin_specs_from_model(model)
    if not pin_specs:
        print("Error: the model declares no control law; nothing to capture.",
              file=sys.stderr)
        return 1

    run = binary_runner.run_binary_cosim(
        model, pin_specs, qemu=args.qemu, firmware_image=args.firmware,
        duration_ms=args.duration_ms, tstep_us=args.tstep_us)
    if not run.time or not run.traces:
        for warning in run.warnings:
            print(f"Error: {warning}", file=sys.stderr)
        print("Error: the run produced no trace data; nothing was saved.",
              file=sys.stderr)
        return 1
    if run.aborted:
        print("Error: the run was aborted; refusing to save a partial trace.",
              file=sys.stderr)
        return 1

    metadata = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "command": ("wosp golden-trace capture --name %s --model %s --qemu %s"
                    % (args.name, args.model, args.qemu)),
        "qemu": args.qemu,
        "qemu_sha256": _sha256(args.qemu),
        "firmware": args.firmware,
        "firmware_sha256": _sha256(args.firmware),
        "callback_hits": run.callback_hits,
        "warnings": list(run.warnings),
    }
    golden_cls(args.name).save(run.time, run.traces, metadata)
    print(f"  callback hits: {run.callback_hits}")
    return 0


def _compare_golden(args, golden_cls):
    if not os.path.exists(args.trace):
        print(f"Error: trace file not found: {args.trace}", file=sys.stderr)
        return 1
    try:
        with open(args.trace, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        time = data["time"]
        traces = data["traces"]
    except Exception as exc:
        print(f"Error: cannot read trace {args.trace}: {exc}", file=sys.stderr)
        return 1

    tolerances = None
    if args.tolerances:
        try:
            tolerances = json.loads(args.tolerances)
        except json.JSONDecodeError as exc:
            print(f"Error: invalid --tolerances JSON: {exc}", file=sys.stderr)
            return 1

    ok, errors = golden_cls(args.name).compare(time, traces, tolerances)
    if ok:
        print(f"Golden trace '{args.name}': MATCH")
        return 0
    print(f"Golden trace '{args.name}': MISMATCH", file=sys.stderr)
    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    return 1


def run_doctor(args):
    """Run doctor command to check environment."""
    import warnings

    issues = []

    # Check WOSP_QEMU
    qemu = os.environ.get("WOSP_QEMU")
    if qemu:
        if os.path.exists(qemu):
            issues.append(("QEMU", "OK", f"Found at {qemu}"))
        else:
            issues.append(("QEMU", "MISSING", f"WOSP_QEMU={qemu} but not found"))
    else:
        issues.append(("WOSP_QEMU", "NOT SET", "WOSP_QEMU environment variable not set"))

    # Check ngspice
    from bridge.ngspice_wrapper import resolve_ngspice_library
    try:
        path, tried = resolve_ngspice_library()
        if path:
            issues.append(("ngspice", "OK", f"Found at {path}"))
        else:
            issues.append(("ngspice", "MISSING", f"Tried: {', '.join(tried)}"))
    except Exception as e:
        issues.append(("ngspice", "ERROR", str(e)))

    # Check firmware
    firmware = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "firmware", "esp32_buck_controller", ".pio", "build", "esp32dev", "qemu_flash.bin"
    )
    if os.path.exists(firmware):
        issues.append(("Firmware", "OK", f"Found at {firmware}"))
    else:
        issues.append(("Firmware", "MISSING", f"Not found at {firmware}"))

    # Summary
    print("=" * 50)
    print("WOWKISPICE Environment Doctor")
    print("=" * 50)

    all_ok = True
    for name, status, detail in issues:
        marker = "OK" if status == "OK" else "FAIL"
        print(f"  [{marker}] {name}: {status}")
        if status != "OK":
            all_ok = False
        print(f"         {detail}")

    print("=" * 50)
    if all_ok:
        print("All checks passed!")
    else:
        print("Some checks failed - see above for details.")
    print("=" * 50)

    return 0 if all_ok else 1


def print_version():
    """Print version information."""
    print("WOWKISPICE Bridge Tools")
    print("Version: development build")
    print("(C) 2026 Project WOWKISPICE")


if __name__ == "__main__":
    sys.exit(main())