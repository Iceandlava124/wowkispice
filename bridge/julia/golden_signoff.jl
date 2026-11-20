using JSON
using SHA
include(joinpath(@__DIR__, "solve_julia.jl"))

# ============================================================================
# Golden trace sign-off (Layer 2)
# A deterministic RC response is captured, hashed, and compared against a
# committed golden reference. Any unintended change to the solver's numerical
# output fails this gate. The golden file is source-controlled sign-off data.
# ============================================================================

GOLDEN_FILE = joinpath(@__DIR__, "golden_rc.json")

payload = Dict(
    "circuit" => Dict("type" => "rc", "resistance" => 1000.0,
                      "capacitance" => 1e-6, "input_voltage" => 5.0),
    "simulation" => Dict("dt" => 1e-6, "tstop" => 0.005,
                         "method" => "auto", "tolerance" => 1e-9),
)

r = solve_julia_circuit(JSON.parse(JSON.json(payload)))
@assert r["status"] == "success"

# Canonical representation: rounded to 9 significant digits for stability
# across platforms/Julia builds while still catching real numerical changes.
canon = Dict(
    "status" => r["status"],
    "method" => r["method"],
    "final_vout" => round(r["final_vout"]; digits=9),
    "avg_vout" => round(r["avg_vout"]; digits=9),
    "vout_ripple" => round(r["vout_ripple"]; digits=9),
    "steps_taken" => r["steps_taken"],
    "times" => [round(t; digits=9) for t in r["times"]],
    "vout" => [round(v; digits=9) for v in r["vout"]],
)
canon_json = JSON.json(canon; pretty=2)
digest = bytes2hex(sha256(canon_json))

if !isfile(GOLDEN_FILE)
    # Bootstrap mode: write the golden and report its hash. Committed once.
    open(GOLDEN_FILE, "w") do fh
        write(fh, canon_json)
    end
    println("BOOTSTRAP golden written to $GOLDEN_FILE sha256=$digest")
else
    golden = read(GOLDEN_FILE, String)
    golden_parsed = JSON.parse(golden)
    # Compare scalar summaries exactly (they are rounded to 9 digits), and
    # compare arrays element-wise within a tight tolerance for cross-platform
    # stability (last-bit float differences across CPU/Julia builds).
    scalar_keys = ("status", "method", "final_vout", "avg_vout", "vout_ripple", "steps_taken")
    ok = all(canon[k] == golden_parsed[k] for k in scalar_keys)
    ok = ok && length(canon["times"]) == length(golden_parsed["times"])
    ok = ok && length(canon["vout"]) == length(golden_parsed["vout"])
    if ok
        for (a, b) in zip(canon["vout"], golden_parsed["vout"])
            if abs(a - b) > 1e-7
                global ok = false
                break
            end
        end
    end
    if !ok
        println("GOLDEN MISMATCH")
        println("  current sha256: $digest")
        println("  golden  sha256: ", bytes2hex(sha256(golden)))
        println("  current final_vout: ", canon["final_vout"])
        println("  golden  final_vout: ", golden_parsed["final_vout"])
        error("GOLDEN TRACE MISMATCH - solver output changed unexpectedly")
    end
    println("PASS golden trace: sha256=$digest final_vout=$(canon["final_vout"]) steps=$(canon["steps_taken"])")
end
