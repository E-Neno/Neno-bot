from __future__ import annotations

import asyncio
from pathlib import Path

from app.storage import db as db_storage
from app.services.consciousness.world_store import WorldStore


def _init_test_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()


def test_first_read_returns_seed(tmp_path: Path):
    _init_test_db(tmp_path)
    store = WorldStore()
    state = asyncio.run(store.read())
    assert state.object_states["kettle"] == "cold"  # 种子默认


def test_write_then_read_persists(tmp_path: Path):
    _init_test_db(tmp_path)
    store = WorldStore()
    state = asyncio.run(store.read())
    state.object_states["kettle"] = "boiling"
    asyncio.run(store.write(state))
    again = asyncio.run(store.read())
    assert again.object_states["kettle"] == "boiling"


def test_bad_json_degrades_to_seed(tmp_path: Path):
    _init_test_db(tmp_path)
    with db_storage.get_conn() as conn:
        conn.execute(
            "INSERT INTO life_world_state (id, state_json, updated_at) "
            "VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET state_json = excluded.state_json",
            ("{not json", "2026-06-07T00:00:00+00:00"),
        )
    store = WorldStore()
    state = asyncio.run(store.read())  # 不抛异常，降级到种子
    assert state.object_states["kettle"] == "cold"
