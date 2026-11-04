/*
 * qtest_client.rs - port of bridge/qtest_client.py.
 *
 * Minimal std-only client for QEMU's qtest protocol. Mirrors the Python
 * module one-to-one: qtest is line oriented but interleaves unsolicited
 * async event lines ([I ...], [R ...], ...) that must be filtered out
 * before the command reply (OK ... / FAIL ... / hex blob) is parsed.
 *
 * `socket` -> std::net::TcpStream, `time` -> std::time::{Instant, Duration}
 * plus std::thread::sleep.  Dependency-free: std only.
 *
 * The public API mirrors the Python names exactly: QtestClient,
 * QtestError, QtestTimeout, connect_tcp, connect_unix, command, read,
 * write, readl/readw/readq, writel/writew/writeq, clock_step, events,
 * close.  `connect_unix` is compiled only on Unix targets because std has
 * no AF_UNIX socket on Windows.
 *
 * Drop closes the socket (Rust's equivalent of the Python context manager).
 */

use std::fmt;
use std::io::{self, Read, Write};
use std::net::{Shutdown, SocketAddr, TcpStream, ToSocketAddrs};
use std::thread;
use std::time::{Duration, Instant};

#[cfg(unix)]
use std::os::unix::net::UnixStream;

/// QEMU replied FAIL to a command.
#[derive(Debug)]
pub struct QtestError(pub String);

/// QEMU did not answer within the deadline.
#[derive(Debug)]
pub struct QtestTimeout(pub String);

impl From<QtestTimeout> for QtestError {
    fn from(t: QtestTimeout) -> QtestError {
        QtestError(t.0)
    }
}

impl fmt::Display for QtestError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl fmt::Display for QtestTimeout {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for QtestError {}

impl From<io::Error> for QtestError {
    fn from(e: io::Error) -> QtestError {
        QtestError(e.to_string())
    }
}

/// Transport endpoint: a TCP stream (always) or a Unix stream (Unix only).
enum InnerSock {
    Tcp(TcpStream),
    #[cfg(unix)]
    Unix(UnixStream),
}

impl InnerSock {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        match self {
            InnerSock::Tcp(s) => s.read(buf),
            #[cfg(unix)]
            InnerSock::Unix(s) => s.read(buf),
        }
    }

    fn write_all(&mut self, buf: &[u8]) -> io::Result<()> {
        match self {
            InnerSock::Tcp(s) => s.write_all(buf),
            #[cfg(unix)]
            InnerSock::Unix(s) => s.write_all(buf),
        }
    }

    fn set_read_timeout(&self, dur: Duration) -> io::Result<()> {
        match self {
            InnerSock::Tcp(s) => s.set_read_timeout(Some(dur)),
            #[cfg(unix)]
            InnerSock::Unix(s) => s.set_read_timeout(Some(dur)),
        }
    }

    fn set_write_timeout(&self, dur: Duration) -> io::Result<()> {
        match self {
            InnerSock::Tcp(s) => s.set_write_timeout(Some(dur)),
            #[cfg(unix)]
            InnerSock::Unix(s) => s.set_write_timeout(Some(dur)),
        }
    }

    fn shutdown(&self) -> io::Result<()> {
        match self {
            InnerSock::Tcp(s) => s.shutdown(Shutdown::Both),
            #[cfg(unix)]
            InnerSock::Unix(s) => s.shutdown(std::os::unix::net::Shutdown::Both),
        }
    }
}

/// Line-oriented client for the qtest protocol.
///
/// qtest is line based, but interleaves unsolicited async event lines that
/// must be filtered out before the command response is parsed:
///
///     [I +0.000000] OPENED
///     [R +0.000587] clock_step
///     [S +0.001227] OK 100000000
///
/// Every reply is either ``OK ...``, ``FAIL ...`` or a bare hex blob.
pub struct QtestClient {
    sock: InnerSock,
    buf: Vec<u8>,
    events: Vec<String>,
    closed: bool,
}

impl QtestClient {
    // ------------------------------------------------------------------ setup

    pub fn connect_tcp(
        host: &str,
        port: u16,
        timeout: f64,
        retry_seconds: f64,
    ) -> Result<QtestClient, QtestError> {
        let addrs: Vec<SocketAddr> = match (host, port).to_socket_addrs() {
            Ok(addrs) => addrs.collect(),
            Err(e) => {
                return Err(QtestError(format!(
                    "could not resolve {}:{} : {}",
                    host, port, e
                )));
            }
        };
        if addrs.is_empty() {
            return Err(QtestError(format!("no addresses for {}:{}", host, port)));
        }

        let deadline = Instant::now() + Duration::from_secs_f64(retry_seconds);
        let connect_timeout = Duration::from_secs_f64(timeout);
        let op_timeout = Duration::from_secs_f64(timeout);
        let mut last: Option<String> = None;

        // QEMU binds the socket asynchronously, so poll rather than assuming
        // the port is live the instant the process is spawned.
        while Instant::now() < deadline {
            let mut connected: Option<InnerSock> = None;
            for addr in &addrs {
                match TcpStream::connect_timeout(addr, connect_timeout) {
                    Ok(sock) => {
                        connected = Some(InnerSock::Tcp(sock));
                        break;
                    }
                    Err(e) => last = Some(e.to_string()),
                }
            }
            if let Some(sock) = connected {
                let _ = sock.set_read_timeout(op_timeout);
                let _ = sock.set_write_timeout(op_timeout);
                return Ok(QtestClient {
                    sock,
                    buf: Vec::new(),
                    events: Vec::new(),
                    closed: false,
                });
            }
            thread::sleep(Duration::from_millis(50));
        }

        Err(match last {
            Some(e) => QtestError(format!(
                "could not reach qtest at {}:{} within {:.1}s ({})",
                host, port, retry_seconds, e
            )),
            None => QtestError(format!(
                "could not reach qtest at {}:{} within {:.1}s",
                host, port, retry_seconds
            )),
        })
    }

    #[cfg(unix)]
    pub fn connect_unix(
        path: &str,
        timeout: f64,
        retry_seconds: f64,
    ) -> Result<QtestClient, QtestError> {
        let deadline = Instant::now() + Duration::from_secs_f64(retry_seconds);
        let op_timeout = Duration::from_secs_f64(timeout);
        let mut last: Option<String> = None;

        while Instant::now() < deadline {
            match UnixStream::connect(path) {
                Ok(sock) => {
                    let _ = sock.set_read_timeout(Some(op_timeout));
                    let _ = sock.set_write_timeout(Some(op_timeout));
                    return Ok(QtestClient {
                        sock: InnerSock::Unix(sock),
                        buf: Vec::new(),
                        events: Vec::new(),
                        closed: false,
                    });
                }
                Err(e) => {
                    last = Some(e.to_string());
                    thread::sleep(Duration::from_millis(50));
                }
            }
        }

        Err(match last {
            Some(e) => QtestError(format!(
                "could not reach qtest at {} within {:.1}s ({})",
                path, retry_seconds, e
            )),
            None => QtestError(format!(
                "could not reach qtest at {} within {:.1}s",
                path, retry_seconds
            )),
        })
    }

    // ------------------------------------------------------------- transport

    fn _readline(&mut self) -> Result<String, QtestError> {
        while !self.buf.contains(&b'\n') {
            let mut chunk = [0u8; 4096];
            let n = match self.sock.read(&mut chunk) {
                Ok(0) => {
                    return Err(QtestError("qtest connection closed by QEMU".to_string()))
                }
                Ok(n) => n,
                Err(e) => return Err(QtestError(e.to_string())),
            };
            self.buf.extend_from_slice(&chunk[..n]);
        }
        let pos = self
            .buf
            .iter()
            .position(|&b| b == b'\n')
            .expect("newline present");
        let line: Vec<u8> = self.buf.drain(..=pos).collect();
        Ok(String::from_utf8_lossy(&line).trim().to_string())
    }

    pub fn command(&mut self, cmd: &str) -> Result<String, QtestError> {
        self.sock.write_all(format!("{}\n", cmd).as_bytes())?;
        loop {
            let line = self._readline()?;
            if line.is_empty() {
                continue;
            }
            if line.starts_with('[') {
                // Unsolicited event, e.g. "[I +0.001] reset" or "[R ...] cmd".
                self.events.push(line);
                continue;
            }
            if line.starts_with("FAIL") {
                return Err(QtestError(format!("{} -> {}", cmd, line)));
            }
            return Ok(line);
        }
    }

    fn _ok_value(&mut self, cmd: &str) -> Result<String, QtestError> {
        let reply = self.command(cmd)?;
        let parts: Vec<&str> = reply.split_whitespace().take(2).collect();
        if parts.len() != 2 {
            return Err(QtestError(format!(
                "{} -> {:?}, expected 'OK <value>'",
                cmd, self.buf
            )));
        }
        Ok(parts[1].to_string())
    }

    // ---------------------------------------------------------------- memory

    pub fn read(&mut self, addr: u64, size: u64) -> Result<Vec<u8>, QtestError> {
        let raw = self._ok_value(&format!("read 0x{:x} 0x{:x}", addr, size))?;
        hex_decode(&raw)
    }

    pub fn write(&mut self, addr: u64, data: &[u8]) -> Result<(), QtestError> {
        let hex = hex_encode(data);
        self.command(&format!(
            "write 0x{:x} 0x{:x} 0x{}",
            addr,
            data.len(),
            hex
        ))?;
        Ok(())
    }

    pub fn readl(&mut self, addr: u64) -> Result<u32, QtestError> {
        u32::from_str_radix(&self._ok_value(&format!("readl 0x{:x}", addr))?, 16)
            .map_err(|e| QtestError(e.to_string()))
    }

    pub fn readw(&mut self, addr: u64) -> Result<u16, QtestError> {
        u16::from_str_radix(&self._ok_value(&format!("readw 0x{:x}", addr))?, 16)
            .map_err(|e| QtestError(e.to_string()))
    }

    pub fn readq(&mut self, addr: u64) -> Result<u64, QtestError> {
        u64::from_str_radix(&self._ok_value(&format!("readq 0x{:x}", addr))?, 16)
            .map_err(|e| QtestError(e.to_string()))
    }

    pub fn writel(&mut self, addr: u64, value: u32) -> Result<(), QtestError> {
        self.command(&format!(
            "writel 0x{:x} 0x{:x}",
            addr,
            value & 0xFFFFFFFF
        ))?;
        Ok(())
    }

    pub fn writew(&mut self, addr: u64, value: u16) -> Result<(), QtestError> {
        self.command(&format!(
            "writew 0x{:x} 0x{:x}",
            addr, value & 0xFFFF
        ))?;
        Ok(())
    }

    pub fn writeq(&mut self, addr: u64, value: u64) -> Result<(), QtestError> {
        self.command(&format!(
            "writeq 0x{:x} 0x{:x}",
            addr,
            value & 0xFFFFFFFFFFFFFFFF
        ))?;
        Ok(())
    }

    // ----------------------------------------------------------------- clock

    pub fn clock_step(&mut self, ns: Option<i64>) -> Result<i64, QtestError> {
        let cmd = match ns {
            Some(n) => format!("clock_step {}", n),
            None => "clock_step".to_string(),
        };
        i64::from_str_radix(&self._ok_value(&cmd)?, 10).map_err(|e| QtestError(e.to_string()))
    }

    // ------------------------------------------------------------- lifecycle

    pub fn events(&self) -> Vec<String> {
        self.events.clone()
    }

    pub fn close(&mut self) {
        if !self.closed {
            let _ = self.sock.write_all(b"quit\n");
            let _ = self.sock.shutdown();
            self.closed = true;
        }
    }
}

impl Drop for QtestClient {
    fn drop(&mut self) {
        self.close();
    }
}

fn hex_encode(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push_str(&format!("{:02x}", b));
    }
    out
}

fn hex_decode(s: &str) -> Result<Vec<u8>, QtestError> {
    let s: String = s.chars().filter(|c| !c.is_ascii_whitespace()).collect();
    if s.len() % 2 != 0 {
        return Err(QtestError(format!("odd-length hex string: {:?}", s)));
    }
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(s.len() / 2);
    for i in (0..bytes.len()).step_by(2) {
        let high = hex_nibble(bytes[i])?;
        let low = hex_nibble(bytes[i + 1])?;
        out.push((high << 4) | low);
    }
    Ok(out)
}

fn hex_nibble(b: u8) -> Result<u8, QtestError> {
    match b {
        b'0'..=b'9' => Ok(b - b'0'),
        b'a'..=b'f' => Ok(b - b'a' + 10),
        b'A'..=b'F' => Ok(b - b'A' + 10),
        _ => Err(QtestError(format!("invalid hex digit: {}", b as char))),
    }
}
