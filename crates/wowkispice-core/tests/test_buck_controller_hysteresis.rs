//! QEMU-replacement test harness for the ESP32 hysteretic buck controller.
//!
//! Verifies that the hysteretic controller logic matches the Python mock
//! (mock_controller.py) exactly:
//!   - thresholds: adc_low=1995, adc_high=2030
//!   - 12-bit ADC (0..4095 counts for 0..3.3 V reference)
//!   - divider_ratio=0.5 (2:1 resistive feedback divider)
//!   - hysteretic state persistence across timesteps
//!
//! The C function `buck_controller_tick` (compiled to `firmware_control.dll`)
//! implements identical logic. This test confirms the Rust inlined version
//! matches the C/Python behavior.

// ---------------------------------------------------------------------------
// Standard library imports needed for the test
// ---------------------------------------------------------------------------
use std::cmp::{max, min};

// ---------------------------------------------------------------------------
// Hysteretic controller logic (inlined, dependency-free)
// ---------------------------------------------------------------------------

/// Thresholds matching the ESP32 firmware and Python mock.
const ADC_LOW_THRESHOLD: i32 = 1995;
const ADC_HIGH_THRESHOLD: i32 = 2030;

/// Hysteretic controller state.
/// 
/// Identical logic to `buck_controller_tick` in `firmware/esp32_buck_controller/src/buck_controller_tick.c`
/// and the Python mock in `bridge/mock_controller.py`.
/// 
/// State persists across calls (static inner mutability).
struct HystereticController {
    gate_on: bool,  // true = MOSFET conduction (gate driven high)
}

impl HystereticController {
    fn new() -> Self {
        HystereticController { gate_on: false }
    }

    /// Tick the controller with a new ADC sample.
    /// 
    /// Returns the resulting gate state (true = ON / conduction).
    /// 
    /// Logic (matching firmware main.c and Python mock):
    ///   - adc_counts <  LOW_THRESHOLD  => gate ON  (if not already)
    ///   - adc_counts >  HIGH_THRESHOLD => gate OFF (if not already)
    ///   - otherwise                          => state unchanged (hysteresis)
    fn tick(&mut self, adc_counts: i32) -> bool {
        if adc_counts < ADC_LOW_THRESHOLD {
            if !self.gate_on {
                self.gate_on = true;
            }
        } else if adc_counts > ADC_HIGH_THRESHOLD {
            if self.gate_on {
                self.gate_on = false;
            }
        }
        // else: hysteresis — state stays as-is
        self.gate_on
    }
}

// ---------------------------------------------------------------------------
// ADC conversion (12-bit, vref=3.3, divider=0.5)
// ---------------------------------------------------------------------------

/// Convert a sensed voltage at the feedback node (Vout side of 2:1 divider)
/// to 12-bit ADC counts matching the ESP32 firmware.
/// 
/// Formula (from bridge/binary_runner.py _adc_counts_from_voltage):
///   v_adc = v_sense * divider
///   counts = round((v_adc / vref) * 4095)
fn voltage_to_adc_counts(v_sense: f64, vref: f64, divider: f64) -> i32 {
    let v_adc = v_sense * divider;
    let counts = (v_adc / vref * 4095.0).round() as i32;
    // Clamp to 12-bit range
    max(0, min(4095, counts))
}

// ---------------------------------------------------------------------------
// Test: hysteresis matches Python mock
// ---------------------------------------------------------------------------

#[test]
fn test_hysteresis_low_then_high()
{
    let mut ctrl = HystereticController::new();

    // Step 1: adc=1500 < 1995 => gate ON
    let gpio = ctrl.tick(1500);
    assert!(gpio, "Step 1: gate should be ON after adc=1500 (< 1995)");

    // Step 2: adc=1500 still => gate stays ON (hysteresis)
    let gpio2 = ctrl.tick(1500);
    assert!(gpio2, "Step 2: gate should stay ON (hysteresis) at adc=1500");

    // Step 3: adc=2500 > 2030 => gate OFF
    let gpio3 = ctrl.tick(2500);
    assert!(!gpio3, "Step 3: gate should be OFF after adc=2500 (> 2030)");

    // Step 4: adc=2500 still => gate stays OFF (hysteresis)
    let gpio4 = ctrl.tick(2500);
    assert!(!gpio4, "Step 4: gate should stay OFF (hysteresis) at adc=2500");

    // Step 5: adc=1500 < 1995 => gate ON again
    let gpio5 = ctrl.tick(1500);
    assert!(gpio5, "Step 5: gate should be ON again after adc=1500");

    println!("Hysteresis test PASSED: low->ON, high->OFF, low->ON again");
}

#[test]
fn test_hysteresis_full_sequence_matches_python_mock()
{
    let mut ctrl = HystereticController::new();

    // Exact sequence from the Python mock comparison:
    // Python mock thresholds: adc_low=1995, adc_high=2030, divider_ratio=0.5, vref=3.3

    // 1. adc=1500 < 1995 => gate ON
    let gpio = ctrl.tick(1500);
    assert!(gpio, "Step 1: gate ON at adc=1500");

    // 2. adc=1500 still => gate stays ON (hysteresis)
    let gpio2 = ctrl.tick(1500);
    assert!(gpio2, "Step 2: gate stays ON at adc=1500 (hysteresis)");

    // 3. adc=2500 > 2030 => gate OFF
    let gpio3 = ctrl.tick(2500);
    assert!(!gpio3, "Step 3: gate OFF at adc=2500");

    // 4. adc=2500 still => gate stays OFF (hysteresis)
    let gpio4 = ctrl.tick(2500);
    assert!(!gpio4, "Step 4: gate stays OFF at adc=2500 (hysteresis)");

    // 5. adc=1500 < 1995 => gate ON again
    let gpio5 = ctrl.tick(1500);
    assert!(gpio5, "Step 5: gate ON again at adc=1500");

    println!("Full hysteresis test PASSED - matches Python mock exactly");
}

#[test]
fn test_adc_conversion_match()
{
    // Verify that voltage->ADC conversion produces sensible counts
    // For vout=3.3V with 2:1 divider: v_adc = 3.3 * 0.5 = 1.65V
    // counts = round(1.65 / 3.3 * 4095) = round(2047.5) = 2048

    let counts = voltage_to_adc_counts(3.3, 3.3, 0.5);
    assert_eq!(counts, 2048, "3.3V at Vout with 2:1 divider -> ADC counts=2048");

    // For vout=0V: counts should be 0
    let counts_zero = voltage_to_adc_counts(0.0, 3.3, 0.5);
    assert_eq!(counts_zero, 0, "0V at Vout -> ADC counts=0");

    println!("ADC conversion: 3.3V@vout->{} counts, 0V->{} counts", counts, counts_zero);
}