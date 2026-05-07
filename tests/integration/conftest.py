from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
import app.security as security
import app.storage.db as db_storage
from app.storage.db import init_db
from app.storage.relationship import init_relationship_tables


TEST_ADMIN_TOKEN = "integration-test-admin-token"


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(db_storage, "DB_DIR", data_dir)
    monkeypatch.setattr(db_storage, "DB_PATH", data_dir / "bot.db")
    init_db()
    init_relationship_tables()
    return data_dir


@pytest.fixture()
def admin_headers(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(security, "ADMIN_TOKEN", TEST_ADMIN_TOKEN)
    return {"X-Admin-Token": TEST_ADMIN_TOKEN}


@pytest.fixture()
def client(
    isolated_db: Path,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    del isolated_db
    del admin_headers

    monkeypatch.setattr(main_module, "start_proactive_scheduler", lambda: None)

    async def fake_stop_proactive_scheduler() -> None:
        return None

    monkeypatch.setattr(main_module, "stop_proactive_scheduler", fake_stop_proactive_scheduler)

    with TestClient(main_module.app) as test_client:
        yield test_client
