import sys
from winpty import PtyProcess

try:
    proc = PtyProcess.spawn("powershell.exe")
    data = proc.read(1024)
    print(f"Data type: {type(data)}")
    print(f"Data: {data[:100]}")
    proc.close(force=True)
except Exception as e:
    print(f"Error: {e}")
