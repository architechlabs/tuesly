import asyncio
import unittest
from test_transport import load_ha_module


class RadioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.radio = load_ha_module('custom_components.tuesly.radio', 'radio.py').RadioScheduler()

    async def test_controls_precede_queued_polls_with_fifo_within_priority(self):
        events = []
        await self.radio.acquire()
        async def job(name, priority):
            async with self.radio.priority(priority):
                events.append(name)
                await asyncio.sleep(0)
        tasks = [asyncio.create_task(job(name, priority)) for name, priority in
                 [('poll', 2), ('control1', 0), ('control2', 0)]]
        await asyncio.sleep(0)
        self.radio.release()
        await asyncio.gather(*tasks)
        self.assertEqual(events, ['control1', 'control2', 'poll'])
        self.assertFalse(self.radio.locked())

    async def test_cancelled_waiter_cannot_leak_radio(self):
        await self.radio.acquire()
        waiter = asyncio.create_task(self.radio.acquire())
        await asyncio.sleep(0)
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        self.radio.release()
        async with asyncio.timeout(.5):
            async with self.radio:
                self.assertTrue(self.radio.locked())
        self.assertFalse(self.radio.locked())

    async def test_cancellation_after_handoff_releases_granted_radio(self):
        await self.radio.acquire()
        waiter = asyncio.create_task(self.radio.acquire())
        await asyncio.sleep(0)
        self.radio.release()
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        async with asyncio.timeout(.5):
            async with self.radio:
                pass
        self.assertFalse(self.radio.locked())
