"""Report what Espressif's QEMU prebuilt package costs, per platform.

Reads ESP-IDF's tools.json. Platform-independent: we want to see every
platform's entry so we can pick the linux-amd64 one for WSL2.
"""
import json
import sys

TOOLS = r"C:\Users\gudae\.platformio\packages\framework-espidf\tools\tools.json"

with open(TOOLS, encoding="utf-8") as f:
    data = json.load(f)

print("tools.json version:", data.get("tools_version"))
print("total tools:", len(data["tools"]))
print()

qemu = [t for t in data["tools"] if "qemu" in t["name"].lower()]
print("qemu-related tools:", [t["name"] for t in qemu])
print()

for tool in qemu:
    print("=" * 70)
    print("name        :", tool["name"])
    print("version     :", tool.get("version"))
    print("description :", tool.get("description", "")[:100])
    print()
    for name, plats in tool.get("installs", []):
        for p in plats:
            url = p.get("url", "")
            print("  platform  :", name)
            print("    url     :", url)
            if "size" in p:
                print("    size    : %s (%.1f MB)" % (p["size"], p["size"] / 1048576))
            if "sha256" in p:
                print("    sha256  :", p["sha256"][:32], "...")
            print()
    if "size" in tool:
        print("  tool 'size' hint:", tool["size"])
    print()