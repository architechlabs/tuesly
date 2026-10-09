"""Recognize Tuya standard-light UUIDs without inspecting fixture labels."""
def light_profile(address: str,provisioning_data: bytes):
    if len(provisioning_data)<18:
        return None
    try:
        mac=bytes.fromhex(address.replace(':',''))
    except ValueError:
        return None
    uuid=provisioning_data[:16]
    if len(mac)!=6 or uuid[:6]!=mac:
        return None
    category=int.from_bytes(uuid[6:8],'big')
    kind=category&15
    if category&0x3000!=0x1000 or category&0x00f0!=0x10 or kind not in (1,2,3,4,5):
        return None
    return {'product_type':kind,'tunable_white':kind in (2,5),'product_id':uuid[8:16].decode('ascii',errors='replace')}
