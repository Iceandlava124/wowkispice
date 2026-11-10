with open('C:\\Users\\gudae\\Music\\PROJECT_WOWKISPICE\\bridge\\ngspice_wrapper.py', 'r') as f:
    current = f.read()
with open('C:\\Users\\gudae\\Music\\PROJECT_WOWKISPICE\\append_methods.py', 'r') as f:
    append = f.read()
combined = current + append
with open('C:\\Users\\gudae\\Music\\PROJECT_WOWKISPICE\\bridge\\ngspice_wrapper.py', 'w') as f:
    f.write(combined)
lines = combined.splitlines()
print(f'Total lines: {len(lines)}')
print(f'Last line: {repr(lines[-1]) if lines else "EMPTY"}')
