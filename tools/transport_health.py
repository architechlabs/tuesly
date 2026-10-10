"""Bounded, credential-free proxy scan diagnostic; no GATT writes."""
import asyncio
import json
import time
import yaml
from aioesphomeapi import APIClient
from aioesphomeapi.model import BluetoothScannerMode
from inspect_mesh import ROOT, MAC, PRIVATE


async def main():
    secrets = yaml.safe_load((ROOT.parent / 'mopeka/firmware-esp32/secrets.yaml').read_text())
    api = APIClient('192.168.20.181', 6053, noise_psk=secrets['tuya_api_encryption_key'],
                    client_info='tuesly-transport-health')
    report = {'stage': 'connecting', 'advertisement_count': 0, 'target_count': 0,
              'scanner_states': [], 'slots': [], 'mesh_candidates': {}}
    cancellations = []
    target = int(MAC.replace(':', ''), 16)
    try:
        started = time.monotonic()
        await asyncio.wait_for(api.connect(login=True), 12)
        report['connect_seconds'] = round(time.monotonic() - started, 2)
        report['stage'] = 'device_info'
        info = await asyncio.wait_for(api.device_info(), 8)
        report['firmware'] = info.esphome_version
        report['stage'] = 'scanning'
        cancellations.append(api.subscribe_bluetooth_scanner_state(
            lambda state: report['scanner_states'].append({'mode': state.mode.name, 'state': state.state.name})))
        cancellations.append(api.subscribe_bluetooth_connections_free(
            lambda free, limit, allocated: report['slots'].append({'free': free, 'limit': limit, 'allocated_count': len(allocated)})))
        def heard(message):
            for adv in message.advertisements:
                report['advertisement_count'] += 1
                raw = bytes(adv.data)
                if b'\x27\x18' in raw or bytes.fromhex(MAC.replace(':', '')) in raw:
                    candidate = report['mesh_candidates'].setdefault(f'{adv.address:012X}', {})
                    candidate.update(rssi=adv.rssi, address_type=adv.address_type,
                                     contains_target_identity=bytes.fromhex(MAC.replace(':', '')) in raw)
                if adv.address != target:
                    continue
                report['target_count'] += 1
                report['target_rssi'] = adv.rssi
                (PRIVATE / 'latest-advertisement.hex').write_text(raw.hex())
                fields = []
                offset = 0
                while offset < len(raw):
                    size = raw[offset]
                    if not size or offset + size + 1 > len(raw):
                        break
                    value = raw[offset + 2:offset + size + 1]
                    fields.append({'type': raw[offset + 1], 'length': len(value),
                                   'service_1827': value[:2] == b'\x27\x18',
                                   'service_1828': value[:2] == b'\x28\x18'})
                    offset += size + 1
                report['target_fields'] = fields
        cancellations.append(api.subscribe_bluetooth_le_raw_advertisements(heard))
        api.bluetooth_scanner_set_mode(BluetoothScannerMode.ACTIVE)
        await asyncio.sleep(25)
        report['stage'] = 'completed'
    except Exception as exc:
        report['failure_type'] = type(exc).__name__
    finally:
        for cancel in reversed(cancellations):
            cancel()
        await api.disconnect(force=True)
    (ROOT / 'reports/transport-health.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
