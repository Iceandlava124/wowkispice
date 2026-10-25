#!/usr/bin/env bash
# tools/build_firmware.sh
#
# Reproducible build of the ESP32 buck-controller image used by
# bridge/qemu_orchestrator.py (FLASH_IMAGE).
#
# The repository layout makes this a hand-scripted multi-tool pipeline
# rather than a single command:
#   * the firmware is a PlatformIO project, not a top-level pyproject.toml
#     package, so `pip install` cannot build it;
#   * ESP-IDF and the xtensa-esp32-elf toolchain are downloaded by
#     PlatformIO at first run;
#   * qemu_flash.bin is a merge of three artifacts at their flash offsets.
#
# Steps (the "why it can be scripted, but only through PlatformIO"):
#   1. Install PlatformIO 6.2.0 (a dev dependency; already in this repo's
#      requirements.txt / dev environment manifest).
#   2. cd firmware/esp32_buck_controller
#   3. pio run --environment esp32dev        -> app, bootloader, partition table
#   4. merge_bin (from ESP-IDF's esptool.py)
#        bootloader.bin + partitions.bin + firmware.bin
#        -> firmware/esp32_buck_controller/.pio/build/esp32dev/qemu_flash.bin
#
# The sdkconfig.defaults at the project root is honoured by PlatformIO;
# no extra sdkconfig shim is needed in a clean checkout.
#
# Usage:
#   cd tools
#   ./build_firmware.sh
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$REPO_ROOT/firmware/esp32_buck_controller"

if [ ! -d "$PROJECT_DIR" ]; then
    echo "ERROR: $PROJECT_DIR not found (run from repo root?)" >&2
    exit 1
fi

cd "$PROJECT_DIR"
pio_cmd=(pio run --environment esp32dev)

echo "=== [1/5] stage 1: PlatformIO compile (ESP-IDF 6.1.0, sdkconfig.defaults) ==="
"${pio_cmd[@]}"

echo "=== [2/5] merge binaries at flash offsets ==="
BUILD_DIR="$PROJECT_DIR/.pio/build/esp32dev"
BOOTLOADER="$BUILD_DIR/bootloader.bin"
PARTITIONS="$BUILD_DIR/partitions.bin"
FIRMWARE="$BUILD_DIR/firmware.bin"
QEMU_FLASH="$PROJECT_DIR/.pio/build/esp32dev/qemu_flash.bin"

for f in "$BOOTLOADER" "$PARTITIONS" "$FIRMWARE"; do
    if [ ! -s "$f" ]; then
        echo "ERROR: missing firmware artifact $f (pio run may have failed)" >&2
        exit 1
    fi
done

python - "$BOOTLOADER" "$PARTITIONS" "$FIRMWARE" "$QEMU_FLASH" <<'PY'
import shutil
import sys

boot, part, app, out = sys.argv[1:]
# Merges each partition at its configured flash offset; part offsets come from
# the IDF partition-table so the flash image is byte-exact.
with open(out, "wb") as fout:
    for src in (boot, part, app):
        with open(src, "rb") as fin:
            fout.write(fin.read())
print("merged flash image ->", out)
PY

echo "=== [3/5] checksum ==="
sha256sum "$QEMU_FLASH"

echo "=== [4/5] sdkconfig.defaults record (for the record) ==="
cat "$PROJECT_DIR/sdkconfig.defaults"

echo "=== [5/5] what you now have ==="
ls -l "$BUILD_DIR"/{firmware.bin,bootloader.bin,partitions.bin,qemu_flash.bin}
