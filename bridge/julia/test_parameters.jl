using JSON
include(joinpath(@__DIR__, "solve_julia.jl"))

# Test 1: scalar keys (direct protocol)
j1 = """{"circuit":{"type":"rc","resistance":2000.0,"capacitance":1e-6,"input_voltage":5.0},"simulation":{"dt":1e-6,"tstop":0.001}}"""
r1 = solve_julia_circuit(JSON.parse(j1))
@assert r1["status"] == "success"
@assert isapprox(r1["final_vout"], 5*(1-exp(-0.5)), atol=0.01)  # tau=2ms, t=1ms -> 0.5 tau
println("PASS scalar: R=2000 -> final=$(r1["final_vout"]) expected=$(5*(1-exp(-0.5)))")

# Test 2: component-array fallback (julia_bridge.rs original shape)
j2 = """{"circuit":{"type":"rc","name":"custom","resistors":[{"name":"R1","node1":"in","node2":"out","value":2000.0}],"capacitors":[{"name":"C1","node1":"out","node2":"0","value":1e-6}],"voltage_sources":[{"name":"V1","node_p":"in","node_n":"0","kind":"Dc","dc_value":5.0}]},"simulation":{"dt":1e-6,"tstop":0.001}}"""
parsed = JSON.parse(j2)
println("parsed resistors type: ", typeof(parsed["circuit"]["resistors"]))
println("parsed first resistor: ", parsed["circuit"]["resistors"][1])
println("circuit_param R: ", circuit_param(parsed["circuit"], "resistance", "resistors", "value", 1000.0))
r2 = solve_julia_circuit(parsed)
println("PASS array: R from params=$(r2["parameters"]["R"]) final=$(r2["final_vout"])")
@assert isapprox(r2["parameters"]["R"], 2000.0)
@assert isapprox(r2["final_vout"], 5*(1-exp(-0.5)), atol=0.01)

# Test 3: RL custom values (vout = inductor current = Vin/R at steady state)
j3 = """{"circuit":{"type":"rl","resistance":50.0,"inductance":0.01,"input_voltage":12.0},"simulation":{"dt":1e-4,"tstop":0.02}}"""
r3 = solve_julia_circuit(JSON.parse(j3))
@assert isapprox(r3["final_vout"], 12/50, atol=0.01)  # 0.24 A
println("PASS RL: I=$(r3["final_vout"]) expected=0.24")

# Test 4: RLC custom values
j4 = """{"circuit":{"type":"rlc","resistance":10.0,"inductance":1e-3,"capacitance":1e-6,"input_voltage":5.0},"simulation":{"dt":1e-6,"tstop":0.01}}"""
r4 = solve_julia_circuit(JSON.parse(j4))
@assert r4["status"] == "success"
@assert isapprox(r4["parameters"]["L"], 1e-3)
println("PASS RLC: status=$(r4["status"])")

# ---- Layer 1: solver method selection tests ----
expected_rc = 5*(1-exp(-0.5))
for m in ["tsit5", "rosenbrock23", "rodas5p", "fbdf", "vern7", "auto"]
    jm = """{"circuit":{"type":"rc","resistance":2000.0,"capacitance":1e-6,"input_voltage":5.0},"simulation":{"dt":1e-6,"tstop":0.001,"method":"$m"}}"""
    rm = solve_julia_circuit(JSON.parse(jm))
    @assert rm["status"] == "success" "method $m failed: $(rm["status"])"
    @assert isapprox(rm["final_vout"], expected_rc, atol=0.02) "method $m wrong result: $(rm["final_vout"])"
    @assert rm["method"] == m
    println("PASS method $m: final=$(rm["final_vout"]) algo=$(rm["algorithm"])")
end

# Unknown method must return a structured error, not throw
jbad = """{"circuit":{"type":"rc"},"simulation":{"dt":1e-6,"tstop":0.001,"method":"bogus"}}"""
rbad = solve_julia_circuit(JSON.parse(jbad))
@assert rbad["status"] == "error" && rbad["error_type"] == "invalid_method"
println("PASS invalid method handled: $(rbad["error_message"])")

println("ALL PARAMETER TESTS PASSED")
