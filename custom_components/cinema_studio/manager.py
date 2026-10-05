"""Temporary manager boundary until selection management is implemented."""

from collections.abc import Awaitable, Callable
from typing import Any

from .catalog import Catalog


class CinemaStudioManager:
    """Minimal lifecycle placeholder for snapshot adoption."""

    async def async_setup(self) -> None:
        """Set up manager state."""

    async def async_install_snapshot(
        self,
        catalog: Catalog,
        raw: dict[str, Any],
        persist: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Persist a validated catalog snapshot before it becomes coordinator data."""
        await persist(raw)
