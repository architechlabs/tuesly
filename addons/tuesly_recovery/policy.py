"""Conservative radio evidence and per-device recovery limits."""
import ast,time

def unprovisioned_uuid(raw):
    offset=0
    while offset<len(raw):
        length=raw[offset]
        if not length or offset+length+1>len(raw):return None
        kind=raw[offset+1];payload=raw[offset+2:offset+length+1]
        if kind==0x16 and payload[:2]==b'\x27\x18' and len(payload)>=20:
            return payload[2:18].hex()
        if kind==0x2B and payload[:1]==b'\x00' and len(payload)>=19:
            return payload[1:17].hex()
        offset+=length+1
    return None

def radio_evidence(scanner,device):
    seen=scanner.get('discovered_device_timestamps',{}).get(device['address'])
    if seen is None or not 0<=scanner['monotonic_time']-seen<=10:return None
    encoded=scanner.get('raw_advertisement_data',{}).get(device['address'])
    if not isinstance(encoded,dict):return None
    try:raw=ast.literal_eval(encoded['repr'])
    except (ValueError,SyntaxError,KeyError):return None
    if not isinstance(raw,bytes) or unprovisioned_uuid(raw)!=device['uuid'].lower():return None
    return seen

def permitted(record,now=None,*,startup=False):
    now=time.time() if now is None else now
    # Successful recoveries must not lock out subsequent power cycles. Failed
    # operations use bounded backoff; address exhaustion is checked separately.
    if startup and now-record.get('last_failure',{}).get('at',0)>=15:return True
    return now>=record.get('retry_after',0)

def remember_startup(pending,scanner,device,now=None):
    """Keep exact fresh radio proof across HA's bounded availability delay."""
    now=time.monotonic() if now is None else now
    mac=device['address']
    seen=radio_evidence(scanner,device)
    prior=pending.get(mac)
    if seen is not None and (prior is None or prior['seen']!=seen):
        pending[mac]={'seen':seen,'expires':now+120}
    candidate=pending.get(mac)
    if candidate and now<candidate['expires']:return True
    pending.pop(mac,None)
    return False

def observe_live_event(event,devices,pending,proxies,*,now=None,monotonic=None):
    """Process actual HA websocket packets, never aggregated service data."""
    now=time.time() if now is None else now
    monotonic=time.monotonic() if monotonic is None else monotonic
    device=next((d for d in devices if d['address']==event.get('address','').upper()),None)
    if device is None:return False
    try:
        if not 0<=now-float(event['time'])<=10:return False
        raw=bytes.fromhex(event['raw'])
    except (KeyError,ValueError,TypeError):return False
    if unprovisioned_uuid(raw)==device['uuid'].lower():
        pending[device['address']]={'seen':event['time'],'expires':monotonic+120}
        return True
    offset=0
    while offset<len(raw):
        length=raw[offset]
        if not length or offset+length+1>len(raw):break
        payload=raw[offset+2:offset+length+1]
        if (raw[offset+1]==0x16 and payload[:2]==b'\x28\x18'
                and ((len(payload)==11 and payload[2]==0) or (len(payload)==19 and payload[2]==1))
                and event.get('connectable')):
            proxies[device['address']]=monotonic
            return True
        offset+=length+1
    return False
