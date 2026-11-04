/*
 * wowkispice-core - Rust port of the WOWKISPICE Python core.
 *
 * Architecture: policy and math live here with no dependencies, mirroring a
 * Python side that depends only on the stdlib.  The C++/Qt5 GUI links the
 * C ABI (crate-type includes cdylib); tests and the parity harness link the
 * Rust API directly.
 *
 * Module layout mirrors bridge/ one-to-one so a reader can always find the
 * Python original from the Rust file name:
 *
 *   control_law  <- bridge/control_law.py
 *   netlist      <- bridge/ngspice_wrapper.py (the pure-logic portion)
 *
 * Parity contract for each module is documented in its own header comment;
 * crates/parity holds the harness that diffs each implementation against
 * Python over a shared battery.
 */

pub mod control_law;
pub mod esp32_regs;
pub mod firmware;
pub mod gpio_model;
pub mod load_stepper;
pub mod measurements;
pub mod netlist;
pub mod pycompat;
pub mod report_generator;
pub mod toolchain_resolver;
