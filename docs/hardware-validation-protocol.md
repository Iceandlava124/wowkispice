# Hardware validation protocol — ESP32 ADC vs simulated counts

This is a step-by-step protocol for a person holding one ESP32 board,
one resistor divider, and this checkout. The goal is to produce a table of
*measured* ADC counts and compare them with the *simulated* counts that the
project's model emits, and to decide a tolerance that the model must meet
before the co-sim loop is considered validated.

**Do not fill in the results of your run here.** Record them in a file you
create in `docs/validation-runs/` and paste that file into the PR.

---

## 1. Parts list

| # | Part | Value | Notes |
|---|---|---|---|
| 1 | ESP32 dev board (WROOM-32) | — | The only board needed; vendor neutral |
| 2 | 2 × resistors | 10 kΩ, 2% or better | For the divider below |
| 3 | DC power supply | 3.3 V, >100 mA | Board VDD; keep the ground plane clean |
| 4 | Breadboard + hookup wire | — | |
| 5 | 10 kΩ NTC or thermistor (optional) | — | For a non-flat transfer curve |
| 6 | Multimeter or calibrated DMM | — | To measure the divider node **before** flashing |
| 7 | Jumper to GPIO 36 (ADC1_CH0) | — | The node the firmware reads |

---

## 2. Wiring

```
3.3 V ──► R1 (top of divider) ──► node X (GPIO36 / ADC1_CH0)
                              │
                              R2 (to GND)
                              │
                              GND ──► board GND
```

* `R1 = R2 = 10 kΩ` gives `V_feedback = V_in / 2` — the same divider the
  firmware assumes.
* Measure the divider ratio on the bench with the DMM *before* you flash.
  Apply the measured ratio to the protocol (a 10 kΩ/10 kΩ divider gives
  exactly `Vx = Vin / 2`).
* Keep the wire from the junction to GPIO36 short and away from any
  switching node; a few hundred millivolts of coupling is enough to move
  the counts by a full LSB.

On the ESP32, `ADC1_CHANNEL_0` is on GPIO36 (sAR ADC1, nomux; the RTC SAR
ADC is the one the model targets).

---

## 3. Firmware to flash

1. Build the firmware the normal way:

   ```bash
   cd firmware/esp32_buck_controller
   pio run --environment esp32dev
   pio run --environment esp32dev --target=upload
   ```

2. Flash with `esptool.py` (or PlatformIO's upload) exactly as you would
   for a real board:

   ```bash
   esptool.py --port /dev/ttyUSB0 write_flash 0x1000 bootloader.bin
   esptool.py --port /dev/ttyUSB0 write_flash 0x8000 partitions.bin
   esptool.py --port /dev/ttyUSB0 write_flash 0x10000 firmware.bin
   ```

   (Adjust offsets to the partition table; the project's
   `sdkconfig.defaults` says 4 MB flash, 40 MHz, DIO.)

3. Open a serial monitor at 115200 baud and watch the boot markers:

   ```
   BUCK_CTRL: Starting ESP32 Buck Converter Closed-Loop Controller...
   BUCK_CTRL: Entering high-speed hysteretic control loop...
   ```

   The firmware reports each threshold as raw counts and, when calibration
   is present, as mV. Capture that log — it is part of your evidence.

---

## 4. Measurement procedure

For each calibration point:

1. Power the board and set the input voltage of the divider to the target
   (`Vin = 2 × Vx` measured at the junction).
2. Wait for the control loop to settle (the firmware loops at 16 ADC
   readings per decision; the loop prints `Loop: N | Raw ADC: S | Gate:
   ON|OFF` every 10000 loops). Let it print at least five `Loop:` lines at
   a stable `Raw ADC:` value.
3. Read `Raw ADC` from the serial log. That is the **measured count** for
   this point.
4. Record the input voltage `Vx` (measured at the junction with the DMM,
   with the board powered and the resistors in place), the measured count,
   and the firmware's claimed threshold counts.

Do this for at least **7 points** spanning the hysteresis band, e.g.:

| Point | `Vin` | `Vx` (divider) | purpose |
|---|---|---|---|
| 1 | 0.5 V | 0.25 V | below `ADC_LOW_THRESHOLD` |
| 2 | 1.0 V | 0.5 V | below band |
| 3 | 1.3 V | 0.65 V | just below `ADC_LOW_THRESHOLD` (1995) |
| 4 | 1.65 V | 0.825 V | at `ADC_LOW_THRESHOLD` |
| 5 | 1.70 V | 0.85 V | just above `ADC_LOW_THRESHOLD` |
| 6 | 3.30 V | 1.65 V | at `ADC_HIGH_THRESHOLD` (2030) |
| 7 | 3.30 V | 1.65 V | just above `ADC_HIGH_THRESHOLD` (repeat for stability) |

If the NTC is in the divider, add its two temperature points and record the
thermistor's own temperature.

---

## 5. What the model emits

The simulated counts are produced by `bridge/control_law.py::_to_counts`
and by the `esp32_sens` model, and the two must agree with each other
before you compare with the board:

* `counts_simulated = round(Vx / Vref * (2^12 - 1))` with `Vref = 3.3 V`
  and `Vx` the **junction** voltage at the moment of the ADC conversion.
* The firmware's decision uses the raw oversampled average (`sum /
  samples_ok`) over 16 reads.

Run the same input points through the project's own model and record the
`counts_simulated` values in the same table.

---

## 6. Computing the error

For each point `i`:

```
error_i = measured_counts_i - simulated_counts_i
```

Report:

* **mean signed error** (bias, in counts)
* **RMSE** (in counts)
* **max |error|** (in counts)
* **counts per LSB** — `3.3/4095 = 0.8057 mV` per LSB, so you can also
  express the error in mV if you prefer.

---

## 7. What counts as agreement

State a tolerance before you look at the result. Recommended starting
tolerance: **±2 counts** (about ±1.6 mV) over the full 7-point table.
The intent is not to make the model perfect; it is to give a pass/fail
number that is meaningful and repeatable.

* **Agree** — mean signed error within ±2 counts and max |error| ≤ ±3
  counts, on at least 5 of the 7 points.
* **Disagree** — otherwise. Then the model is *not* the firmware-visible
  ADC, and the co-sim loop must be gated on the two differing by more
  than the tolerance.
* **Inconclusive** — you could not make the firmware emit a stable count
  (e.g. it panicked on the interrupt watchdog). In that case the relevant
  deliverable is a defect report against the unmodelled ADC, not a
  validation number.

---

## 8. Deliverables

* `docs/validation-runs/<date>-adc-table.csv` — the raw table with the
  `Vin`, `Vx`, `measured_counts`, `simulated_counts`, `error` columns.
* `docs/validation-runs/<date>-summary.txt` — bias, RMSE, max error,
  pass/fail verdict, and what you did NOT validate (noise floor, eFuse
  calibration, input impedance) — or **UNKNOWN** if you did not measure
  them.
* The serial log (`docs/validation-runs/<date>-boot.log`) from the
  firmware's boot sequence.

Do not write the pass/fail verdict into `docs/hardware-validation-protocol.md`
itself; that document is the protocol, not the result.
