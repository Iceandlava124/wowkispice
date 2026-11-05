/*
 * test_qtest_client.rs - Rust gate for bridge/qtest_client.py.
 *
 * Transcribes QtestClient: line-oriented qtest protocol parsing (OK / FAIL /
 * hex blob), async event filtering ([I ...], [R ...], ...), memory read/write
 * (read/write/readl/readw/readq/writel/writew/writeq), clock_step, events,
 * close, Drop. A std::net::TcpListener mocks QEMU's qtest port so no real
 * emulator is needed.
 */

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::thread;
use wowkispice_core::qtest_client::{hex_decode, hex_encode, QtestClient, QtestError};

/// Spin a mock qtest server on a free port. `handler` receives each client
/// line and writes reply bytes to the stream. Returns (port, join_handle).
fn mock_qtest_server<F>(mut handler: F) -> (u16, thread::JoinHandle<()>)
where
    F: FnMut(&str, &mut TcpStream) + Send + 'static,
{
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let handle = thread::spawn(move || {
        for stream in listener.incoming() {
            match stream {
                Ok(mut s) => {
                    s.set_read_timeout(Some(std::time::Duration::from_secs(5)))
                        .ok();
                    s.set_write_timeout(Some(std::time::Duration::from_secs(5)))
                        .ok();
                    let mut buf = [0u8; 4096];
                    let mut leftover = Vec::new();
                    loop {
                        match s.read(&mut buf) {
                            Ok(0) => break,
                            Ok(n) => {
                                leftover.extend_from_slice(&buf[..n]);
                                while let Some(pos) = leftover.iter().position(|&b| b == b'\n')
                                {
                                    let line = String::from_utf8_lossy(&leftover[..=pos])
                                        .trim()
                                        .to_string();
                                    leftover.drain(..=pos);
                                    handler(&line, &mut s);
                                }
                            }
                            Err(_) => break,
                        }
                    }
                }
                Err(_) => break,
            }
        }
    });
    (port, handle)
}

/// Connect a QtestClient to the mock server and return it.
fn connect_client(port: u16) -> QtestClient {
    QtestClient::connect_tcp("127.0.0.1", port, 5.0, 2.0).unwrap()
}

// ----------------------------------------------------------------------
// hex_encode / hex_decode
// ----------------------------------------------------------------------

#[test]
fn test_hex_encode_round_trip() {
    let data = vec![0x00, 0x01, 0x7f, 0x80, 0xff, 0xab, 0xcd];
    let enc = hex_encode(&data);
    assert_eq!(enc, "00017f80ffabcd");
    let dec = hex_decode(&enc).unwrap();
    assert_eq!(dec, data);
}

#[test]
fn test_hex_decode_odd_length_errors() {
    assert!(hex_decode("abc").is_err());
}

#[test]
fn test_hex_decode_invalid_digit_errors() {
    assert!(hex_decode("0xgg").is_err());
}

#[test]
fn test_hex_decode_strips_whitespace() {
    let data = vec![0x12, 0x34];
    let enc = "12 34\n";
    assert_eq!(hex_decode(enc).unwrap(), data);
}

// ----------------------------------------------------------------------
// QtestError / QtestTimeout Display
// ----------------------------------------------------------------------

#[test]
fn test_qtest_error_display() {
    let e: QtestError = QtestError("boom".to_string());
    assert_eq!(format!("{e}"), "boom");
}

#[test]
fn test_qtest_timeout_into_error() {
    let t = wowkispice_core::qtest_client::QtestTimeout("slow".to_string());
    let e: QtestError = t.into();
    assert_eq!(format!("{e}"), "slow");
}

// ----------------------------------------------------------------------
// connect_tcp failure
// ----------------------------------------------------------------------

#[test]
fn test_connect_tcp_refused() {
    let err = QtestClient::connect_tcp("127.0.0.1", 1, 0.1, 0.1).err().unwrap();
    assert!(format!("{err}").contains("could not reach qtest"));
}

// ----------------------------------------------------------------------
// command: OK reply, event filtering, FAIL error
// ----------------------------------------------------------------------

#[test]
fn test_command_ok_reply() {
    let (port, _handle) = mock_qtest_server(|line, s| {
        if line == "readl 0x1000" {
            let _ = s.write_all(b"OK 0xdeadbeef\n");
        }
    });
    let mut client = connect_client(port);
    let value = client.command("readl 0x1000").unwrap();
    assert_eq!(value, "OK 0xdeadbeef");
}

#[test]
fn test_command_filters_async_events() {
    let (port, _handle) = mock_qtest_server(|line, s| {
        if line == "readl 0x1000" {
            // QEMU interleaves async events before the reply
            let _ = s.write_all(b"[I +0.001] reset\n[R +0.002] readl\nOK 0xcafebabe\n");
        }
    });
    let mut client = connect_client(port);
    let value = client.command("readl 0x1000").unwrap();
    assert_eq!(value, "OK 0xcafebabe");
    assert_eq!(client.events().len(), 2);
    assert!(client.events()[0].starts_with("[I"));
    assert!(client.events()[1].starts_with("[R"));
}

#[test]
fn test_command_fail_raises_qtest_error() {
    let (port, _handle) = mock_qtest_server(|line, s| {
        if line == "badcmd" {
            let _ = s.write_all(b"FAIL invalid command\n");
        }
    });
    let mut client = connect_client(port);
    let err = client.command("badcmd").unwrap_err();
    assert!(format!("{err}").contains("FAIL"));
    assert!(format!("{err}").contains("badcmd"));
}

// ----------------------------------------------------------------------
// memory read/write
// ----------------------------------------------------------------------

#[test]
fn test_read_write_round_trip() {
    let (port, _handle) = mock_qtest_server(|line, s| {
        if line.starts_with("read 0x") {
            let _ = s.write_all(b"OK 01020304\n");
        }
    });
    let mut client = connect_client(port);
    let data = client.read(0x1000, 4).unwrap();
    assert_eq!(data, vec![0x01, 0x02, 0x03, 0x04]);
}

#[test]
fn test_readl_readw_readq() {
    let (port, _handle) = mock_qtest_server(|line, s| {
        if line == "readl 0x1000" {
            let _ = s.write_all(b"OK 0x12345678\n");
        } else if line == "readw 0x1000" {
            let _ = s.write_all(b"OK 0xabcd\n");
        } else if line == "readq 0x1000" {
            let _ = s.write_all(b"OK 0x1122334455667788\n");
        }
    });
    let mut client = connect_client(port);
    assert_eq!(client.readl(0x1000).unwrap(), 0x12345678);
    assert_eq!(client.readw(0x1000).unwrap(), 0xabcd);
    assert_eq!(client.readq(0x1000).unwrap(), 0x1122334455667788);
}

#[test]
fn test_writel_writew_writeq() {
    let (port, _handle) = mock_qtest_server(|line, s| {
        assert!(
            line == "writel 0x1000 0x12345678"
                || line == "writew 0x1000 0xabcd"
                || line == "writeq 0x1000 0x1122334455667788"
        );
        let _ = s.write_all(b"OK\n");
    });
    let mut client = connect_client(port);
    client.writel(0x1000, 0x12345678).unwrap();
    client.writew(0x1000, 0xabcd).unwrap();
    client.writeq(0x1000, 0x1122334455667788).unwrap();
}

#[test]
fn test_clock_step() {
    let (port, _handle) = mock_qtest_server(|line, s| {
        if line == "clock_step" {
            let _ = s.write_all(b"OK 1000000\n");
        } else if line == "clock_step 5000" {
            let _ = s.write_all(b"OK 5000\n");
        }
    });
    let mut client = connect_client(port);
    assert_eq!(client.clock_step(None).unwrap(), 1000000);
    assert_eq!(client.clock_step(Some(5000)).unwrap(), 5000);
}

// ----------------------------------------------------------------------
// close / Drop
// ----------------------------------------------------------------------

#[test]
fn test_close() {
    let (port, _handle) = mock_qtest_server(|line, s| {
        if line == "quit" {
            let _ = s.write_all(b"OK\n");
        }
    });
    let mut client = connect_client(port);
    client.close(); // must not panic
}

// ----------------------------------------------------------------------
// Drop calls close
// ----------------------------------------------------------------------

#[test]
fn test_drop_calls_close() {
    let (port, _handle) = mock_qtest_server(|_, _| {});
    {
        let _client = connect_client(port);
    } // Drop should fire here without panicking
}
