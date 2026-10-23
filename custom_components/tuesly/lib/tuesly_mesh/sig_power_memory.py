"""Tuya documented compact DP 33 power-off memory messages.

https://developer.tuya.com/en/docs/iot-device-dev/tuya-sigmesh-device-vendor-model-access-standard?id=K9pikwhoo3gux
Fixed-size DP types omit the length byte; raw/string/bitmap include it.
"""
READ_MEMORY=bytes.fromhex('ccd007010121')
DATA_OPCODE=0xCDD007

def memory_dp(params):
    """Return a fully validated (type, value) for DP 33, or None."""
    if not params or params[0]!=1:
        return None
    offset=1;found=None
    while offset<len(params):
        if offset+2>len(params):return None
        dp,kind=params[offset:offset+2];offset+=2
        if kind in (1,4):size=1
        elif kind==2:size=4
        elif kind in (0,3,5):
            if offset>=len(params):return None
            size=params[offset];offset+=1
        else:return None
        if offset+size>len(params):return None
        value=params[offset:offset+size];offset+=size
        if dp==33:
            if kind not in (0,4) or not value or value[0] not in (0,1,2):return None
            found=(kind,value)
    return found

def write_memory(kind,value,mode):
    if kind not in (0,4) or not value or mode not in (0,1):
        raise ValueError('Unsupported memory payload')
    # Preserve any device-defined custom-state bytes in a raw DP.
    updated=bytes([mode])+value[1:]
    payload=bytes.fromhex('c9d00701')+bytes([33,kind])
    if kind==0:payload+=bytes([len(updated)])
    return payload+updated,updated
