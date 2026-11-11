using DifferentialEquations
using JSON

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

    # Simple RC circuit model
    # R in series with C to ground, Vin applied
    R = 1000.0  # ohms
    C = 1e-6    # farads
    Vin = 5.0   # volts

    # ODE for RC circuit: dVc/dt = (Vin - Vc) / (R*C)
    function rc_ode!(du, u, p, t)
        du[1] = (Vin - u[1]) / (R * C)
    end

    u0 = [0.0]  # initial capacitor voltage
    tspan = (0.0, tstop)

    # Choose solver based on method
    if method == "Tsit5"
        prob = ODEProblem(rc_ode!, u0, tspan)
        sol = solve(prob, Tsit5(); abstol=tolerance, reltol=tolerance)
    elseif method == "Rodas5"
        prob = ODEProblem(rc_ode!, u0, tspan)
        sol = solve(prob, Rodas5(); abstol=tolerance, reltol=tolerance)
    else
        prob = ODEProblem(rc_ode!, u0, tspan)
        sol = solve(prob, Tsit5(); abstol=tolerance, reltol=tolerance)
    end

    # Prepare output times and voltages
    times = [sol.t[i] for i in 1:length(sol.t)]
    vout = [sol.u[i][1] for i in 1:length(sol.u)]

    # Compute summary stats
    final_vout = last(vout)
    avg_vout = mean(vout)
    vout_ripple = maximum(vout) - minimum(vout)

    result = Dict(
        "status" => "success",
        "times" => times,
        "vout" => vout,
        "final_vout" => final_vout,
        "avg_vout" => avg_vout,
        "vout_ripple" => vout_ripple,
        "steps_taken" => length(sol.t)
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
        println("Error: ", e)
        println("Usage: julia solve_julia.jl '{\"circuit\": {...}, \"simulation\": {...}}'")
    end
end