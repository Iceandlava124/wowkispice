#!/usr/bin/env python3
"""
overnight_ollama.py - Run the full WOSP instruction set on a local Ollama model.

Reads the product vision document and a map of the actual repository, then
works through a fixed list of deliverables (implementation plan, editor
design, MCU co-sim design, AI assistant design, gap review), saving each
answer as Markdown under overnight/.

- Resumable: finished deliverables are skipped on relaunch (--force to redo).
- Auto-picks the best available model (override with --model).
- Keeps the machine awake for the duration (Windows SetThreadExecutionState).
- Stdlib only; requires the Ollama server (ollama serve) to be running.

Usage:
    python tools/overnight_ollama.py                 # run everything pending
    python tools/overnight_ollama.py --dry-run       # show the plan only
    python tools/overnight_ollama.py --only 01,05    # selected deliverables
    python tools/overnight_ollama.py --smoke         # tiny API sanity check
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "overnight")
VISION_PATH = r"C:\Users\gudae\Music\YES — now we're talking. That's the.txt"
API = "http://127.0.0.1:11434"

# Prefer the biggest model that fits the machine; fall back to what exists.
MODEL_PREFS = ["qwen2.5-coder:7b", "qwen2.5-coder:3b", "deepseek-r1:7b",
               "llama3.2:latest", "deepseek-r1:1.5b"]

SYSTEM_PROMPT = (
    "You are a senior EDA and embedded-software architect working on WOSP "
    "(LTspice-style circuit simulator + MCU co-simulation + AI design assistant). "
    "You are given the product vision and a map of the real repository. "
    "Answer in GitHub-flavored Markdown. Be concrete: name actual files, classes "
    "and functions from the repo map, give code sketches where useful, and state "
    "trade-offs explicitly. No filler, no disclaimers, no restating the prompt."
)

VISION_FALLBACK = """\
WOSP = LTspice + MCU simulation + AI design assistant in one desktop tool.
Unique value: real SPICE accuracy (ngspice) combined with running the user's
compiled MCU firmware (Renode/custom) against the analog circuit, plus an AI
layer that suggests component values and topologies.
Stack (finalized): PyQt5 + QGraphicsScene schematic editor, pyqtgraph waveform
viewer, ngspice analog solver, custom lightweight MCU emulation (Renode later),
PyTorch + Optuna for AI, SQLite/PostgreSQL storage, PyInstaller packaging.
Key UX: copy LTspice (drag components, wire by clicking endpoints, right-click
edit value, R rotate, F2 run, scroll zoom, undo/redo) and ADD: MCU palette
(Arduino/STM32/ESP32/custom .elf), firmware loader, GPIO inspector, a .cosim
simulation mode, and an AI design-assistant sidebar.
Phases: 1 core+basic UI, 2 LTspice-style UI, 3 MCU integration, 4 AI assistant,
5 polish (shortcuts, exports, help).
"""

# Honest snapshot of the current codebase so the model doesn't have to guess.
REPO_NOTES = """\
CURRENT STATE OF THE REPO (verified):
- bridge/ngspice_wrapper.py: NgSpiceEngine ctypes bridge to ngspice.dll with
  sharedspice callbacks (GetVSRCData/GetSyncData/SendData); load_circuit, cmd,
  get_vector_array. Works end-to-end on Windows (tools/ngspice_dll).
- bridge/studio_engine.py: StudioSimulationEngine - transient co-sim with a
  Python ESP32 control loop (mock_controller), real SPICE AC/Bode, Monte Carlo,
  IV curves, MPPT tracer, UART/I2C/SPI/CAN decoder.
- bridge/cad_engine.py: SchematicComponent + SchematicNetlistEngine. NOW has a
  REAL graph->SPICE compiler (compile_netlist): union-find net resolution over
  wires, pin aliasing, ground handling, model lines, warnings; to_dict/load_dict
  for save/open/undo. Empty schematic falls back to the legacy reference buck.
- bridge/renode_orchestrator.py + run_cosim.resc: launches real Renode with
  ngspice external-source bridge (mode=mock uses the Python controller).
- ui/: three tkinter apps (studio_app.py 1100 lines with instrument tabs,
  ltspice_workbench.py, dashboard.py) - preset dropdowns + sliders, static
  hand-drawn schematics. NO drag-drop editor yet. This is the main gap.
- tests/: unittest suites, run as `python tests/test_<name>.py` (pytest not
  installed). test_sota_suite covers the new netlist compiler. CI
  (.github/workflows/cosim-ci.yml) runs bridge tests on ubuntu + apt ngspice.
- Installed for the new UI: PyQt5 5.15 + pyqtgraph 0.14 (requirements.txt
  needs updating to include them).
- Not yet built: PyQt5 schematic editor, firmware .hex/.elf loader, GPIO
  inspector, .cosim mode in UI, AI design assistant panel.
"""

TASKS = [
    ("01-implementation-plan.md",
     "Master implementation plan",
     "Produce the definitive implementation plan to take this repository from "
     "its current state to the full WOSP vision. Order the work into phases "
     "with concrete, independently mergeable tasks. For every task name the "
     "files to create or modify, what changes inside them, and how to verify "
     "it (which test or manual check). Flag which existing code should be "
     "reused vs replaced, and call out the riskiest steps first."),

    ("02-schematic-editor-design.md",
     "PyQt5 schematic editor design (Phase 2)",
     "Design the new flagship PyQt5 application window: LTspice-style "
     "schematic editor (QGraphicsScene), left component palette, right "
     "pyqtgraph waveform viewer, bottom netlist/console, F2 to simulate. "
     "Specify the class hierarchy (scene items, pins, wires, main window), "
     "every gesture (place, wire pin-to-pin, right-click edit value, R rotate, "
     "Del, Ctrl+Z/Y undo using cad_engine to_dict/load_dict snapshots, wheel "
     "zoom, pan), and exactly how F2 flows through SchematicNetlistEngine."
     "compile_netlist into NgSpiceEngine and back into plotted traces. Include "
     "the key method signatures and an event-flow table."),

    ("03-mcu-cosim-design.md",
     "MCU co-simulation + firmware loader design (Phase 3)",
     "Design Phase 3: MCU palette entries (Arduino Uno, STM32, ESP32, custom "
     ".elf/.hex), a firmware loader, a GPIO inspector panel showing live pin "
     "states during simulation, and a .cosim mode coupling MCU and circuit. "
     "Explain how to reuse the existing pieces: ngspice_wrapper's "
     "GetVSRCData/GetSyncData callbacks, mock_controller's hysteretic loop, "
     "renode_orchestrator + run_cosim.resc for real firmware, and "
     "renode_adc_peripheral for ADC feedback. Deliver: data flow for lockstep "
     "co-sim, the GPIO state model, when to use the mock vs Renode, and how "
     "the compiled netlist needs an MCU element (currently MCU compiles to a "
     "comment line) - propose the exact SPICE modeling of a GPIO pin."),

    ("04-ai-assistant-design.md",
     "AI design assistant design (Phase 4)",
     "Design the AI Design Assistant sidebar: target specs (Vin, Vout, Iout, "
     "efficiency, size), a Suggest Design action that populates the schematic "
     "with real component values, an optimizer (Optuna) for efficiency/ripple/"
     "cost, stability checks (phase margin from the existing Bode analysis in "
     "studio_engine.run_real_spice_bode), and a sensitivity/trade-off view. "
     "Be pragmatic: specify a deterministic rule-based topology selector + "
     "value calculator first (buck, boost, LDO, RC filter), then where Optuna "
     "and later PyTorch models plug in, what data to store in SQLite for "
     "training, and how suggestions are applied to the schematic graph "
     "undoably."),

    ("05-gap-review.md",
     "Vision-vs-code gap review",
     "Act as a demanding reviewer. Compare the product vision against the "
     "actual repository state described in the notes: list every gap in "
     "priority order (P0/P1/P2), what exists that is solid, what is "
     "theater (fake or hardcoded behavior that looks like a feature), and the "
     "top 10 concrete next actions with rough effort estimates. Be specific "
     "about which tkinter UIs should be retired vs kept, and whether the "
     "existing Renode integration is real or aspirational."),
]


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, "run.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def api(path: str, payload=None, timeout=30):
    url = API + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_models():
    try:
        return [m["name"] for m in api("/api/tags").get("models", [])]
    except (urllib.error.URLError, OSError) as e:
        log(f"FATAL: cannot reach Ollama at {API}: {e}")
        log("Start it with: ollama serve")
        sys.exit(1)


def pick_model(override: str, models):
    if override:
        if not any(m == override or m.split(":")[0] == override for m in models):
            log(f"FATAL: model '{override}' not pulled. Available: {models}")
            sys.exit(1)
        return override
    for pref in MODEL_PREFS:
        if pref in models:
            return pref
    if models:
        log(f"No preferred model found, falling back to {models[0]}")
        return models[0]
    log("FATAL: no models pulled. Run: ollama pull qwen2.5-coder:7b")
    sys.exit(1)


def read_vision() -> str:
    try:
        with open(VISION_PATH, "r", encoding="utf-8", errors="replace") as f:
            text = f.read().strip()
        log(f"Vision doc loaded from {VISION_PATH} ({len(text)} chars)")
        return text
    except OSError:
        log(f"WARN: vision doc not found at {VISION_PATH}; using built-in summary")
        return VISION_FALLBACK


SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".freebuff",
             "overnight", ".pytest_cache"}
SKIP_PREFIXES = ("tools/ngspice", "tools/renode", "tools/*.7z")
TEXT_EXTS = {".py", ".md", ".cir", ".yml", ".yaml", ".bat", ".txt", ".c",
             ".h", ".ini", ".resc", ".repl", ".lib"}


def build_repo_context() -> str:
    """File tree with line counts + REPO_NOTES."""
    entries = []
    total_files = total_lines = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, ROOT)
        if rel_dir == ".":
            rel_dir = ""
        rel_prefix = rel_dir.replace(os.sep, "/")
        if rel_prefix and any(rel_prefix.startswith(p.rstrip("*")) for p in SKIP_PREFIXES):
            continue
        for name in sorted(filenames):
            rel = f"{rel_prefix}/{name}" if rel_prefix else name
            if any(rel.startswith(p.rstrip("*")) for p in SKIP_PREFIXES):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in TEXT_EXTS and name not in ("Dockerfile", "docker-compose.yml"):
                continue
            lines = 0
            if ext in {".py", ".c", ".h"}:
                try:
                    with open(os.path.join(dirpath, name), "r",
                              encoding="utf-8", errors="replace") as f:
                        lines = sum(1 for _ in f)
                except OSError:
                    pass
            entries.append((rel, lines))
            total_files += 1
            total_lines += lines

    tree = "\n".join(
        f"{rel}  ({n} lines)" if n else rel for rel, n in sorted(entries)
    )
    return (
        "REPOSITORY FILE MAP "
        f"({total_files} source files, ~{total_lines} lines of Python/C):\n"
        f"{tree}\n\n{REPO_NOTES}"
    )


def generate(model: str, prompt: str, num_ctx: int, num_predict: int) -> str:
    payload = {
        "model": model,
        "system": SYSTEM_PROMPT,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "15m",
        "options": {"num_ctx": num_ctx, "num_predict": num_predict,
                    "temperature": 0.6},
    }
    last_err = None
    for attempt in range(1, 4):
        try:
            t0 = time.time()
            resp = api("/api/generate", payload, timeout=7200)
            dt = time.time() - t0
            text = resp.get("response", "")
            eval_count = resp.get("eval_count") or 0
            rate = eval_count / dt if dt > 0 and eval_count else 0
            log(f"generated {eval_count} tokens in {dt/60:.1f} min ({rate:.1f} tok/s)")
            return text
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last_err = e
            log(f"attempt {attempt}/3 failed: {e}; retrying in 30s")
            time.sleep(30)
    log(f"FATAL: generation failed after 3 attempts: {last_err}")
    return ""


def set_awake(on: bool):
    """Keep Windows from sleeping while the overnight run is active."""
    try:
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes = __import__("ctypes")
        state = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(state)
        log("System sleep disabled" if on else "System sleep restored")
    except Exception:
        log("WARN: could not disable system sleep (run on AC power!)")


def main():
    ap = argparse.ArgumentParser(description="Overnight Ollama batch runner for WOSP")
    ap.add_argument("--model", help="Ollama model name (default: auto-detect)")
    ap.add_argument("--only", help="Comma-separated task ids, e.g. 01,05")
    ap.add_argument("--force", action="store_true", help="Redo finished tasks")
    ap.add_argument("--dry-run", action="store_true", help="Print plan and exit")
    ap.add_argument("--smoke", action="store_true", help="Tiny API sanity check")
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--num-predict", type=int, default=3072)
    args = ap.parse_args()

    models = list_models()
    log(f"Available models: {', '.join(models) if models else '(none)'}")

    if args.smoke:
        model = pick_model(args.model, models)
        out = generate(model, "Reply with exactly: PONG", args.num_ctx, 4)
        print(repr(out))
        return

    model = pick_model(args.model, models)
    log(f"Using model: {model} (ctx={args.num_ctx}, max_out={args.num_predict})")

    wanted = None
    if args.only:
        wanted = {t.strip() for t in args.only.split(",")}

    plan = []
    for i, (fname, title, _) in enumerate(TASKS, 1):
        tid = f"{i:02d}"
        if wanted and tid not in wanted and fname[:2] not in wanted:
            continue
        dest = os.path.join(OUT_DIR, fname)
        done = os.path.exists(dest) and os.path.getsize(dest) > 200
        plan.append((tid, fname, title, dest, done))

    if args.dry_run:
        print("\nPlan:")
        for tid, fname, title, _, done in plan:
            status = "DONE (skip, --force to redo)" if done else "pending"
            print(f"  [{tid}] {title} -> overnight/{fname}  [{status}]")
        return

    vision = read_vision()
    context = build_repo_context()
    os.makedirs(OUT_DIR, exist_ok=True)

    pending = [p for p in plan if not (p[4] and not args.force)]
    if not pending:
        log("Nothing to do - all selected deliverables are finished.")
        return
    log(f"{len(pending)} deliverable(s) queued on {model}")

    set_awake(True)
    results = []
    try:
        for tid, fname, title, dest, _ in pending:
            log(f"--- Task {tid}: {title} ---")
            prompt = (
                f"# PRODUCT VISION\n{vision}\n\n"
                f"# REPOSITORY CONTEXT\n{context}\n\n"
                f"# YOUR DELIVERABLE\n{title}\n\n{TASKS[int(tid) - 1][2]}"
            )
            log(f"prompt is {len(prompt)} chars; generating (this can take a while on CPU)...")
            text = generate(model, prompt, args.num_ctx, args.num_predict)
            if not text:
                log(f"Task {tid} failed; stopping (relaunch to resume).")
                break
            header = (f"# {title}\n\n_Generated by {model} on "
                      f"{datetime.now().isoformat(timespec='seconds')}_\n\n")
            tmp = dest + ".part"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(header + text)
            os.replace(tmp, dest)
            log(f"saved overnight/{fname} ({len(text)} chars)")
            results.append(fname)
    finally:
        set_awake(False)

    # Index of everything produced (old + new)
    index_lines = ["# Overnight deliverables\n"]
    for _, fname, title, dest, _ in plan:
        mark = "x" if os.path.exists(dest) else " "
        index_lines.append(f"- [{mark}] {title} - `{fname}`")
    with open(os.path.join(OUT_DIR, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(index_lines) + "\n")

    log(f"Done. {len(results)} new file(s) in overnight/")
    log("Review overnight/INDEX.md for the full set.")


if __name__ == "__main__":
    main()
