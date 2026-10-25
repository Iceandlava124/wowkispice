# TODOS.md

Deferred scope, collected across all /autoplan phases for `baseline-fix`
(CEO → Design [skipped, no UI scope] → DX [skipped by owner at D5] → Eng), 2026-10-24.

## From CEO (Phase 1)

| Item | Severity | Why deferred |
|---|---|---|
| Resolve the pyqtgraph segfault (3 UI test files, ~146 tests uncollectable) | High | Orthogonal to the loop; embedded tests do not import pyqtgraph. `import pyqtgraph` exits 139 while `import PyQt5.QtWidgets` exits 0, so probe `QT_OPENGL=software` first, then the RHI backends, then bisect — bounded, with a stop condition. Never land a bare `except ImportError` that converts a crash into a silent pass. |
| Close or narrow `docs/KNOWN_ISSUES.md` item 8 (claims the sanitiser rejects `.tran`) | Medium | Stale: `test_ngspice_bridge.py` and `test_ngspice_dll_proof.py` both pass today. |
| Reconcile `docs/final_pass_todos.md`'s "29 passed / 15 failed" against the measured 166/6/2-plus-3-crashes | Medium | Two different runners produced the two numbers; the doc predates this survey. |

## From Eng (Phase 3)

| Item | Severity | Why deferred |
|---|---|---|
| Delete the duplicate `QemuMonitor` / `cycle_adc_and_gate` / `sweep_report` | **Critical** | `bridge/qemu_monitor.py:34,147,188` and `bridge/qemu_orchestrator.py:49,90,103` implement the same QOM/HMP surface with incompatible signatures, and `qemu_orchestrator.py:116` re-imports the other module's names so both are reachable. This is the direct cause of the three stale `TestQemuGateBridge` failures. Deferred because deletion is outside the loop's critical path and re-landing it would re-scope the plan the owner just set — but the plan names the canonical module so links 6 and 7 cannot pick wrong. |
| Retire the third gate reader at `bridge/esp32_regs.py:75 def read_gate(client, pin)` | Medium | Same duplication family as above; three readers of `xp /1wx 0x3FF44004`. |
| Record the QEMU monitor TCP bind as an invariant | Low | `qemu_orchestrator.py:204` binds `tcp:127.0.0.1:<free>,server=on,wait=off`. Loopback-only today. Worth an assertion so a future edit cannot widen it to `0.0.0.0` and expose an unauthenticated guest control surface. |

## Owner-gated (cannot be done on this machine)

| Item | Blocker |
|---|---|
| Recover `tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch` | Not in git, not derivable from the checkout. `git ls-files tools/qemu-patch` is empty. Everything in the loop waits on this. |
| Produce `qemu-system-xtensa` | `tools/build_qemu.sh` clones `espressif/qemu` at `esp-develop-9.2.2-20260417` and applies the missing patch. |
| Link `firmware.elf` | `pio` is installed and already built a bootloader and partitions, but zero application objects exist. The build stalls, it does not fail. |
| Provide the ngspice `.dll` decryption key | `tools/ngspice-47_dll_64.7z` is encrypted at rest; `setup.ps1` is the documented unlock step. |

## Explicitly out of scope, permanently

- Any claim of agreement with real silicon. No test in this repo measures hardware.
- CI runners and pilot packaging. Separate infrastructure effort.
