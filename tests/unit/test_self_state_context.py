from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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


def _write_world_state(
    location: str,
    action: str,
    threads: list[dict],
    *,
    self_context: str = "",
) -> None:
    ws = seed_world_state(load_world_def())
    ws.location = location
    ws.last_tick = {"action": action}
    ws.open_threads = threads
    ws.self_context = self_context
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
    assert "18" in block
    assert "活泼" in block


def test_sleeping_state_renders_woken(tmp_path: Path):
    _init_db(tmp_path)
    _write_agent_state(30.0, "sleeping")
    _write_world_state("bedroom", "睡着", threads=[])

    from app.services.chat.self_state_context import build_self_state_context
    block = build_self_state_context()
    assert block is not None
    assert "睡着了" in block
    assert "吵醒" in block or "睡眼惺忪" in block


def test_sleeping_state_keeps_persisted_self_context_and_live_sleep_status(tmp_path: Path):
    _init_db(tmp_path)
    _write_agent_state(30.0, "sleeping")
    _write_world_state(
        "bedroom",
        "睡着",
        threads=[],
        self_context="你今晚画了很久，后来回到卧室歇下。",
    )

    from app.services.chat.self_state_context import build_self_state_context
    block = build_self_state_context()
    assert "你今晚画了很久" in block
    assert "睡着了" in block


def test_persisted_self_context_replaces_manual_life_summary(tmp_path: Path):
    _init_db(tmp_path)
    _write_agent_state(80.0, "awake", mood_label="平静")
    _write_world_state(
        "living_room",
        "翻开书",
        threads=[],
        self_context="你现在窝在客厅画画，心情很松。",
    )

    from app.services.chat.self_state_context import build_self_state_context
    block = build_self_state_context()
    assert "你现在窝在客厅画画，心情很松。" in block
    assert "刚在翻开书" not in block
    assert "18" in block


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


def test_life_state_disabled_still_returns_seed(tmp_path: Path, monkeypatch):
    _init_db(tmp_path)
    _write_agent_state(80.0, "awake")
    import app.config as cfg
    monkeypatch.setattr(cfg, "CONSCIOUSNESS_CHAT_SELF_STATE_ENABLED", False)

    from app.services.chat.self_state_context import build_self_state_context
    block = build_self_state_context()
    assert block is not None
    assert "18" in block
    assert "活泼" in block
    assert "现在的你在" not in block


def test_state_read_failure_still_returns_seed_and_logs_warning(tmp_path: Path):
    _init_db(tmp_path)
    from app.services.chat import self_state_context as module

    with patch.object(
        module.db_storage, "fetch_one", side_effect=RuntimeError("db unavailable")
    ), patch.object(module, "log_event") as logged:
        block = module.build_self_state_context(trace_id="seed-fallback")

    assert block is not None
    assert "18" in block
    assert "活泼" in block
    logged.assert_called_once()


def test_no_state_still_returns_deterministic_seed(tmp_path: Path):
    _init_db(tmp_path)  # 空库，没有 agent_state 行
    from app.services.chat.self_state_context import build_self_state_context
    block = build_self_state_context()
    assert block is not None
    assert "18" in block
    assert "活泼" in block
    assert "现在的你在家里" not in block


def test_presence_gate_and_defer_marker_remain(tmp_path: Path, monkeypatch):
    _init_db(tmp_path)
    _write_agent_state(80.0, "awake")
    _write_world_state("living_room", "画画", threads=[], self_context="你在客厅画画。")
    import app.config as cfg
    monkeypatch.setattr(cfg, "WORLD_PRESENCE_GATE_ENABLED", True)

    from app.services.chat.self_state_context import build_self_state_context
    from app.services.consciousness.presence import DEFER_MARKER
    block = build_self_state_context()
    assert DEFER_MARKER in block
    assert "只" in block and "输出" in block
