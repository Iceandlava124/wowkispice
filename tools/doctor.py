"""
doctor.py - WOSP environment health check
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# J-fix: a Windows console on cp1252 cannot encode the glyphs below and would
# die with UnicodeEncodeError mid-report. Keep every emitted character inside
# ASCII, and belt-and-braces reconfigure stdout/stderr so any stray non-ASCII
# in a path or message is replaced instead of raising.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

from bridge.toolchain_resolver import ToolchainResolver


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def checkmark(ok):
    # ASCII only: cp1252 consoles have no glyph for check/cross marks.
    tag = "[OK]" if ok else "[X] "
    color = Colors.GREEN if ok else Colors.RED
    return f"{color}{tag}{Colors.RESET}"


def warn(text):
    print(f"{Colors.YELLOW}[!]{Colors.RESET} {text}")


def info(text):
    print(f"{Colors.BLUE}[i]{Colors.RESET} {text}")


def doctor():
    print(f"{Colors.BOLD}WOSP Environment Doctor{Colors.RESET}")
    print("=" * 60)
    print()
    
    resolver = ToolchainResolver()
    status = resolver.get_status()
    
    all_ok = True
    
    # Check Python environment
    print(f"{Colors.BOLD}Python Environment{Colors.RESET}")
    print(f"  {checkmark(True)} Python {sys.version.split()[0]}")
    print(f"  {checkmark(hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))} Virtual environment")
    print()
    
    # Check QEMU
    print(f"{Colors.BOLD}QEMU (ESP32 Emulation){Colors.RESET}")
    if status["qemu"]["found"]:
        print(f"  {checkmark(True)} QEMU found: {status['qemu']['path']}")
        if status["qemu"]["patched"]:
            print(f"  {checkmark(True)} Patched for ESP32 SENS/ADC")
        else:
            print(f"  {checkmark(False)} May not have SENS model (ADC injection won't work)")
            warn("Use a patched QEMU build for real firmware cosimulation")
        all_ok = all_ok and status["qemu"]["patched"]
        # Try qualification
        try:
            from tools.qualify_qemu import QemuQualifier
            q = QemuQualifier()
            if q.qualify(status["qemu"]["path"]):
                print(f"  {checkmark(True)} QEMU qualified")
            else:
                print(f"  {checkmark(False)} QEMU qualification issues")
        except Exception as e:
            warn(f"Could not qualify QEMU: {e}")
    else:
        print(f"  {checkmark(False)} QEMU not found")
        warn("Run: python tools/fetch_qemu.py or set WOSP_QEMU")
        all_ok = False
    print()
    
    # Check ngspice
    print(f"{Colors.BOLD}ngspice (Circuit Simulation){Colors.RESET}")
    if status["ngspice"]["found"]:
        print(f"  {checkmark(True)} ngspice found: {status['ngspice']['path']}")
    else:
        print(f"  {checkmark(False)} ngspice not found")
        warn("Run setup.ps1 or install ngspice")
        all_ok = False
    print()
    
    # Check firmware
    print(f"{Colors.BOLD}Firmware{Colors.RESET}")
    repo_root = Path(__file__).parent.parent
    fw_bin = repo_root / "firmware" / "esp32_buck_controller" / ".pio" / "build" / "esp32dev" / "qemu_flash.bin"
    if fw_bin.exists():
        print(f"  {checkmark(True)} Firmware binary exists: {fw_bin}")
    else:
        print(f"  {checkmark(False)} Firmware binary not found")
        warn("Build with PlatformIO or place prebuilt qemu_flash.bin")
    print()
    
    # Check tests
    print(f"{Colors.BOLD}Tests{Colors.RESET}")
    tests_dir = repo_root / "tests"
    if tests_dir.exists():
        test_count = len(list(tests_dir.glob("test_*.py")))
        print(f"  {checkmark(True)} {test_count} test files found")
    print()
    
    # Summary
    print("=" * 60)
    if all_ok:
        print(f"{Colors.GREEN}{Colors.BOLD}[OK] Environment looks good!{Colors.RESET}")
        print("\nYou can run:")
        print("  python -m pytest tests -v")
        print("  python tools/run_tests.py")
    else:
        print(f"{Colors.YELLOW}{Colors.BOLD}[!] Some issues found{Colors.RESET}")
        print("\nRecommendations:")
        print("  1. Run: .\\setup.ps1 (Windows) or ./setup.sh (Linux)")
        print("  2. Run: python tools/fetch_qemu.py")
        print("  3. Check docs/SETUP.md for details")
    print()
    
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(doctor())
