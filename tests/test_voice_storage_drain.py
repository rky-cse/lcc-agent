import asyncio
import threading
import unittest
from library_claim.live_voice import storage_call

class StorageDrainTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_waits_for_storage_thread_to_release_resources(self):
        entered=threading.Event();release=threading.Event();closed=threading.Event()
        def work():
            try:
                entered.set();release.wait(timeout=5)
            finally:closed.set()
        task=asyncio.create_task(storage_call(work))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait,2))
            task.cancel();await asyncio.sleep(0)
            self.assertFalse(task.done());self.assertFalse(closed.is_set())
        finally:
            release.set()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(closed.is_set())
