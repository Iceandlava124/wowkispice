"""Set/get the SENS adc1-value property over the QEMU HMP monitor.

Usage: qom_set.py <port> [value]
Without a value it only reads the current property.
"""
import socket
import sys
import time
import re

PORT = int(sys.argv[1])
VALUE = sys.argv[2] if len(sys.argv) > 2 else None
PATH = "/machine/peripheral/sens"

for _ in range(30):
    try:
        s = socket.create_connection(("127.0.0.1", PORT), timeout=3)
        break
    except OSError:
        time.sleep(0.5)
else:
    sys.exit("monitor never came up on port %d" % PORT)
s.settimeout(4)


def cmd(c, wait=1.5):
    s.sendall(c.encode() + b"\n")
    time.sleep(wait)
    out = b""
    while True:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        out += chunk
    txt = re.sub(r"\x1b\[[0-9;]*[A-Za-z]|\r", "", out.decode(errors="replace"))
    lines = []
    for line in txt.splitlines():
        if not line.strip() or "(qemu)" in line or "monitor - type" in line:
            continue
        # strip the readline echo of the command we just typed
        if "qom-" in line and not line.startswith(("0", "1", "2", "3", "4",
                                                   "5", "6", "7", "8", "9",
                                                   "Error")):
            continue
        lines.append(line)
    return lines


cmd("", wait=0.5)
if VALUE is None:
    print("get:", cmd("qom-get %s adc1-value" % PATH))
else:
    print("set:", cmd("qom-set %s adc1-value %s" % (PATH, VALUE)))
    print("get:", cmd("qom-get %s adc1-value" % PATH))
s.close()
