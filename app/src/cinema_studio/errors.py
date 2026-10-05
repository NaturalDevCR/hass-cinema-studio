"""Domain errors raised by the Studio core; the HTTP layer maps them to status codes."""

from __future__ import annotations


class StudioError(Exception):
    """Base class for every error the Studio raises on purpose."""


class NotFoundError(StudioError):
    """The requested entity does not exist."""


class ConflictError(StudioError):
    """The change clashes with existing data (duplicate id, entity still in use)."""


class InvalidError(StudioError):
    """The input is well-formed but not acceptable."""
