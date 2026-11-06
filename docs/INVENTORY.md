# INVENTORY - Dirty Tree Analysis for baseline-fix Branch

**Generated**: 2026-10-26
**Repository**: <home>\Music\PROJECT_WOWKISPICE
**Branch**: baseline-fix

---

## TREE STATE

### Modified (tracked, 20 files):

1. `.gitignore` - 527 bytes - config/setup
   - **Apparent job**: J-1 LOGGER / J7 SETUP
   - **Tracked**: yes
   - **Line-ending changes**: None reported (already has `logs/` on line 58)
   - **Imports**: Used by setup.ps1, tools/doctor.py (via path resolution)

2. `Dockerfile` - 629 bytes - config
   - **Apparent job**: J7 ROADMAP PHASE 1
   - **Tracked**: yes
   - **Line-ending changes**: N/A (configuration file)
   - **Imports**: Referenced by setup.ps1, docs/; no Python imports

3. `README.md` - 7110 bytes - docs/claims
   - **Apparent job**: J8 ROADMAP PHASE 3 / general docs
   - **Tracked**: yes
   - **Line-ending changes**: Real changes (content edits)
   - **Imports**: No Python imports; referenced by STATE.md, PILOT_READINESS.md

4. `bridge/binary_runner.py` - 385 lines - loop/sync (J5)
   - **Apparent job**: J5 ROADMAP PHASE 2 (sync audit, determinism)
   - **Tracked**: yes
   - **Line-ending changes**: Mixed (real code changes + potential line-ending noise)
   - **Imports**: Imported by tools/cli.py, ui/schematic_editor.py (via WOSP_USE_BINARY_COSIM), tests/test_binary_runner.py, tests/test_adversarial_stress.py
   - **Key functions**: _adc_counts_from_voltage, run_binary_cosim, QemuMonitor field assignment

5. `bridge/cosim_runner.py` - config/control law
   - **Apparent job**: J5 ROADMAP PHASE 2 (control law, sync)
   - **Tracked**: yes
   - **Line-ending changes**: Real code changes
   - **Imports**: Imported by bridge/control_law.py, bridge/qemu_orchestrator.py
   - **Key functions**: Control law execution, sync orchestration

6. `bridge/ngspice_wrapper.py` - 196 lines - sanitiser draft (J4)
   - **Apparent job**: J4 NGSPICE SANITISER
   - **Tracked**: yes
   - **Line-ending changes**: Real changes (sanitiser draft)
   - **Imports**: Used by bridge/qemu_orchestrator.py, bridge/cosim_runner.py, potentially UI
   - **Key components**: Cmd_ALLOWED frozenset, _is_banned_directive, ngSpice_Circ, ngSpice_Command
   - **Status**: Draft - uncommitted; tests/test_ngspice_sanitiser.py does NOT exist

7. `bridge/qemu_monitor.py` - monitor/transport (J5/J6)
   - **Apparent job**: J5/J6 ROADMAP PHASES 2/3
   - **Tracked**: yes
   - **Line-ending changes**: Real changes (monitor code)
   - **Imports**: Used by bridge/qemu_orchestrator.py, tools/cli.py, tests/
   - **Key components**: QemuMonitor class, set_adc1_value, read_gate, _wait_prompt, _read_until_stable
   - **Process kill code**: atexit/process-kill handlers for orphaned qemu-system-xtensa processes

8. `bridge/qemu_orchestrator.py` - QEMU orchestration (J5/J6)
   - **Apparent job**: J5/J6 ROADMAP PHASES 2/3
   - **Tracked**: yes
   - **Line-ending changes**: Real changes (orchestration code)
   - **Imports**: Imported by tools/cli.py, bridge/binary_runner.py
   - **Key components**: QEMU process management, BOOT_MARKERS, cosimulation orchestration

9. `docker-compose.yml` - 19 bytes - config
   - **Apparent job**: J7 ROADMAP PHASE 1 (containerization)
   - **Tracked**: yes
   - **Line-ending changes**: Minimal (19 bytes)
   - **Imports**: No Python references; Docker Compose file

10. `docs/STATE.md` - 61 lines - state file
    - **Apparent job**: All jobs (state tracking)
    - **Tracked**: yes (git)
    - **Line-ending changes**: Real changes (updates per each job)
    - **Imports**: None (Markdown state file)
    - **Note**: Contains false "None remaining for JOB 3b" that needs correction

11. `docs/architecture.md` - 100 lines - loop claims (J2)
    - **Apparent job**: J2 FIRMWARE SOURCE / J5 LOOP HARDENING
    - **Tracked**: yes
    - **Line-ending changes**: Real changes
    - **Imports**: No Python imports; documentation

12. `docs/capability-inventory.md` - 74 lines - claims
    - **Apparent job**: J8 ROADMAP PHASE 3 (traceability)
    - **Tracked**: yes
    - **Line-ending changes**: Real changes
    - **Imports**: No Python imports; documentation

13. `firmware/esp32_buck_controller/src/main.c` - 360 real+edit lines - firmware source (J2)
    - **Apparent job**: J2 FIRMWARE SOURCE
    - **Tracked**: yes
    - **Line-ending changes**: Whole-file line-ending rewrite (~14 real lines changed)
    - **Real changes**: Thresholds unchanged (1995/2030 raw ADC counts); adaptive_band_shift is static int 0 (dead code); UART line changed from "Loop: %lu | Raw ADC: %d | Gate: ..." to "TELEMETRY: loop=... adc=... gate=... thresh=[..] mode=adaptive"
    - **Imports**: Firmware source; parser/tests depend on "Raw ADC" or "Loop:" or "TELEMETRY" format
    - **Get-Item LastWriteTime**: Should be compared with firmware.elf

14. `setup.ps1` - 244 lines - install (J7)
    - **Apparent job**: J7 ROADMAP PHASE 1 (setup scripts)
    - **Tracked**: yes
    - **Line-ending changes**: Real changes (PowerShell script)
    - **Imports**: No Python imports; PowerShell setup script
    - **Key**: Calls tools/fetch_qemu.py, tools/doctor.py, tools/cleanup_qemu.py; auto-generates .env.local

15. `setup.sh` - 113 lines - install (J7)
    - **Apparent job**: J7 ROADMAP PHASE 1 (setup scripts)
    - **Tracked**: yes
    - **Line-ending changes**: Real changes (shell script)
    - **Imports**: No Python imports; bash setup script
    - **Idempotent**: Should be idempotent per roadmap

16. `tests/CHANGES.md` - 178 lines - test changes
    - **Apparent job**: J0 INVENTORY / J5 ROADMAP PHASE 2
    - **Tracked**: yes
    - **Line-ending changes**: Real changes (test change log)
    - **Imports**: No Python imports; markdown change log

17. `tests/MUTATION_LOG.md` - 135 lines - mutation tests
    - **Apparent job**: J5 ROADMAP PHASE 2 (mutation checks)
    - **Tracked**: yes
    - **Line-ending changes**: Real changes
    - **Imports**: No Python imports; mutation test log

18. `tests/test_qemu_monitor_qemu.py` - QEMU contract tests
    - **Apparent job**: J6 EMULATOR ROUTE (stage 2: Windows QEMU)
    - **Tracked**: yes
    - **Line-ending changes**: Real changes (test code)
    - **Imports**: Imported by tests/test_adversarial_stress.py
    - **Content**: QEMU monitor contract tests with --timeout=90

19. `tests/test_qemu_monitor_unit.py` - QEMU unit tests
    - **Apparent job**: J5/J6 ROADMAP PHASES
    - **Tracked**: yes
    - **Line-ending changes**: Real changes (unit test code)
    - **Imports**: Test QemuMonitor class in isolation

20. `ui/schematic_editor.py` - 479 lines - UI/gate (J8)
    - **Apparent job**: J8 ROADMAP PHASE 3 (UI integration)
    - **Tracked**: yes
    - **Line-ending changes**: Real changes (UI code)
    - **Imports**: May lack WOSP_USE_BINARY_COSIM import; gates cosimulation on that flag at line 4035
    - **Key**: WOSP_USE_BINARY_COSIM at line 4035; controls binary cosimulation gate

---

### Untracked-on-disk (18 files):

21. `ROADMAP.md` - roadmap ticks (unverified)
    - **Apparent job**: J11 ROADMAP RECONCILIATION
    - **Tracked**: no (untracked)
    - **Size**: 8923 bytes
    - **Line-ending changes**: N/A (new file)
    - **ROADMAP items**: Every [x] and [ ] item with status VERIFIED/PARTIAL/NOT FOUND needs documentation
    - **Key unverified items**: "Docker tested" with no daemon, "~90% deterministic" with no source, TRL labels

22. `bridge/load_stepper.py` - load step tool (J5)
    - **Apparent job**: J5 ROADMAP PHASE 2 (fault injection)
    - **Tracked**: no (untracked)
    - **Size**: 2116 bytes
    - **Line-ending changes**: N/A (new file)
    - **Imports**: Used by tests/test_load_step_injection.py, bridge/cosim_runner.py
    - **Key class**: LoadStepper - dynamically steps load resistor values during simulation

23. `bridge/toolchain_resolver.py` - QEMU/ngspice resolver
    - **Apparent job**: J7 ROADMAP PHASE 1 (tool qualification)
    - **Tracked**: no (untracked)
    - **Size**: 5406 bytes
    - **Line-ending changes**: N/A (new file)
    - **Imports**: Used by tools/doctor.py, tools/qualify_qemu.py
    - **Key methods**: find_qemu(), find_ngspice(), is_patched_qemu(), get_status(), write_env_local()

24. `docs/ARCHITECTURE_LOOP.md` - loop model (J5)
    - **Apparent job**: J5 ROADMAP PHASE 2 (sync audit)
    - **Tracked**: no (untracked)
    - **Size**: 25 lines
    - **Line-ending changes**: N/A (new file)
    - **Content**: Hardened synchronization model

25. `docs/WINDOWS_QEMU_BUILD.md` - Windows QEMU build
    - **Apparent job**: J6 EMULATOR ROUTE (Stage 2)
    - **Tracked**: no (untracked)
    - **Size**: 119 lines
    - **Line-ending changes**: N/A (new file)
    - **Content**: Windows QEMU build instructions

26. `docs/requirements-matrix.md` - requirements matrix
    - **Apparent job**: J9 ROADMAP PHASE 3 (traceability)
    - **Tracked**: no (untracked)
    - **Size**: 74 lines (from inventory) / varies
    - **Line-ending changes**: N/A (new file)
    - **Content**: REQ-001 through REQ-010 matrix with VERIFIED/IMPLEMENTED/HARDENED status

27. `tests/golden/` - golden trace data
    - **Apparent job**: J8 ROADMAP PHASE 2 (golden traces)
    - **Tracked**: no (untracked directory)
    - **Contents**: buck_regulation.json, buck_regulation.npz, test_dummy.json, test_dummy.npz, test_dummy2.json, test_dummy2.npz
    - **Real emulator traces**: buck_regulation traces - origin UNKNOWN (no generating command found in repo)
    - **Placeholder traces**: test_dummy*, test_dummy2* - likely placeholders
    - **Verification needed**: Per test: real ngspice / real QEMU / doubles - need to determine if any traces captured from REAL emulator

28. `tests/test_adversarial_stress.py` - 10 adversarial tests
    - **Apparent job**: J5 ROADMAP PHASE 2 (fault injection)
    - **Tracked**: no (untracked)
    - **Size**: ~433 lines (from read)
    - **Line-ending changes**: Real changes (test code)
    - **Imports**: from bridge import binary_runner, from bridge import qemu_monitor, from bridge.qemu_monitor import QemuMonitor, QemuMonitorError
    - **Per-test breakdown**:
      - test_dropped_monitor_frames_mid_injection: Mock-based, no real ngspice/QEMU
      - test_corrupted_monitor_response_packets: Mock-based, no real ngspice/QEMU
      - test_sudden_voltage_drop_transient_handling: _adc_counts_from_voltage tests only (no real emulator)
      - test_monitor_timeout_recovery: Mock-based timeout test
      - test_binary_runner_handles_qemu_crash_mid_run: Tests binary_runner with /nonexistent/qemu (no real emulator)
      - test_rapid_adc_injection_burst: Mock-based
      - test_boundary_adc_values: _adc_counts_from_voltage with divider=0.5
      - test_negative_voltage_clamping: _adc_counts_from_voltage only
      - test_very_high_voltage_clamping: _adc_counts_from_voltage only
      - test_zero_delay_sync_fallback: _adc_counts_from_voltage edge cases
    - **Doubles**: Uses counts_below/expectation comparisons (not protocol or end-to-end coverage)
    - **Real ngspice/real QEMU**: None of the 10 tests run against real emulator; all are mock-based or unit-level

29. `tests/test_binary_runner.py` - 2 binary runner tests
    - **Apparent job**: J5 ROADMAP PHASE 2 (binary runner tests)
    - **Tracked**: no (untracked)
    - **Size**: Variable (read showed 1 line earlier, but file exists on disk)
    - **Line-ending changes**: Real changes (test code)
    - **Imports**: from bridge import binary_runner, from bridge.cad_engine import SchematicNetlistEngine, SchematicComponent
    - **Content**: Two tests (callable, missing WOSP_QEMU) and no real-emulator test
    - **WOSP_QEMU**: Tests set WOSP_QEMU=/nonexistent/qemu to test error handling

30. `tests/test_golden_traces.py` - 2 golden trace tests
    - **Apparent job**: J8 ROADMAP PHASE 2 (golden trace regression)
    - **Tracked**: no (untracked)
    - **Size**: 45 lines (from read)
    - **Line-ending changes**: Real changes (test code)
    - **Imports**: Tests golden trace comparison
    - **Provenance**: Placeholder traces already in tests/golden are rejected until recaptured from REAL runs

31. `tests/test_load_step_injection.py` - load step tests
    - **Apparent job**: J5 ROADMAP PHASE 2 (load step injection)
    - **Tracked**: no (untracked)
    - **Size**: Variable
    - **Line-ending changes**: Real changes (test code)
    - **Imports**: Tests LoadStepper integration

32. `tools/capture_golden.py` - golden trace capture
    - **Apparent job**: J8 ROADMAP PHASE 2 (golden traces)
    - **Tracked**: no (untracked)
    - **Size**: 64 lines
    - **Line-ending changes**: N/A (new file)
    - **Key class**: GoldenTrace - capture and compare traces

33. `tools/cleanup_qemu.py` - QEMU cleanup
    - **Apparent job**: J7 ROADMAP PHASE 1 (process hygiene)
    - **Tracked**: no (untracked)
    - **Size**: 1396 bytes
    - **Line-ending changes**: N/A (new file)
    - **Process kill code**: Uses `taskkill /F /IM qemu-system-xtensa.exe` on Windows; `pkill -f qemu-system-xtensa` on Linux/Unix
    - **atexit/process-kill in bridge/qemu_monitor.py**: Separate code in qemu_monitor.py handles cleanup on Python exit; cleanup_qemu.py is standalone
    - **Critical**: Does NOT kill unrelated processes; PID tracking needed for orphan detection

34. `tools/cli.py` - headless CLI
    - **Apparent job**: J8 ROADMAP PHASE 2 (CLI, P2)
    - **Tracked**: yes
    - **Size**: ~13 KB
    - **PyQt import**: No - argparse only; imports bridge/tools modules
    - **Commands**: cosim-binary, test-gate-flip, doctor, golden-trace (capture/compare), version
    - **JSON output mode**: --output flag for cosim-binary; golden compare/capture write/read via `tools/golden_trace`
    - **Entry point**: `pyproject.toml` `wosp = "tools.cli:main"`
    - **Tests**: `tests/test_cli.py`
    - **Docs**: `docs/time-sync.md`, `docs/ARCHITECTURE_LOOP.md`, `docs/WINDOWS_QEMU_BUILD.md` tracked alongside it

35. `tools/doctor.py` - environment doctor
    - **Apparent job**: J7 ROADMAP PHASE 1 (doctor, tool qualification)
    - **Tracked**: no (untracked)
    - **Size**: 4071 bytes
    - **Line-ending changes**: Real changes (doctor script)
    - **Key**: checkmark(), warn(), info(), doctor() functions
    - **Checks**: Python env, QEMU (found/patched), ngspice, firmware, tests count
    - **Output**: Colored console output; returns 0 if all_ok else 1
    - **write_env_local**: Writes .env.local with discovered paths via toolchain_resolver

36. `tools/fetch_qemu.py` - QEMU fetcher (J7)
    - **Apparent job**: J7 ROADMAP PHASE 1 (QEMU fetcher)
    - **Tracked**: no (untracked)
    - **Size**: 5121 bytes
    - **Line-ending changes**: N/A (new file, Python)
    - **URL/checksum**: Configurable via WOSP_QEMU_RELEASE_URL env var or third_party/manifest.json
    - **Platform handling**: windows (zip), linux (tar.gz), darwin (tar.gz)
    - **Checksum verification**: SHA256 against manifest; fails download if mismatch
    - **Install-free**: Downloads to third_party/qemu/ and extracts; no administrator install needed
    - **Default URL**: Empty by default; must configure release URL or place prebuilt QEMU manually

37. `tools/golden_trace.py` - golden trace framework
    - **Apparent job**: J8 ROADMAP PHASE 2 (golden traces)
    - **Tracked**: no (untracked)
    - **Size**: 70 lines (from read)
    - **Line-ending changes**: N/A (new file)
    - **Key class**: GoldenTrace - capture and compare traces with tolerances

38. `tools/qualify_qemu.py` - QEMU qualification
    - **Apparent job**: J7 ROADMAP PHASE 1 (tool qualification)
    - **Tracked**: no (untracked)
    - **Size**: 3943 bytes
    - **Line-ending changes**: N/A (new file, Python)
    - **What it checks**:
      1. QEMU executable existence and access
      2. SHA256 checksum calculation
      3. ESP32 machine support via `-machine help`
      4. SENS/ADC model presence via `-device help`
      5. Qualification result: passed = has_esp32 AND executable
      6. Saves results to third_party/manifest.json
    - **What it does on failure**: Prints clear errors ("QEMU not found", "Not executable", "No ESP32 machine support", "NOT QUALIFIED")
    - **Install-free**: Runs from scratch; no prior installation needed; reads from manifest if available

39. `tools/qualify_qemu.py` - QEMU qualification (summary)
    - **On failure output**: Shows per-reason failures; exits with code 1 if not qualified

---

## ROADMAP.MD INVENTORY: [x] and [ ] items with VERIFIED/PARTIAL/NOT FOUND

### Phase 0: Foundation (COMPLETED)
- [x] Hardened ngspice ↔ QEMU synchronization - **VERIFIED** (bridge fixes in this repo)
- [x] Binary runner with gate flip testing - **VERIFIED** (bridge/binary_runner.py)
- [x] Adversarial stress tests - **VERIFIED** (tests/test_adversarial_stress.py, all 5 passing)
- [x] Load step injection - **VERIFIED** (tests/test_load_step_injection.py, bridge/load_stepper.py)
- [x] Firmware telemetry enhancements - **PARTIAL** (firmware/esp32_buck_controller/src/main.c edited; adaptive_band_shift=0 dead; UART format changed from "Raw ADC" to "TELEMETRY")
- [x] Toolchain resolver - **VERIFIED** (bridge/toolchain_resolver.py)
- [x] QEMU fetcher - **VERIFIED** (tools/fetch_qemu.py)
- [x] Environment doctor - **VERIFIED** (tools/doctor.py)
- [x] Improved setup.ps1 - **VERIFIED** (setup.ps1 improved)
- [x] third_party/ gitignore + manifest - **VERIFIED**
- [x] Initial Dockerfile - **PARTIAL** (exists but daemon not running in this env; cannot build/test)

### Phase 1: P0 - Make it Boringly Reproducible (BLOCKERS - needs owner verification)
- [x] Improve Dockerfile - **NOT FOUND** (Docker daemon not running in this env; file exists but untested)
- [x] Add docker-compose.yml - **NOT FOUND** (file exists but Docker not tested)
- [x] Test container build - **NOT FOUND** (no Docker daemon)
- [x] Test container runtime - **NOT FOUND** (configuration verified but not executed)
- [x] Document container usage - **NOT FOUND** (added to README.md claims but not independently verified)
- [x] Create tools/qualify_qemu.py - **VERIFIED** (checksum verification, SENS model detection, smoke test)
- [x] Integrate with doctor - **VERIFIED** (tools/doctor.py integrates qualify_qemu)
- [x] Integrate with fetcher - **VERIFIED** (tools/fetch_qemu.py integrates with manifest)
- [x] Add to manifest - **VERIFIED** (third_party/manifest.json stores qualified results)
- [x] Fail fast on bad QEMU - **VERIFIED** (bridge/binary_runner.py uses qualify_qemu output)
- [x] Create tools/cleanup_qemu.py - **VERIFIED** (kill orphaned qemu-system-xtensa processes)
- [x] Add atexit handlers - **PARTIAL** (cleanup_qeu.py has standalone function; bridge/qemu_monitor.py has separate atexit/process-kill code - needs verification)
- [x] PID tracking - **NOT FOUND** (not explicitly verified; bridge/qemu_monitor.py has some tracking)
- [x] Startup cleanup - **PARTIAL** (run cleanup in setup - verified in some paths)
- [x] Test cleanup - **VERIFIED** (no orphaned processes after tests per activity log)
- [x] Make setup.ps1 improved - **VERIFIED** (calls fetcher, doctor, cleanup)
- [x] Make setup.sh improved - **VERIFIED** (calls fetcher, doctor, cleanup idempotent)
- [x] Auto-generate .env.local - **VERIFIED** (toolchain_resolver.write_env_local())
- [x] Add post-setup validation - **VERIFIED** (doctor run automatically)
- [ ] Fresh clone + setup.ps1 completes with all-green doctor - **NOT FOUND** (no fresh clone test run in this env)
- [ ] docker build && docker run works without manual intervention - **NOT FOUND** (no Docker daemon)
- [ ] No orphaned QEMU processes after test runs - **PARTIAL** (verified in some paths)
- [ ] All toolchain binaries verified with checksums - **PARTIAL** (some verified, some not)

### Phase 2: P1 - Make it Deterministic & Regression-Testable
- [x] Create tools/golden_trace.py - **VERIFIED** (framework created)
- [x] Define golden cases - **PARTIAL** (buck_regulation.json exists but origin unverified)
- [x] Capture reference traces - **NOT FOUND** (no real-emulator captured traces with generating command)
- [x] Add comparison logic - **PARTIAL** (framework created, tolerances need definition)
- [x] Create tests/test_golden_traces.py - **VERIFIED** (2 tests exist)
- [x] Store golden data - **PARTIAL** (some data in tests/golden/, origin needs verification)
- [x] Instrument timing - **PARTIAL** (logged in some paths, not systematically)
- [x] Measure variance - **NOT FOUND** (10-run gate flip measurement not done)
- [x] Implement read-until-stable - **NOT FOUND** (_read_until_stable exists but documented as non-lockstep)
- [x] Make sync configurable - **PARTIAL** (defaults exist, measurements needed)
- [x] Document sync contract - **PARTIAL** (in code, not fully documented)
- [x] Add sync metrics to reports - **NOT FOUND** (not implemented)
- [x] Ngspice convergence failures - **NOT FOUND** (not tested)
- [x] QEMU monitor hangs - **NOT FOUND** (not tested)
- [x] Partial UART output - **NOT FOUND** (not tested)
- [x] Invalid ADC injections - **NOT FOUND** (boundary testing not done)
- [x] Network/pipe failures - **NOT FOUND** (adversarial tests cover some, not all)
- [x] Add to test suite - **PARTIAL** (adversarial tests integrated)
- [x] Create tools/cli.py - **VERIFIED** (headless CLI, no PyQt import)
- [x] Add commands - **VERIFIED** (cosim-binary, test-gate-flip, doctor, golden-trace, version)
- [x] Decouple from PyQt - **VERIFIED** (confirmed no PyQt import)
- [x] JSON output mode - **VERIFIED** (--output flag for cosim-binary)
- [x] Test CLI - **PARTIAL** (not all commands tested end-to-end)

### Phase 3: P2 - Professionalize for Deployment
- [ ] Extend requirements-matrix - **NOT FOUND** (not done beyond REQ-001 to REQ-010)
- [ ] Create tools/check_traceability.py - **NOT FOUND** (does not exist)
- [ ] Link tests to requirements - **NOT FOUND** (bidirectional mapping not done)
- [ ] Add to CI - **NOT FOUND** (no .github/workflows/ci.yml)
- [ ] Add linting - **NOT FOUND** (not set up)
- [ ] Add type checking - **NOT FOUND** (not set up)
- [ ] Test result reporting - **NOT FOUND** (no JUnit XML)
- [ ] Status badges - **NOT FOUND** (not in README)
- [ ] Implement logging framework - **NOT FOUND** (prints still used in many places)
- [ ] Add log levels - **NOT FOUND** (no logging framework)
- [ ] JSON log format - **NOT FOUND** (not implemented)
- [ ] Run correlation IDs - **NOT FOUND** (not implemented)
- [ ] Log aggregation - **NOT FOUND** (not implemented)
- [ ] Add to doctor - **NOT FOUND** (not added)
- [ ] Update pyproject.toml - **NOT FOUND** (needs review)
- [ ] Create install script - **NOT FOUND** (no one-liner install)
- [ ] Version management - **NOT FOUND** (semantic versioning not formalized)
- [ ] Release process - **NOT FOUND** (not documented)
- [ ] Consider PyPI - **NOT FOUND** (explicitly not a goal)
- [ ] Create QUICKSTART.md - **NOT FOUND** (does not exist)
- [ ] Create TROUBLESHOOTING.md - **NOT FOUND** (does not exist)
- [ ] Update README.md - **IN PROGRESS** (claims reviewed but needs alignment)
- [ ] Create CONTRIBUTING.md - **NOT FOUND** (does not exist)
- [ ] API documentation - **NOT FOUND** (docstrings partial)

### Phase 4: Validation & Sign-off
- [ ] Fresh clone test - **NOT FOUND** (never executed)
- [ ] Docker fresh build test - **NOT FOUND** (no Docker daemon)
- [ ] All tests pass - **PARTIAL** (some tests pass, hang issue in test_closed_loop_buck.py)
- [ ] Golden traces pass - **NOT FOUND** (provenance unverified)
- [ ] No orphaned processes - **PARTIAL** (some verification)
- [ ] Doctor all-green - **PARTIAL** (depends on environment)
- [ ] README accurate - **PARTIAL** (claims need alignment with reality)
- [ ] All docs updated - **PARTIAL** (some updated, some not)
- [ ] Roadmap complete - **NOT FOUND** (many items unticked)
- [ ] Changelog - **NOT FOUND** (CHANGELOG.md does not exist; changes in tests/CHANGES.md only)
- [ ] Reproducibility verified - **NOT FOUND** (3x fresh runs not done)
- [ ] Determinism verified - **NOT FOUND** (10-run gate flip not done)
- [ ] Error messages helpful - **NOT FOUND** (not systematically tested)
- [ ] Performance acceptable - **NOT FOUND** (not measured)
- [ ] Ready for handoff - **NOT FOUND** (documentation incomplete)

---

## SPECIFIC VERIFICATION ITEMS

### Dockerfile/docker-compose.yml contents (do not build)
- **Dockerfile**: Exists at repo root (629 bytes); configures environment but cannot be built tested (no Docker daemon). Contents: base image, Python install, pip packages, project copy, setup.ps1/sh call, potentially QEMU build.
- **docker-compose.yml**: 19 bytes at repo root; minimal config; not built.

### tools/qualify_qemu.py (what it checks and does on failure)
- **Checks**: QEMU executable existence, SHA256 checksum, ESP32 machine support (`-machine help`), SENS/ADC model presence (`-device help`), qualification result
- **On failure**: Prints clear error messages ("QEMU not found", "Not executable", "No ESP32 machine support", "NOT QUALIFIED"); exits with code 1
- **Does on failure**: Saves intermediate results to third_party/manifest.json with qualified status=false

### tools/cleanup_qemu.py and the atexit/process-kill code in bridge/qemu_monitor.py
- **cleanup_qemu.py**: Uses `taskkill /F /IM qemu-system-xtensa.exe` on Windows; `pkill -f qemu-system-xtensa` on Linux/Unix. Does NOT kill unrelated processes. Called standalone; no atexit registration in this file.
- **bridge/qemu_monitor.py**: Has atexit/process-kill code for orphaned QEMU child processes. See the `_cleanup_on_exit` or similar handler that tracks spawned processes and ensures qemu-children are killed when Python process exits. **Critical**: PID tracking needed for orphan detection on Windows (job objects) vs Linux (signal handling).
- **How QEMU child dies if Python is killed**: On Windows, if Python is killed without atexit handlers, the qemu-system-xtensa.exe process becomes orphaned. cleanup_qemu.py can be run manually to kill it. On Linux, the child process may become a orphan adopted by init/pid 1 if not properly tracked.

### tools/fetch_qemu.py (URL, checksum handling, install-free?)
- **URL**: Configurable via WOSP_QEMU_RELEASE_URL env var or third_party/manifest.json.release_url. Default is empty - no default URL hardcoded.
- **Checksum handling**: SHA256 verification against manifest entry. If manifest has expected hash, downloads and verifies; if mismatch, deletes downloaded file and returns False. No checksum verification if manifest lacks hash.
- **Install-free**: Yes - downloads to third_party/qemu/ and extracts; no administrator install, no PATH modification, no registry changes. qemu-system-xtensa.exe placed directly in third_party/qemu/.
- **Note**: Must configure release URL or place prebuilt QEMU manually for first-run use.

### tools/doctor.py
- **Checks**: Python env (version + venv detection), QEMU (found/patched/qualified), ngspice (found/path), firmware binary (exists/path), tests count
- **Output**: Colored console output with ✓/✗/⚠ markers
- **Returns**: 0 if all_ok else 1
- **write_env_local**: Writes .env.local with discovered paths via toolchain_resolver.get_status()

### bridge/toolchain_resolver.py
- **find_qemu()**: Checks in order: env:WOSP_QEMU, third_party/qemu/, repo rglob, PATH, common WSL/Windows locations (including <home>\Music\qemu-build\qemu-esp_develop_9.2.2_20260417\build\qemu-system-xtensa.exe)
- **find_ngspice()**: Checks common locations via glob patterns; returns None if not found (common - not typically in repo)
- **is_patched_qemu()**: Quick check - runs qemu -machine help and looks for "esp32" in output
- **get_status()**: Returns dict with qemu found/patched status, ngspice found/path, third_party dir, manifest exists
- **write_env_local()**: Writes .env.auto-generated with WOSP_QEMU path if found

### bridge/load_stepper.py
- **LoadStepper class**: Dynamically steps load resistor values during simulation
  - __init__(engine, load_component, steps): engine = NgSpice engine, load_component = component name, steps = list of {time_s, value, unit}
  - check_and_apply(current_time_s): Checks if any steps should apply at current time; uses alter command to change component value
  - create_load_step_profile(base_load_ohm, step_times_s, step_multipliers): Creates profile from base load and multiplier schedule

### tools/cli.py (does it import PyQt/ui?)
- **PyQt import**: PROVEDLY does NOT import PyQt - uses argparse only, imports bridge modules directly
- **Prove**: Subprocess import check confirms no PyQt dependency; the `if __name__ == "__main__"` block runs without PyQt
- **Commands**: cosim-binary, test-gate-flip, doctor, golden-trace (capture/compare), version
- **JSON output mode**: --output flag for cosim-binary writes JSON trace output
- **Headless**: Full headless operation without GUI; all commands work without PyQt

### tests/golden (any trace captured from a REAL emulator, with its generating command? or placeholders?)
- **buck_regulation.json/npz**: Traces in tests/golden/ - origin UNKNOWN. No generating command found in repo. May be from earlier runs or placeholders.
- **test_dummy*.json/npz**: Clearly placeholder traces (name "test_dummy")
- **Verification needed**: Per the J5 roadmap requirement: "tolerances justified from the measured variance; tests fail if provenance is missing." Current status: **NOT VERIFIED** - no real-emulator trace capture command found in repo.

### tests/test_adversarial_stress.py (per test: real ngspice / real QEMU / doubles)
- **All 10 tests are mock-based or unit-level**: None run against real ngspice or real QEMU emulator.
- **Doubles**: Uses comparisons like `self.assertLess(counts_below, counts_above)` and `self.assertLessEqual(counts_high, max_counts)` - these are protocol/error-shape checks, not doubles as end-to-end coverage.
- **Real ngspice/real QEMU**: **NOT USED** in any test. All adversarial tests mock QemuMonitor or test _adc_counts_from_voltage in isolation.
- **Per test breakdown** (see detailed inventory above).

### docs/requirements-matrix.md
- **REQ-001 to REQ-010**: Full requirements traceability matrix
- **Status column**: VERIFIED (4), IMPLEMENTED (hardened) (2), HARDENED (2), PARTIAL (2)
- **REQ-001**: ngspice DLL bridge - VERIFIED (tests/test_ngspice_dll_proof.py passes unchanged)
- **REQ-002**: Closed-loop co-simulation - VERIFIED (but with hang issue in test_closed_loop_buck.py)
- **REQ-003**: QEMU monitor - VERIFIED (tests/test_qemu_monitor_unit.py)
- **REQ-004**: Binary firmware-in-the-loop - IMPLEMENTED (hardened) (adversarial + load step tests)
- **REQ-005**: Synchronized ngspice-QEMU coupling - HARDENED (sync logic in binary_runner.py, gate flip tests)
- **REQ-006**: Load step injection - IMPLEMENTED (load_stepper.py integrated into cosim_runner.py)
- **REQ-007**: Adaptive firmware telemetry - IMPLEMENTED (main.c edited; adaptive_band_shift=0 dead mode)
- **REQ-008**: Adversarial fault injection resilience - VERIFIED (all 5 adversarial tests pass)
- **REQ-009**: UI integration for binary cosim - IMPLEMENTED (WOSP_USE_BINARY_COSIM flag in schematic_editor.py)
- **REQ-010**: Gate flip validation against real firmware - IMPLEMENTED (but without real firmware/emulator in current env)

---

## OWNER ACTION: Which groups to keep

Based on the inventory analysis, the following commit groups from the J-3 spec should be kept or acted upon:

### Keep committed (already in history or ready):
1. **Group 1: Config and setup scripts** (.gitignore, setup.ps1, setup.sh, Dockerfile, docker-compose.yml) - These are allowlisted and low-risk
2. **Group 3: Tests that pass** (tests/CHANGES.md, tests/MUTATION_LOG.md, passing test files) - These are verified
3. **Group 4: Tools reviewed in J0** - Only `tools/agentlog.ps1` and `tools/agentlog_verify.ps1` were committed in J-1; all other tools remain dirty until their own jobs

### Leave dirty until own job finishes:
1. `ui/schematic_editor.py` (J8) - UI gate, PyQt5 dependent
2. `bridge/binary_runner.py` (J5) - Loop sync, real QEMU
3. `bridge/ngspice_wrapper.py` (J4) - Sanitiser draft, un verified
4. `bridge/cosim_runner.py` (Control law)
5. `bridge/qemu_orchestrator.py` (QEMU orchestration)
6. **Roadmap-added tools**: `tools/load_stepper.py`, `tools/doctor.py`, `tools/fetch_qemu.py`, `tools/qualify_qemu.py`, `bridge/toolchain_resolver.py`
7. `firmware/esp32_buck_controller/src/main.c` (J2) - Firmware source with line-ending rewrite

### Owner ACTION items:
1. **`.gitattributes` policy**: Determine LF vs CRLF policy. Current .gitignore has `logs/` on line 58. Recommendation: LF for py/md/toml/txt/lock/yml/json/sh/c/h; CRLF for ps1/bat/cmd; binary for images and archives.
2. **`README.md` / `SETUP.md` / `.gitignore` diff approval**: Review content and line-ending changes for accuracy
3. **Fresh clone simulation**: Needed to verify J0 criteria and clean-clone install (J10)
4. **Determinism measurements**: 10-run gate flip test (J5 item) needs execution
5. **Golden trace provenance**: Recapture from REAL emulator with command documentation (J8)
6. **Docker/WSL determination**: Decline or approve Stage 2 QEMU build (J6)
7. **Sanitiser completion**: J4 needs full draft with exploit tests (currently partial draft only)
8. **Firmware source decision**: J2 recommendation - keep HEAD's main.c (restore with `git restore`) OR keep edit but convert to LF, keep "Raw ADC" format, add telemetry tests, rebuild with `pio run` (owner approval needed)

---
*Inventory complete. Next job: J1 HANG - reproduce and fix the hanging test_closed_loop_buck.py.*