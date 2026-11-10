with open('ci_fail_log.txt', 'rb') as f:
    raw = f.read()
try:
    content = raw.decode('utf-16-le')
except:
    try:
        content = raw.decode('utf-8', errors='replace')
    except:
        content = str(raw)
print(content[:5000])
