from __future__ import annotations

import json
from pathlib import Path

from app.services.consciousness.world_time import read_world_time_snapshot
from app.storage import db as db_storage


def _init_db(tmp_path: Path) -> None:
    db_storage.DB_DIR = tmp_path / "data"
    db_storage.DB_PATH = db_storage.DB_DIR / "bot.db"
    db_storage.init_db()


def test_world_time_snapshot_includes_date_from_last_tick(tmp_path: Path):
    _init_db(tmp_path)
    db_storage.execute_write(
        "INSERT INTO life_world_state (id, state_json, updated_at) VALUES (1, ?, ?)",
        (
            json.dumps(
                {
                    "sim_minutes": 8 * 60 + 56,
                    "last_tick": {
                        "real_date": "2026-06-26",
                        "real_time": "08:56",
                    },
                }
            ),
            "2026-06-26T00:56:00+00:00",
        ),
    )

    snapshot = read_world_time_snapshot()

    assert snapshot is not None
    assert snapshot["display_date"] == "2026-06-26"
    assert snapshot["display_time"] == "08:56"


def test_world_time_snapshot_derives_date_from_updated_at_for_legacy_rows(tmp_path: Path):
    _init_db(tmp_path)
    db_storage.execute_write(
        "INSERT INTO life_world_state (id, state_json, updated_at) VALUES (1, ?, ?)",
        (
            json.dumps({"sim_minutes": 8 * 60 + 56}),
            "2026-06-25T23:56:00+00:00",
        ),
    )

    snapshot = read_world_time_snapshot()

    assert snapshot is not None
    assert snapshot["display_date"] == "2026-06-26"
    assert snapshot["display_time"] == "08:56"
