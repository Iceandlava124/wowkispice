# Julia Deployment Guide

## Distribution Model: "Bring Your Own Julia"

This project does NOT bundle Julia in the Windows installer. Julia is a **user-installed runtime dependency** (~150-300MB). This decision keeps the baseline binary small (~20MB) and avoids NSIS template drift.

### ✅ What's Included in the Windows Installer

- Rust core (`wowkispice-core` crate) — zero external dependencies
- Julia backend bridge code (`julia_bridge.rs`, `solve_julia.jl`)
- All 342 Rust tests (baseline + Julia feature)
- Documentation (`JULIA_SETUP.md`)
- CI configuration (`julia-ci.yml`)

### 📋 User Installation Steps

**1. Install Julia 1.13.x**
- Download from: https://julialang.org/downloads/
- Verify: `julia --version` → `1.13.3`

**2. Install Required Packages**
Open Julia REPL and run:
```julia
using Pkg
Pkg.add(["DifferentialEquations", "JSON"])
```
- `DifferentialEquations.jl` — ODE solver (Tsit5, Rodas5, etc.)
- `JSON.jl` — JSON parsing for Rust⇄Julia communication

**3. First-Run Precompilation**
- The **first** Julia invocation takes 30-60 seconds for package precompilation
- Subsequent calls are **instant** (<1s)

**4. Run with Rust**
```bash
# Baseline (no Julia needed)
cargo test

# With Julia solver enabled
cargo test --features julia
```

### 📦 SBOM (Software Bill of Materials)

**SBOM Status**: Component list documented; formal CycloneDX generation requires `cyclonedx-bom` toolchain with internet access and Python build environment (lxml compilation).

| Component | Location | License | Notes |
|-----------|----------|---------|-------|
| `wowkispice-core` crate | `crates/wowkispice-core/` | MIT/Apache-2.0 (workspace) | Rust library, zero runtime deps |
| `julia_bridge.rs` | `crates/wowkispice-core/src/` | MIT/Apache-2.0 | FFI bridge, feature-flagged |
| `solve_julia.jl` | `bridge/julia/` | MIT | Julia solver, 4 circuit models |
| `DifferentialEquations.jl` | User-installed runtime | MIT | ODE solver package |
| `JSON.jl` | User-installed runtime | MIT | JSON parsing package |
| `ngspice.dll` | Optional bundled dependency | LGPL-3.0 | For ngspice integration |

**SBOM Format**: CycloneDX JSON.

**How to Generate SBOM** (when toolchain is available):
```bash
# Install the toolchain
python3 -m pip install cython lxml

# Run SBOM generation (from workspace root)
cd ..
cyclonedx-bom -j -o SBOMs/cyclonedx-bom.json \
  -p crates/wowkispice-core \
  -p bridge/julia \
  --parsers rust,cpp,python

# The SBOM artifact is available as a GitHub Actions workflow artifact:
#   Name: cyclonedx-sbom
#   Path: SBOMs/cyclonedx-bom.json
```

**SBOM Exclusions**:
- Windows OS components
- Build-time tools (CMake, NSIS, Python)
- Developer local configuration files

### 📦 Deployment Artifacts

| Artifact | Size | Included | Notes |
|----------|------|----------|-------|
| `wowkispice-core` crate | ~20MB | ✅ | Rust only, zero deps |
| `Julia backend files` | ~2MB | ✅ | Source code only |
| `Julia runtime` | 150-300MB | ❌ | User-installed, "Bring Your Own Julia" |
| **Total deployment size** | **~20MB** | ✅ | No Julia needed for baseline |

### 🔧 For IT / DevOps Teams

| Requirement | Status |
|-----------|--------|
| **Group policy Julia installation** | ✅ Supported via Julia installer MSI |
| **Silent Julia install** | ✅ `julia-1.13.x-windows-x86_64.exe /quiet` |
| **Environment variable setup** | ✅ Add `C:\Julia\bin` to PATH |
| **Docker / CI integration** | ✅ See `julia-ci.yml` configuration |
| **Audit / SBOM generation** | ⚠️ Requires `cyclonedx-bom` toolchain; see above |

### 🔄 Upgrading Julia

To upgrade from Julia 1.13.x to 1.13.(x+1):
```bash
# Download new installer from julialang.org
# Run installer (overwrites existing installation)
# Reinstall packages:
using Pkg
Pkg.upgrade()
```

### 🆘 Troubleshooting

| Issue | Solution |
|-------|----------|
| `julia not found in PATH` | Add `C:\Julia\bin` to system PATH |
| `Package DifferentialEquations not found` | Run: `julia -e 'using Pkg; Pkg.add("DifferentialEquations")'` |
| `Solver failed to converge` | Check circuit topology; try `Rodas5` instead of `Tsit5` |
| `JSON parse error` | Verify input JSON matches expected schema |

### 📞 Support

- **Julia issues**: https://julialang.zendesk.com/
- **This project**: Open issues on GitHub `baseline-fix` branch
- **Performance questions**: Documentation describes benchmark methodology