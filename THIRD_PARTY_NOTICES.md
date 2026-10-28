# Third-party notices

Every statement below was read from a file in this checkout, at the time of
job R4-01 (2026-10-28). Nothing here is quoted from memory. Where a component
ships without a readable license file, the table says so and claims nothing.

Reproduce the evidence with:

```powershell
# this project's own license
Get-Content LICENSE -TotalCount 3

# installed Python distributions: the license each package declares about itself
.venv\Scripts\python.exe -c "import glob,re; [print(m) for m in sorted(glob.glob('.venv/Lib/site-packages/*.dist-info/METADATA'))]"

# bundled ngspice binary: embedded copyright banner, and the absence of a license file
Get-ChildItem -Recurse tools\ngspice_dll -Include *COPYING*,*LICENSE*,*GPL*
```

## 1. This project

| Item | Read from | Value read |
|---|---|---|
| Project license | `LICENSE`, first three lines | `Apache License` / `Version 2.0, January 2004` |

**Open contradiction (not fixed here, it is a licensing decision):**
`pyproject.toml` declares `license = {text = "MIT"}` while `LICENSE` contains
the Apache License 2.0 text. One of the two is wrong. Recorded in
`docs/KNOWN_ISSUES.md`; resolving it is an OWNER ACTION, not an agent edit.

## 2. Python dependencies

Read from `.venv/Lib/site-packages/<distribution>.dist-info/METADATA`, field
`License:` (falling back to the `License ::` classifier when the field is
absent or holds a copyright line instead of a license name). `.venv/` is not
tracked in git; these rows describe the environment `setup.ps1` builds from
`requirements.lock`.

| Distribution | Version | License as declared by the package |
|---|---|---|
| PyQt5 | 5.15.11 | `GPL v3` |
| PyQt5-Qt5 | 5.15.2 | `LGPL v3` |
| PyQt5_sip | 12.20.0 | `BSD-2-Clause` |
| colorama | 0.4.6 | classifier only: `OSI Approved :: BSD License` |
| contourpy | 1.3.3 | `BSD 3-Clause License` |
| cycler | 0.12.1 | classifier only: `OSI Approved :: BSD License` |
| fonttools | 4.67.0 | `MIT` |
| iniconfig | 2.3.1 | no license field and no classifier |
| kiwisolver | 1.5.1 | field holds a separator line, not a license name |
| matplotlib | 3.8.2 | `PSF` |
| numpy | 1.26.4 | field holds a copyright line; no classifier |
| packaging | 26.3 | no license field and no classifier |
| pillow | 13.0.0 | no license field and no classifier |
| pip | 25.0.1 | `MIT` |
| pluggy | 1.7.0 | `MIT` |
| Pygments | 2.21.0 | no license field and no classifier |
| pyparsing | 3.3.3 | no license field and no classifier |
| pypdf | 4.0.0 | classifier only: `OSI Approved :: BSD License` |
| pyqtgraph | 0.14.0 | `MIT` |
| pytest | 8.2.2 | `MIT` |
| pytest-timeout | 2.3.1 | `MIT` |
| python-dateutil | 3.0.0 | `Dual License` |
| scipy | 1.11.4 | field holds a copyright line; no classifier |
| six | 1.17.0 | `MIT` |
| tzdata | 2026.5 | `Apache-2.0` |

Rows that read "no license field" or "field holds a copyright line" are not
omissions in this file: the installed metadata genuinely does not name a
license. Each package's own license file, where one is shipped inside its
`.dist-info`, is the authoritative text and travels with the installed wheel.

Consequence worth stating plainly: `PyQt5` declares **GPL v3**. A distributed
build that links PyQt5 is distributed under those terms, not under the
project's Apache-2.0 text alone. This observation is read from the metadata
above; what to do about it is an OWNER ACTION.

## 3. ngspice shared library (bundled, not tracked in git)

`setup.ps1` downloads the official Windows DLL build into
`tools/ngspice_dll/`. Read from that binary
(`Spice64_dll/dll-vs/ngspice.dll`, 8,590,848 bytes):

```
** The U. C. Berkeley CAD Group
** Copyright 1985-1994, Regents of the University of California.
** Copyright 2001-2026, The ngspice team.
```

* Searched the binary for `General Public License` and `GNU`: **not present**.
* Searched the whole of `tools/ngspice_dll` for `*COPYING*`, `*LICENSE*`,
  `*GPL*`: **no file found**.

Verdict: the copyright holders are read from the shipped binary; the license
text is **not present in this checkout and is therefore not asserted here**.
OWNER ACTION: vendor the upstream `COPYING` next to the DLL (this needs a
download, which the agent may not perform under the rules in force).

## 4. QEMU (built by the user, never redistributed by this repo)

* `git ls-files` contains no QEMU source and no emulator binary; the only
  QEMU-related tracked files are the two device-model patches under
  `tools/qemu-patch/` and `tools/build_qemu.sh`, which clones a pinned
  upstream tag.
* No license file for QEMU exists in this checkout, so none is quoted.

Verdict: **not asserted**. QEMU's own license travels with the QEMU source the
user clones.

## 5. ESP32 framework and firmware build output

* `firmware/esp32_buck_controller/.pio/` is untracked build output; no
  framework license file is present in this checkout.

Verdict: **not asserted**.

## 6. `circuits/components/models.lib`

Header read from the file itself:

```
* PROJECT_WOWKISPICE Component Library: Power & Mixed-Signal Subcircuits
* Reverse-engineered high-fidelity SPICE models for hardware co-simulation
```

Project-authored content; no third-party notice applies.
