with open('ci_fail_log.txt', 'rb') as f:
    raw = f.read()
# Try UTF-16 LE first (common for GitHub Actions logs)
try:
    content = raw.decode('utf-16-le')
except:
    try:
        content = raw.decode('utf-8', errors='replace')
    except:
        content = str(raw)

# Print only relevant lines (skip ANSI escape codes and binary garbage)
import re
lines = content.split('\n')
for line in lines:
    # Remove ANSI escape codes
    clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', clean)
    clean = clean.replace('\x1b', '').replace('\x00', '')
    if clean.strip():
        print(clean[:300])
