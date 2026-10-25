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
   `C:\Users\gudae\Music\qemu-build\qemu-esp_develop_9.2.2_20260417\build`.
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
   Task 8's value-add (docs, naming, formatting, messages, structure) must
   not regress those tests; the sanitiser bug (issue 8) is a blocker for
   that list, not part of it.
