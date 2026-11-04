/*
 * test_serial_console.rs - Rust gate for bridge/serial_console.py.
 *
 * Transcribes the pure-string parsing and buffer behavior of SerialConsole:
 * line splitting (CRLF/LF/blank-line handling), bounded retention with
 * dropped-line counting, UTF-8 lossy decoding, case-insensitive grep, and
 * summary state.
 */

use wowkispice_core::serial_console::*;

// ----------------------------------------------------------------------
// parse_uart
// ----------------------------------------------------------------------

#[test]
fn test_parse_uart_empty() {
    assert!(parse_uart("").is_empty());
}

#[test]
fn test_parse_uart_single_line() {
    assert_eq!(parse_uart("hello"), vec!["hello"]);
}

#[test]
fn test_parse_uart_lf_separated() {
    assert_eq!(
        parse_uart("a\nb\nc"),
        vec!["a", "b", "c"]
    );
}

#[test]
fn test_parse_uart_crlf_separated() {
    assert_eq!(
        parse_uart("a\r\nb\r\nc\r\n"),
        vec!["a", "b", "c"]
    );
}

#[test]
fn test_parse_uart_mixed_line_endings() {
    assert_eq!(
        parse_uart("a\r\nb\nc\r\nd"),
        vec!["a", "b", "c", "d"]
    );
}

#[test]
fn test_parse_uart_drops_blank_lines() {
    assert_eq!(
        parse_uart("a\n\nb\n\n"),
        vec!["a", "b"]
    );
}

#[test]
fn test_parse_uart_trims_whitespace() {
    assert_eq!(
        parse_uart("  a  \n\tb\t\n"),
        vec!["a", "b"]
    );
}

#[test]
fn test_parse_uart_unterminated_last_line() {
    assert_eq!(
        parse_uart("a\nb"),
        vec!["a", "b"]
    );
}

// ----------------------------------------------------------------------
// SerialConsole::new / count / total_seen
// ----------------------------------------------------------------------

#[test]
fn test_console_default_max_lines() {
    let c = SerialConsole::default();
    assert_eq!(c.max_lines, 5000);
}

#[test]
fn test_console_new_clamps_to_one() {
    let c = SerialConsole::new(0);
    assert_eq!(c.max_lines, 1);
}

#[test]
fn test_console_count_and_total_seen() {
    let mut c = SerialConsole::new(10);
    c.write("line1\nline2\nline3\n");
    assert_eq!(c.count(), 3);
    assert_eq!(c.total_seen(), 3);
}

#[test]
fn test_console_bounded_retention_drops_oldest() {
    let mut c = SerialConsole::new(3);
    c.write("a\nb\nc\nd\ne\n");
    // Only the last 3 lines remain
    assert_eq!(c.count(), 3);
    assert_eq!(c.lines, vec!["c", "d", "e"]);
    assert_eq!(c.total_seen(), 5);
    assert_eq!(c.dropped, 2);
}

#[test]
fn test_console_text_joins_with_newline() {
    let mut c = SerialConsole::new(10);
    c.write("one\ntwo\nthree\n");
    assert_eq!(c.text(), "one\ntwo\nthree");
}

#[test]
fn test_console_clear_resets_state() {
    let mut c = SerialConsole::new(10);
    c.write("line1\nline2\n");
    c.clear();
    assert_eq!(c.count(), 0);
    assert_eq!(c.total_seen(), 0);
    assert_eq!(c.text(), "");
}

// ----------------------------------------------------------------------
// grep (case-insensitive substring)
// ----------------------------------------------------------------------

#[test]
fn test_console_grep_case_insensitive() {
    let mut c = SerialConsole::new(10);
    c.write("Error: something failed\nWarning: be careful\ninfo: all good\n");
    let hits = c.grep("error");
    assert_eq!(hits, vec!["Error: something failed"]);
}

#[test]
fn test_console_grep_no_match() {
    let mut c = SerialConsole::new(10);
    c.write("hello world\n");
    assert!(c.grep("xyz").is_empty());
}

// ----------------------------------------------------------------------
// summary
// ----------------------------------------------------------------------

#[test]
fn test_console_summary() {
    let mut c = SerialConsole::new(100);
    c.write("a\nb\nc\n");
    let s = c.summary();
    assert_eq!(s.lines, 3);
    assert_eq!(s.dropped, 0);
    assert!(!s.truncated);
    assert_eq!(s.max_lines, 100);
}

#[test]
fn test_console_summary_truncated() {
    let mut c = SerialConsole::new(2);
    c.write("a\nb\nc\nd\n");
    let s = c.summary();
    assert_eq!(s.lines, 2);
    assert_eq!(s.dropped, 2);
    assert!(s.truncated);
    assert_eq!(s.max_lines, 2);
}
