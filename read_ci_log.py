import sys

with open('/tmp/ci_fail4.log', 'rb') as f:
    raw = f.read()
try:
    content = raw.decode('utf-16-le')
except:
    content = raw.decode('utf-8', errors='replace')
lines = content.split('\n')
for line in lines:
    if line.strip():
        print(line[:200])
