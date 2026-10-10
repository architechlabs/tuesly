"""Bound radio work so user controls precede routine state polling."""
import asyncio
import heapq
import itertools
from contextlib import asynccontextmanager

class RadioScheduler:
    def __init__(self):
        self._waiting=[]
        self._order=itertools.count()
        self._held=False

    def _wake_next(self):
        if self._held:
            return
        while self._waiting:
            _,_,future=heapq.heappop(self._waiting)
            if future.cancelled():
                continue
            self._held=True
            future.set_result(None)
            return

    async def _acquire(self,priority):
        future=asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiting,(priority,next(self._order),future))
        self._wake_next()
        try:
            await future
        except BaseException:
            if future.done() and not future.cancelled():
                self._release()
            else:
                future.cancel()
            raise

    def _release(self):
        self._held=False
        self._wake_next()

    async def __aenter__(self):
        await self._acquire(0)
        return self

    async def acquire(self):
        await self._acquire(0)
        return True

    def release(self):
        self._release()

    def locked(self):
        return self._held

    async def __aexit__(self,*args):
        self._release()

    @asynccontextmanager
    async def priority(self,value):
        await self._acquire(value)
        try:
            yield
        finally:
            self._release()

def get_radio(hass):
    return hass.data.setdefault('tuesly_mesh_controller',{}).setdefault('radio_lock',RadioScheduler())
