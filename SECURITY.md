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
  and write output files from *within* a netlist. Since JOB 4 the loader
  in `bridge/ngspice_wrapper.py` runs every netlist line through an
  allowlist sanitiser before `ngSpice_Circ`, and scans the contents of
  allowlisted `.include` files with the same rules (recursive, depth
  capped). What was actually observed per vector is recorded under
  "Tested vectors" below; anything not listed there was not tested.
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
* **File interpretation is not authenticated.** Since JOB 4 the loader
  rejects `.include`/`.lib`/`.inc` targets outside `ALLOWED_INCLUDE_DIRS`
  (default: `circuits/components` only, resolved against the repo root,
  never against a guess from the caller's cwd) and scans the included
  file's own lines with the same directive allowlist, recursively up to
  `INCLUDE_SCAN_DEPTH_LIMIT` (5). The include line is rewritten to the
  validated absolute path so ngspice reads exactly the file that was
  checked. This behaviour was tested (see below); it does not
  authenticate *authorship* — a malicious file placed inside
  `circuits/components` is still inside the trust boundary.

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


---

## Tested vectors (JOB 4, 2026-10-27)

These are the exploit vectors actually executed against the real ngspice
library (ngspice-47 shared library, Creation Date Aug 11 2026, loaded from
`tools/ngspice_dll/.../ngspice.dll`). Each vector ran in its own child
process with a working directory under `%TEMP%`, so any marker file or file
read is provable on disk outside the repository. Two targets: **HEAD**
(`git show HEAD:bridge/ngspice_wrapper.py`, 16720 bytes, extracted to
`%TEMP%\wosp_exp_head_pkg`, every child printing `module.__file__` to prove
which copy imported) and the **current working-tree draft**. Commands and
full output: `logs/activity.jsonl` jobs `S3A-EXPLOIT` and `S3B-INCLUDE`
(`logs/out/*.txt`).

| # | Vector | HEAD result | Draft result |
|---|--------|-------------|--------------|
| 1 | `.control` block in a netlist containing `shell echo PWNED> <marker>` | **marker created** (block executed on `run`) | `RuntimeError: banned directive @line: .control` at load; no marker |
| 2 | `cmd("shell echo PWNED> <marker>")` | **marker created** | **marker created** — `cmd()` is NOT filtered (see residual) |
| 3 | `cmd("source <file>")` where the file holds a sentinel line | rc 1; file **NOT read**: ngspice printed `"C:Users...source_sentinel.cir": No such file or directory` (it stripped the backslashes) and the DLL entered `cannot recover and awaits to be reset or detached` | same |
| 4 | `.include` of an existing file **outside** `circuits/components` | **file READ**: log contains `sentinel_outside_xyz` + `Error: circuit not parsed` — although `cmd("run")` still returned 0 | `RuntimeError: .include outside allowed directories`; sentinel absent, file never read |
| 5 | `cmd("write <path> v(out)")` after a run | rc 0, **no file found** anywhere in `%TEMP%` or the repo (not observed) | same |
| 6 | `cmd("wrdata <path> v(out)")` | rc 0, **no file found** (not observed) | same |
| 7 | `cmd("hardcopy <path> v(out)")` | rc 0, log `Can't open viewport for graphics.`, **no file found** (not observed) | same |
| 8 | bare `shell ... > <marker>` line in a netlist (element position) | parsed as an element: `Error on line 2 ... Unable to find definition of model`, **no marker** (not executed) | same |
| 9 | `.control` + `shell` **inside** an allowed `.include`d file (vector placed in `circuits/components/`) | **marker created** (included `.control` executed) | **before the content scan: marker created; after: rejected at load, marker never created** (tests `TestIncludedFileContent`, mutant M5) |

> **The table above records the state before job R4-01 (2026-10-28).** It is
> kept as history. The current state, with the `cmd()` gap closed and every
> row re-run as a pytest case, is in "After R4-01" below.

### Residual findings at that time (tested, NOT blocked — stated plainly)

* `NgSpiceEngine.cmd()` passed any string straight to `ngSpice_Command`.
  Vector 2 executed `shell` through it on the draft as well as on HEAD. That
  gap is closed by job R4-01 below.
* Vector 3 did not prove an arbitrary-file read (the path was mangled
  before ngspice opened it), and it wedges the shared DLL into an
  unrecoverable error state until reset/detach.
* Vectors 5-7 returned rc 0 without producing a file in this environment.
  That was an observation, not a guarantee; after R4-01 they are refused
  before ngspice is entered, which is a guarantee about this loader rather
  than about ngspice.
* Vectors are run against the shipped Windows DLL only. No claim is made
  about other ngspice builds, other platforms, or about behaviour that was
  not listed in the table.

### After R4-01: `cmd()` guarded (2026-10-28)

`NgSpiceEngine.cmd()` now passes its string through `validate_cmd()` first:

* the verb (first whitespace-delimited token, lowercased) must be in
  `Cmd_ALLOWED` — `run`, `bg_run`, `reset`, `destroy`, `alter`, `stop`,
  `setplot`, `tran`. That set is the complete vocabulary of every `.cmd(`
  call site under `bridge/`, `ui/`, `tests/` and `tools/` (grep: run x36,
  setplot x6, stop x1, alter x1, plus `tran ...` from
  `bridge/mock_controller.py:156`);
* the string must contain no `\r`, `\n`, `;`, `|`, `&`, backtick, `$`, `<`
  or `>` — the characters that let one string carry a second command or a
  redirection;
* a refusal is a `RuntimeError` naming the verb, so a policy refusal is
  distinguishable from a simulator error.

Measured after the guard (every one of these is now a pytest case in
`tests/test_security_vectors.py`, run against the real library):

| # | Vector | Now |
|---|--------|-----|
| 1 | `.control` + `shell` in a netlist | rejected at load, deck never reaches `ngSpice_Circ`, no marker |
| 2 | `cmd("shell echo PWNED> <marker>")` | `RuntimeError: not on allowlist: 'shell'`, command never reaches `ngSpice_Command`, no marker |
| 3 | `cmd('source "<file>"')` | `RuntimeError: not on allowlist: 'source'`, ngspice never asked to read the file |
| 4 | `.include` of a file outside `circuits/components` | `RuntimeError: outside allowed directories`, deck never reaches `ngSpice_Circ`, no marker |
| 5 | `cmd('write "<path>" v(out)')` | `RuntimeError: not on allowlist: 'write'`, no file created |
| 6 | `cmd('wrdata "<path>" v(out)')` | `RuntimeError: not on allowlist: 'wrdata'`, no file created |
| 7 | `cmd('hardcopy "<path>" v(out)')` | `RuntimeError: not on allowlist: 'hardcopy'`, no file created |
| 8 | bare `shell ... > <marker>` in element position | still parsed as an element; run attempted; no marker |
| 9 | `.control` + `shell` inside an allowed include | rejected at load, error names the included file, no marker |

"Never reaches ngspice" is not inferred from captured output: the tests shadow
`ngSpice_Command` and `ngSpice_Circ` with recorders and assert the recorder was
never called.

Mutation evidence (`logs/cmd/r4_mutate.py`, agentlog job `R4-01-MUTATE`):
5 mutants, **5 killed**, tree restored and SHA256 re-checked.

```powershell
.venv\Scripts\python.exe -m pytest tests\test_security_vectors.py -q --timeout=60
```

Residual after R4-01, stated plainly:

* The allowlist stops what this loader can be asked to do; it is not a sandbox
  for `ngspice` itself, and a caller that constructs a command from untrusted
  text can still choose among the allowed verbs.
* Vector 8's outcome (element-position `shell`) depends on ngspice's parser,
  not on this loader; the test asserts only that no marker appears.
* The vectors were run against the shipped Windows DLL only.
* Third-party license texts for ngspice and QEMU are not present in this
  checkout; `THIRD_PARTY_NOTICES.md` records that rather than guessing.

### Verification commands

```powershell
.venv\Scripts\python.exe -m pytest tests\test_ngspice_sanitiser.py -q --timeout=60
# includes: .meas alias, include allowlist, included-content scan,
#           depth limit, missing-file rejection, foreign-cwd equivalence
powershell -NoProfile -File tools\agentlog.ps1 -Job VERIFY -ScriptFile logs\cmd\j4_mutate.ps1
# mutation check: 7/7 mutants killed (MUTATION_LOG.md, 2026-10-27 entries)
```
