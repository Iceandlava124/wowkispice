"""
cleanup_qemu.py - Clean up orphaned QEMU processes
"""
import os
import sys
import platform
import subprocess


def cleanup_qemu():
    """Kill any orphaned qemu-system-xtensa processes"""
    print("Cleaning up orphaned QEMU processes...")
    
    system = platform.system()
    
    try:
        if system == "Windows":
            # Use taskkill
            result = subprocess.run(
                ["taskkill", "/F", "/IM", "qemu-system-xtensa.exe"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            if result.returncode == 0:
                print("✓ Killed qemu-system-xtensa.exe processes")
            elif result.returncode == 128:
                print("✓ No orphaned processes found")
            else:
                print("✓ Cleanup attempted")
        else:
            # Linux/Unix
            result = subprocess.run(
                ["pkill", "-f", "qemu-system-xtensa"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            if result.returncode == 0:
                print("✓ Killed orphaned qemu-system-xtensa processes")
            else:
                print("✓ No orphaned processes found")
    except Exception as e:
        print(f"⚠ Cleanup error: {e}")
        return False
    
    return True


if __name__ == "__main__":
    cleanup_qemu()
