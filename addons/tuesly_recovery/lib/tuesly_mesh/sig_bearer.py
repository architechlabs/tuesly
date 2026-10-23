"""Bounded Proxy SAR framing for the GATT bearer."""
import time


def frames(pdu, mtu=23):
    if not pdu or pdu[0] & 0xc0 or mtu < 23:
        raise ValueError('Invalid complete Proxy PDU or MTU')
    kind, payload = pdu[0], pdu[1:]
    size = mtu - 4
    chunks = [payload[i:i+size] for i in range(0, len(payload), size)] or [b'']
    return [bytes([kind | (0 if len(chunks) == 1 else 0x40 if i == 0 else
                            0xc0 if i == len(chunks)-1 else 0x80)]) + chunk
            for i, chunk in enumerate(chunks)]


class Reassembler:
    def __init__(self):
        self.reset()

    def reset(self):
        self.kind = None
        self.buffer = b''
        self.deadline = 0

    def feed(self, data):
        if not data:
            return None
        sar, kind = data[0] >> 6, data[0] & 0x3f
        if sar == 0:
            self.reset()
            return bytes(data)
        if sar == 1:
            self.kind, self.buffer, self.deadline = kind, bytes(data[1:]), time.monotonic()+20
            return None
        if self.kind != kind or time.monotonic() > self.deadline or len(self.buffer)+len(data)-1 > 384:
            self.reset()
            return None
        self.buffer += bytes(data[1:])
        if sar == 3:
            result = bytes([kind]) + self.buffer
            self.reset()
            return result
        return None
