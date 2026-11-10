import os

with open('ci_fail_log.txt', 'rb') as f:
    raw = f.read()

try:
    content = raw.decode('utf-16-le')
except:
    content = raw.decode('utf-8', errors='replace')

lines = content.split('\n')
out_lines = []
for line in lines:
    clean = line.replace('\x1b', '').replace('\x00', '').replace('\ufeff', '')
    if clean.strip():
        out_lines.append(clean[:300])

with open('ci_fail_clean.txt', 'w', encoding='utf-8') as f:
    for line in out_lines:
        f.write(line + '\n')

print('Written %d lines to ci_fail_clean.txt' % len(out_lines))
