with open('C:\\Users\\gudae\\Music\\PROJECT_WOWKISPICE\\bridge\\ngspice_wrapper.py', 'r') as f:
    current = f.read()

# Find where the append_code marker was
idx = current.find('append_code = ')
if idx >= 0:
    clean = current[:idx]
    clean = clean.rstrip() + '\n'
    with open('C:\\Users\\gudae\\Music\\PROJECT_WOWKISPICE\\bridge\\ngspice_wrapper.py', 'w') as f:
        f.write(clean)
    lines = clean.splitlines()
    print('Lines:', len(lines))
    last = lines[-1] if lines else 'EMPTY'
    print('Last line:', repr(last))
else:
    print('Could not find append_code marker')
    print('Current length:', len(current))
