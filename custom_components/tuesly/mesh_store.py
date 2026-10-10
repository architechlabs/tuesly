"""HA-owned mesh journal. Save reservations before handing credentials to a node."""
from __future__ import annotations
import asyncio
import copy
import secrets


class MeshJournal:
    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()
        self.state = None
        self.next_seq = self.seq_end = 0

    async def load(self):
        async with self.lock:
            if self.state is None:
                self.state = await self.store.async_load()
                if self.state is None:
                    self.state = dict(net_key=secrets.token_hex(16), app_key=secrets.token_hex(16),
                                      iv_index=0, address_next=2, sequence_high=0, nodes={})
                    await self.store.async_save(copy.deepcopy(self.state))
                # Discard the old process's unused sequence lease after restart.
                self.next_seq = self.seq_end = self.state['sequence_high']
        return self

    async def allocate_sequences(self, count=1):
        if not 1 <= count <= 32:
            raise ValueError('Invalid sequence reservation')
        async with self.lock:
            if self.next_seq + count > self.seq_end:
                start = self.state['sequence_high']
                end = start + max(256, count)
                if end > 0x1000000:
                    raise RuntimeError('Mesh sequence space exhausted; IV Update is required')
                candidate = copy.deepcopy(self.state)
                candidate['sequence_high'] = end
                await self.store.async_save(candidate)
                self.state = candidate
                self.next_seq, self.seq_end = start, end
            result = self.next_seq
            self.next_seq += count
            return result

    async def reserve(self, mac, *, replace=False):
        async with self.lock:
            if mac in self.state['nodes'] and not replace:
                return copy.deepcopy(self.state['nodes'][mac])
            # PB-GATT capabilities allow up to 255 elements. Never reuse a range,
            # including failed reservations whose provisioning outcome is uncertain.
            address = self.state['address_next']
            if address + 254 > 0x7fff:
                raise RuntimeError('Mesh address space exhausted')
            candidate = copy.deepcopy(self.state)
            if mac in candidate['nodes']:
                candidate.setdefault('retired_nodes', []).append(
                    {'address': mac, 'record': candidate['nodes'][mac]})
            candidate['address_next'] = address + 255
            candidate['nodes'][mac] = dict(address=address, status='reserved')
            await self.store.async_save(candidate)
            self.state = candidate
            return copy.deepcopy(candidate['nodes'][mac])

    async def restore_node(self, mac, record):
        """Restore prior credentials after failure before Provisioning Data.

        Keep the new address reservation consumed because its outcome may be
        uncertain. Callers must never use this after handing over new keys.
        """
        async with self.lock:
            candidate = copy.deepcopy(self.state)
            candidate['nodes'][mac] = copy.deepcopy(record)
            await self.store.async_save(candidate)
            self.state = candidate

    async def update(self, mac, **fields):
        async with self.lock:
            candidate = copy.deepcopy(self.state)
            candidate['nodes'][mac].update(fields)
            await self.store.async_save(candidate)
            self.state = candidate

    async def accept_received(self, mac, source, sequence):
        """Persist a bounded replay window before delivering an authenticated packet."""
        async with self.lock:
            node = self.state['nodes'][mac]
            if not node['address'] <= source < node['address'] + node['elements']:
                return False
            previous = node.get('received', {}).get(str(source), [-1, 0])
            high, bitmap = previous
            if sequence > high:
                shift = sequence - high
                bitmap = 1 if shift >= 64 else ((bitmap << shift) | 1) & ((1 << 64)-1)
                high = sequence
            else:
                distance = high - sequence
                if distance >= 64 or bitmap & (1 << distance):
                    return False
                bitmap |= 1 << distance
            candidate = copy.deepcopy(self.state)
            candidate['nodes'][mac].setdefault('received', {})[str(source)] = [high, bitmap]
            await self.store.async_save(candidate)
            self.state = candidate
            return True


async def get_journal(hass):
    from homeassistant.helpers.storage import Store
    bucket = hass.data.setdefault('tuesly_mesh_controller', {})
    journal = bucket.setdefault('journal', MeshJournal(Store(hass, 1, 'tuesly.mesh')))
    return await journal.load()
