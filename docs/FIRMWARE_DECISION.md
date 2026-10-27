# FIRMWARE DECISION — `firmware/esp32_buck_controller/src/main.c`

**Job:** J2 · **Branch:** `baseline-fix` · **Date:** 2026-10-27
**Status:** RECOMMENDATION (a) — restore HEAD's `main.c`. OWNER ACTION required.

---

## 1. The real diff (line-ending rewrite removed)

Plain `git --no-pager diff --stat`:

```
 firmware/esp32_buck_controller/src/main.c | 360 ++++++++++++++++--------------
 1 file changed, 187 insertions(+), 173 deletions(-)
```

`git --no-pager diff --ignore-space-at-eol --stat`:

```
 firmware/esp32_buck_controller/src/main.c | 22 ++++++++++++++++++----
 1 file changed, 18 insertions(+), 4 deletions(-)
```

**Line-ending churn accounts for ~169 of the 173 deleted lines.** The file was
converted wholesale (it is CRLF in the working tree); only **18 insertions and
4 deletions** are real. Rule 2 flagged: this diff is dominated by line-ending
changes.

## 2. The real changes (`git --no-pager diff --ignore-space-at-eol`)

```
@@ -40,6 +40,12 @@
 #define ADC_LOW_THRESHOLD   1995
 #define ADC_HIGH_THRESHOLD  2030

+// Telemetry and adaptive mode support (enhanced for load-step testing)
+#define TELEMETRY_ENABLED 1
+#define ADAPTIVE_MODE_ENABLED 1
+static uint32_t loop_iteration = 0;
+static int adaptive_band_shift = 0;
@@ -132,6 +138,7 @@
     while (1) {
+        loop_iteration++;
@@ -151,13 +158,17 @@
+        // Adaptive mode: adjust hysteresis band based on load conditions
+        int low_thresh = ADC_LOW_THRESHOLD + adaptive_band_shift;
+        int high_thresh = ADC_HIGH_THRESHOLD + adaptive_band_shift;
         // Hysteretic switching logic
-        if (raw_adc < ADC_LOW_THRESHOLD) {
+        if (raw_adc < low_thresh) {
-        } else if (raw_adc > ADC_HIGH_THRESHOLD) {
+        } else if (raw_adc > high_thresh) {
@@ -166,8 +177,11 @@
-            ESP_LOGI(TAG, "Loop: %lu | Raw ADC: %d | Gate: %s",
-                     (unsigned long)loop_count, raw_adc, current_gate_state ? "ON" : "OFF");
+            ESP_LOGI(TAG, "TELEMETRY: loop=%lu adc=%d gate=%s thresh=[%d,%d] mode=adaptive",
+                     (unsigned long)loop_count, raw_adc, current_gate_state ? "ON" : "OFF",
+                     low_thresh, high_thresh);
+        } else if (loop_count % 1000 == 0 && TELEMETRY_ENABLED) {
+            ESP_LOGD(TAG, "LOOP:%lu ADC:%d GATE:%d", (unsigned long)loop_count, raw_adc, current_gate_state);
```

### Thresholds unchanged

`Select-String -Pattern 'ADC_LOW_THRESHOLD|ADC_HIGH_THRESHOLD'`:

```
40: #define ADC_LOW_THRESHOLD   1995
41: #define ADC_HIGH_THRESHOLD  2030
125:         int thr = t ? ADC_HIGH_THRESHOLD : ADC_LOW_THRESHOLD;
162:         int low_thresh = ADC_LOW_THRESHOLD + adaptive_band_shift;
163:         int high_thresh = ADC_HIGH_THRESHOLD + adaptive_band_shift;
```

**1995 / 2030 are untouched.** The gate decision boundary is unchanged.

### `adaptive_band_shift` is dead

Every occurrence:

```
47: static int adaptive_band_shift = 0;
162:         int low_thresh = ADC_LOW_THRESHOLD + adaptive_band_shift;
163:         int high_thresh = ADC_HIGH_THRESHOLD + adaptive_band_shift;
```

Assignment search (`adaptive_band_shift\s*=[^=]`) returns only line 47, the
initializer. **Nothing ever writes it**, so `low_thresh == ADC_LOW_THRESHOLD`
and `high_thresh == ADC_HIGH_THRESHOLD` at run time. `ADAPTIVE_MODE_ENABLED`
(line 45) is defined and **never referenced anywhere**. `loop_iteration`
(line 46) is incremented at 141 and never read. The "adaptive mode" is a
no-op that only adds two additions per loop.

## 3. What breaks if the format changes — file:line

`Select-String` across `bridge`, `tools`, `tests`, `ui`, `docs`:

### Breaks (real parsers of the firmware's UART text)

| file:line | pattern | result with new format |
|---|---|---|
| `tools/demo_closed_loop.py:218` | `r"Raw ADC: \d+ \| Gate: (ON\|OFF)"` | **no match** → prints `FAIL: no control-loop sample printed.` and returns 1 |
| `tools/demo_closed_loop.py:247` | `r"Raw ADC: %d \| Gate: %s" % (value, expected_gate)` | **no match** → `FAIL: firmware never printed '...'`, returns 1 |
| `tools/demo_closed_loop.py:257` | `r"BUCK_CTRL: Loop"` | 0 matches → `control-loop samples observed : 0` |
| `docs/hardware-validation-protocol.md:93-94` | instructs reading `Loop: N \| Raw ADC: S \| Gate: ON\|OFF` | procedure no longer matches what the firmware prints |
| `docs/systems-map.md:188` | documents `BUCK_CTRL: Loop: . \| Raw ADC: . \| Gate: .` | claim no longer true |

`tools/demo_closed_loop.py` is the script that demonstrates the whole point of
this project (inject ADC → firmware reacts → gate flips). With the edited
`main.c` it **fails at step [4/6]** and again at step [6/6].

### Does not break (uses the format only as literal test fixture text)

| file:line | note |
|---|---|
| `tests/test_editor_workflow.py:401` | `text = "BUCK_CTRL: Loop: 10000 \| Raw ADC: 2010 \| Gate: ON\r\nReady\r\n"` — hand-written string fed to the UI console; it does not read firmware output, so it keeps passing while testing a format the firmware no longer emits |
| `tests/test_editor_workflow.py:468` | same, second fixture |

### Not a consumer

Matches on the bare word `TELEMETRY` in `bridge/control_law.py:198,233`,
`bridge/mock_controller.py:65`, `bridge/report_generator.py:56`,
`bridge/studio_engine.py:34` are that code's **own** telemetry fields — they
never parse the UART line. Same for `docs/requirements-matrix.md:11,20` and
`docs/STATE.md:15`, which merely assert the enhancement exists.

## 4. Timestamps — the built binary predates the edit

`Get-Item`:

| path | LastWriteTime | size |
|---|---|---|
| `firmware/esp32_buck_controller/src/main.c` | **2026-10-26 07:48:03** | 7551 |
| `firmware/esp32_buck_controller/.pio/build/esp32dev/firmware.elf` | **2026-10-24 21:30:44** | 3133368 |
| `firmware/esp32_buck_controller/.pio/build/esp32dev/qemu_flash.bin` | 2026-10-24 21:39:57 | 4194304 |
| `firmware/esp32_buck_controller/.pio/build/esp32dev/firmware.bin` | 2026-10-24 21:30:45 | 159360 |

**The source is ~1 day 10 hours newer than the ELF.** Every artifact under
`.pio/` dates from 2026-10-24. The telemetry edit has **never been compiled**,
so:

* the emulator and `tools/demo_closed_loop.py` currently run the **HEAD**
  firmware, which still prints `Loop: ... | Raw ADC: ...`;
* any claim that the repo's built firmware contains "adaptive telemetry" is
  false;
* restoring `main.c` therefore changes **nothing** about what the binary does.

## 5. Recommendation

**(a) Keep HEAD's `main.c`.**

Reasons, all measured above:

1. Nothing in this queue needs telemetry or an adaptive band. The goal
   (GOAL paragraph) is `ngspice → ADC → emulator → firmware → GPIO18 gate`,
   and the gate law is defined by 1995/2030, which are unchanged either way.
2. `adaptive_band_shift` is provably dead (no writer), so option (b)'s
   "remove the dead adaptive code" would leave a diff of telemetry-only value.
3. The edited format **breaks `tools/demo_closed_loop.py`** at three separate
   match sites, and would break it in J5/J8 whenever the emulator track runs.
4. The whole-file line-ending conversion (CRLF) violates the repo's
   line-ending discipline and makes the diff unreadable — 169 of 173 deletions
   are whitespace.
5. The binary is already the HEAD build, so restoring costs **zero** rebuild.
   Option (b) would require `pio run`, which rule 7 forbids without approval.
6. `tests/test_editor_workflow.py:401,468` hard-code the old format as their
   fixture; keeping HEAD keeps them honest.

### OWNER ACTION

Run exactly this, from the repo root:

```
git --no-pager restore firmware/esp32_buck_controller/src/main.c
```

Then confirm with:

```
git --no-pager status --short firmware/esp32_buck_controller/src/main.c
```

Expected: **no output** (the file no longer differs from HEAD).

I did **not** run this: rule 3 makes any revert of a file in the owner's tree
an OWNER ACTION.

### If the owner instead prefers (b)

Then, and only then, with owner approval for the rebuild:

1. convert `main.c` back to the branch's line endings;
2. delete `adaptive_band_shift`, `ADAPTIVE_MODE_ENABLED`, `loop_iteration`
   and their uses;
3. restore the original `ESP_LOGI` line — `Loop: %lu | Raw ADC: %d | Gate: %s`;
4. add tests asserting the telemetry format against `tools/demo_closed_loop.py`'s
   three regexes;
5. run `pio run` (**owner approval required**, rule 7) and re-check the
   timestamps in §4.

Until then `docs/requirements-matrix.md` REQ-007 ("Adaptive firmware
telemetry — IMPLEMENTED") is **not** supported: it is unbuilt, and its
adaptive branch never executes.
