from __future__ import annotations

import json
import re
from typing import Any, Callable

from app.llm.openrouter_client import chat_with_openrouter

from .world_model import WorldDef, WorldState


ROOM_LABELS = {
    "bedroom": "卧室",
    "living_room": "客厅",
    "kitchen": "厨房",
    "balcony": "阳台",
    "entryway": "玄关",
    "building_entrance": "小区楼下",
    "convenience_store": "便利店",
    "cafe": "咖啡馆",
    "park": "小公园",
}

ACTION_LABELS = {
    "read_book": "读书",
    "make_tea": "泡茶",
    "boil_water": "烧水",
    "cook": "做饭",
    "water_plant": "浇花",
    "clean": "收拾屋子",
    "rest": "休息",
    "eat": "吃东西",
    "look_window": "望向窗外",
    "sleep": "睡觉",
    "organize": "整理",
    "turn_on_light": "开灯",
    "turn_off_light": "关灯",
    "turn_on_tv": "打开电视",
    "turn_off_tv": "关掉电视",
    "listen_music": "听音乐",
    "play_music": "放音乐",
    "use_phone": "看手机",
    "check_phone": "看手机",
    "move": "走动",
    "go_out": "出门",
    "walk": "走动",
    "nap": "小憩",
    "tidy_up": "收拾",
    "wash_dishes": "洗碗",
    "draw": "画画",
    "sketch": "画速写",
}

ACTION_TEMPLATES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("move_to", "move to", "go_to", "go to", "walk_to", "walk to"), "前往{target}"),
    (("turn_on", "switch_on"), "打开{target}"),
    (("turn_off", "switch_off"), "关掉{target}"),
    (("check", "inspect", "look_at"), "查看{target}"),
    (("use",), "使用{target}"),
    (("read",), "读{target}"),
    (("clean",), "清理{target}"),
    (("organize", "tidy"), "整理{target}"),
    (("sit_at", "sit_on"), "坐到{target}旁"),
    (("buy", "purchase"), "买下{target}"),
    (("drink",), "喝{target}"),
    (("eat",), "吃{target}"),
)


def _has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def _normalize_key(value: str) -> str:
    value = re.sub(r"[\s\-]+", "_", value.strip().lower())
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def _humanize_key(value: str) -> str:
    return _normalize_key(value).replace("_", " ") or "行动"


def _object_label(world_def: WorldDef, state: WorldState, key: str) -> str | None:
    if key in state.dyn_objects:
        return str(state.dyn_objects[key].get("label") or key)
    if key in world_def.objects:
        return world_def.objects[key].label
    return None


def target_label(world_def: WorldDef, state: WorldState, key: str) -> str:
    normalized = _normalize_key(key)
    if normalized in ROOM_LABELS:
        return ROOM_LABELS[normalized]
    if normalized in world_def.rooms:
        return normalized
    label = _object_label(world_def, state, normalized)
    if label:
        return label
    return _humanize_key(normalized)


def _template_label(world_def: WorldDef, state: WorldState, action: str) -> str | None:
    raw = action.strip()
    normalized = _normalize_key(raw)
    spaced = raw.strip().lower()

    for prefixes, template in ACTION_TEMPLATES:
        for prefix in prefixes:
            if " " in prefix:
                marker = f"{prefix} "
                if spaced.startswith(marker):
                    target = raw[len(marker):].strip()
                    if target:
                        return template.format(target=target_label(world_def, state, target))
            marker = f"{prefix}_"
            if normalized.startswith(marker):
                target = normalized[len(marker):]
                if target:
                    return template.format(target=target_label(world_def, state, target))
    return None


def localize_action(world_def: WorldDef, state: WorldState, action: Any) -> str:
    value = str(action or "").strip()
    if not value:
        return "发呆"
    if _has_cjk(value):
        return value

    normalized = _normalize_key(value)
    if value in ACTION_LABELS:
        return ACTION_LABELS[value]
    if normalized in ACTION_LABELS:
        return ACTION_LABELS[normalized]

    templated = _template_label(world_def, state, value)
    if templated:
        return templated
    return _humanize_key(value)


def localize_action_record(world_def: WorldDef, state: WorldState, record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    if not out.get("action_label"):
        out["action_label"] = localize_action(world_def, state, out.get("action"))
    return out


def localize_last_tick(world_def: WorldDef, state: WorldState, last_tick: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(last_tick, dict):
        return {}
    return localize_action_record(world_def, state, last_tick)


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def suggest_action_label_with_mimo(
    world_def: WorldDef,
    state: WorldState,
    action: str,
    *,
    llm_client: Callable[..., str] = chat_with_openrouter,
) -> str | None:
    """Ask MiMo for a display-only label for an unknown action.

    This is intentionally not used by read-only snapshot rendering. Callers should
    cache accepted results and keep world state mutations separate from labels.
    """
    from app.config import MIMO_API_KEY, MIMO_BASE_URL, MIMO_MODEL, MIMO_TIMEOUT

    if not MIMO_API_KEY:
        return None

    rooms = {key: ROOM_LABELS.get(key, key) for key in world_def.rooms}
    objects = {
        key: (state.dyn_objects.get(key, {}) or {}).get("label") or value.label
        for key, value in world_def.objects.items()
    }
    for key, value in state.dyn_objects.items():
        objects[key] = value.get("label") or key

    prompt = {
        "action": str(action or ""),
        "location": state.location,
        "room_label": ROOM_LABELS.get(state.location, state.location),
        "known_rooms": rooms,
        "known_objects": objects,
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你只为虚拟生活世界的动作生成中文展示标签。"
                "不要改变世界状态。只输出 JSON：{\"label\":\"不超过12个字\"}。"
            ),
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    url = MIMO_BASE_URL.rstrip("/") + "/chat/completions"
    content = llm_client(
        MIMO_API_KEY,
        url,
        MIMO_MODEL,
        messages,
        timeout=MIMO_TIMEOUT,
        trace_id="world_action_localizer",
    )
    label = str(_extract_json_object(content).get("label") or "").strip()
    if not label or len(label) > 24 or "\n" in label:
        return None
    return label


def maybe_suggest_action_label_with_mimo(
    world_def: WorldDef,
    state: WorldState,
    action: str,
    *,
    llm_client: Callable[..., str] = chat_with_openrouter,
) -> str | None:
    from app.config import WORLD_ACTION_LLM_LABEL_ENABLED

    if not WORLD_ACTION_LLM_LABEL_ENABLED:
        return None
    return suggest_action_label_with_mimo(
        world_def,
        state,
        action,
        llm_client=llm_client,
    )
