# HANG TRIAGE — `tests/test_closed_loop_buck.py::TestClosedLoopBuck::test_buck_regulation`

**Job:** J1
**Branch:** `baseline-fix`
**Date:** 2026-10-27
**Status:** ROOT CAUSE FOUND, FIXED, MUTATION-CHECKED

---

## 1. Summary

The hang was **not** in ngspice, not a singular matrix, and not QEMU-related.
It was a **ctypes prototype mismatch**: `GetSyncData_t` in
`bridge/ngspice_wrapper.py` declared **6** parameters where the shipped
ngspice header declares **7**. ctypes reads the C stack using the declared
prototype, so the callback was entered with the wrong frame; it failed
silently inside ngspice's C code, and the `ngSpice_Command("run")` that
followed never returned.

The defect is now fixed, covered by three regression tests, and
mutation-checked: re-introducing the defect reproduces the hang **3 times out
of 3**.

---

## 2. Independent expected source

`tools/ngspice_dll/Spice64_dll/include/ngspice/sharedspice.h:319` (read from
disk in this session with `Select-String -Pattern 'GetSyncData'`):

```c
typedef int (GetSyncData)(double, double*, double, int, int, int, void*);
```

7 parameter types — `double, double*, double, int, int, int, void*` — plus an
`int` return type.

> `tools/ngspice_dll/` is gitignored, so a clean clone has no copy of this
> header. The regression test falls back to the typedef quoted above and says
> so in its source string rather than skipping.

---

## 3. Reproduction and timing

### 3.1 Fixed tree — `test_buck_regulation` alone, 3 runs

Command (each run): `pytest "tests/test_closed_loop_buck.py::TestClosedLoopBuck::test_buck_regulation" -q --timeout=30 -p no:cacheprovider`

| Run | pytest summary | wall ms | exit |
|-----|----------------|---------|------|
| 1 | `1 passed, 13 warnings in 1.07s` | 1744 | 0 |
| 2 | `1 passed, 13 warnings in 0.80s` | 1221 | 0 |
| 3 | `1 passed, 13 warnings in 0.75s` | 1199 | 0 |

### 3.2 Fixed tree — 10 more runs of the same test

| Run | ms | result |
|-----|-----|--------|
| 1 | 1766 | 1 passed in 1.05s |
| 2 | 1254 | 1 passed in 0.83s |
| 3 | 1341 | 1 passed in 0.85s |
| 4 | 1391 | 1 passed in 0.91s |
| 5 | 1502 | 1 passed in 1.02s |
| 6 | 1562 | 1 passed in 0.87s |
| 7 | 1417 | 1 passed in 0.88s |
| 8 | 1258 | 1 passed in 0.80s |
| 9 | 1362 | 1 passed in 0.89s |
| 10 | 1340 | 1 passed in 0.88s |

`pass=10 fail=0`, `ms min=1254 max=1766 mean=1419.3 variance=21725.4`

### 3.3 Fixed tree — whole file, 3 runs (all 6 tests, one process)

| Run | result | wall ms |
|-----|--------|---------|
| 1 | `6 passed in 0.88s` | 1631 |
| 2 | `6 passed in 1.64s` | 2659 |
| 3 | `6 passed in 1.17s` | 1870 |

**16/16 passing runs. The hang does not reproduce with the fix in place.**

### 3.4 Process snapshots (python / qemu)

Sampled with `Get-Process` before run 1, after each of runs 1–3, and after the
10-run and 3-file-run batches:

| Point | qemu count | python count |
|-------|-----------|--------------|
| before run 1 | 0 | 23 |
| after run 1 | 0 | 23 |
| after run 2 | 0 | 23 |
| after run 3 | 0 | 23 |
| after all 16 runs | 0 | 23 |

The 23 python processes are pre-existing (PIDs 3856, 8244, 9308 … started
26-10 and 27-10, including `.venv\Scripts\python.exe`, the system Python and
one `C:\msys64\ucrt64\bin\python.exe`). **The test spawns no persistent
python and no qemu process at any point.**

---

## 4. Is the hang intermittent?

**No — it is deterministic given the defect.** Two independent measurements:

* **Fixed code:** 16/16 runs pass, spread 1199–2659 ms.
* **Defective code (the mutant, below):** 3/3 runs hang and are killed by the
  30 s pytest timeout, taking 30972 / 30907 / 31234 ms.

The original report of "passed in an earlier 363-passed run, hangs now" is
therefore **not** explained by randomness. The variable that changed was the
declaration in `bridge/ngspice_wrapper.py`, not process leftovers, DLL state,
ordering or timing:

* **leftover processes** — ruled out: qemu count is 0 and python count is
  constant at 23 across every snapshot; the hang reproduces in a scratch
  directory with no other instance of the module loaded.
* **DLL state** — ruled out as the trigger: the same DLL is loaded in the
  passing runs; only the prototype changed.
* **ordering** — ruled out: the test passes in isolation and as part of the
  whole file.
* **timing** — ruled out as cause: passing-run durations vary by a factor of
  two (1199–2659 ms) with no correlation to outcome.

What *does* vary with the defect is the symptom's duration: a hang until the
30 s timeout, versus ~1 s.

---

## 5. Mutation check (rule 5)

Scratch copy outside the repo: `<home>\AppData\Local\Temp\wosp_mut`
(containing `bridge/`, `tests/`, `circuits/`, `tools/ngspice_dll`).

### 5.1 Baseline of the scratch copy

```
SCRATCH PROBE module.__file__ = <home>\AppData\Local\Temp\wosp_mut\bridge\ngspice_wrapper.py
SCRATCH PROBE sys.executable  = <home>\Music\PROJECT_WOWKISPICE\.venv\Scripts\python.exe
SCRATCH PROBE cwd             = <home>\AppData\Local\Temp\wosp_mut
--- BASELINE (unmutated scratch) ---
6 passed, 13 warnings in 1.89s
baseline exit=0
```

### 5.2 The mutant

One parameter dropped from the declaration — the same defect as the original:

```python
GetSyncData_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_double,
    ctypes.POINTER(ctypes.c_double), ctypes.c_double, ctypes.c_int,
    ctypes.c_int, ctypes.c_void_p)  # MUTANT: dropped one int parameter
print('MUTANT-MARKER GetSyncData_t mutated in', __file__, flush=True)
```

### 5.3 Proof the mutant is the code under test

```
MUTANT-MARKER GetSyncData_t mutated in <home>\AppData\Local\Temp\wosp_mut\bridge\ngspice_wrapper.py
module.__file__ = <home>\AppData\Local\Temp\wosp_mut\bridge\ngspice_wrapper.py
sys.executable  = <home>\Music\PROJECT_WOWKISPICE\.venv\Scripts\python.exe
```

### 5.4 Mutant outcome — the original hang, reproduced

```
..+++++++++++++++++++++++++++++++++++ Timeout +++++++++++++++++++++++++++++++++++
...
  File "<home>\AppData\Local\Temp\wosp_mut\bridge\mock_controller.py", line 156, in run_closed_loop_simulation
    engine.cmd(tran_cmd)
  File "<home>\AppData\Local\Temp\wosp_mut\bridge\ngspice_wrapper.py", line 328, in cmd
    return self.lib.ngSpice_Command(command.encode('utf-8'))
+++++++++++++++++++++++++++++++++++ Timeout +++++++++++++++++++++++++++++++++++
mutant pytest exit=1
```

This is exactly the reported stack: `mock_controller.py:156` →
`ngspice_wrapper.py:328` `ngSpice_Command`.

Repeated 3×:

```
MUTANT RUN 1: exit=1  elapsed ms=30972  summary: Timeout
MUTANT RUN 2: exit=1  elapsed ms=30907  summary: Timeout
MUTANT RUN 3: exit=1  elapsed ms=31234  summary: Timeout
qemu after: 0   python total: 23
```

### 5.5 Regression tests kill the mutant (arity class only)

```
3 failed, 14 warnings in 0.77s
mutant exit=1
```

with these messages:

```
AssertionError: 6 != 7 : CFUNCTYPE declares 6 parameters for 7 header params
  (tools\ngspice_dll\Spice64_dll\include\ngspice\sharedspice.h:319)
AssertionError: <class 'ctypes.c_void_p'> is not <class 'ctypes.c_long'> : parameter 6 of
  GetSyncData: header says int, CFUNCTYPE says <class 'ctypes.c_void_p'>
  (...sharedspice.h:319)
AssertionError: 'args' not found in {} : handler was never invoked with the seven
  declared arguments; ctypes swallowed an arity mismatch
  (...sharedspice.h:319)
```

Owner tree, same tests: **`6 passed`**, exit 0.

**No surviving mutant.**

---

## 6. Second defect found and fixed in the same file

`get_vector_complex()` had lost two lines (`vec = vec_ptr.contents` and the
`v_length <= 0` guard), producing `NameError: name 'vec' is not defined` at
line 524 when a `.ac` sweep read a complex vector.

Current code, `bridge/ngspice_wrapper.py:519-526`:

```python
vec_ptr = self.lib.ngGet_Vec_Info(vec_name.encode('utf-8'))
if not vec_ptr:
    vec_ptr = self.lib.ngGet_Vec_Info(f"v({vec_name})".encode('utf-8'))
if not vec_ptr:
    return [], []
vec = vec_ptr.contents
if vec.v_length <= 0:
    return [], []
```

Covered by `tests/test_measurements.py` through
`bridge/analysis_runner.py:107,113,434,436,438`:

```
16 passed, 20 deselected in 4.07s
exit=0
```

---

## 7. Other fixes made to this file while green tests demanded them

* `.noise` and `.disto` added to the analysis-directive allowlist because
  `tests/test_components_library.py` sends them and fails without them.
* `.meas` / `.include` remain **rejected** by the J4 sanitiser draft — those
  4 failures belong to J4 and are recorded in `ROADMAP.md` and
  `docs/STATE.md`, not here.

---

## 8. Files changed by J1

| File | Change |
|------|--------|
| `bridge/ngspice_wrapper.py` | `GetSyncData_t` parameter restored; `get_vector_complex` body restored; `.noise`/`.disto` allowlisted |
| `tests/test_closed_loop_buck.py` | new `TestGetSyncDataArityMatchesHeader` class: 3 tests, all with `@pytest.mark.timeout(30)` |
| `docs/HANG_TRIAGE.md` | this file |

---

## 9. Regression tests added

`TestGetSyncDataArityMatchesHeader` in `tests/test_closed_loop_buck.py`:

1. `test_cfunctype_arity_matches_the_header` — `_argtypes_` length must equal
   the header's parameter count, and `_restype_` must be `ctypes.c_int`.
2. `test_cfunctype_types_match_the_header_parameter_by_parameter` — each of
   the 7 entries must map to the header's C type.
3. `test_callback_accepts_the_seven_header_arguments` — actually **calls** the
   callback with all seven arguments, because constructing a CFUNCTYPE does
   not check its arity.

### Two wrong assumptions, corrected after measuring

The first draft of these tests failed against correct code. Measured, not
guessed (`logs/cmd/probe_cfuntyp.py`, `logs/cmd/probe_cint.py`):

* `ctypes.CFUNCTYPE(...)._argtypes_` contains **only the parameters**; the
  return type lives in `_restype_`. Expected length is 7, not 8.
* On this Windows build `ctypes.c_int is ctypes.c_long` — same object id — so
  the header's `int` maps to the object printed as `ctypes.c_long`.

The assertion order in test 3 was then changed so a dead handler reports
`'args' not found in {}` instead of a misleading `returned != 0`.
`tests/CHANGES.md` carries the entry.
