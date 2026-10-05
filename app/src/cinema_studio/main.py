"""Container entry point: ``python -m cinema_studio.main``."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import uvicorn

from .app import create_app
from .config import Paths, load_options
from .lifecycle import APP_PORT
from .supervisor import SupervisorClient

OPTIONS_PATH = Path("/data/options.json")

# Supervisor log levels that uvicorn and logging do not know by name.
_LEVEL_ALIASES = {"trace": "debug", "notice": "info", "fatal": "critical"}
_LEVELS = {"critical", "error", "warning", "info", "debug"}


def resolve_log_level(options: dict[str, object]) -> str:
    """Map the add-on ``log_level`` option to a level name both uvicorn and logging accept."""
    level = str(options.get("log_level", "info")).strip().lower()
    level = _LEVEL_ALIASES.get(level, level)
    return level if level in _LEVELS else "info"


def uvicorn_options(log_level: str) -> dict[str, Any]:
    """Server settings. Forwarded headers are ignored: ``require_ingress`` trusts only the peer
    address, so a client must not be able to rewrite it with ``X-Forwarded-For``."""
    return {
        "host": "0.0.0.0",
        "port": APP_PORT,
        "log_level": log_level,
        "proxy_headers": False,
        "forwarded_allow_ips": "",
    }


def main() -> None:
    log_level = resolve_log_level(load_options(OPTIONS_PATH))
    logging.basicConfig(
        level=log_level.upper(), format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    # httpx logs every request at INFO, which would echo each Supervisor call.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = create_app(
        Paths.from_env(), supervisor=SupervisorClient(os.environ.get("SUPERVISOR_TOKEN"))
    )
    uvicorn.run(app, **uvicorn_options(log_level))


if __name__ == "__main__":
    main()
