"""Signal the running observer only after the user's physical cycle reply."""
import json,time
from ha_recovery import PRIVATE
path=PRIVATE/'driver-cycle-confirmation.json'
state=json.loads(path.read_text())
if time.time()-state['armed_at']>600:
    raise RuntimeError('Cycle observer has expired')
state.update(confirmed=True,confirmed_at=time.time())
path.write_text(json.dumps(state))
print('Physical cycle confirmation delivered to observer')
