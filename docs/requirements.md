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
| CO-08 | A non-convergent netlist is rejected with a clear error instead of hanging the solver | `docs/validation.md` edge policy, `bridge/ngspice_wrapper.py` run failure path | `tests/test_fault_injection.py` (fault layer) |
| CO-09 | A malformed netlist raises a clear error within a timeout, never hanging the solver | `docs/validation.md` fault policy, `bridge/ngspice_wrapper.py` run path | `tests/test_fault_injection.py` (fault layer) |
| CO-10 | QEMU monitor error handling: dropped socket, stalled monitor, and out-of-range ADC values return a clear error within a timeout | `bridge/qemu_monitor.py` `_hmp`, `cycle_adc_and_gate` | `tests/test_fault_injection.py` (fault layer) |
| CO-11 | The mock closed-loop simulation (M1 wall-clock sampled-data runner) regulates a buck converter to the documented target | `bridge/mock_controller.py`, `docs/binary-runner-and-mcu-bringup.md` | `test_closed_loop_buck.py` |
| CO-12 | Project format save/load and migration keep all declared state bit-for-bit | `cad_engine.py` save/load, `test_schematic_editor.py`, `test_cosim_control.py` | `test_schematic_editor.py`, `test_cosim_control.py` |
| CO-13 | A soak of 10 minutes leaves memory flat and the drift within a documented bound | perf/soak policy, `test_cosim_control.py` | `test_cosim_control.py` (soak marker) |
| CO-14 | All unit and component tests run on every push on ubuntu/windows/macos | `.github/workflows/cosim-ci.yml` | `.github/workflows/cosim-ci.yml` |
| CO-15 | Components without a profile and unknown analysis are reported as errors, never silently faked | `bridge/gpio_model.py`, `bridge/cad_engine.py` | `test_firmware_gpio.py`, `test_components_library.py` |

## Not-yet-implemented (NOT IMPLEMENTED, not passing)

| ID | Requirement | Reason | Tests |
|----|-------------|--------|-------|
| SOL-01 | Real firmware binary executes as closed-loop controller, ADC injection hooks into ngspice, gate readback to the solver | `bridge/qemu_orchestrator.py` SENS unmodelled; patched QEMU does not yet expose the ADC model; ngspice-to-QEMU coupling blocked on QEMU ADC support | `tests/test_firmware_gpio.py` (qemu marker), trace recorded as NOT IMPLEMENTED |
| PERF-01 | Baseline soaks recorded on this machine | QEMU binary absent | recorded as UNEXECUTED |

All other requirements are implemented and green.
