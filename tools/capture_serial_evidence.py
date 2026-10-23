"""Read bench USB logs without commanding a reset; opening CH340 may affect DTR."""
import json,time
import serial
from serial.tools import list_ports
from ha_recovery import ROOT
ports=list(list_ports.comports())
print('Serial ports:',[p.device for p in ports],flush=True)
port=serial.Serial(port=None,baudrate=115200,timeout=.2)
port.dtr=False;port.rts=False;port.port='COM8';port.open()
lines=[];buffer='';deadline=time.monotonic()+30
try:
    while time.monotonic()<deadline:
        buffer+=port.read(4096).decode(errors='replace')
        while '\n' in buffer:
            line,buffer=buffer.split('\n',1)
            if any(key in line.lower() for key in ('password','encryption','ssid','bssid')):continue
            lines.append(line)
            if any(key in line.lower() for key in ('error','warn','rst:','boot:','watchdog','panic','scan','connect','disconn','target','heap','uptime')):
                print(line,flush=True)
finally:
    port.close()
    (ROOT/'reports/usb-stall-evidence.log').write_text('\n'.join(lines),encoding='utf-8')
