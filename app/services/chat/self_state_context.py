"""把 Neno 此刻真实的生活状态注入主聊天系统提示（Phase 5：对话↔世界打通）。

主聊天回合是同步的，故这里走同步 DB 读：从 agent_state 取精力/情绪，从 life_world_state
取所在房间、正在做的事、心里挂着的牵挂，渲染成一段「你此刻真实在过的生活」喂给系统提示。
让回话的是正过着这段日子的她本人，而不是每次现编日常的无状态人设。

read-only、零模型成本；任何读失败都静默跳过，绝不阻断聊天。可用 env 关闭。
"""
from __future__ import annotations

import json

from app.storage import db as db_storage
from app.utils.logging_utils import log_event

_ROOM_ZH = {
    "bedroom": "卧室",
    "kitchen": "厨房",
    "living_room": "客厅",
    "balcony": "阳台",
    "quiet_room": "房间",
}


def _energy_phrase(value: float, status: str) -> str:
    if status == "sleeping":
        return "在睡觉"
    if value >= 70:
        return "精力还行"
    if value >= 45:
        return "有点懒散"
    if value >= 25:
        return "有点累了"
    return "很困，快撑不住了"


def _active_threads(threads: list[dict]) -> list[str]:
    """挑出还活跃的牵挂：loss/residue 任意强度，goal 需 carry>=2；按强度取前 2 条。"""
    out = []
    for t in threads or []:
        if t.get("resolved"):
            continue
        kind = t.get("kind")
        if kind in ("loss", "residue") or (kind == "goal" and t.get("carry_count", 0) >= 2):
            out.append(t)
    out.sort(key=lambda t: t.get("intensity", 0), reverse=True)
    return [t.get("topic", "") for t in out[:2] if t.get("topic")]


def _render_chat_seed_context(seed: dict | None) -> str:
    if not seed:
        return ""
    name = str(seed.get("name", "")).strip()
    age = seed.get("age")
    temperament = str(seed.get("temperament", "")).strip()
    parts = []
    if name and age not in (None, ""):
        parts.append(f"你叫 {name}，{age} 岁。")
    elif name:
        parts.append(f"你叫 {name}。")
    if temperament:
        parts.append(f"气质{temperament}。")
    return "".join(parts)


def build_self_state_context(trace_id: str | None = None) -> str | None:
    """渲染确定性种子 + 生活语境 + 实时睡醒状态。"""
    from app.config import CONSCIOUSNESS_CHAT_SELF_STATE_ENABLED, NENO_SEED

    lines = ["【此刻的你】"]
    seed_context = _render_chat_seed_context(NENO_SEED)
    if seed_context:
        lines.append(seed_context)
    seed_fallback = "\n".join(lines) if seed_context else None

    # 这个开关只关闭生活状态接读；确定性种子始终保留。
    if not CONSCIOUSNESS_CHAT_SELF_STATE_ENABLED:
        return seed_fallback

    try:
        # 精力 / 情绪 ← agent_state
        a_row = db_storage.fetch_one(
            "SELECT state_json FROM agent_state WHERE id = 1 LIMIT 1"
        )
        has_agent_state = bool(a_row)
        e_val = 80.0
        e_status = "awake"
        mood_label = ""
        if a_row:
            astate = json.loads(a_row["state_json"])
            energy = astate.get("energy", {}) or {}
            e_val = float(energy.get("value", 80.0))
            e_status = str(energy.get("status", "awake"))
            mood_label = str((astate.get("mood", {}) or {}).get("label", "")).strip()

        # 所在 / 正在做 / 牵挂 ← life_world_state
        location = ""
        doing = ""
        threads: list[dict] = []
        persisted_self_context = ""
        w_row = db_storage.fetch_one(
            "SELECT state_json FROM life_world_state WHERE id = 1 LIMIT 1"
        )
        has_world_state = bool(w_row)
        if w_row:
            wstate = json.loads(w_row["state_json"])
            location = str(wstate.get("location", ""))
            last_tick = wstate.get("last_tick") or {}
            doing = str(last_tick.get("action", "")).strip()
            threads = wstate.get("open_threads") or []
            persisted_self_context = str(wstate.get("self_context", "")).strip()

        place_zh = _ROOM_ZH.get(location, "家里")
        energy_phrase = _energy_phrase(e_val, e_status)

        if persisted_self_context:
            lines.append(persisted_self_context)

        # 实时睡醒判断不能依赖可能有刷新延迟的 self_context；作为独立层叠加。
        if has_agent_state and e_status == "sleeping":
            lines.append(f"现在的你其实在{place_zh}睡着了。对方这条消息是把你吵醒/睡眼惺忪时看到的——")
            lines.append("可以迷糊、慢半拍、或埋怨被吵，按真实反应来，别装作一直精神地在等消息。")
        elif not persisted_self_context and (has_agent_state or has_world_state):
            bits = [f"现在的你在{place_zh}"]
            if doing and doing not in ("醒来", "发呆"):
                bits.append(f"刚在{doing}")
            if has_agent_state:
                bits.append(energy_phrase)
            if has_agent_state and mood_label:
                bits.append(f"心情{mood_label}")
            lines.append("，".join(bits) + "。")

        if not persisted_self_context:
            care = _active_threads(threads)
            if care:
                lines.append("心里还隐隐挂着：" + "、".join(care) + "。")

        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 — 注入失败绝不阻断聊天
        log_event(
            "chat",
            "self_state_context_warning",
            trace_id=trace_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return seed_fallback
