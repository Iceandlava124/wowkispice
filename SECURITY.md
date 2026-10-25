# Security

## Threat model

This project's trustworthiness boundary is **untrusted project data** that
the user points at the simulator. The two classes that matter most for the
deliverables in this phase are:

1. **Untrusted netlists / project files loaded by ngspice** — the contents
   of circuits you draw, netlists you import, and files the schematic
   editor compiles into SPICE. The loader is `bridge/ngspice_wrapper.py`
   (`load_circuit`, `load_circuit_file`).
2. **Local monitor / QMP / qtest sockets** — the channels by which QEMU
   (with the real ESP32 firmware binary) is driven and observed:
   `-monitor tcp:127.0.0.1:PORT`, `-qtest tcp:PORT`, and the HMP console.

The attack surface of concern is *not* the NGSpice C solver itself (we
treat it as a third-party oracle, and its own security is out of scope
here), but what happens when **untrusted text is handed to it** and what
happens when **a local socket is reachable from a hostile origin**.

### What is protected

* All QEMU monitor/QMP/qtest bindings in this repository bind to
  `127.0.0.1` or a unix socket only. The monitor is not exposed on the
  wildcard. (This is the *default*; see the verification command in the
  QEMU section.)
* The ngspice netlist loader never passes control to a shell: the C
  solver's command set is the *only* thing that can be executed, and we
  treat ngspice's command language as a data format.
* No secrets, tokens or credentials exist anywhere in the repository
  today. `git ls-files` shows none, and `gitleaks` is not installed in
  this environment (see Task 5).
* The ngspice `-I` and `-D` flags, if used by a caller, are never set from
  untrusted input; they are not part of the load path.

### What is NOT protected (and why)

* **`ngspice` is a full SPICE simulator, not a sandbox.** Its netlist
  language includes directives that can source files, run shell commands,
  and write output files from *within* a netlist. The loader in this
  project does not canonicalise a netlist before handing it to ngspice,
  so this is a genuine risk with an untrusted file. The fix is in
  `bridge/ngspice_wrapper.py` (sanitiser added in this phase) and the
  companion test `tests/test_ngspice_dll_proof.py`.
* **A hostile process that already controls the local user account is
  outside the threat model.** The sockets protect the *local* loop from
  *other local users*; a user who can already launch QEMU and write to
  `/tmp` can already defeat the isolation.
* **The patched QEMU device models are unvalidated against silicon.** See
  `docs/fidelity.md`. A malicious guest image can probe the model; the
  model is a *simulation* and its output is not a promise about hardware.
* **ngspice's `system()`, `.control`, `.endc`, `.include`, `.lib`,
  `write`, `fft` and related control-language features are not
  automatically rejected by this loader.** The sanitizer in
  `bridge/ngspice_wrapper.py` rejects a defined set on load and is
  tested. ngspice itself has more; anything we did not enumerate stays
  allowed by the sanitizer and is documented as a residual risk. Do not
  trust a netlist that was never passed through the sanitizer.
* **File interpretation is not authenticated.** A netlist that embeds a
  `.include` pointing at a file the user did not author is *not* blocked
  by this sanitizer — the sanitizer rejects directives on *load*, not
  sources that come from inside a `*.lib` model. Whether a project file
  reaching the loader is malicious is a policy decision for the app layer;
  the loader's job is to make that policy enforceable and auditable.

## Reporting issues

* **Security issues:** open a PR against `main` with the label
  `security`, or email the project owner. The maintainers will triage
  within one release window.
* **Non-security bugs:** use `.github/ISSUE_TEMPLATE/bug_report.yml`.
* **No CVE, no third-party response obligations.** This is an open-source
  pilot; we will fix confirmed issues, but we make no warranties of any
  kind.

## Verification

Run these commands before every release:

```bash
# 1. The malicious-netlist gate (must exit 1 *before* the fix, 0 *after*)
python tests/test_ngspice_dll_proof.py

# 2. QEMU socket scopes (must bind to loopback/unix, never wildcard)
python -m bridge.qemu_monitor     # --qemu /path/to/patched/qemu-system-xtensa
# the orchestrator's -monitor line is "tcp:127.0.0.1:PORT" by construction

# 3. Full test suite
python tools/run_tests.py
```

---

## Software bill of materials (regarding this document)

| Component | License | License type | Distribution obligations |
|---|---|---|---|
| QEMU (Espressif fork) | GNU GPLv2+ | GPL/LGPL | If distributed, offer source + patch |
| ngspice | GNU GPLv2+ | GPL/LGPL | Ships as a shared library; see THIRD_PARTY_NOTICES.md |
| ESP-IDF / PlatformIO | Apache-2.0 / MIT | permissive | build toolchain only |
| Python dependencies | per-package | mixed | runtime only |

The GPL obligations for QEMU and ngspice are restated in
`THIRD_PARTY_NOTICES.md`; redistribution is not part of the pilot and the
project is distributed as source + a build procedure.
