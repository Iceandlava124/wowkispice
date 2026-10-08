# PROJECT_WOWKISPICE · Multi-MNC Codebase Audit — Whip-Around Notice

**Audience / scope:** 15 MNC / large-org audit teams, each with its own slice of interest and preferred implementation posture. This notice is the handoff a product + platform lead would give before a cross-org review.

**Two-sentence summary:** The codebase is a *real* analog+MCU co-simulator built on `libngspice` (ctypes) with a LTspice-shaped PyQt5 editor, a schematic→SPICE compiler, and a closed-loop per-timestep co-sim path that imports control logic from ESP32/Xtensa firmware source. The differentiation is the MCU story: compiled firmware boots and runs its real control loop in patched Espressif QEMU (900k samples / 90 s, zero panics), but inside the simulation loop firmware behavior is **parsed, not executed** — the in-loop controller is a model of the firmware's logic.

**Why 15 teams, not 1:** The repo is not one product; it is several value propositions layered on one solver spine. The natural audit is org-by-org, because each team buys a different slice and would implement a different layer first.

---

## Audited slices (one per org)

1. Industry-standard EDA incumbent — solver SDK spine + netlist library + deterministic identity
2. Analog IC design house — physics-verifiable components + analysis coverage
3. Automotive Tier-1 supplier — control-law-first co-sim
4. Automotive OEM systems integration — qualification + traceability + Gerber gap
5. Aircraft OEM avionics — certification-evidence discipline (real vs modelled vs parsed)
6. Marine / process-control OEM — reliability + distribution analysis
7. Energy-infrastructure OEM — closed-loop regulation evidence package
8. Power-converter / motor-drive integrator — motor + PWM + current control + MCU hardware truth
9. Regional design-hub / foundry PDK user — KiCad export + BOM + netlist awareness
10. Test & measurement IC vendor — verifiable device models + analysis coverage
11. MCU silicon vendor (Espressif tier) — Xtensa/ESP32 execution story as differentiator
12. MCU / MCU IP licensee (STMicro / NXP tier) — MCU hardware-truth layer
13. Automotive Tier-2 firmware vendor — firmware-facing surface (parse + import + GPIO profiles)
14. Systems-integrator / lab-automation vendor — headless / CI / reproducibility / exports
15. Open-source-signal-chain / regional-tech nonprofit — education-friendly, honest, licenced

---

## Cross-cutting findings every team converges on

- **Real vs modelled vs parsed must be labelled per artifact**, not just on one page.
- **A saved scenario must reconstruct its exact netlist + mode.**
- **Netlist identity should be canonical and comparable** across tools/runs.
- **The QEMU↔ngspice automatic bridge is either built or explicitly broken** — today it is the biggest differentiator-to-gap.
- **CI and the container story must be real or explicitly marked stale.**
- **`cad_engine` should be a reusable, testable netlist library**, not private to the editor.
- **Per-timestep callback cost is a real design signal** for the in-loop Python controller.
- **Document-restore is a contract** that should be tested under failure paths, not only success.
- **Gerber/.kicad_pcb and user-schematic `.dc`** are honest gaps to close or defer.
- **Pin-count parity + glyph correctness** should gate any new board symbol.
- **Component fidelity should be verified under swept I-V/AC**, not assumed.

---

## Honest caveats carried from the repo's own docs

- In-loop firmware = parsed model, not executed image. Compiled image boots+runs in patched QEMU (900k samples/90 s, zero panics); analog injection is real via manual `qom-set`; automatic bridge is not built.
- KiCad schematic + netlist exist; PCB-layout formats do not.
- `.dc` is wired for demo devices; user-schematic `.dc` is raw-netlist-only.
- `.github/workflows/cosim-ci.yml` exists but has never executed in CI history.
- Dockerfile/docker-compose are known broken (predate `find_library` fallback; copy neither `ui/` nor `tools/`).
- Tests cover the Python controller vs three scraped C constants; they do not prove the compiled image's behaviour end-to-end.
- Renode path is abandoned; `circuits/components/models.lib` + demo models are reverse-engineered.

---

## Where to read the per-org detail

Full per-org audit-team sections (interest, read of the codebase, preferred implementation posture) plus the cross-org synthesis and caveats are in:

- [docs/.team-audit-archive/2026-10-08-team-audit-archive.md](docs/.team-audit-archive/2026-10-08-team-audit-archive.md)

---

**Handoff one-liner:** If you want the "which team gets which layer and how they'd implement it" view, start at §3 of the archive; if you want the org-independent roadmap candidates, start at §4; if you want the caveats that any roadmap item must carry, start at §5.
