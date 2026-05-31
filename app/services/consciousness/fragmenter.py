"""Fragmenter — split LLM output into chat-style fragments with typing delays."""
import random
import logging
from datetime import datetime
from .config import ConsciousnessConfig

logger = logging.getLogger(__name__)


class Fragmenter:
    """
    文案碎片化切分 + 打字延迟 + 单位时间频控。
    LLM 输出用 | 分隔多条消息。
    """

    def __init__(self, config: ConsciousnessConfig) -> None:
        self._cfg = config
        self._sent_count_this_hour: int = 0
        self._hour_bucket: int = -1

    def split(self, raw_text: str, energy: float) -> list[str]:
        """
        按 | 切分，并按精力过滤数量和长度。
        - energy < 30：最多 1 条，截断到 10 字
        - energy < 60：最多 3 条
        - energy >= 60：最多 max_fragments_per_burst 条
        """
        parts = [p.strip() for p in raw_text.split("|") if p.strip()]
        if energy < 30:
            parts = parts[:1]
            if parts:
                parts[0] = parts[0][:10]
        elif energy < 60:
            parts = parts[:3]
        else:
            parts = parts[:self._cfg.max_fragments_per_burst]
        return parts

    def typing_delay(self, text: str) -> float:
        """
        打字延迟 = 字数 / chars_per_second + 随机抖动（±20%）
        夹紧到 [min_delay, max_delay]
        """
        base = len(text) / self._cfg.typing_chars_per_second
        jitter = base * random.uniform(-0.2, 0.2)
        return max(
            self._cfg.typing_min_delay,
            min(self._cfg.typing_max_delay, base + jitter),
        )

    def check_rate_limit(self) -> bool:
        """每小时频控，返回 True 表示允许"""
        now_hour = datetime.now().hour
        if now_hour != self._hour_bucket:
            self._hour_bucket = now_hour
            self._sent_count_this_hour = 0
        return self._sent_count_this_hour < self._cfg.max_proactive_per_hour

    def record_sent(self) -> None:
        self._sent_count_this_hour += 1
