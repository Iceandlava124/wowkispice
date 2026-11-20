using JSON
include(joinpath(@__DIR__, "solve_julia.jl"))

# ============================================================================
# Validation corpus - Layer 1 Step 3
# Independent reference values from closed-form physics (NOT from the solver).
# Each case compares the numerical solution's final value against an analytic
# expression derived separately. Reports max/mean error and a gate result.
# ============================================================================

struct ValCase
    name::String
    json::String
    analytic::Float64
    tol::Float64
end

cases = ValCase[]

# --- RC step response: V(t) = Vin(1 - e^(-t/RC)) ---
for (R, C, tstop) in [(1000.0, 1e-6, 0.001), (2000.0, 1e-6, 0.001),
                      (500.0, 2.2e-6, 0.002), (10000.0, 0.1e-6, 0.0005)]
    Vin = 5.0
    push!(cases, ValCase(
        "RC R=$R C=$C t=$tstop",
        """{"circuit":{"type":"rc","resistance":$R,"capacitance":$C,"input_voltage":$Vin},"simulation":{"dt":1e-7,"tstop":$tstop,"method":"auto","tolerance":1e-8}}""",
        Vin * (1 - exp(-tstop / (R * C))), 1e-4))
end

# --- RL step: I(t) = Vin/R (1 - e^(-Rt/L)) ---
for (R, L, tstop) in [(50.0, 0.01, 0.02), (100.0, 1e-3, 0.001), (10.0, 0.1, 0.05)]
    Vin = 12.0
    push!(cases, ValCase(
        "RL R=$R L=$L Vin=$Vin",
        """{"circuit":{"type":"rl","resistance":$R,"inductance":$L,"input_voltage":$Vin},"simulation":{"dt":1e-6,"tstop":$tstop,"method":"auto","tolerance":1e-8}}""",
        Vin / R * (1 - exp(-R * tstop / L)), 1e-3))
end

# --- RLC underdamped step: Vc(t) = Vin[1 - e^(-αt)(cos ωd t + (α/ωd) sin ωd t)] ---
# α=R/(2L), ω0=1/sqrt(LC), ωd=sqrt(ω0²-α²). Valid when R < 2√(L/C).
begin
    R, L, C, Vin, tstop = 10.0, 1e-3, 1e-6, 5.0, 0.002
    α = R / (2L); ω0 = 1 / sqrt(L * C); ωd = sqrt(ω0^2 - α^2)
    analytic = Vin * (1 - exp(-α*tstop) * (cos(ωd*tstop) + (α/ωd)*sin(ωd*tstop)))
    push!(cases, ValCase(
        "RLC underdamped R=$R L=$L C=$C",
        """{"circuit":{"type":"rlc","resistance":$R,"inductance":$L,"capacitance":$C,"input_voltage":$Vin},"simulation":{"dt":1e-7,"tstop":$tstop,"method":"auto","tolerance":1e-8}}""",
        analytic, 5e-3))
end

# --- Diode: at steady state, I_in = I_s(e^(V/Vt) - 1) => V = Vt ln(1 + I_in/I_s) ---
begin
    I_in, I_s, V_t, tstop = 1e-3, 1e-12, 0.026, 1e-5
    analytic = V_t * log(1 + I_in / I_s)
    push!(cases, ValCase(
        "Diode I=$I_in Is=$I_s",
        """{"circuit":{"type":"diode","input_current":$I_in,"saturation_current":$I_s,"thermal_voltage":$V_t},"simulation":{"dt":1e-9,"tstop":$tstop,"method":"auto","tolerance":1e-8}}""",
        analytic, 2e-3))
end

# Run the corpus
max_err = 0.0
failed = String[]
println("=== VALIDATION CORPUS ===")
for c in cases
    r = solve_julia_circuit(JSON.parse(c.json))
    if r["status"] != "success"
        push!(failed, "$(c.name): solver status $(r["status"])")
        println("FAIL $(c.name): status=$(r["status"])")
        continue
    end
    got = r["final_vout"]
    err = abs(got - c.analytic)
    global max_err = max(max_err, err)
    ok = err <= c.tol
    println("$(ok ? "PASS" : "FAIL") $(c.name): got=$got analytic=$(c.analytic) err=$err tol=$(c.tol)")
    if !ok
        push!(failed, "$(c.name): err=$err > tol=$(c.tol)")
    end
end

println("=== SUMMARY: $(length(cases) - length(failed))/$(length(cases)) passed, max_err=$max_err ===")
if !isempty(failed)
    for f in failed
        println("  FAILED: ", f)
    end
    error("VALIDATION CORPUS FAILED")
end
println("VALIDATION CORPUS PASSED")
