using JSON
include(joinpath(@__DIR__, "solve_julia.jl"))

# Performance regression gate (Layer 7): a reference solve must complete
# within a generous wall-clock budget. This catches pathological slowdowns
# (e.g. a solver change that suddenly takes 100x more steps) without being
# flaky on slow CI runners. Correctness is gated separately by other tests.
payload = Dict("circuit" => Dict("type" => "rc", "resistance" => 1000.0,
                                 "capacitance" => 1e-6, "input_voltage" => 5.0),
               "simulation" => Dict("dt" => 1e-6, "tstop" => 0.005, "method" => "auto"))

r = solve_julia_circuit(JSON.parse(JSON.json(payload)))
@assert r["status"] == "success"
ms = r["solve_time_ms"]
# Generous 30s budget for a simple RC solve; catches catastrophic regressions.
@assert ms < 30000 "solve took $(ms)ms, expected < 30000ms"
println("PASS perf: solve_time_ms=$ms steps=$(r["steps_taken"]) (budget 30000ms)")
