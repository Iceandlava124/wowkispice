with open('C:\\Users\\gudae\\Music\\PROJECT_WOWKISPICE\\bridge\\ngspice_wrapper.py', 'r') as f:
    content = f.read()
print(f'Total lines: {len(content.splitlines())}')
# Check key patterns
for pattern in ['_init_done', '_instance', '_init_lock', 'reset()', '_stop_requested']:
    if pattern in content:
        print(f'Found: {pattern}')
    else:
        print(f'NOT FOUND: {pattern}')
