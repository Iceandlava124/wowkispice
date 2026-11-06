/*
 * mock_controller.rs - Mock MCU firmware running closed-loop hysteretic control.
 *
 * Port of bridge/mock_controller.py to Rust, using wowkispice-ffi::NgSpiceFfi.
 *
 * Simulates ESP32 firmware:
 *   - Input: Feedback voltage from a 2:1 resistive divider (V_fb = V_out / 2)
 *   - ADC: 12-bit (0..4095 counts for 0..3.3V)
 *   - Output: GPIO 0V / 3.3V
 *
 * The defaults are DERIVED FROM firmware/esp32_buck_controller/src/main.c, not
 * picked by hand, so this path and bridge/control_law.py agree on the decision
 * boundary:
 *
 *     count = (target +/- hyst) * divider_ratio / adc_vref * 4095
 *
 * The firmware declares ADC_LOW_THRESHOLD 1995 and ADC_HIGH_THRESHOLD 2030.
 * Inverting that with divider_ratio 0.5 and vref 3.3 gives target 3.2436 V and
 * hysteresis 0.0282 V, which reproduce 1995 and 2030 exactly.
 *
 * Note: ngspice is a process-wide singleton. These functions deliberately do
 * NOT call engine.quit() - quitting would break every later engine in this
 * process (observed as a hang). Process exit tears it down.
 */

use std::fs;
use std::path::Path;
use std::sync::{Arc, Mutex};

use crate::NgSpiceFfi;
use crate::NgVectorInfo;

/// Result of a closed-loop co-simulation run.
pub struct ClosedLoopResult {
    pub time_ms: Vec<f64>,      // time in milliseconds
    pub vout: Vec<f64>,         // output voltage (V)
    pub vgate: Vec<f64>,        // gate drive voltage (V)
    pub avg_vout: f64,          // steady-state average Vout (V)
    pub ripple_p2p: f64,        // peak-to-peak ripple in steady state (V)
    pub switch_count: i64,      // total GPIO transitions
}

/// Mock ESP32 buck controller - hysteretic control law.
///
/// Reads the divided feedback node, quantises to 12-bit ADC counts,
/// applies hysteretic thresholds, and drives the gate pin.
pub struct MockESP32BuckController {
    pub target_vout: f64,
    pub hyst_vout: f64,
    pub divider_ratio: f64,
    pub adc_vref: f64,
    pub adc_low: i64,
    pub adc_high: i64,
    pub gpio_state: bool,        // false = 0V (LOW), true = 3.3V (HIGH)
    pub latest_vout: f64,
    pub latest_fb: f64,
    pub switch_count: i64,
    pub history_time: Vec<f64>,
    pub history_vout: Vec<f64>,
    pub history_vgate: Vec<f64>,
}

impl MockESP32BuckController {
    pub fn new(
        target_vout: f64,
        hyst_vout: f64,
        divider_ratio: f64,
        adc_vref: f64,
    ) -> Self {
        // Feedback voltage thresholds at the divider output.
        let v_fb_low = (target_vout - hyst_vout) * divider_ratio;
        let v_fb_high = (target_vout + hyst_vout) * divider_ratio;

        // 12-bit ADC threshold counts (0..4095).
        let adc_low = ((v_fb_low / adc_vref) * 4095.0) as i64;
        let adc_high = ((v_fb_high / adc_vref) * 4095.0) as i64;

        Self {
            target_vout,
            hyst_vout,
            divider_ratio,
            adc_vref,
            adc_low,
            adc_high,
            gpio_state: false,
            latest_vout: 0.0,
            latest_fb: 0.0,
            switch_count: 0,
            history_time: Vec::new(),
            history_vout: Vec::new(),
            history_vgate: Vec::new(),
        }
    }

    /// Called by ngspice at every transient calculation step (sync callback).
    /// Reads the `vout` and `fb` vectors from the live plot via get_vec_info.
    pub fn on_sync(
        &mut self,
        actual_time: f64,
        _old_delta: f64,
        _redostep: i32,
        _ident: i32,
        _location: i32,
        get_vec_info: extern "C" fn(*mut i8) -> *mut NgVectorInfo,
    ) -> i32 {
        // Read vout - last accepted sample from the solver.
        if let Some(val) = unsafe { read_last_sample(get_vec_info, b"vout") } {
            self.latest_vout = val;
            self.history_time.push(actual_time);
            self.history_vout.push(val);
            self.history_vgate
                .push(if self.gpio_state { 3.3 } else { 0.0 });
        }
        // Read fb - the divider output the ADC actually samples.
        if let Some(val) = unsafe { read_last_sample(get_vec_info, b"fb") } {
            self.latest_fb = val;
        }
        0
    }

    /// Called by ngspice whenever it evaluates the external voltage source (Vgate).
    /// Executes the hysteretic decision logic and returns the pin voltage.
    pub fn on_vsrc(&mut self) -> f64 {
        // Feedback comes from the simulated divider node. This is what the
        // ADC pin sees, including the effect of Rfb_top/Rfb_bot loading
        // vout. divider_ratio is NOT applied here - it was already used
        // to derive the thresholds in the constructor.
        let v_feedback = self.latest_fb;

        // 12-bit ADC quantization (0..3.3V -> 0..4095).
        let raw_adc = ((v_feedback / self.adc_vref) * 4095.0).clamp(0.0, 4095.0) as i64;

        let old_state = self.gpio_state;
        if raw_adc < self.adc_low {
            self.gpio_state = true;   // Turn MOSFET ON (charge inductor)
        } else if raw_adc > self.adc_high {
            self.gpio_state = false;  // Turn MOSFET OFF (freewheel diode)
        }

        if self.gpio_state != old_state {
            self.switch_count += 1;
        }

        if self.gpio_state { 3.3 } else { 0.0 }
    }
}

/// Raw ngspice vector info (mirrors sharedspice.h layout) for reading samples.
/// Re-exported from lib.rs; kept here for documentation clarity.
type NgVectorInfoRaw = NgVectorInfo;

/// Read the last sample of a named real vector via ngGet_Vec_Info.
/// Safe wrapper: the raw pointer dereference inside is unsafe but confined.
fn read_last_sample(
    get_vec_info: extern "C" fn(*mut i8) -> *mut NgVectorInfo,
    name: &[u8],
) -> Option<f64> {
    let c_name = std::ffi::CString::new(name).ok()?;
    let info = unsafe { get_vec_info(c_name.as_ptr() as *mut i8) };
    if info.is_null() {
        return None;
    }
    let info = unsafe { &*info };
    if info.v_length <= 0 || info.v_realdata.is_null() {
        return None;
    }
    Some(unsafe { *info.v_realdata.add(info.v_length as usize - 1) })
}

/// Run high-speed closed-loop co-simulation between Mock ESP32 and ngspice Buck Converter.
///
/// Loads `circuits/buck_converter.cir`, sets up VSRC + sync callbacks,
/// runs a transient analysis, and returns steady-state metrics.
pub fn run_closed_loop_simulation(
    total_time_ms: f64,
    tstep_us: f64,
) -> Result<ClosedLoopResult, String> {
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .ok_or("cannot determine repo root")?;
    let cir_path = repo_root.join("circuits").join("buck_converter.cir");
    let cir_path_str = cir_path
        .to_str()
        .ok_or("circuit path is not valid UTF-8")?;

    let controller = Arc::new(Mutex::new(MockESP32BuckController::new(
        3.2436, 0.0282, 0.5, 3.30,
    )));

    let mut engine = NgSpiceFfi::new().map_err(|e| format!("cannot start ngspice: {e}"))?;

    // Extract get_vec_info_fn BEFORE calling init_sync, since callbacks fire
    // during the sync call and &self is not available.
    let get_vec_info_fn = engine
        .get_vec_info_fn()
        .ok_or("ngGet_Vec_Info not resolved")?;

    let controller_clone = controller.clone();
    let vsrc_cb = Box::new(move |_time: f64, _name: &str| -> f64 {
        // on_vsrc is called by ngspice to get the pin voltage.
        // We need to mutate the controller, so lock it.
        let mut c = controller_clone.lock().unwrap();
        c.on_vsrc()
    });

    let controller_sync = controller.clone();
    let sync_cb = Box::new(move |time: f64, _old_delta: f64, _redostep: i32, _id: i32, _location: i32| -> i32 {
        let mut c = controller_sync.lock().unwrap();
        c.on_sync(time, 0.0, 0, 0, 0, get_vec_info_fn)
    });

    // ngSpice_Init with VSRC and sync callbacks.
    engine
        .init(Some(vsrc_cb), None, None, Some(sync_cb))
        .map_err(|e| format!("ngSpice_Init failed: {e}"))?;

    // Read the circuit deck from file.
    let deck = fs::read_to_string(cir_path_str)
        .map_err(|e| format!("cannot read circuit file {cir_path_str}: {e}"))?;
    let lines: Vec<&str> = deck.lines().collect();
    engine
        .load_circuit(&lines)
        .map_err(|e| format!("load_circuit failed: {e}"))?;

    // Run transient analysis.
    let tran_cmd = format!("tran {tstep_us}u {total_time_ms}m uic");
    engine
        .cmd(&tran_cmd)
        .map_err(|e| format!("tran command failed: {e}"))?;

    // Extract results from the controller.
    let c = controller.lock().unwrap();
    if c.history_time.is_empty() {
        return Err("Simulation did not produce any data points.".to_string());
    }

    // Time is in seconds from ngspice; convert to ms.
    let time_ms: Vec<f64> = c.history_time.iter().map(|&t| t * 1000.0).collect();
    let vout = c.history_vout.clone();
    let vgate = c.history_vgate.clone();
    drop(c);

    // Steady-state metrics (last 60% of timeline).
    let steady_start = (total_time_ms * 0.4) as usize;
    let steady_vout: Vec<f64> = time_ms
        .iter()
        .zip(vout.iter())
        .filter(|(t, _)| **t >= steady_start as f64)
        .map(|(_, &v)| v)
        .collect();

    if steady_vout.is_empty() {
        return Err("No steady-state data collected.".to_string());
    }

    let avg_vout = steady_vout.iter().sum::<f64>() / steady_vout.len() as f64;
    let max_v = steady_vout
        .iter()
        .copied()
        .fold(f64::NEG_INFINITY, f64::max);
    let min_v = steady_vout
        .iter()
        .copied()
        .fold(f64::INFINITY, f64::min);
    let ripple_p2p = max_v - min_v;

    let controller = Arc::try_unwrap(controller).map_err(|_| "controller still referenced".to_string())?;
    let switch_count = controller.into_inner().unwrap().switch_count;

    Ok(ClosedLoopResult {
        time_ms,
        vout,
        vgate,
        avg_vout,
        ripple_p2p,
        switch_count,
    })
}

// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_controller_thresholds_match_firmware() {
        // target=3.2436, hyst=0.0282, divider=0.5, vref=3.30
        // v_fb_low = (3.2436 - 0.0282) * 0.5 = 1.6077
        // v_fb_high = (3.2436 + 0.0282) * 0.5 = 1.6359
        // adc_low = 1.6077 / 3.30 * 4095 = 1995.0 -> 1995
        // adc_high = 1.6359 / 3.30 * 4095 = 2030.0 -> 2030
        let c = MockESP32BuckController::new(3.2436, 0.0282, 0.5, 3.30);
        assert_eq!(c.adc_low, 1995);
        assert_eq!(c.adc_high, 2030);
    }

    #[test]
    fn test_controller_decide_below_low_drives_high() {
        let mut c = MockESP32BuckController::new(3.2436, 0.0282, 0.5, 3.30);
        c.latest_fb = 1.5; // below adc_low equivalent
        let v = c.on_vsrc();
        assert_eq!(v, 3.3);
        assert!(c.gpio_state);
    }

    #[test]
    fn test_controller_decide_above_high_drives_low() {
        let mut c = MockESP32BuckController::new(3.2436, 0.0282, 0.5, 3.30);
        c.latest_fb = 2.0; // above adc_high equivalent
        let v = c.on_vsrc();
        assert_eq!(v, 0.0);
        assert!(!c.gpio_state);
    }

    #[test]
    fn test_controller_hysteresis_holds() {
        let mut c = MockESP32BuckController::new(3.2436, 0.0282, 0.5, 3.30);
        // Start low -> drive high
        c.latest_fb = 1.5;
        let _ = c.on_vsrc();
        assert!(c.gpio_state);
        // Stay high (in band)
        c.latest_fb = 1.62;
        let _ = c.on_vsrc();
        assert!(c.gpio_state);
        // Go high -> drive low
        c.latest_fb = 2.0;
        let _ = c.on_vsrc();
        assert!(!c.gpio_state);
        // Stay low (in band)
        c.latest_fb = 1.62;
        let _ = c.on_vsrc();
        assert!(!c.gpio_state);
    }

    #[test]
    fn test_controller_switch_count_increments_on_edge() {
        let mut c = MockESP32BuckController::new(3.2436, 0.0282, 0.5, 3.30);
        assert_eq!(c.switch_count, 0);
        c.latest_fb = 1.5;
        c.on_vsrc(); // LOW -> HIGH, switch 1
        assert_eq!(c.switch_count, 1);
        c.latest_fb = 1.5;
        c.on_vsrc(); // HIGH -> HIGH, no switch
        assert_eq!(c.switch_count, 1);
        c.latest_fb = 2.0;
        c.on_vsrc(); // HIGH -> LOW, switch 2
        assert_eq!(c.switch_count, 2);
    }

    #[test]
    fn test_adc_quantization_clip() {
        let mut c = MockESP32BuckController::new(3.2436, 0.0282, 0.5, 3.30);
        // v_feedback = 3.3V -> 4095 counts, clamped
        c.latest_fb = 3.3;
        // adc_high = 2030, 4095 > 2030 -> drive LOW
        assert_eq!(c.on_vsrc(), 0.0);
        // v_feedback = 0V -> 0 counts, below adc_low -> drive HIGH
        c.latest_fb = 0.0;
        assert_eq!(c.on_vsrc(), 3.3);
    }

    #[test]
    fn test_closed_loop_result_no_dll() {
        // NgSpiceFfi::new() will fail without the DLL - that's expected.
        let result = run_closed_loop_simulation(5.0, 0.5);
        assert!(result.is_err());
    }
}
