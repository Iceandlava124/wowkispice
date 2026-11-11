using DifferentialEquations
using JSON
using Statistics

# Main solver function that takes JSON input and returns JSON output
function solve_julia_circuit(circuit_json)
    # Parse the circuit description
    circuit = circuit_json["circuit"]
    simulation = circuit_json["simulation"]

    # Extract parameters
    dt = simulation["dt"]
    tstop = simulation["tstop"]
    method = get(simulation, "method", "Tsit5")
    tolerance = get(simulation, "tolerance", 1e-6)

    # Circuit type selection (from circuit["type"])
    circuit_type_lower = lowercase(get(circuit, "type", "rc"))

    # Thermal voltage for diode model
    V_t = 0.026  # ~26mV at room temperature

    # --- Diode model (Shockley equation) ---
    # Input current captured from circuit JSON
    function diode_ode!(du, u, p, t)
        I_in = get(circuit, "input_current", 1e-3)  # from circuit JSON, default 1mA
        I = u[1]  # diode current
        V = u[1]  # diode voltage
        I_s = 1e-12  # saturation current
        du[1] = (I_in - I_s*(exp(V/V_t)-1))  # input_current - diode current
    end

    # --- RL circuit model ---
    # Input voltage, R, L captured from circuit JSON
    function rl_ode!(du, u, p, t)
        V_in = get(circuit, "input_voltage", 5.0)  # from circuit JSON, default 5V
        R = get(circuit, "resistance", 100.0)  # from circuit JSON, default 100 ohms
        L = get(circuit, "inductance", 1e-3)  # from circuit JSON, default 1mH
        I = u[1]  # inductor current
        du[1] = (V_in - I*R)/L
    end

    # --- RLC resonance model (underdamped) ---
    # Input voltage, R, L, C captured from circuit JSON
    function rlc_ode!(du, u, p, t)
        V_in = get(circuit, "input_voltage", 5.0)  # from circuit JSON, default 5V
        R = get(circuit, "resistance", 10.0)  # from circuit JSON, default 10 ohms
        L = get(circuit, "inductance", 1e-3)  # from circuit JSON, default 1mH
        C = get(circuit, "capacitance", 1e-6)  # from circuit JSON, default 1uF
        V_c = u[1]  # capacitor voltage
        I_l = u[2]  # inductor current
        du[1] = I_l  # dVc/dt = I_l/C
        du[2] = (V_in - R*I_l - V_c)/L  # dI_l/dt = (V - R*I - V_c)/L
    end

    # --- Simple RC circuit model (default) ---
    # R, C, Vin used with default values
    R = 1000.0  # ohms
    C = 1e-6  # farads
    Vin = 5.0   # volts

    # ODE for RC circuit: dVc/dt = (Vin - Vc) / (R*C)
    function rc_ode!(du, u, p, t)
        du[1] = (Vin - u[1]) / (R * C)
    end

    # Initial capacitor/inductor voltage
    u0 = [0.0, 0.0]  # [capacitor voltage, inductor current]
    tspan = (0.0, tstop)

    # Choose circuit type and solver with error handling + timing
    sol = nothing
    start_time = time_ns()
    if circuit_type_lower == "diode"
        try
            prob = ODEProblem(diode_ode!, u0, tspan)
            sol = solve(prob, Tsit5(); abstol=tolerance, reltol=tolerance)
        catch e
            elapsed_ms = Float64(time_ns() - start_time) / 1_000_000
            return Dict{String,Any}("status" => "error", "error_type" => "solver_failure", "error_message" => string(e), "solve_time_ms" => elapsed_ms)
        end
    elseif circuit_type_lower == "rl"
        try
            prob = ODEProblem(rl_ode!, u0, tspan)
            sol = solve(prob, Tsit5(); abstol=tolerance, reltol=tolerance)
        catch e
            elapsed_ms = Float64(time_ns() - start_time) / 1_000_000
            return Dict{String,Any}("status" => "error", "error_type" => "solver_failure", "error_message" => string(e), "solve_time_ms" => elapsed_ms)
        end
    elseif circuit_type_lower == "rlc"
        try
            prob = ODEProblem(rlc_ode!, u0, tspan)
            sol = solve(prob, Tsit5(); abstol=tolerance, reltol=tolerance)
        catch e
            elapsed_ms = Float64(time_ns() - start_time) / 1_000_000
            return Dict{String,Any}("status" => "error", "error_type" => "solver_failure", "error_message" => string(e), "solve_time_ms" => elapsed_ms)
        end
    else
        # Default to RC circuit
        try
            prob = ODEProblem(rc_ode!, u0, tspan)
            sol = solve(prob, Tsit5(); abstol=tolerance, reltol=tolerance)
        catch e
            elapsed_ms = Float64(time_ns() - start_time) / 1_000_000
            return Dict{String,Any}("status" => "error", "error_type" => "solver_failure", "error_message" => string(e), "solve_time_ms" => elapsed_ms)
        end
    end

    solve_time_ms = Float64(time_ns() - start_time) / 1_000_000

    # Verify solver succeeded: check sol !== nothing and solution has data
    if sol === nothing || length(sol.t) == 0 || length(sol.u) == 0
        return Dict{String,Any}("status" => "error", "error_type" => "convergence_failure", "error_message" => "Solver returned no valid solution", "solve_time_ms" => solve_time_ms)
    end

    # Prepare output times and voltages
    # For single-variable circuits (RC, diode, RL): vout = u[1]
    # For RLC: vout = u[1] (capacitor voltage)
    vout = Float64[sol.u[i][1] for i in 1:length(sol.u)]

    # Compute summary stats
    final_vout = Float64(last(vout))
    avg_vout = Float64(mean(vout))
    vout_ripple = Float64(maximum(vout) - minimum(vout))

    # Build result Dict with explicit types for JSON safety
    result = Dict{String,Any}(
        "status" => "success",
        "times" => Float64[sol.t[i] for i in 1:length(sol.t)],
        "vout" => vout,
        "final_vout" => final_vout,
        "avg_vout" => avg_vout,
        "vout_ripple" => vout_ripple,
        "steps_taken" => Int(length(sol.t)),
        "circuit_type" => circuit_type_lower,
        "solve_time_ms" => solve_time_ms
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
        # Return error as JSON if JSON parse fails or solver fails
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