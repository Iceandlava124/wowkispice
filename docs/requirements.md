# Requirements Traceability

Testable requirements derived from behaviours this repository actually claims.
Each requirement maps to one or more real tests via `@pytest.mark.req("ID")`.

## Requirements

| ID | Requirement | Source | Tests |
|----|-------------|--------|-------|
| CO-01 | ngspice DLL resolves on first use, and a clean Nx-mutex/once-init gives every engine the same solved plot, not `m_addr == m_first_addr` replicates | `bridge/ngspice_wrapper.py` resolve + `tools/prove_physics_engine.py` proof 2 | `test_ngspice_bridge.py`, `test_ngspice_dll_proof.py` |
| CO-02 | A transient solve reproduces the closed-form RC step `v(t) = V0*(1 - e^(-t/RC))` within a justified tolerance | closed-form ODE; solver reltol; timestep | `test_ngspice_bridge.py::TestNgSpiceBridge::test_rc_circuit_mathematical_precision` |
| CO-03 | A second-order RLC underdamped tank rings at `wd = sqrt(1/ LC - (R/2L)^2)` and decays at `alpha = R/2L`, within documented tolerances | closed-form RLC | `test_ngspice_dll_proof.py::TestNgSpiceDllProof::test_proof3_underdamped_rlc_ringing` |
| CO-04 | A two-source symmetric circuit does not alias the two solve instances to the same matrix in memory | `prove_physics_engine.py` proof 1 + `test_ngspice_bridge.py` | `test_ngspice_bridge.py`, `test_ngspice_dll_proof.py` |
| CO-05 | ngspice `qom-set /machine/peripheral/sens adc1-value` injects a sample and the GPIO18 gate readback is driven by the injected value | `bridge/qemu_monitor.py`, `docs/binary-runner-and-mcu-bringup.md` | `tests/test_firmware_gpio.py` (qemu marker), `tests/test_fault_injection.py` |
| CO-06 | A closed loop with the real firmware's own ADC thresholds (1995/2030) regulates a buck to the documented target voltage | `firmware/esp32_buck_controller/src/main.c`, `bridge/control_law.py`, `bridge/cosim_runner.py` | `test_cosim_control.py`, `test_closed_loop_buck.py` |
| CO-07 | A load sweep changes the switching rate of the real controller while the output stays on target | `docs/binary-runner-and-mcu-bringup.md` §5, `test_cosim_control.py` | `test_cosim_control.py::TestCosimEndToEnd::test_output_is_regulated_across_a_load_sweep` |
| CO-08 | A non-convergent netlist is rejected with a clear error instead of hanging the solver | `docs/validation.md` edge policy, `bridge/ngspice_wrapper.py` run failure path | `tests/test_solver_error_handling.py` |
| CO-09 | A malformed netlist raises a clear error within a timeout, never hanging the solver | `docs/validation.md` fault policy, `bridge/ngspice_wrapper.py` run path | `tests/test_solver_error_handling.py` |
| CO-10 | QEMU monitor error handling: dropped socket, stalled monitor, and out-of-range ADC values return a clear error within a timeout | `bridge/qemu_monitor.py` `_hmp`, `cycle_adc_and_gate` | `tests/test_fault_injection.py`, `tests/test_adversarial_stress.py`, `tests/test_qemu_monitor_unit.py` |
| CO-11 | The mock closed-loop simulation (M1 wall-clock sampled-data runner) regulates a buck converter to the documented target | `bridge/mock_controller.py`, `docs/binary-runner-and-mcu-bringup.md` | `test_closed_loop_buck.py` |
| CO-12 | Project format save/load and migration keep all declared state bit-for-bit | `cad_engine.py` save/load, `test_schematic_editor.py`, `test_cosim_control.py` | `test_schematic_editor.py`, `test_cosim_control.py` |
| CO-14 | The unit and component suite runs on every push to this branch (single ubuntu runner) | `.github/workflows/cosim-ci.yml` | `tests/test_ci_workflow.py` |
| CO-15 | Components without a profile and unknown analysis are reported as errors, never silently faked | `bridge/gpio_model.py`, `bridge/cad_engine.py` | `test_firmware_gpio.py`, `test_components_library.py` |

## Not-yet-implemented (NOT IMPLEMENTED, not passing)

| ID | Requirement | Reason | Tests |
|----|-------------|--------|-------|
| PERF-01 | Baseline soaks recorded on this machine | QEMU binary absent | recorded as UNEXECUTED |
| CO-13 | A soak of 10 minutes leaves memory flat and the drift within a documented bound | the "(soak marker)" test was never implemented; no soak runs in the suite today | none - tracked with the baseline soaks (PERF-01) |

All other requirements are implemented and green.

**SOL-01 retired (2026-10-29):** the row that claimed the real firmware
does not execute as the closed-loop controller is obsolete.
`bridge/binary_runner.py` now runs that loop — solver sense ->
`qom-set adc1-value` -> GPIO18 gate readback -> source callback each
timestep — measured as a gate flip at 1995/2030 through
`tools/run_emulator_tests.ps1` (3 passed, 0 skips, log #201) and as 10
loop runs / 30 flips with documented latency bounds (log #207). Its
reason, "patched QEMU does not expose the ADC model", is false for the
patched build: `adc1-value` is present (log #193-#199 locator work).
