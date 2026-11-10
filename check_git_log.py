import subprocess
result = subprocess.run(['git', 'log', '--oneline', '--', 'bridge/ngspice_wrapper.py'], capture_output=True, text=True)
print(result.stdout)
