using JSON
include(joinpath(@__DIR__, "solve_julia.jl"))

# ============================================================================
# Input validation tests (Layer 3: robustness & safety)
# Invalid inputs must fail CLEANLY with structured errors - never hang, crash,
# or produce silent NaN/Inf output.
# ============================================================================

function expect_error(json_str, label)
    r = solve_julia_circuit(JSON.parse(json_str))
    @assert r["status"] == "error" "$label should fail but got: $(r["status"])"
    @assert haskey(r, "error_type") "$label missing error_type"
    println("PASS $label: error_type=$(r["error_type"])")
end

# Valid baseline to mutate
base = Dict("circuit" => Dict("type" => "rc", "resistance" => 1000.0,
                              "capacitance" => 1e-6, "input_voltage" => 5.0),
            "simulation" => Dict("dt" => 1e-6, "tstop" => 0.001, "method" => "auto"))

# --- Negative/zero component values ---
bad = deepcopy(base); bad["circuit"]["resistance"] = 0.0
expect_error(JSON.json(bad), "zero resistance")
bad = deepcopy(base); bad["circuit"]["capacitance"] = -1e-6
expect_error(JSON.json(bad), "negative capacitance")

# --- Invalid simulation params ---
bad = deepcopy(base); bad["simulation"]["tstop"] = 0.0
expect_error(JSON.json(bad), "zero tstop")
bad = deepcopy(base); bad["simulation"]["dt"] = -1e-6
expect_error(JSON.json(bad), "negative dt")
bad = deepcopy(base); bad["simulation"]["tstop"] = 1e-9; bad["simulation"]["dt"] = 1e-6
expect_error(JSON.json(bad), "dt larger than tstop")

# --- NaN / Inf (JSON.jl can parse these as strings or floats) ---
bad = deepcopy(base); bad["circuit"]["resistance"] = "NaN"
expect_error(JSON.json(bad), "non-numeric resistance")

# --- Missing required fields ---
bad = Dict("circuit" => Dict("type" => "rc"), "simulation" => Dict("dt" => 1e-6))
expect_error(JSON.json(bad), "missing tstop")

# Valid input must still succeed
r = solve_julia_circuit(JSON.parse(JSON.json(base)))
@assert r["status"] == "success"
@assert all(isfinite, r["vout"])
println("PASS valid input succeeds with finite output")

println("ALL VALIDATION TESTS PASSED")
