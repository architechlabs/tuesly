"""Tuya documented compact DP 33 power-off memory messages.

https://developer.tuya.com/en/docs/iot-device-dev/tuya-sigmesh-device-vendor-model-access-standard?id=K9pikwhoo3gux
Fixed-size DP types omit the length byte; raw/string/bitmap include it.
"""
READ_MEMORY=bytes.fromhex('ccd007010121')
READ_POWER_POLICY=bytes.fromhex('ccd00701022122')
DATA_OPCODE=0xCDD007

def power_dps(params):
    """Decode compact DPs, validating the documented DP33/34 layouts."""
    if not params or params[0]!=1:
        return {}
    offset=1;found={}
    while offset<len(params):
        if offset+2>len(params):return {}
        dp,kind=params[offset:offset+2];offset+=2
        if kind in (1,4):size=1
        elif kind==2:size=4
        elif kind in (0,3,5):
            if offset>=len(params):return {}
            size=params[offset];offset+=1
        else:return {}
        if offset+size>len(params):return {}
        value=params[offset:offset+size];offset+=size
        if dp==33:
            # Raw v0: version, mode, H/S/V/brightness/temperature (five u16s).
            if kind!=0 or len(value)!=12 or value[0]!=0 or value[1] not in (0,1,2):return {}
            if dp in found:return {}
            found[dp]=(kind,value)
        elif dp==34:
            if kind!=1 or value not in (b'\x00',b'\x01') or dp in found:return {}
            found[dp]=(kind,value)
    return found

def memory_dp(params):
    return power_dps(params).get(33)

def memory_mode(value):
    if len(value)!=12 or value[0]!=0:
        raise ValueError('Unsupported DP33 version or length')
    return value[1]

def write_memory(kind,value,mode):
    if kind!=0 or len(value)!=12 or value[0]!=0 or mode not in (0,1):
        raise ValueError('Unsupported memory payload')
    # Preserve the version and all five custom lighting values.
    updated=value[:1]+bytes([mode])+value[2:]
    payload=bytes.fromhex('c9d00701')+bytes([33,kind])
    if kind==0:payload+=bytes([len(updated)])
    return payload+updated,updated

def write_power_policy(value,restore):
    payload,updated=write_memory(0,value,1 if restore else 0)
    dnd=b'\x01' if restore else b'\x00'
    return payload+bytes([34,1])+dnd,{33:(0,updated),34:(1,dnd)}
