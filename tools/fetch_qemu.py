"""
fetch_qemu.py - Download prebuilt patched QEMU for WOSP
"""
import os
import sys
import json
import hashlib
import platform
import zipfile
import tarfile
from pathlib import Path
from urllib.request import urlopen, urlretrieve
from urllib.error import URLError


REPO_ROOT = Path(__file__).parent.parent
THIRD_PARTY = REPO_ROOT / "third_party"
QEMU_DIR = THIRD_PARTY / "qemu"
MANIFEST_PATH = THIRD_PARTY / "manifest.json"


# Default release URL - can be overridden via env or manifest
DEFAULT_RELEASE_URL = os.environ.get("WOSP_QEMU_RELEASE_URL", "")


def get_platform_info():
    """Get platform and architecture info"""
    system = platform.system().lower()  # windows, linux, darwin
    machine = platform.machine().lower()
    
    if system == "windows":
        plat = "windows"
        ext = "zip"
    elif system == "linux":
        plat = "linux"
        ext = "tar.gz"
    elif system == "darwin":
        plat = "macos"
        ext = "tar.gz"
    else:
        plat = system
        ext = "tar.gz"
    
    return plat, machine, ext


def sha256_file(filepath):
    """Calculate SHA256 of file"""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def load_manifest():
    """Load or create manifest"""
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, 'r') as f:
            return json.load(f)
    return {"qemu": {}}


def save_manifest(manifest):
    """Save manifest"""
    THIRD_PARTY.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, 'w') as f:
        json.dump(manifest, indent=2, fp=f)


def fetch_qemu(force=False):
    """Fetch prebuilt patched QEMU"""
    print("WOSP QEMU Fetcher")
    print("=" * 60)
    
    plat, machine, ext = get_platform_info()
    print(f"Platform: {plat} ({machine})")
    
    # Check if already exists
    if not force:
        QEMU_DIR.mkdir(parents=True, exist_ok=True)
        for name in ["qemu-system-xtensa", "qemu-system-xtensa.exe"]:
            for root, dirs, files in os.walk(QEMU_DIR):
                if name in files:
                    print(f"✓ QEMU already exists: {os.path.join(root, name)}")
                    return True
    
    manifest = load_manifest()
    release_url = DEFAULT_RELEASE_URL or manifest.get("qemu", {}).get("release_url", "")
    
    if not release_url:
        print("\n⚠ No release URL configured")
        print("To use prebuilt QEMU, set WOSP_QEMU_RELEASE_URL or add to third_party/manifest.json")
        print("\nAlternatively, build from source using tools/build_qemu.sh")
        print("Or place a prebuilt qemu-system-xtensa in third_party/qemu/")
        return False
    
    print(f"\nFetching from: {release_url}")
    
    THIRD_PARTY.mkdir(parents=True, exist_ok=True)
    QEMU_DIR.mkdir(parents=True, exist_ok=True)
    
    download_path = THIRD_PARTY / f"qemu-patched.{ext}"
    
    try:
        print("Downloading...")
        urlretrieve(release_url, download_path)
        print(f"Downloaded to {download_path}")
        
        # Verify checksum if in manifest
        expected_hash = manifest.get("qemu", {}).get("sha256")
        if expected_hash:
            print("Verifying checksum...")
            actual_hash = sha256_file(download_path)
            if actual_hash != expected_hash:
                print(f"✗ Checksum mismatch!")
                print(f"  Expected: {expected_hash}")
                print(f"  Got: {actual_hash}")
                download_path.unlink()
                return False
            print("✓ Checksum verified")
        
        # Extract
        print("Extracting...")
        if ext == "zip":
            with zipfile.ZipFile(download_path, 'r') as zf:
                zf.extractall(QEMU_DIR)
        elif ext == "tar.gz":
            with tarfile.open(download_path, 'r:gz') as tf:
                tf.extractall(QEMU_DIR)
        
        download_path.unlink()
        print("✓ Extracted successfully")
        
        # Make executable on Unix
        if plat != "windows":
            for root, dirs, files in os.walk(QEMU_DIR):
                for name in files:
                    if name == "qemu-system-xtensa":
                        p = os.path.join(root, name)
                        os.chmod(p, 0o755)
        
        # Update manifest
        manifest.setdefault("qemu", {})["downloaded"] = True
        manifest["qemu"]["platform"] = plat
        save_manifest(manifest)
        
        print("\n✓ QEMU ready!")
        return True
        
    except URLError as e:
        print(f"✗ Download failed: {e}")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fetch prebuilt patched QEMU")
    parser.add_argument("--force", action="store_true", help="Force re-download")
    args = parser.parse_args()
    
    success = fetch_qemu(force=args.force)
    sys.exit(0 if success else 1)
