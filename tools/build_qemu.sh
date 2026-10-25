#!/usr/bin/env bash
# tools/build_qemu.sh
#
# Reproducible Espressif QEMU build for PROJECT_WOWKISPICE.
#
# What this produces:
#   ./build/qemu-system-xtensa   (patched, Xtensa ESP32 build)
#
# The patch applied here is the one that models the ESP32 SAR ADC
# (esp32_sens) so the firmware binary can be executed and fed ADC samples.
# The patch itself is NOT committed to the repo; see docs/toolchain.md §1 for
# the commit/tag it applies to and how to fetch the patch from the owner.
#
# Usage:
#   cd tools
#   ./build_qemu.sh            # builds into ./build/
#   export WOSP_QEMU=$(pwd)/build/qemu-system-xtensa
#
# Verification performed at the end (exit 1 on failure):
#   1. the binary runs and --version prints
#   2. qemu-system-xtensa -machine help lists the esp32_sens device
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIN_TAG="esp-develop-9.2.2-20260417"
PATCH="$REPO_ROOT/tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch"
BUILD_DIR="$REPO_ROOT/tools/build"
QEMU_BIN="$BUILD_DIR/qemu-system-xtensa"

mkdir -p "$BUILD_DIR"
cd "$REPO_ROOT"

echo "=== [1/5] Clone Espressif QEMU (esp-develop) at $PIN_TAG ==="
rm -rf "$REPO_ROOT/build/qemu-src"
git clone --depth 1 --branch "$PIN_TAG" \
    https://github.com/espressif/qemu.git "$REPO_ROOT/build/qemu-src"
cd "$REPO_ROOT/build/qemu-src"

echo "=== [2/5] Apply the esp32_sens patch ==="
if [ ! -f "$PATCH" ]; then
    echo "ERROR: patch not found at $PATCH" >&2
    echo "docs/toolchain.md §1 records the patch and commit/tag, and the owner" >&2
    echo "must re-supply it before a byte-exact rebuild. The platform cannot" >&2
    echo "run without a patched QEMU." >&2
    exit 1
fi
git apply --check "$PATCH" || { echo "PATCH APPLY --CHECK FAILED" >&2; exit 1; }
git apply "$PATCH"

echo "=== [3/5] Configure ==="
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"
cmake -S "$REPO_ROOT/build/qemu-src" \
      -B "$BUILD_DIR/build" \
      -DCMAKE_BUILD_TYPE=Release \
      -DENABLE_GTK=off \
      -DENABLE_SDL=off \
      -DENABLE_COCOA=off \
      -DENABLE_VNC=off \
      -DDRIVER_QGA=off \
      -DENABLE_UDEV=off \
      -DENABLE_CAP=off \
      -DENABLE_FUSION=off \
      -DENABLE_GRECORDER=off \
      -DENABLE_SLIRP=off \
      -DENABLE_GUS=off \
      -DENABLE_KVM=off \
      -DENABLE_LINUX_AIO=off \
      -DBUILD_DOCS=off \
      -DINSTALL_CMREL=OFF \
      -DEXAMPLES=off

echo "=== [4/5] Build qemu-system-xtensa ==="
make -C "$BUILD_DIR/build" -j"$(nproc 2>/dev/null || echo 2)" qemu-system-xtensa
cp "$BUILD_DIR/build/qemu-system-xtensa" "$QEMU_BIN"

echo "=== [5/5] Verify ==="
"$QEMU_BIN" --version
if ! "$QEMU_BIN" -machine help | grep -q esp32_sens; then
    echo "ERROR: esp32_sens device not listed in -machine help" >&2
    exit 1
fi
echo "OK: patched QEMU is at $QEMU_BIN"
echo "    esp32_sens device listed."
echo "    sha256: $(sha256sum "$QEMU_BIN" | awk '{print $1}')"
