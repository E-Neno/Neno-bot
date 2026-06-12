from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.storage import db as db_storage
from app.services.consciousness.models import NenoState
from app.services.consciousness.world_model import load_world_def, seed_world_state


def _init_db(tmp_path: Path) -> None:
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    db_storage.DB_DIR = d
    db_storage.DB_PATH = d / "bot.db"
    db_storage.init_db()


def _write_agent_state(energy_value: float, status: str, mood_label: str = "平静") -> None:
    st = NenoState()
    st.energy.value = energy_value
    st.energy.status = status
    st.mood.label = mood_label
    now = datetime.now(timezone.utc).isoformat()
    db_storage.execute_write(
        "INSERT INTO agent_state (id, revision, state_json, updated_at) VALUES (1, 1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json",
        (st.model_dump_json(), now),
    )


def _write_world_state(location: str, action: str, threads: list[dict]) -> None:
    ws = seed_world_state(load_world_def())
    ws.location = location
    ws.last_tick = {"action": action}
    ws.open_threads = threads
    now = datetime.now(timezone.utc).isoformat()
    db_storage.execute_write(
        "INSERT INTO life_world_state (id, state_json, updated_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json",
        (json.dumps(ws.model_dump(), ensure_ascii=False), now),
    )


def test_awake_state_renders_place_and_activity(tmp_path: Path):
    _init_db(tmp_path)
    _write_agent_state(80.0, "awake", mood_label="懒洋洋")
    _write_world_state("living_room", "翻开书", threads=[])

    from app.services.chat.self_state_context import build_self_state_context
    block = build_self_state_context()
    assert block is not None
    assert "客厅" in block
    assert "翻开书" in block
    assert "懒洋洋" in block
    assert "睡" not in block.split("\n")[1]  # 醒着不该说在睡


def test_sleeping_state_renders_woken(tmp_path: Path):
    _init_db(tmp_path)
    _write_agent_state(30.0, "sleeping")
    _write_world_state("bedroom", "睡着", threads=[])

    from app.services.chat.self_state_context import build_self_state_context
    block = build_self_state_context()
    assert block is not None
    assert "睡着了" in block
    assert "吵醒" in block or "睡眼惺忪" in block


def test_active_threads_surface(tmp_path: Path):
    _init_db(tmp_path)
    _write_agent_state(60.0, "awake")
    threads = [
        {"kind": "loss", "topic": "扔掉的旧杯子", "intensity": 0.6, "resolved": False},
        {"kind": "goal", "topic": "把书读完", "intensity": 0.5, "carry_count": 3, "resolved": False},
        {"kind": "goal", "topic": "随便一个", "intensity": 0.3, "carry_count": 1, "resolved": False},
    ]
    _write_world_state("balcony", "浇花", threads=threads)

    from app.services.chat.self_state_context import build_self_state_context
    block = build_self_state_context()
    assert "扔掉的旧杯子" in block       # loss 一定上
    assert "随便一个" not in block        # carry<2 的 goal 不上


def test_disabled_returns_none(tmp_path: Path, monkeypatch):
    _init_db(tmp_path)
    _write_agent_state(80.0, "awake")
    import app.config as cfg
    monkeypatch.setattr(cfg, "CONSCIOUSNESS_CHAT_SELF_STATE_ENABLED", False)

    from app.services.chat.self_state_context import build_self_state_context
    assert build_self_state_context() is None


def test_no_state_returns_none(tmp_path: Path):
    _init_db(tmp_path)  # 空库，没有 agent_state 行
    from app.services.chat.self_state_context import build_self_state_context
    assert build_self_state_context() is None
