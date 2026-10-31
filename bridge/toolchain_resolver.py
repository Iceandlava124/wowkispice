"""
toolchain_resolver.py - Centralized discovery of QEMU and ngspice toolchains
"""
import os
import sys
import json
from pathlib import Path
from typing import Optional, Dict, Any


REPO_ROOT = Path(__file__).parent.parent
THIRD_PARTY = REPO_ROOT / "third_party"
QEMU_DIR = THIRD_PARTY / "qemu"
MANIFEST_PATH = THIRD_PARTY / "manifest.json"


class ToolchainResolver:
    """Centralized resolver for build toolchains"""
    
    def __init__(self):
        self.repo_root = REPO_ROOT
        self.third_party = THIRD_PARTY
        self.qemu_dir = QEMU_DIR
        self.manifest_path = MANIFEST_PATH
    
    def find_qemu(self) -> Optional[str]:
        """Find qemu-system-xtensa binary"""
        candidates = []
        
        # 1. Environment variable
        env_qemu = os.environ.get("WOSP_QEMU")
        if env_qemu:
            candidates.append(("env:WOSP_QEMU", env_qemu))
        
        # 2. third_party/qemu
        if self.qemu_dir.exists():
            for name in ["qemu-system-xtensa", "qemu-system-xtensa.exe", "qemu-system-xtensa-bin"]:
                p = self.qemu_dir / name
                if p.exists():
                    candidates.append(("third_party/qemu", str(p)))
            # Also check subdirs
            for root, dirs, files in os.walk(self.qemu_dir):
                for name in files:
                    if name in ["qemu-system-xtensa", "qemu-system-xtensa.exe"]:
                        candidates.append(("third_party/qemu", os.path.join(root, name)))
        
        # 3. Local repo dirs
        for pattern in ["qemu*", "build/qemu*", "*qemu-build*/**/qemu-system-xtensa*"]:
            for p in self.repo_root.rglob("qemu-system-xtensa*"):
                if p.is_file() and not str(p).startswith(str(self.repo_root / ".git")):
                    candidates.append(("repo", str(p)))
                    break
        
        # 4. PATH
        import shutil
        for name in ["qemu-system-xtensa", "qemu-system-xtensa.exe"]:
            found = shutil.which(name)
            if found:
                candidates.append(("PATH", found))
        
        # 5. Common WSL/Windows locations
        common_paths = [
            r"C:\Users\gudae\Music\qemu-build\qemu-esp_develop_9.2.2_20260417\build\qemu-system-xtensa.exe",
            "/usr/bin/qemu-system-xtensa",
            "/usr/local/bin/qemu-system-xtensa",
        ]
        for p in common_paths:
            if os.path.exists(p):
                candidates.append(("common", p))
        
        for source, path in candidates:
            if os.path.exists(path):
                return path
        return None
    
    def find_ngspice(self) -> Optional[str]:
        """Find the ngspice library/DLL the bridge would actually load.

        Delegates to bridge.ngspice_wrapper.resolve_ngspice_library() first
        ($WOSP_NGSPICE_LIB -> bundled tools/ngspice_dll DLL ->
        ctypes.util.find_library) so the doctor never reports a different
        library than the one the simulation would use; the legacy glob
        patterns below are only a fallback for exotic installs.
        """
        from bridge.ngspice_wrapper import resolve_ngspice_library

        try:
            path, _tried = resolve_ngspice_library()
        except Exception:
            path = None
        if path:
            return path

        import glob

        # Fallback: common locations outside the wrapper's search order
        patterns = [
            str(self.repo_root / "ngspice*" / "*ngspice*"),
            str(self.repo_root / "bin" / "*ngspice*"),
            str(self.repo_root / "lib" / "*ngspice*"),
            "C:/msys64/*/lib/*ngspice*",
            "C:/Spice64/*",
        ]

        for pattern in patterns:
            for p in glob.glob(pattern, recursive=True):
                if os.path.isfile(p):
                    return p

        return None
    
    def is_patched_qemu(self, qemu_path: str) -> bool:
        """Check if qemu has SENS/ADC model (patched)"""
        # Quick check - try to run help or look for esp32_sens
        try:
            import subprocess
            result = subprocess.run([qemu_path, "-machine", "help"], 
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                  timeout=5)
            out = result.stdout + result.stderr
            if b"esp32" in out.lower():
                return True
        except:
            pass
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get full toolchain status"""
        qemu = self.find_qemu()
        ngspice = self.find_ngspice()
        return {
            "qemu": {
                "found": qemu is not None,
                "path": qemu,
                "patched": self.is_patched_qemu(qemu) if qemu else False
            },
            "ngspice": {
                "found": ngspice is not None,
                "path": ngspice
            },
            "third_party_dir": str(self.third_party),
            "manifest_exists": self.manifest_path.exists()
        }
    
    def write_env_local(self) -> str:
        """Write .env.local with discovered paths"""
        status = self.get_status()
        env_path = self.repo_root / ".env.local"
        lines = []
        lines.append("# Auto-generated by toolchain_resolver")
        lines.append(f"# Generated: {__import__('datetime').datetime.now().isoformat()}")
        lines.append("")
        if status["qemu"]["found"]:
            lines.append(f"WOSP_QEMU={status['qemu']['path']}")
        lines.append("")
        with open(env_path, 'w') as f:
            f.write('\n'.join(lines))
        return str(env_path)


if __name__ == "__main__":
    resolver = ToolchainResolver()
    status = resolver.get_status()
    print(json.dumps(status, indent=2))
