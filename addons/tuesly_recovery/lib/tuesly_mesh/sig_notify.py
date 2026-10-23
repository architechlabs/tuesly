"""Notification lifecycle compatible with Bleak 3 and HA's ESPHome backend."""
CCCD_UUID='00002902-0000-1000-8000-00805f9b34fb'

async def enable_notifications(client,characteristic,callback):
    # The ESPHome active backend writes CCCD through its API during this call.
    # Bleak 3 rejects high-level direct CCCD writes, on every platform.
    await client.start_notify(characteristic,callback)

async def disable_notifications(client,characteristic):
    backend=getattr(client,'_backend',None)
    delegate=getattr(backend,'_backend',backend)
    esphome=any(item is not None and type(item).__module__.startswith('bleak_esphome')
                for item in (backend,delegate))
    try:
        # Native backends manage CCCD in stop_notify. ESPHome unregisters only
        # locally: clear the peer through its backend API before PB handoff.
        # The facade's backend attribute is used only at this compatibility edge.
        if backend is None or esphome:
            descriptor=next((item for item in getattr(characteristic,'descriptors',())
                if isinstance(item.uuid,str) and item.uuid.lower()==CCCD_UUID),None)
            if descriptor is not None:
                if backend is None:
                    await client.write_gatt_descriptor(descriptor.handle,b'\x00\x00')
                else:
                    await backend.write_gatt_descriptor(descriptor,b'\x00\x00')
    finally:
        await client.stop_notify(characteristic)
