"""API token storage and the request guards for the integration API and the Ingress UI."""

from __future__ import annotations

import hmac
import os
import secrets
import threading
from pathlib import Path

from fastapi import HTTPException, Request

from .config import Paths

INGRESS_PEER = "172.30.32.2"


class TokenStore:
    """The integration API token, persisted in a file only the App's user can read."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        token = self._read()
        if token:
            # Tighten files that were created before the 0600 guarantee.
            path.chmod(0o600)
        else:
            token = self._generate()
        self._token = token

    def get(self) -> str:
        with self._lock:
            return self._token

    def rotate(self) -> str:
        with self._lock:
            self._token = self._generate()
            return self._token

    def masked(self) -> str:
        """The token with its middle hidden, for display: ``abcd…wxyz``."""
        token = self.get()
        return f"{token[:4]}…{token[-4:]}"

    def _read(self) -> str:
        try:
            return self._path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""

    def _generate(self) -> str:
        token = secrets.token_urlsafe(32)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(f".{self._path.name}.{secrets.token_hex(4)}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(token)
            os.replace(tmp, self._path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return token


def require_ingress(request: Request) -> None:
    """Allow only the Supervisor's Ingress proxy, or anyone in dev mode."""
    paths: Paths = request.app.state.paths
    if paths.dev_mode:
        return
    if request.client is None or request.client.host != INGRESS_PEER:
        raise HTTPException(status_code=403, detail="The UI is only available through Ingress")


def require_bearer(request: Request) -> None:
    """Require ``Authorization: Bearer <api token>``."""
    scheme, _, presented = request.headers.get("Authorization", "").partition(" ")
    expected: str = request.app.state.tokens.get()
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        presented.strip().encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
