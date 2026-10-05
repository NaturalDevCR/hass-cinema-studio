"""API token storage and the two request guards."""

import dataclasses
import re
import stat
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from cinema_studio.auth import (
    INGRESS_PEER,
    TokenStore,
    require_bearer,
    require_ingress,
)
from cinema_studio.config import Paths

pytestmark = pytest.mark.studio


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_token_store_creates_a_private_token(tmp_path: Path):
    path = tmp_path / "data" / "api_token"
    store = TokenStore(path)
    token = store.get()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    assert path.read_text(encoding="utf-8").strip() == token
    assert mode(path) == 0o600


def test_token_store_persists_across_instances(tmp_path: Path):
    path = tmp_path / "api_token"
    assert TokenStore(path).get() == TokenStore(path).get()


def test_token_store_regenerates_an_empty_file(tmp_path: Path):
    path = tmp_path / "api_token"
    path.write_text("\n", encoding="utf-8")
    assert TokenStore(path).get() != ""


def test_token_store_tightens_a_permissive_file(tmp_path: Path):
    path = tmp_path / "api_token"
    path.write_text("a" * 43, encoding="utf-8")
    path.chmod(0o644)
    assert TokenStore(path).get() == "a" * 43
    assert mode(path) == 0o600


def test_token_store_rotate_replaces_and_persists(tmp_path: Path):
    path = tmp_path / "api_token"
    store = TokenStore(path)
    old = store.get()
    new = store.rotate()
    assert new != old
    assert store.get() == new
    assert TokenStore(path).get() == new
    assert mode(path) == 0o600
    assert list(tmp_path.iterdir()) == [path]


def test_token_store_masks_all_but_the_ends(tmp_path: Path):
    path = tmp_path / "api_token"
    path.write_text("abcdEFGHijklMNOPwxyz", encoding="utf-8")
    store = TokenStore(path)
    assert store.masked() == "abcd…wxyz"
    assert "EFGH" not in store.masked()


@pytest.fixture
def guarded(paths: Paths, tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.paths = paths
    app.state.tokens = TokenStore(tmp_path / "api_token")

    @app.get("/ingress", dependencies=[Depends(require_ingress)])
    async def ingress() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/bearer", dependencies=[Depends(require_bearer)])
    async def bearer() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_ingress_accepts_only_the_supervisor_peer(guarded: FastAPI):
    assert TestClient(guarded, client=(INGRESS_PEER, 50000)).get("/ingress").status_code == 200
    denied = TestClient(guarded, client=("192.168.1.20", 50000)).get("/ingress")
    assert denied.status_code == 403
    assert isinstance(denied.json()["detail"], str)
    assert TestClient(guarded).get("/ingress").status_code == 403


def test_ingress_is_open_in_dev_mode(guarded: FastAPI, paths: Paths):
    guarded.state.paths = dataclasses.replace(paths, dev_mode=True)
    assert TestClient(guarded).get("/ingress").status_code == 200


def test_ingress_peer_constant():
    assert INGRESS_PEER == "172.30.32.2"


def test_bearer_requires_the_token(guarded: FastAPI):
    client = TestClient(guarded)
    token = guarded.state.tokens.get()
    missing = client.get("/bearer")
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert isinstance(missing.json()["detail"], str)
    assert client.get("/bearer", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/bearer", headers={"Authorization": f"Basic {token}"}).status_code == 401
    assert client.get("/bearer", headers={"Authorization": token}).status_code == 401
    assert client.get("/bearer", headers={"Authorization": "Bearer "}).status_code == 401
    assert client.get("/bearer", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/bearer", headers={"Authorization": f"bearer {token}"}).status_code == 200


def test_bearer_follows_a_rotated_token(guarded: FastAPI):
    client = TestClient(guarded)
    old = guarded.state.tokens.get()
    new = guarded.state.tokens.rotate()
    assert client.get("/bearer", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert client.get("/bearer", headers={"Authorization": f"Bearer {new}"}).status_code == 200


def test_bearer_rejects_non_ascii_without_crashing(guarded: FastAPI):
    response = TestClient(guarded).get(
        "/bearer", headers={"Authorization": "Bearer tökén".encode()}
    )
    assert response.status_code == 401
