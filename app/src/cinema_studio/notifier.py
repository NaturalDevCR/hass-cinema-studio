"""Thread-safe debouncing of repository catalog revisions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

_LOGGER = logging.getLogger(__name__)


class CatalogNotifier:
    """Construct on the owning event loop, then use mark_changed from any thread."""

    def __init__(self, send: Callable[[int], Awaitable[None]], delay: float = 1.0) -> None:
        self._send = send
        self._delay = delay
        self._loop = asyncio.get_running_loop()
        self._changed = asyncio.Event()
        self._latest: int | None = None
        self._pending: int | None = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    def mark_changed(self, revision: int) -> None:
        if self._closed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is self._loop:
            self._mark_changed(revision)
        else:
            self._loop.call_soon_threadsafe(self._mark_changed, revision)

    def _mark_changed(self, revision: int) -> None:
        if self._closed or (self._latest is not None and revision <= self._latest):
            return
        # Repository callbacks from different threads can arrive out of commit order.
        self._latest = self._pending = revision
        self._changed.set()
        if self._task is None or self._task.done():
            self._task = self._loop.create_task(self._run(), name="catalog-notifier")

    async def _run(self) -> None:
        while self._pending is not None:
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=self._delay)
            except TimeoutError:
                revision = self._pending
                self._pending = None
                try:
                    await self._send(revision)
                except Exception:
                    _LOGGER.exception("Could not notify catalog revision %s", revision)

    async def flush(self) -> None:
        """Wait for queued thread callbacks, the debounce, and any pending send."""
        await asyncio.sleep(0)
        while self._task is not None and not self._task.done():
            await asyncio.shield(self._task)

    async def close(self) -> None:
        self._closed = True
        self._pending = None
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
