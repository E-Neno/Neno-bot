from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.storage.db import fetch_one

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _time_segment(hour: int) -> str:
    if 0 <= hour <= 4:
        return "凌晨"
    if 5 <= hour <= 8:
        return "早晨"
    if 9 <= hour <= 11:
        return "上午"
    if 12 <= hour <= 13:
        return "中午"
    if 14 <= hour <= 17:
        return "下午"
    if 18 <= hour <= 20:
        return "傍晚"
    return "晚上"


def _format_gap(minutes: int | None) -> str | None:
    if minutes is None:
        return "首次聊天"
    if minutes < 1:
        return "不到1分钟"

    days, remainder = divmod(minutes, 24 * 60)
    hours, mins = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if mins or not parts:
        parts.append(f"{mins}分钟")
    return "".join(parts)


def _parse_sqlite_utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(BEIJING_TZ)


def _last_chat_time(session_id: str) -> datetime | None:
    row = fetch_one(
        """
        SELECT created_at
        FROM messages
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id,),
    )
    if row is None:
        return None
    return _parse_sqlite_utc_datetime(row["created_at"])


def build_time_context(session_id: str) -> dict:
    now = datetime.now(BEIJING_TZ)
    last_chat_time = _last_chat_time(session_id)

    gap_minutes = None
    is_new_day = False
    if last_chat_time is not None:
        gap_seconds = max(0, int((now - last_chat_time).total_seconds()))
        gap_minutes = gap_seconds // 60
        is_new_day = now.date() != last_chat_time.date()

    return {
        "now_local": now.strftime("%Y-%m-%d %H:%M"),
        "weekday": WEEKDAYS[now.weekday()],
        "time_segment": _time_segment(now.hour),
        "gap_minutes": gap_minutes,
        "gap_text": _format_gap(gap_minutes),
        "is_new_day": is_new_day,
    }


def build_time_context_message(time_context: dict) -> str:
    segment = str(time_context.get("time_segment") or "").strip() or "这会儿"
    minutes = time_context.get("gap_minutes")
    if minutes is None:
        gap = "这是第一次聊"
    else:
        minutes = int(minutes)
        if minutes < 10:
            gap = "刚聊过没多久"
        elif minutes < 60:
            gap = "隔了一小会儿没聊"
        elif minutes < 24 * 60:
            hours = max(1, minutes // 60)
            gap = f"隔了{hours}小时没聊"
        else:
            days = max(1, minutes // (24 * 60))
            gap = f"隔了{days}天没聊"
    return f"现在{segment}，{gap}。"
