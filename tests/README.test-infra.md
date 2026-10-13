# Test engineering handbook for `tests/`

## What this suite is
These are integration-level tests for the WOWKISPICE desktop project. The core
editor test is `tests/test_schematic_editor.py`. It exercises the real PyQt5
editor, the ngspice bridge, and the studio engine through the actual Qt window,
not through mocked internals.

## How tests are discovered
- Files are discovered by the conventional `tests/test_*.py` pattern.
- Each file is its own unittest/pytest module.
- Individual tests are discovered from `Test*` classes and `test_*` methods.

## Environment requirements
- The editor tests require a real Qt binding. The committed import is
  `from PyQt5.QtCore import ...`.
- Headless runs use `QT_QPA_PLATFORM=offscreen`.
- Ngspice-dependent tests need the ngspice DLL set up for the environment that
  runs them. Do not assume it is present in every Python environment.
- Numerical tests use numpy; pytest-based tests use pytest.

## Which Python to use
- The project’s `.venv` does not currently have PyQt5 installable from PyPI for
  this machine, so the Qt editor tests are run through a separate Python that
  has PyQt5 available. On this machine that was `py -3.12`.
- Do not hardcode the system Python or the project `.venv` as the only test
  runner. Treat “which interpreter has PyQt5” as a real environment concern.

## Test categories
- `test_schematic_editor.py` is the flagship editor integration suite. It
  covers placement, wiring, undo/redo, netlist compilation, F2 simulation,
  analysis tabs, and the serial/UART decode path.
- `test_sota_suite.py` and `test_studio_suite.py` cover studio-engine paths,
  including `decode_uart_packets`.
- Other files cover more targeted behaviors such as firmware/GPIO parsing,
  ngspice bridge math, measurements, and exporters.

## UART decode tests are strict on behavior
- The UART decoder is tested not only for the happy path.
- One class of tests requires the decoder to return nothing when the input is
  not a real 8N1 stream. It is not acceptable for the decoder to invent canned
  demo packets in that case.
- If you touch `bridge/studio_engine.py:decode_uart_packets`, re-run at least:
  - `tests/test_schematic_editor.py`
  - `tests/test_sota_suite.py`
  - `tests/test_studio_suite.py`

## Editing tests
- Prefer editing the behavior under test over weakening assertions.
- Do not change a test to hide a missing feature.
- If a test is wrong, say so explicitly and propose the corrected assertion
  rather than silently making the implementation fake the result.

## Parallel execution
- Suites can be run in parallel by test file because most of them are isolated
  by process.
- A reliable pattern on this machine is:
  - launch one `py -3.12 -m pytest tests/test_<suite>.py` per suite
  - write each to its own log
  - wait for all jobs
  - reconcile exit codes and summary lines from the logs
- Do not rely on a single pooled pytest invocation for integration results if
  some of those suites need different interpreters or environment setup.

## Exit status discipline
- When you filter or summarize test output, preserve the real exit status.
- Example pattern:
  - `py -3.12 -m pytest ... > log 2>&1 ; echo "EXITCODE=$?"`
- A clean-looking summary printed after the fact is not a substitute for the
  command’s actual exit code.

## Coverage you should expect before calling this “integrated”
- Editor parses and constructs.
- F2 simulation path runs through ngspice and populates plots.
- Undo/redo and wiring integrity tests pass.
- Analysis tabs that depend on studio engine or measurements pass.
- UART decode happy path and “no fake frames” path both pass.
- Any suite that imports `bridge.studio_engine` and calls
  `decode_uart_packets` is re-verified after that function changes.

## Failure triage
- If a Qt test fails to import, treat it as an environment issue first.
- If a ngspice test fails to import, treat it as a DLL/runtime setup issue.
- If a decoder-dependent test fails, read the decoder logic before changing the
  test. The decoder must not fabricate packets to satisfy the suite.

## Source of truth
- The authoritative request is the current user message or handoff, not any
  older staging notes about “Stage 0/1/2/3”.
- Provenance labels and historical rewrites are separate concerns. Do not mix
  them into the “make the tip runnable” edit unless explicitly asked.
