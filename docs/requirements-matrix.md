# Requirements Matrix

> **Source of truth:** `docs/requirements.md` (CO-01…CO-15) is the table
> `tools/check_traceability.py` enforces on every run — 14 requirements,
> 16 executed tests (log #224, guards in `tests/test_tool_fixes.py`).
> This file is the legacy REQ-00x view, reconciled 2026-10-29 to that
> table and to session evidence. Do not add rows here; add them to
> `docs/requirements.md` with a `@pytest.mark.req("ID")` test.

| REQ ID | Requirement | Design/Implementation | Verification/Test | Status (2026-10-29) |
|--------|-------------|------------------------|-------------------|----------------------|
| REQ-001 | ngspice DLL bridge for circuit simulation | `bridge/ngspice_wrapper.py` | `tests/test_ngspice_dll_proof.py`, `tests/test_ngspice_bridge.py` | VERIFIED (CO-01/CO-04; sanitiser suite 36 tests) |
| REQ-002 | Closed-loop co-simulation with control laws | `bridge/cosim_runner.py`, `bridge/control_law.py` | `tests/test_cosim_control.py` | VERIFIED (CO-06/CO-07) |
| REQ-003 | QEMU monitor for firmware interaction | `bridge/qemu_monitor.py` | `tests/test_qemu_monitor_unit.py`, `tests/test_fault_injection.py` | VERIFIED (CO-10) |
| REQ-004 | Binary firmware-in-the-loop co-simulation | `bridge/binary_runner.py` | `tests/test_binary_runner.py`; Track B real emulator | VERIFIED — gate flip against real firmware, 3 passed/0 skips (#201) |
| REQ-005 | Synchronized ngspice-QEMU coupling | `bridge/binary_runner.py` (sync, `_read_until_stable`) | `tests/test_qemu_monitor_qemu.py::test_gate_flip_against_real_firmware` | VERIFIED under WSL — 10 runs, 30/30 flips, 20.3-20.8 ms (#207); skips by default on Windows with a named reason |
| REQ-006 | Load step injection for transient testing | `bridge/load_stepper.py`, `bridge/cosim_runner.py` | `tests/test_load_step_injection.py` | IMPLEMENTED — tests green; engine-realness not asserted (ROADMAP §Phase 2) |
| REQ-007 | Adaptive firmware telemetry | `firmware/esp32_buck_controller/src/main.c` (uncommitted edit) | none | NOT VERIFIED — telemetry edit unreviewed and `adaptive_band_shift` dead (`docs/FIRMWARE_DECISION.md`); owner decision pending |
| REQ-008 | Adversarial fault-injection resilience | `tests/test_adversarial_stress.py`, `tests/test_fault_injection.py` | 106 tests across five families (#213) | VERIFIED — pipe/UART/ADC families remain doubles-based (ROADMAP §2.3) |
| REQ-009 | UI integration for binary cosim | `ui/schematic_editor.py` (`WOSP_USE_BINARY_COSIM`) | manual integration only | UNVERIFIED — no automated test; the editor suite carries the R2 crash (`docs/KNOWN_ISSUES.md`) |
| REQ-010 | Gate-flip validation against real firmware | `bridge/binary_runner.py` | `tests/test_qemu_monitor_qemu.py` | VERIFIED under WSL (#201); Windows side skips as UNEXECUTED with the exact missing item |

## Traceability Notes

- Every VERIFIED row maps to a CO row in `docs/requirements.md` or to a
  numbered run in `logs/activity.jsonl`.
- Synchronisation paths carry timeouts and error handling (CO-08/CO-09/CO-10).
- Adversarial tests cover dropped frames, corrupted responses, timeouts;
  the real-emulator half of that story is R8's orphan/fault evidence
  (#210-#213).
