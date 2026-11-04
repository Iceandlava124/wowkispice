/*
 * serial_console.rs - port of bridge/serial_console.py.
 *
 * UART / print() output capture from firmware, for the editor panel.
 *
 * What this does NOT do: fabricate firmware output. An empty console says
 * the console is empty.
 *
 * Parsing is deliberately dumb - split lines, strip the trailing CR that every
 * UART driver emits - because the interesting part is the firmware's own text,
 * and a clever parser would only mangle it.
 *
 * Pure computation over strings: no serial port, no Qt, no filesystem.
 * Dependency-free (std only). Mirrors bridge/serial_console.py one-to-one.
 */

/// Split captured UART bytes into clean lines.
///
/// Handles both CRLF and bare LF, drops blank lines, and tolerates a final
/// line with no terminator (which is what a capture cut mid-print looks like).
pub fn parse_uart(text: &str) -> Vec<String> {
    if text.is_empty() {
        return Vec::new();
    }
    let normalized = text.replace("\r\n", "\n").replace("\r", "\n");
    normalized
        .split('\n')
        .map(|line| line.trim().to_string())
        .filter(|line| !line.is_empty())
        .collect()
}

/// Bounded, append-only capture of firmware print output.
///
/// `max_lines` keeps the widget from growing without limit during a long run;
/// the oldest lines are dropped first, and the count of dropped lines is kept
/// so the UI can say "showing last N of M" rather than silently lying about
/// the capture.
#[derive(Debug, Clone)]
pub struct SerialConsole {
    pub max_lines: usize,
    pub lines: Vec<String>,
    pub dropped: usize,
}

impl Default for SerialConsole {
    fn default() -> Self {
        Self::new(5000)
    }
}

impl SerialConsole {
    /// Create a console that retains at most `max_lines` lines.
    ///
    /// Mirrors `__init__(self, max_lines: int = 5000)`; a value below 1 is
    /// forced to 1 so the buffer can never vanish entirely.
    pub fn new(max_lines: usize) -> Self {
        Self {
            max_lines: max_lines.max(1),
            lines: Vec::new(),
            dropped: 0,
        }
    }

    /// Number of lines currently held.
    pub fn count(&self) -> usize {
        self.lines.len()
    }

    /// Lines written over the lifetime of this console, including dropped ones.
    pub fn total_seen(&self) -> usize {
        self.dropped + self.lines.len()
    }

    /// Append UART data.
    ///
    /// Accepts anything `AsRef<[u8]>` (`&str`, `&[u8]`, `String`, `Vec<u8>`...),
    /// because the source may be a live byte stream (Renode) or a decoded text
    /// file, and callers should not have to care. Bytes are decoded as UTF-8
    /// with replacement, exactly like Python's `decode("utf-8", errors="replace")`.
    pub fn write<T: AsRef<[u8]>>(&mut self, data: T) {
        let text = String::from_utf8_lossy(data.as_ref());
        for line in parse_uart(&text) {
            self.lines.push(line);
            if self.lines.len() > self.max_lines {
                self.lines.remove(0);
                self.dropped += 1;
            }
        }
    }

    /// All held lines joined with `\n`.
    pub fn text(&self) -> String {
        self.lines.join("\n")
    }

    /// Drop every captured line and reset the dropped count.
    pub fn clear(&mut self) {
        self.lines.clear();
        self.dropped = 0;
    }

    /// Lines containing `needle` as a substring, case-insensitively.
    pub fn grep(&self, needle: &str) -> Vec<String> {
        let low = needle.to_lowercase();
        self.lines
            .iter()
            .filter(|line| line.to_lowercase().contains(low.as_str()))
            .cloned()
            .collect()
    }

    /// Counts an inspector can show without re-scanning the buffer.
    pub fn summary(&self) -> ConsoleSummary {
        ConsoleSummary {
            lines: self.count(),
            dropped: self.dropped,
            truncated: self.dropped > 0,
            max_lines: self.max_lines,
        }
    }
}

/// Snapshot of [`SerialConsole`] state; mirrors the `summary()` dict.
#[derive(Debug, Clone, Default)]
pub struct ConsoleSummary {
    pub lines: usize,
    pub dropped: usize,
    pub truncated: bool,
    pub max_lines: usize,
}
