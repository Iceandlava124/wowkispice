# Support & Lifecycle Policy (Layer 7)

## Versioning

WOWKISPICE follows semantic versioning. `VERSION` holds the current release;
`wosp-cli --version` reports the workspace package version. Every release is
tied to a git commit and a GitHub Actions green run on Windows, Linux, and
macOS.

## Supported platforms

| Platform | Status |
|---|---|
| Windows 10/11 (x64) | Primary — CLI, Julia backend, GUI, self-check |
| Linux (x64, glibc) | Julia backend + CLI verified in CI; ngspice bridge environment-dependent |
| macOS (arm64) | Julia backend + CLI verified in CI |

## Support window

- The current minor version receives fixes.
- The previous minor version receives security fixes for 3 months after the
  next minor release.
- Older versions are unsupported; users should upgrade.

## Deprecation policy

A feature is deprecated for at least one minor release before removal:
1. Mark deprecated in docs and emit a runtime warning if applicable.
2. Document the replacement and migration path.
3. Remove only in the next major release.

## Known limitations (honest)

- Julia is a bring-your-own runtime; `bootstrap-julia.bat/.sh` automates setup
  but the ~160MB runtime is not bundled.
- The bundled Windows ngspice.dll segfaults on some transient circuits; real
  ngspice transient tests are documented as environment-dependent.
- Formal safety certification (UL/IEC/DO) is out of scope.

## Performance regression

`solve_time_ms` is reported by the Julia solver and is available to an external
performance tracker. A hard performance gate (fail CI if a reference solve
slows by >20%) is a future enhancement; the validation corpus and stiff test
currently bound correctness, not timing.

## Reporting issues

Include: `wosp-cli --version`, Julia version, OS, the exact command, and the
full JSON error output (the solver returns structured errors with diagnostics).
