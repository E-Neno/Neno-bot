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


def build_self_state_context(trace_id: str | None = None) -> str | None:
    """渲染「你此刻的真实状态」系统块；无状态或出错返回 None（聊天照常）。"""
    try:
        from app.config import CONSCIOUSNESS_CHAT_SELF_STATE_ENABLED
        if not CONSCIOUSNESS_CHAT_SELF_STATE_ENABLED:
            return None

        # 精力 / 情绪 ← agent_state
        a_row = db_storage.fetch_one(
            "SELECT state_json FROM agent_state WHERE id = 1 LIMIT 1"
        )
        if not a_row:
            return None
        astate = json.loads(a_row["state_json"])
        energy = astate.get("energy", {}) or {}
        e_val = float(energy.get("value", 80.0))
        e_status = str(energy.get("status", "awake"))
        mood_label = str((astate.get("mood", {}) or {}).get("label", "")).strip()

        # 所在 / 正在做 / 牵挂 ← life_world_state
        location = ""
        doing = ""
        threads: list[dict] = []
        w_row = db_storage.fetch_one(
            "SELECT state_json FROM life_world_state WHERE id = 1 LIMIT 1"
        )
        if w_row:
            wstate = json.loads(w_row["state_json"])
            location = str(wstate.get("location", ""))
            last_tick = wstate.get("last_tick") or {}
            doing = str(last_tick.get("action", "")).strip()
            threads = wstate.get("open_threads") or []

        place_zh = _ROOM_ZH.get(location, "家里")
        energy_phrase = _energy_phrase(e_val, e_status)

        lines = ["=== 你此刻的真实状态（你正过着的生活，不是设定）==="]
        if e_status == "sleeping":
            lines.append(f"现在的你其实在{place_zh}睡着了。对方这条消息是把你吵醒/睡眼惺忪时看到的——")
            lines.append("可以迷糊、慢半拍、或埋怨被吵，按真实反应来，别装作一直精神地在等消息。")
        else:
            bits = [f"现在的你在{place_zh}"]
            if doing and doing not in ("醒来", "发呆"):
                bits.append(f"刚在{doing}")
            bits.append(energy_phrase)
            if mood_label:
                bits.append(f"心情{mood_label}")
            lines.append("，".join(bits) + "。")

        care = _active_threads(threads)
        if care:
            lines.append("心里还隐隐挂着：" + "、".join(care) + "。")

        lines.append(
            "聊到你的近况、在干嘛、状态时，自然顺着这个真实情况来，别跳出去现编另一套；"
            "但这是你的生活底色，不用主动报数值、不用刻意汇报。"
        )

        # ④：要不要现在回，由你自己临场拿捏，不是规则。允许你这次不回。
        from app.config import WORLD_PRESENCE_GATE_ENABLED
        if WORLD_PRESENCE_GATE_ENABLED:
            from app.services.consciousness.presence import DEFER_MARKER
            lines.append(
                f"如果你此刻真的太沉浸在手上的事、心情不想搭理、或困得快撑不住——不想现在回这条，"
                f"就**只**输出 `{DEFER_MARKER}` 这几个字，别的什么都别写，也别硬挤一句敷衍。"
                f"等你缓过来/有空了自然会回。多数时候你是会回的，只在确实不想的时候才这样。"
            )
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 — 注入失败绝不阻断聊天
        log_event(
            "chat",
            "self_state_context_warning",
            trace_id=trace_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return None
