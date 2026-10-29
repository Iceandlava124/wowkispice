# Known issues and TODO

This file lists the open items left by Tasks 1-7 and 8 for the project
owner to decide on. Nothing here is a claim about the state of the code;
it is a decision log. Items are one line each; multiple paragraphs mean
the item is a known bug with reproduced output.

## 2026-10-24 verification pass

Current verified state on the dev box (Windows + WSL Ubuntu, Python 3.12.10):

- Windows suite (`python tools/run_tests.py`): **363 passed, 2 skipped,
  exit 0** — the 2 skips are the real-QEMU contract tests, UNEXECUTED on
  the Windows side because the built QEMU is a Linux binary (run them under
  WSL, see below).
- `run_selfcheck.bat` (fresh clone, see item 4): **SELF-CHECK: PASS**.
- **Real-QEMU contract tests EXECUTED under WSL**: both tests in
  `tests/test_qemu_monitor_qemu.py` pass against the freshly built
  `qemu-system-xtensa` (ADC injection via `qom-set`, GPIO18 readback via
  `xp`). The bridge was proven against the real emulator, not a double.
- The Task 7/8 failure lists further below (items 7, 8, 10) are **stale**:
  those tests pass as of this pass; they are kept as history, not as open
  blockers.

1. **PyQt5 5.15.9 segfaults at import on this platform (FIXED by pin).**
   Symptom: any process importing `pyqtgraph` died with 0xC0000005
   (Windows access violation, exit 3221225477) at
   `pyqtgraph/graphicsItems/GraphicsWidget.py` class definition — a sip
   multiple-inheritance type creation, not a pyqtgraph bug. Reproduced with
   pyqtgraph 0.13.1, 0.13.3, 0.13.7 and 0.14.0 and with PyQt5-sip 12.13.0
   and 12.20.0; plain `QtWidgets.QGraphicsWidget()` worked, isolating the
   defect to the PyQt5 5.15.9 wheel. Fix: `PyQt5==5.15.11` (now the floor
   in `requirements.txt` and the pin in `requirements.lock`). This had
   silently disabled 6 UI test files; they now run and pass.
2. **QEMU rebuild VERIFIED (was: blocked on meson/sudo).** meson 1.12.1
   installed into WSL user site without sudo (`pip install --user
   --break-system-packages meson`); `./configure --target-list=xtensa-softmmu
   <builddir>` + `ninja -C build qemu-system-xtensa` produced
   `qemu-system-xtensa` 9.2.2 with the esp32_sens patch and the
   immediate-conversion timer fix. Build output lives outside this repo at
   `<home>\Music\qemu-build\qemu-esp_develop_9.2.2_20260417\build`.
3. **`bridge/qemu_monitor.py`'s monitor path had never run (FIXED).**
   `start()` launched QEMU with `stdout=DEVNULL` and no stdin pipe, so
   `_hmp()` could not talk to it at all; the HMP protocol was also
   mis-modelled (readline vs readline-echo-with-ANSI + prompt-without-newline).
   Rewritten against the real wire format (verified by probe): `-monitor
   stdio -serial none`, reader thread, prompt-delimited replies, ANSI-stripped
   echo removal, `xp` reply parsed as `addr: value`, and `Error:` replies from
   `qom-set` raised as `QemuMonitorError` so a wrong QEMU build fails loudly.
4. **setup.ps1 reported success on a machine where it had failed (FIXED).**
   With MSYS2's `python` first on PATH, `venv` produced a `bin/`-layout env,
   every `$VenvPy` call then raised CommandNotFound, and a stale
   `$LASTEXITCODE=0` made the probe read as success — the script printed
   "libngspice is already present" and exited 0 with nothing set up. Fixes:
   interpreter selection (py launcher -3.12 → -3 → python; rejects non-win32
   sys.platform and non-`win-*` distutils platform, which catches MSYS2's
   native-looking but bin/-layout build), a hard `Test-Path` layout guard
   after venv creation, and `$LASTEXITCODE` reset before both probes. Verified:
   a pristine copy of the repo bootstrapped from scratch (venv → deps →
   checksum-verified ngspice download → BIND_OK → full suite 363 passed
   → SELF-CHECK: PASS).
5. **Two-track emulator gate: runnable, and impossible to ignore silently.**
   Track A (`tools/run_tests.py`) keeps default skips but every qemu-marker
   skip reason now names the exact missing item (unset `WOSP_QEMU` / binary
   not found at `<path>` / Linux ELF seen from Windows); the new
   `--require-emulator` flag turns any such skip into exit 3. Track B
   (`tools/run_emulator_tests.ps1`) checks `wsl --status`, prints which
   locator found the binary, runs the documented `wsl -- bash -lc` pytest
   command, prints the summary, and exits non-zero on WSL-missing,
   binary-missing, any skip, or any failure. Verified 2026-10-24: Track A
   default 363+2 UNEXECUTED, `--require-emulator` fails without the binary,
   Track B passes 2/2 against the real emulator.
6. **`bridge/emulator_orchestrator.py` is UNVERIFIED / NOT IN USE: no
   esp-emu binary exists.** Facts from a read-only survey on 2026-10-24:
   - No Rust emulator source in the tree: zero `Cargo.toml` and zero `*.rs`
     files (filesystem listing and `git ls-files` agree).
   - No toolchain on this machine: `cargo`, `rustc` and `esp-emu` are all
     NOT FOUND, and no download link for an emulator binary exists anywhere
     in the repo (the only emulator URL in the repo is the Espressif *QEMU
     source* clone).
   - The module is imported by nothing (a repo-wide search for
     `emulator_orchestrator` matches only the file itself) and it launches a
     binary at `~\.local\bin\esp-emu.exe` (`WOSP_EMU` / `DEFAULT_EMU`) that
     does not exist on this machine.
   - Its docstring cites `tests/test_wsl_qmp_cycle.py` — a file deleted by
     the same commit that added the module.
   - **The 60522dc flip-flop:** commit `60522dc` (2026-10-18, "Switch
     filesystem from QEMU Linux ELF to native Windows esp-emu") deleted
     `tools/qemu-patch/`, the QEMU-gated tests and the `qemu_monitor` shim
     in order to switch to esp-emu. The switch was never finished: no binary,
     no source, no licence, no test ever ran. Commit `b2d8a43` (2026-10-22)
     then wired the automatic ngspice<->QEMU bridge instead, so the repo
     went back to QEMU while the orphaned esp-emu module stayed behind.
     The module's docstring now carries an "UNVERIFIED / NOT IN USE" banner;
     no code was changed.
   - The only emulator verified on this box is the patched Espressif QEMU
     built in WSL2: the contract tests pass 2/2 against it (item 5 above).
   **OWNER DECISION — pick one:**
   (a) **delete** `bridge/emulator_orchestrator.py` (nothing imports it);
   (b) **keep it as a stub** under the banner, documented as not-in-use;
   (c) **supply the binary** together with its source and licence, add a
   working test, and only then remove the banner.

## 2026-10-25 — patched-QEMU provenance (reproducibility pass)

1. **Provenance of the running binary: a local source tree, not this
   repo.** The `qemu-system-xtensa` used by Track B was built from
   `<home>\Music\qemu-build\qemu-esp_develop_9.2.2_20260417`
   (WSL `/mnt/c/...`): pinned tag `esp-develop-9.2.2-20260417` (commit
   `40edcca`) + commit `478892a` (the 0001 model content as a commit) + one
   working-tree edit (the immediate-conversion fix, now exported as 0002)
   + an unrelated `scripts/symlink-install-tree.py` local hack that is
   excluded from both patches.
2. **Both patches now exist in the repo worktree (pending commit).**
   `tools/qemu-patch/0001-...` recovered byte-exactly from `60522dc^`
   (sha256 `1b67e3ae...`, matches `Get-FileHash` to the git blob);
   `0002-...` exported from the build tree's working diff of
   `hw/misc/esp32_sens.c` (sha256 `d26ad451...`, pure LF).
3. **Does the on-disk 0001 match what was actually built? — step 3 showed
   YES for the source.** Two pieces of evidence: (a) `git show --format=
   478892a` in the build tree is byte-identical to the recovered 0001;
   (b) in a fresh scratch clone at the pinned tag, `git apply --check` +
   `git apply` of 0001 then 0002 both exited 0, and the resulting six
   patched files are byte-identical to the build tree (`diff` of
   `hw/misc/esp32_sens.c` empty; the other five clean under `diff -q`).
   **Still unresolved:** whether the binary in `qemu-build/.../build/` was
   actually compiled from exactly that source state — no build log in this
   repo links binary → source.
4. **UNVERIFIED: "binary rebuilt from patches 0001+0002 from scratch."**
   No from-scratch rebuild was run (not part of this pass). Proposed but
   not executed: on the pinned tag with 0001 then 0002 applied, run
   SETUP.md Part E's line — `./configure --target-list=xtensa-softmmu
   --disable-docs --disable-gtk --disable-sdl --disable-vnc --disable-spice
   --enable-slirp && ninja -C build` — then record
   `./build/qemu-system-xtensa --version` and the binary's sha256 here.
   **Owner decision:** run it once and close this item.
5. **Leftover:** the untracked helper `tools/build_qemu.sh` still applies
   only 0001; it needs the 0002 step (file was outside this pass's
   allowlist). Likewise SETUP.md Part E's apply block still shows only
   0001 — the exact two-patch command is documented in
   `tools/qemu-patch/README.md`.

## End of Task 7 items

1. **Firmware build is CPU-bound and hits the 2-minute timeout on this box.**
   `pio run --environment esp32dev` compiles FreeRTOS + lwIP + the app in a
   few minutes on a 4-core box, then the build *appears* to stall inside
   the linker/driver compile loop. The gate in
   `docs/toolchain.md` §6 therefore requires a machine with more cores to
   run and paste the output; the checksum table in `toolchain.md` is still
   unfilled until a real `qemu_flash.bin` is produced. **Owner decision:**
   how long the gate timeout is and whether CI uses a larger runner.
2. **QEMU and the patched `esp32_sens` build are not run on this machine.**
   `docs/toolchain.md` §6 and `docs/platform-support.md` mark the QEMU/FIRMWARE
   steps **UNVERIFIED**; the only verified parts are the ngspice
   `.dll` physics proofs. **Owner decision:** provide the pinned QEMU
   (Espressif publish it at the commit/tag documented in
   `docs/toolchain.md` §1) and a `qemu_flash.bin` so the boot test can be
   gated.
3. **The automatic ngspice↔QEMU bridge is not implemented.**

   `bridge/qemu_orchestrator.py` boots the firmware and reads the UART; it
   does not inject ADC values or read the gate decision back into the
   solver. See `docs/architectures.md` and `docs/binary-runner-and-mcu-bringup.md`
   M1. **Owner decision:** whether the bridge is a separate tool or part of
   the editor; it is the Phase-1 deliverable in `systems-map.md` §4/§8.
4. **`tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch` is not
   in git.** `git ls-files tools/qemu-patch` is empty in this checkout, so a
   clean clone cannot reproduce the exact patch by itself; the commit/tag pin
   and the build procedure are documented in `docs/toolchain.md` §1. **Owner
   decision:** re-include the patch in the repo (or provide a
   release-asset/download step) and fill the checksum table.
5. **Firmware calibration is unvalidated against hardware.** `firmware/src/main.c`
   reports thresholds in raw counts; the eFuse calculation path exists but is
   not exercised against a board. `docs/hardware-validation-protocol.md` is
   written to measure this; it has not been executed. **Owner decision:**
   run the resistor-divider protocol and paste the results.
6. **ngspice `.dll` is encrypted at rest.** `tools/ngspice-47_dll_64.7z` is a
   4.4 MB encrypted archive holding the Windows `ngspice.dll` and its DLLs.
   The key is held by the owner; `setup.ps1` is the documented unlock step.
   **Owner decision:** make the unlock reproducible (offer a script or
   regenerate the archive) so a clean clone can build the physics proofs.
7. **Each failure is a real blocking defect and must be fixed before Phase 1**
   (gate: `python tools/run_tests.py` exits 0). Expected blockers:
   - `test_editor_workflow.py` (2 failures, 2 errors):
     `test_roll_forward_after_select_and_modify` and
     `test_confirm_set` still assert the legacy `selected_level` naming;
     the editor now reports `getSelectedLevel()` per the audit. Fix the
     assertions against the contract the tests describe.
   - `test_schematic_editor.py` (12 failures, 4 errors):
     `test_component_refresh_on_wire_change` and the selection/undo cases
     assert the pre-audit behavior; the audit refactored `selectItem`/`undo`
     to act on the `selectedItem` singleton, so the tests must be updated to
     the audit contract.
   - `test_studio_suite.py` (6 errors) and `test_sota_suite.py` (1 error):
     the legacy gallery/studio harness still imports
     `tools/studio_engine.py` (which was moved to
     `bridge/studio_engine.py`) under a name the test cannot resolve.
     Fix the import, or keep the old name as an alias for the gallery
     harness, and then regenerate the suite test list to remove the broken
     entries it records.
   - `test_ui_polish.py` (1 failure, 11 errors): `test_cursor_readout_without_a_pixel_names_a_visible_trace`
     and `test_clicking_a_trace_row_chooses_what_the_cursor_measures` read
     `win._last_time[0]` which is not set by the harness that drives the
     editor headlessly. Fix the harness to set `_last_time` before driving
     the click, and `test_trace_list_is_rebuilt_and_visibility_is_honoured`
     which fails on a stale trace list; the fix is on the test side, not a
     code change.
   - `test_ngspice_dll_proof.py` / `test_ngspice_bridge.py` (5 failures):
     the `load_circuit` contract changed in Task 4: a banned directive now
     surfaces as a `RuntimeError` rather than returning 0. The tests assert
     the old contract and must be rewritten to:
     1. expect a `RuntimeError` from `load_circuit` on the malicious netlist,
     2. assert the marker file is never created,
     3. assert the sanitiser error is deterministic.
   - `ngspice_wrapper.py` raises a `UnboundLocalError` when the log is not a
     `list` and the wrapper is used. The public API exports
     `self.output_logs` as a `list[str]`; the sanitiser, the wrapper's own
     `_cb_*` callbacks, and the test harness must all write to a `list`.
8. **The sanitiser (ban-list for untrusted netlists) and the ngspice
   bridge tests are incompatible.** `bridge/ngspice_wrapper.py` rejects
   **every** solver directive, including `.tran` (the transient-analysis
   card the tests rely on). Commit `3ed68a6` added the sanitiser; `6b7f433`
   added the tests (both shown in `git log --oneline bridge/ngspice_wrapper.py`,
   `tests/test_ngspice_bridge.py`). The tests therefore fail with
   `RuntimeError: ngSpice_Circ rejected the untrusted netlist` and zero
   returned points. Reproduced on this box; a `git checkout 6b7f433~1`
   (pre-saniatiserr) makes the two files pass. Owner decision: remove
   `.tran`/`.ac`/`.ic`/`.dc`/`.step`/`.options` from the ban list, or
   rewrite the two test files as sanitiser-contract tests, or do both.

## End of Task 8 items

8. **No performance measurements for the ngspice bridge.** None of the
   proof harnesses measure wall-clock time or memory.
9. **No formal license audit.** The third-party notices say "Apache-2.0"
   and "GPLv2+", but the component licenses were read from the upstream
   LICENSE files only; the ngspice DLL is 4.4 MB and encrypted, so it was
   not inspected.
10. **The Task 7/Task 8 blocker list is stale.** The failures above are no
   longer only the Task 7 set: `test_ngspice_dll_proof.py` and
   `test_ngspice_bridge.py` are now failing on this machine because the
   sanitiser in `3ed68a6` rejects the `.tran` card the tests require.
   Task 8's value-add (docs, naming, formatting, messages, structure)   must not regress those tests; the sanitiser bug (issue 8) is a blocker for
   that list, not part of it.

## JOB 3 findings — QEMU monitor coupling (2026-10-25)

Found while auditing and repairing `tests/test_qemu_monitor_unit.py` and
`tests/test_firmware_gpio.py`. None of these are fixed here: `bridge/` was
outside this job's allowlist. Each is a real defect a reviewer can check
against the named lines.

1. **Two classes are named `QemuMonitor`, and one of them is dead code.**
   - `bridge/qemu_monitor.py:36` — stdio/HMP implementation: `start()` Popen's
     `[qemu, -display none, -machine esp32, -monitor stdio, -serial none]`
     (line 86), a reader thread fills a buffer, `_hmp()` (line 216) waits for
     the `(qemu) ` prompt (line 128), strips ANSI (line 214) and the echo line
     (line 239), and `read_gate()` parses `xp` as `addr: value` (lines
     201-204). `cycle_adc_and_gate` is at line 245, `sweep_report` at 293.
   - `bridge/qemu_orchestrator.py:49` — a session-based implementation with
     its own `cycle_adc_and_gate` (line 90) and `sweep_report` (line 103),
     written for the older TCP/`-monitor tcp:` launch style.
   - **The orchestrator versions are unreachable:** line 116 of that same file
     does `from bridge.qemu_monitor import QemuMonitor, cycle_adc_and_gate,
     sweep_report`, which overwrites the module attributes defined at lines
     49/90/103. Nothing outside the file references them.
   - The dead variant is also wrong if ever revived: its `_hmp` uses
     `stdout.readline()`, which cannot see a prompt that has no trailing
     newline; `read_gate()` does `int(raw, 16)` on the whole reply, which
     raises on real HMP output shaped `000000003ff44004: 0x00040000`; and its
     success message calls `mon.read_gate()` a SECOND time (so `gate_high` and
     the message can disagree, and each cycle costs two HMP round trips).
   **OWNER DECISION — pick one:** (a) delete the shadowed local
   `QemuMonitor`/`cycle_adc_and_gate`/`sweep_report` from
   `bridge/qemu_orchestrator.py` and import from `bridge.qemu_monitor`
   explicitly; (b) rename the session-based variant and keep both with a
   documented split of responsibility; (c) declare `bridge/qemu_monitor.py`
   the single canonical module and make everything else a re-export shim
   (the pattern `bridge/firmware_runner.py` already follows).

2. **Neither `QemuMonitor` is used by the live demo or the co-simulation
   path.** `tools/demo_closed_loop.py` boots QEMU itself with
   `-monitor tcp:127.0.0.1:<port>` (line 192) and speaks HMP inline through its
   own `hmp_cmd()` (qom-set at line 233); it imports no `bridge` module at all.
   `bridge/cosim_runner.py` imports only `control_law` and `ngspice_wrapper`.
   The only production import surface for `bridge/qemu_monitor.py` is the
   re-export shim `bridge/firmware_runner.py`, whose sole caller is
   `tests/test_fault_injection.py`. So today the monitor client is exercised
   by tests only, and the demo carries a second, independent copy of the HMP
   protocol logic (different transport: TCP vs stdio) that can drift from it.
   **OWNER DECISION:** wire the demo and/or co-sim loop through
   `QemuMonitor`, or accept `qemu_monitor.py` as a test-supported library and
   document that the demo is the only production user of HMP.

3. **`sweep_report()` cannot complete a sweep on a real monitor.**
   `cycle_adc_and_gate()` calls `qmp.stop()` in its `finally` block
   (`bridge/qemu_monitor.py:282-283`), so after the first value the handle is
   dead: with a real monitor, rows 2..n come back `ok=False, "QEMU process is
   not running"`. The double in `tests/test_firmware_gpio.py` masks this
   because its `stop()` only records a flag. Pinned but NOT hard-coded as a
   contract by `test_sweep_report_one_row_per_value_over_a_single_monitor`,
   which asserts one row per value, no exception, and exactly ONE `Popen` for
   the whole sweep. **OWNER DECISION:** move the stop out of the per-cycle
   `finally` into `sweep_report()`/the caller, or make `stop()` conditional on
   who started the monitor.

4. **Coverage split (stated so nobody over-reads the green run).** Protocol
   behaviour — command bytes, `(qemu) ` prompt handling, echo stripping,
   `Error:` raising, `xp` parsing, dropped pipe, silent-timeout, garbage
   output, sweep launch count — is covered ONLY by the test double
   `tests/fakes/fake_hmp_qemu.py`; it proves protocol handling and nothing
   about firmware, ADC physics or the real emulator. Boot, the patched SENS
   device, real `qom-set`/`xp` against the guest, and the error path on the
   real binary are covered ONLY by `tests/test_qemu_monitor_qemu.py` under
   the `qemu` marker (Track B, `tools/run_emulator_tests.ps1`, 2 passed under
   WSL). The GPIO tests are wiring tests against a double and count as
   neither.


## 2026-10-27 - Intermittent native access violation in the editor worker (found by the J4 gate)

- Symptom: a full-suite run crashed with `Windows fatal exception: access
  violation` in `ui/schematic_editor.py:688 _run_in_worker` <-
  `:3027 run_simulation` during
  `tests/test_editor_workflow.py::test_progress_reaches_complete_after_a_run`,
  at 16% of the run (logs/job S3B-INCLUDE, first gate attempt; Python 3.12
  thread dump printed with the faulting frames).
- Isolated rerun: `pytest tests/test_editor_workflow.py` -> **36 passed in
  13.75s** (logs/job S3B-INCLUDE).
- Second full-suite attempt: **437 passed, 3 skipped, 0 failed in 259.49s**.
- Not attributable to the JOB 4 include scan/rewrite: the crashing deck
  (`arduino_circuit()`) contains no `.include` line, and the new sanitiser
  tests collect *after* `test_editor_workflow` alphabetically (the crash
  happened at 16%, before they would run).
- Status: **INTERMITTENT, cause unknown, outside J4's allowlist.** To
  triage: re-run `tools/run_tests.py` a few times and, if it recurs,
  investigate the Qt worker thread / in-process ngspice interaction in
  `ui/schematic_editor.py`. Owner decision needed on whether to chase this
  before the pilot.

## 2026-10-28 - R4-01 security and licence audit

Open defects found while making the SECURITY.md vector table executable.

1. **`LICENSE` and `pyproject.toml` disagree about the project licence.**
   `LICENSE` contains the Apache License 2.0 text (`Apache License`,
   `Version 2.0, January 2004`, read with `Get-Content LICENSE -TotalCount 3`)
   while `pyproject.toml` declares `license = {text = "MIT"}`. One is wrong.
   OWNER ACTION: decide which, then change the other.
2. **No licence text for ngspice or QEMU exists in this checkout.** Searched
   `tools/ngspice_dll` for `*COPYING*`, `*LICENSE*`, `*GPL*`: no match. The
   shipped binary carries only its copyright banner
   (`Copyright 1985-1994, Regents of the University of California` /
   `Copyright 2001-2026, The ngspice team`) and no licence text.
   `THIRD_PARTY_NOTICES.md` records this rather than guessing.
   This contradicts item 9 above ("the component licenses were read from the
   upstream LICENSE files only"): there is no such file here, and
   `tools/ngspice-47_dll_64.7z` cannot be opened on this box (no 7-Zip
   present), so that earlier statement is not reproducible from the tree.
   OWNER ACTION: vendor the upstream `COPYING` beside the DLL.
3. **PyQt5 declares GPL v3** (read from `.venv/Lib/site-packages/
   PyQt5-5.15.11.dist-info/METADATA`, field `License: GPL v3`). Any
   distributed build links GPL-3 code, whatever the project's own licence
   says. Decision belongs to the owner, not to an agent edit.
4. **Historical evidence logs were redacted, not rewritten.** The R4 path
   scrub replaced the developer's home directory with `<home>` in
   `tests/MUTATION_LOG.md`, `docs/HANG_TRIAGE.md`, `docs/INVENTORY.md` and
   other tracked files. Measurements, counts and hashes in those logs are
   untouched; only the path prefix changed, so no file-location evidence can
   be checked against it again.

## 2026-10-28 - the editor-worker access violation is no longer rare

The intermittent crash recorded on 2026-10-27 reproduced **4 times in a row**
on commit `40a0ef5`, after the same suite had completed cleanly 4 times earlier
in the same session.

```
Windows fatal exception: access violation
Current thread (most recent call first):
  File "ui\schematic_editor.py", line 688 in _run_in_worker
  File "ui\schematic_editor.py", line 3027 in run_simulation
  File "tests\test_editor_workflow.py", line 284 in test_progress_reaches_complete_after_a_run
```

* Four reproductions: `logs/baseline/r2b-run1.txt` .. `r2b-run3.txt`
  (via `tools/agentlog.ps1`, jobs `R2-02-RUN1/2/3`) and
  `logs/baseline/diag-crash.txt` (direct pytest, exit 139, crash at 15%).
* Isolation: `pytest tests/test_editor_workflow.py` -> **36 passed in 6.90s**.
* Everything else: `pytest tests --deselect tests/test_editor_workflow.py`
  -> **418 passed, 3 skipped, 36 deselected, exit 0**.
* Not caused by the R4-01 changes: the crash lands in
  `test_editor_workflow.py`, which runs before any file this session touched,
  and the same tree produced four clean 453/3/0 runs an hour earlier.
* Consequence: SCORECARD v1 row **R2** is FAIL on its "zero flaky tests"
  clause. Next job R2-03 is this defect.
* Note for whoever picks it up: `ui/schematic_editor.py` carries uncommitted
  work from an earlier job (the same file is listed as modified at session
  start), so a fix there has to be agreed with the owner before it can be
  committed on its own.

## 2026-10-28 (second entry point) - the editor-worker crash also fires through test_ui_polish

Job `R5-01-GATEFULL` (log entry 138), full suite with nothing deselected:

```
........................................................................ [ 14%]
Windows fatal exception: access violation
Current thread 0x00005c90 (most recent call first):
  File "ui\schematic_editor.py", line 686 in _run_in_worker
  File "ui\schematic_editor.py", line 3027 in run_simulation
  File "tests\test_editor_workflow.py", line 284 in test_progress_reaches_complete_after_a_run
exit 1
```

Job `R5-01-GATE2` (entry 119) reached the same frames through a different
file, `tests/test_ui_polish.py:573 test_clicking_a_trace_row_chooses_what_the_cursor_measures`,
with `test_editor_workflow.py` deselected - so the fault is the Qt worker
path itself, not one test.

Isolation, this session:

* `pytest tests/test_editor_workflow.py` -> 36 passed (earlier session)
* `pytest tests/test_ui_polish.py` -> **76 passed in 79.06 s** (entry 137)
* `pytest tests --deselect <both files>` -> **366 passed, 3 skipped, 112
  deselected, exit 0, 78.15 s** (entry 129)
* `tools/run_tests.py` -> exit 1, thread dump only, no FAILED test line
  (entry 134)

Status unchanged: INTERMITTENT, needs full-suite context, R2 remains FAIL.
`ui/schematic_editor.py` still carries uncommitted work from an earlier job,
so a fix there needs the owner's agreement before it can be committed alone.

## 2026-10-28 (job R2-03) - editor-worker access violation: measured, one fix tried and reverted

Reproduction matrix (full detail in `docs/SCORECARD.md`, job R2-03):

```
8 prefix files, 118 tests                  11 runs   0 crashes
prefix + half the other modules             1 run    0 crashes
prefix + the other half                     1 run    0 crashes
all 31 modules imported, prefix tests only 11 runs   1 crash
full suite (pytest)                         4 runs   4 crashes
tools/run_tests.py                          2 runs   2 crashes
```

Always the same two frames: `ui/schematic_editor.py:686` (the in-loop
`QApplication.processEvents()`) from `run_simulation`, reached from
`tests/test_editor_workflow.py:284` or `tests/test_ui_polish.py:573`. The
earlier session faulted on line 688, the post-loop `processEvents()`.

Fix attempted: keep the `_SimWorker` reference alive, disconnect `progress`
from the window, `worker.wait()` to completion and drain the queue before
returning (instead of `self._worker = None` immediately after the loop).
Result: 36 passed alone, 5/5 import-context runs clean, then the full suite
and `tools/run_tests.py` both crashed at the same line. The hunk was
reverted; `git diff ui/schematic_editor.py` shows only the earlier job's
42/17 lines again.

Consequence: row **R2 is BLOCKED**, not FAIL. Three attempts have not
identified the freed object; the manifestation depends on heap layout (the
same 103 executed tests are clean without the other modules' imports).

Owner questions added (see SCORECARD):

1. Approve running the suite under a memory debugger (Application Verifier /
   Dr. Memory / an address sanitizer) to name the object being freed -
   installing one needs approval.
2. Approve staging a fix to `ui/schematic_editor.py` hunk-by-hunk so the
   earlier job's uncommitted 42/17 lines are not swept into it.

## 2026-10-29 — a hard kill of python leaves an orphaned QEMU (WSL)

Measured (activity log #210, #212): after `SIGKILL` of the python that
spawned it, the `qemu-system-xtensa` child **survives** — closing its stdin
(stdin-EOF) does not terminate it. `tools/cleanup_qemu.py` reaps it, so the
process table does reach zero through the documented reaper; prevention
would instead set `prctl(PR_SET_PDEATHSIG, SIGKILL)` (Linux) at the three
spawn sites: `bridge/qemu_monitor.py::start`,
`bridge/binary_runner.py::test_gate_flip`,
`tools/demo_closed_loop.py::run_demo`.

Not applied: those files are outside the R8 job's commit allowlist (owner
decision 2 lists two of them as do-not-commit until their own jobs are
DONE). Windows needs no patch here: it cannot execute the Linux emulator,
and the hard-kill check measured zero QEMU processes (#211).

**OWNER ACTION:** approve staging the three-site PDEATHSIG patch (two of
the three files are on the do-not-commit list).
