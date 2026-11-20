# The solver only uses Tsit5 and ODEProblem, both from OrdinaryDiffEq.
# Importing the full DifferentialEquations meta-package would pull in ~300
# packages (SDEs, DDEs, DAEs, ...) that this script never calls.
using OrdinaryDiffEq
using JSON
using Statistics

# Resolve the requested solver method. All algorithms come from the pinned
# OrdinaryDiffEq project. "auto" uses AutoTsit5(Rosenbrock23()) which switches
# to a stiff solver when the problem requires it -- this is the industry-grade
# default because a fixed explicit method can fail on stiff circuits.
function select_algorithm(method::String)
    m = lowercase(method)
    if m == "tsit5"
        return Tsit5()
    elseif m == "rosenbrock23"
        return Rosenbrock23()
    elseif m == "rodas5p"
        return Rodas5P()
    elseif m == "fbdf"
        return FBDF()
    elseif m == "vern7"
        return Vern7()
    elseif m == "auto" || m == "autotsit5"
        return AutoTsit5(Rosenbrock23())
    else
        # Unknown method: fail loudly rather than silently use a different one
        throw(ArgumentError("unknown solver method '$method' (supported: tsit5, rosenbrock23, rodas5p, fbdf, vern7, auto)"))
    end
end

# Resolve a circuit parameter from the JSON protocol.
#
# Rust (julia_bridge.rs) sends BOTH explicit scalar keys and component arrays
# ([{"name":...,"node1":...,"node2":...,"value":...}, ...]). Older callers may
# send only one shape, so prefer the scalar key and fall back to the first
# component in the array. This is what makes component values actually
# configurable instead of silently using hard-coded defaults.
function circuit_param(circuit, scalar_key, array_key, value_key, default::Float64)
    if haskey(circuit, scalar_key)
        v = circuit[scalar_key]
        v isa Number && return Float64(v)
    end
    if haskey(circuit, array_key)
        arr = circuit[array_key]
        if arr isa AbstractVector && !isempty(arr)
            first_item = arr[1]
            # JSON.jl parses objects as JSON.Object <: AbstractDict, not Dict
            if first_item isa AbstractDict && haskey(first_item, value_key)
                v = first_item[value_key]
                v isa Number && return Float64(v)
            end
        end
    end
    return default
end

# Main solver function that takes JSON input and returns JSON output
function solve_julia_circuit(circuit_json)
    circuit = circuit_json["circuit"]
    simulation = circuit_json["simulation"]

    dt = simulation["dt"]
    tstop = simulation["tstop"]
    method = get(simulation, "method", "auto")
    tolerance = get(simulation, "tolerance", 1e-6)

    # Resolve the solver; unknown methods return a structured error (not a throw).
    local algorithm
    try
        algorithm = select_algorithm(method)
    catch e
        return Dict{String,Any}("status" => "error", "error_type" => "invalid_method",
            "error_message" => string(e), "solve_time_ms" => 0.0)
    end

    circuit_type_lower = lowercase(get(circuit, "type", "rc"))

    # --- Parameters resolved from JSON (with documented defaults) ---
    # Scalars are preferred; component arrays from julia_bridge.rs are the
    # fallback so both protocol shapes work.
    R = circuit_param(circuit, "resistance", "resistors", "value", 1000.0)
    C = circuit_param(circuit, "capacitance", "capacitors", "value", 1e-6)
    L = circuit_param(circuit, "inductance", "inductors", "value", 1e-3)
    Vin = circuit_param(circuit, "input_voltage", "voltage_sources", "dc_value", 5.0)
    I_in = circuit_param(circuit, "input_current", "current_sources", "value", 1e-3)
    # Diode physics constants: only explicit scalar keys are meaningful here
    # (a diode's generic "value" field may encode a part number or Vf, not I_s).
    I_s = haskey(circuit, "saturation_current") ? Float64(circuit["saturation_current"]) : 1e-12
    V_t = haskey(circuit, "thermal_voltage") ? Float64(circuit["thermal_voltage"]) : 0.026

    # --- Diode model (Shockley equation) ---
    function diode_ode!(du, u, p, t)
        V = u[1]
        du[1] = I_in - I_s * (exp(V / V_t) - 1)
    end

    # --- RL circuit model: dI/dt = (Vin - I*R)/L ---
    function rl_ode!(du, u, p, t)
        I = u[1]
        du[1] = (Vin - I * R) / L
    end

    # --- RLC resonance model (state: [capacitor voltage, inductor current]) ---
    function rlc_ode!(du, u, p, t)
        V_c = u[1]
        I_l = u[2]
        du[1] = I_l / C
        du[2] = (Vin - R * I_l - V_c) / L
    end

    # --- RC circuit model: dVc/dt = (Vin - Vc)/(R*C) ---
    function rc_ode!(du, u, p, t)
        du[1] = (Vin - u[1]) / (R * C)
    end

    u0 = [0.0, 0.0]
    tspan = (0.0, tstop)

    sol = nothing
    start_time = time_ns()
    if circuit_type_lower == "diode"
        try
            prob = ODEProblem(diode_ode!, u0, tspan)
            sol = solve(prob, algorithm; abstol=tolerance, reltol=tolerance)
        catch e
            elapsed_ms = Float64(time_ns() - start_time) / 1_000_000
            return Dict{String,Any}("status" => "error", "error_type" => "solver_failure", "error_message" => string(e), "solve_time_ms" => elapsed_ms)
        end
    elseif circuit_type_lower == "rl"
        try
            prob = ODEProblem(rl_ode!, u0, tspan)
            sol = solve(prob, algorithm; abstol=tolerance, reltol=tolerance)
        catch e
            elapsed_ms = Float64(time_ns() - start_time) / 1_000_000
            return Dict{String,Any}("status" => "error", "error_type" => "solver_failure", "error_message" => string(e), "solve_time_ms" => elapsed_ms)
        end
    elseif circuit_type_lower == "rlc"
        try
            prob = ODEProblem(rlc_ode!, u0, tspan)
            sol = solve(prob, algorithm; abstol=tolerance, reltol=tolerance)
        catch e
            elapsed_ms = Float64(time_ns() - start_time) / 1_000_000
            return Dict{String,Any}("status" => "error", "error_type" => "solver_failure", "error_message" => string(e), "solve_time_ms" => elapsed_ms)
        end
    else
        try
            prob = ODEProblem(rc_ode!, u0, tspan)
            sol = solve(prob, algorithm; abstol=tolerance, reltol=tolerance)
        catch e
            elapsed_ms = Float64(time_ns() - start_time) / 1_000_000
            return Dict{String,Any}("status" => "error", "error_type" => "solver_failure", "error_message" => string(e), "solve_time_ms" => elapsed_ms)
        end
    end

    solve_time_ms = Float64(time_ns() - start_time) / 1_000_000

    if sol === nothing || length(sol.t) == 0 || length(sol.u) == 0
        return Dict{String,Any}("status" => "error", "error_type" => "convergence_failure", "error_message" => "Solver returned no valid solution", "solve_time_ms" => solve_time_ms)
    end

    vout = Float64[sol.u[i][1] for i in 1:length(sol.u)]
    final_vout = Float64(last(vout))
    avg_vout = Float64(mean(vout))
    vout_ripple = Float64(maximum(vout) - minimum(vout))

    result = Dict{String,Any}(
        "status" => "success",
        "times" => Float64[sol.t[i] for i in 1:length(sol.t)],
        "vout" => vout,
        "final_vout" => final_vout,
        "avg_vout" => avg_vout,
        "vout_ripple" => vout_ripple,
        "steps_taken" => Int(length(sol.t)),
        "circuit_type" => circuit_type_lower,
        "solve_time_ms" => solve_time_ms,
        "method" => method,
        "algorithm" => string(typeof(algorithm)),
        # Echo resolved parameters so callers can confirm what was simulated
        "parameters" => Dict{String,Any}(
            "R" => R, "C" => C, "L" => L, "Vin" => Vin,
            "I_in" => I_in, "I_s" => I_s, "V_t" => V_t,
        ),
    )
    return result
end

# If running as script with command line argument
if length(ARGS) > 0
    try
        input_json = ARGS[1]
        circuit_json = JSON.parse(input_json)
        result = solve_julia_circuit(circuit_json)
        println(JSON.json(result))
    catch e
        if length(ARGS) > 0
            try
                err_dict = Dict{String,Any}(
                    "status" => "error",
                    "error_type" => "json_parse_error",
                    "error_message" => "Invalid JSON input: " * string(e),
                    "solve_time_ms" => 0.0
                )
                println(JSON.json(err_dict))
            catch
                println("Error: Invalid input - must provide valid JSON as first argument")
            end
        else
            println("Error: No input provided")
        end
    end
end
