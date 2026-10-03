"""
serial_console.py - UART / print() output from firmware, for the editor panel.

The vision doc asks for a serial console next to the waveform viewer. What can
be captured honestly today is whatever the firmware writes over a UART that the
host can see: a real Renode run's UART log, a captured text file, or lines fed
in by the user.

What this does NOT do: fabricate firmware output. An empty console says the
console is empty.

Parsing is deliberately dumb - split lines, strip the trailing CR that every
UART driver emits - because the interesting part is the firmware's own text,
and a clever parser would only mangle it.
"""

from typing import Dict, List, Optional


def parse_uart(text: str) -> List[str]:
    """
    Split captured UART bytes into clean lines.

    Handles both CRLF and bare LF, drops blank lines, and tolerates a final
    line with no terminator (which is what a capture cut mid-print looks like).
    """
    if not text:
        return []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in normalized.split("\n") if line.strip()]


class SerialConsole:
    """
    Bounded, append-only capture of firmware print output.

    `max_lines` keeps the widget from growing without limit during a long run;
    the oldest lines are dropped first, and the count of dropped lines is kept
    so the UI can say "showing last N of M" rather than silently lying about
    the capture.
    """

    def __init__(self, max_lines: int = 5000):
        self.max_lines = max(1, int(max_lines))
        self.lines: List[str] = []
        self.dropped = 0

    @property
    def count(self) -> int:
        return len(self.lines)

    @property
    def total_seen(self) -> int:
        return self.dropped + len(self.lines)

    def write(self, data) -> None:
        """
        Append UART data.

        Accepts str or bytes, because the source may be a live byte stream
        (Renode) or a decoded text file, and callers should not have to care.
        """
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8", errors="replace")
        for line in parse_uart(str(data)):
            self.lines.append(line)
            if len(self.lines) > self.max_lines:
                del self.lines[0]
                self.dropped += 1

    def text(self) -> str:
        return "\n".join(self.lines)

    def clear(self) -> None:
        self.lines.clear()
        self.dropped = 0

    def grep(self, needle: str) -> List[str]:
        """Lines containing a substring, case-insensitively."""
        low = needle.lower()
        return [l for l in self.lines if low in l.lower()]

    def summary(self) -> Dict[str, object]:
        """Counts an inspector can show without re-scanning the buffer."""
        return {
            "lines": self.count,
            "dropped": self.dropped,
            "truncated": self.dropped > 0,
            "max_lines": self.max_lines,
        }