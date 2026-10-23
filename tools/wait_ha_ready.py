"""Wait for the authorized HA restart without repeatedly restarting it."""
import time
from ha_recovery import rest
deadline=time.monotonic()+240
while time.monotonic()<deadline:
    try:
        rest('/api/',timeout=5)
        print('Home Assistant API ready',flush=True)
        break
    except Exception as exc:
        print('Waiting for HA:',type(exc).__name__,flush=True)
        time.sleep(5)
else:
    raise RuntimeError('HA did not become ready within 240 seconds')
