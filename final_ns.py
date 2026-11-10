with open('C:\\Users\\gudae\\Music\\PROJECT_WOWKISPICE\\bridge\\ngspice_wrapper.py', 'r') as f:
    current = f.read()

with open('C:\\Users\\gudae\\Music\\PROJECT_WOWKISPICE\\append_methods.py', 'r') as f:
    append_raw = f.read()

# Strip the append_code = ''' wrapper
if append_raw.startswith("append_code = '''"):
    append_content = append_raw[len("append_code = '''"):]
    if append_content.endswith("'''"):
        append_content = append_content[:-3]
else:
    append_content = append_raw

combined = current.rstrip() + '\n' + append_content

with open('C:\\Users\\gudae\\Music\\PROJECT_WOWKISPICE\\bridge\\ngspice_wrapper.py', 'w') as f:
    f.write(combined)

lines = combined.splitlines()
print(f'Total lines: {len(lines)}')
print(f'Last line: {repr(lines[-1]) if lines else "EMPTY"}')
