# Contributing

This is PROJECT_WOWKISPICE: an open-source mixed-signal co-simulator, a
genuine UI, firmware-adjacent tooling, and a working test hub. All
contributions are welcome, but the gates below are what keep the pilot
verifiable, so read them before you start.

---

## 1. Environment setup

```bash
git clone <repo>
cd <repo>
# 1. Pinned interpreter: Python 3.12 (see .venv/pyvenv.cfg).
# 2. create the virtualenv the repo expects
python -m venv .venv
source .venv/bin/activate
# 3. install all runtime + dev dependencies
pip install -r requirements.txt
# 4. run the environment gate
python tools/selfcheck.py      # must print SELF-CHECK: PASS, exit 0
```

The repo carries:

* `requirements.txt` — runtime dependencies.
* `requirements.lock` — the exact versions the test suite runs with.
* `.venv/` — the environment used by CI and by the test runner.

Do not silently swap the interpreter or the packages. If a dependency
conflicts on your machine, open an issue; do not edit
`requirements.lock`.

---

## 2. Running the test suite

```bash
# test runner (stdlib-only, works on Windows and WSL)
python tools/run_tests.py
# or directly with pytest
python -m pytest
```

Prerequisites: `pytest`, `numpy`, `matplotlib`, `PyQt5`, `pyqtgraph`,
`pypdf`, and the ngspice bridge library. `tools/run_tests.py` executes the
test files directly; each file must run its own `unittest` suite as a
script as well as being pytest-collectable.

Guiding principle: if `tools/run_tests.py` exits non-zero, the change is not
done, regardless of how many individual tests you saw pass.

---

## 3. Commit style

* One logical change per commit. The project history is the audit trail.
* One commit per task, with a clear message — this is a hard rule of the
  workshop (see the handoff notes):
  `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
* Keep the diff reviewable. Do not reformat a whole file to add five lines.
* Do not delete existing code or documentation without explaining why in
  the commit message.
* Do not rewrite git history. Rebase locally only; push with a force only
  on your own feature branch.
* Every new feature or behaviour change lands with a test that fails
  before the fix and passes after it.

---

## 4. What is and is not a green light

* `selfcheck.py` → `SELF-CHECK: PASS` is the **prototype gate** (environment
  and installability), not a substitute for the validation corpus
  (`docs/industry-readiness.md` Phase 1).
* The firmware boot check (`python -m bridge.qemu_orchestrator`) requires a
  patched QEMU and an ESP32 image. Those two artifacts are **unverified**
  on any machine that does not have them. Report that explicitly instead of
  pretending the boot worked.
* The ngspice physics proofs (`tools/prove_physics_engine.py`,
  `tests/test_ngspice_dll_proof.py`) are the highest-signal tests in the
  repo: three independent verifications of the solver against closed-form
  references. Keep them green.

---

## 5. Security

* Never commit secrets, tokens, or credentials. Use the repository's
  documented secret store and `git-secrets`/`gitleaks` where installed.
* The ngspice netlist loader must never execute `.control`/`.endc` blocks,
  shell commands, `system()`, or file-write/include directives from
  untrusted input. The sanitizer lives in `bridge/ngspice_wrapper.py` and a
  malicious-netlist rejection test lives in
  `tests/test_ngspice_dll_proof.py`.
* The QEMU monitor and QMP sockets bind to `127.0.0.1` or a unix socket.
  Any change that widens that scope needs a SECURITY.md-compatible review.

---

## 6. Branch and PR process

1. fork → branch (`feat/...`, `fix/...`, `docs/...`)
2. make the change, add/extend a test
3. `python tools/run_tests.py` → 0 failures
4. `python tools/selfcheck.py` → `SELF-CHECK: PASS`
5. push, open PR against `main`, fill the template (`.github/ISSUE_TEMPLATE/bug_report.yml`
   for bugs, a short description for features)

The maintainers' job is to keep the gates fast to run and honest about what
is verified. Do not ask us to pretend a verification passed.
