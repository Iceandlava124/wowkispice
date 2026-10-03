"""Cross-check parse_elf() against GNU readelf for the real ESP32 firmware.elf.

Temporary verification helper - not part of the test suite.
"""
import re
import subprocess
import sys

sys.path.insert(0, r"C:\Users\gudae\Music\PROJECT_WOWKISPICE")
from bridge import firmware

ELF = r"C:\Users\gudae\Music\PROJECT_WOWKISPICE\firmware\esp32_buck_controller\.pio\build\esp32dev\firmware.elf"
READELF = r"C:\Users\gudae\.platformio\packages\toolchain-xtensa-esp-elf\bin\xtensa-esp32-elf-readelf.exe"

out = subprocess.run([READELF, "-S", ELF], capture_output=True, text=True).stdout
ref = {}
for line in out.splitlines():
    m = re.match(r"\s*\[\s*(\d+)\]\s+(\S+)\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)", line)
    if m:
        ref[int(m.group(1))] = dict(name=m.group(2), type=m.group(3),
                                    address=int(m.group(4), 16),
                                    offset=int(m.group(5), 16),
                                    size=int(m.group(6), 16))

img = firmware.load_firmware(ELF)
ours = img.sections

print("%-4s %-22s %-11s %-11s %-9s %s" % ("idx", "name", "addr", "offset", "size", "vs readelf"))
print("-" * 78)
bad = 0
for i, s in enumerate(ours):
    r = ref.get(i)
    if not r:
        continue
    # readelf prints the NULL section as "NULL" (it has no name) and truncates
    # long names to e.g. ".rtc_fast_re[...]"; only compare names it printed
    # in full.
    name_ok = True
    if r["name"] == "NULL":
        name_ok = s["name"] == ""
    elif r["name"].endswith("[...]"):
        name_ok = r["name"][:-5] in s["name"]
    else:
        name_ok = s["name"] == r["name"]
    ok = (name_ok and s["address"] == r["address"]
          and s["offset"] == r["offset"] and s["size"] == r["size"])
    if not ok:
        bad += 1
    if i < 20 or not ok:
        print("%-4d %-22s 0x%08X  0x%08X   %-9d %s" % (
            i, s["name"] or "(unnamed)", s["address"], s["offset"], s["size"],
            "ok" if ok else "MISMATCH readelf=%s/0x%X/0x%X/%d" % (
                r["name"], r["address"], r["offset"], r["size"])))

print()
print("sections compared :", len(ref))
print("mismatches        :", bad)
print("machine           :", img.machine)
print("entry             : 0x%08X" % img.entry_point)
sys.exit(1 if bad else 0)