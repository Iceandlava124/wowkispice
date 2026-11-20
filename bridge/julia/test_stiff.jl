using JSON
include(joinpath(@__DIR__, "solve_julia.jl"))

# Stiff circuit: R=1000, L=1e-6 -> tau = L/R = 1 microsecond.
# Simulating to 1 ms spans 1000 time constants. An explicit method (Tsit5)
# must resolve the fast initial transient with tiny steps; a stiff method
# (Rosenbrock23, used by 'auto') should need far fewer steps.
tstop = 1e-3
params = (R = 1000.0, L = 1e-6, Vin = 12.0)
analytic = params.Vin / params.R  # steady-state current = 0.012 A

results = Dict{String,Any}()
for m in ["tsit5", "auto"]
    j = """{"circuit":{"type":"rl","resistance":$(params.R),"inductance":$(params.L),"input_voltage":$(params.Vin)},"simulation":{"dt":1e-9,"tstop":$tstop,"method":"$m","tolerance":1e-6}}"""
    r = solve_julia_circuit(JSON.parse(j))
    @assert r["status"] == "success"
    @assert isapprox(r["final_vout"], analytic, atol=1e-5) "stiff case $m wrong: $(r["final_vout"])"
    results[m] = r
    println("method=$m steps=$(r["steps_taken"]) final=$(r["final_vout"]) algo=$(r["algorithm"][1:min(end,40)])")
end

# The stiff-aware 'auto' solver should not take MORE steps than explicit Tsit5
# on this stiff problem (usually far fewer). This proves the switching works.
tsit_steps = results["tsit5"]["steps_taken"]
auto_steps = results["auto"]["steps_taken"]
println("steps: tsit5=$tsit_steps auto=$auto_steps")
@assert auto_steps <= tsit_steps "auto solver should not need more steps on a stiff problem"
println("PASS stiff-circuit: auto solver handles stiff RL efficiently (steps=$auto_steps <= tsit5=$tsit_steps)")
