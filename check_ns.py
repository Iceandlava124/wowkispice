with open('C:\\Users\\gudae\\Music\\PROJECT_WOWKISPICE\\bridge\\ngspice_wrapper.py', 'r') as f:
    content = f.read()
# Check if singleton pattern exists
if '_instance' in content and '_init_done' in content:
    print('Singleton pattern FOUND')
else:
    print('Singleton pattern NOT FOUND')
print(f'Total lines: {len(content.splitlines())}')
