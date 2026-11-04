/*
 * parity - harness binaries that diff the Rust core against the Python
 * originals in the bridge package over a shared battery.
 *
 * One binary per module (parity_control_law, parity_netlist, ...), mirroring
 * native/tools/parity_control_law.c and .py.
 *
 * PLACEHOLDER main; parity_control_law is being written.
 */

fn main() {
    eprintln!("parity: no harness selected (see src/bin/)");
    std::process::exit(2);
}
