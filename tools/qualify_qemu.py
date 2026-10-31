"""
qualify_qemu.py - Qualify patched QEMU binary
"""
import os
import sys
import json
import hashlib
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.toolchain_resolver import ToolchainResolver


class QemuQualifier:
    def __init__(self):
        self.resolver = ToolchainResolver()
        self.repo_root = Path(__file__).parent.parent
        
    def qualify(self, qemu_path=None):
        """Qualify a QEMU binary"""
        if qemu_path is None:
            qemu_path = self.resolver.find_qemu()
        
        if not qemu_path or not os.path.exists(qemu_path):
            print("✗ QEMU not found")
            return False
        
        print(f"Qualifying: {qemu_path}")
        print("=" * 60)
        
        results = {
            "path": qemu_path,
            "exists": True,
            "executable": os.access(qemu_path, os.X_OK) or qemu_path.endswith('.exe'),
            "sha256": self.sha256_file(qemu_path),
            "has_esp32": False,
            "has_sens": False,
            "passed": False
        }
        
        print(f"SHA256: {results['sha256']}")
        
        # Check if executable
        if not results["executable"]:
            print("✗ Not executable")
            return False
        print("✓ Executable")
        
        # Check for ESP32 support
        try:
            result = subprocess.run([qemu_path, "-machine", "help"], 
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                  timeout=10)
            out = (result.stdout + result.stderr).lower()
            if b"esp32" in out:
                results["has_esp32"] = True
                print("✓ ESP32 machine support")
            else:
                print("✗ No ESP32 machine support")
        except Exception as e:
            print(f"✗ Failed to query machines: {e}")
            return False
        
        # Check for SENS model (patched)
        try:
            result = subprocess.run([qemu_path, "-device", "help"], 
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                  timeout=10)
            out = (result.stdout + result.stderr).lower()
            if b"sens" in out or b"adc" in out:
                results["has_sens"] = True
                print("✓ SENS/ADC model present (patched)")
            else:
                print("⚠ SENS/ADC model not detected (may not be patched)")
        except Exception as e:
            print(f"⚠ Could not check devices: {e}")
        
        results["passed"] = results["has_esp32"] and results["executable"]
        
        print("=" * 60)
        if results["passed"] and results["has_sens"]:
            print("✓ QUALIFIED - Fully patched for WOSP")
        elif results["passed"]:
            print("⚠ PARTIALLY QUALIFIED - Has ESP32 but SENS model unclear")
        else:
            print("✗ NOT QUALIFIED")
        
        # Save to manifest
        manifest_path = self.repo_root / "third_party" / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)
            manifest.setdefault("qemu", {})["qualified"] = results
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)
            print(f"\nResults saved to {manifest_path}")
        
        return results["passed"] and results["has_sens"]
    
    def sha256_file(self, filepath):
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()


if __name__ == "__main__":
    qualifier = QemuQualifier()
    success = qualifier.qualify()
    sys.exit(0 if success else 1)
