"""Perception service: weather, hot topics, time context with TTL cache and graceful degradation."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.storage.db import add_debug_event

from .config import ConsciousnessConfig
from .models import WeatherSnapshot, WorldState

logger = logging.getLogger(__name__)

TTL_WEATHER_MINUTES = 15
TTL_HOT_TOPICS_MINUTES = 10
HTTP_TIMEOUT = 5.0

WEEKDAY_LABELS = ["一", "二", "三", "四", "五", "六", "日"]

HOT_TOPIC_APIS = [
    {
        "name": "weibo",
        "url": "https://weibo.com/ajax/side/hotSearch",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        },
        "extract": "weibo_json",
    },
    {
        "name": "baidu",
        "url": "https://top.baidu.com/board?tab=realtime",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        "extract": "baidu_html",
    },
    {
        "name": "douyin_fallback",
        "url": "https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        "extract": "douyin_json",
    },
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _extract_weibo(data: dict) -> list[str]:
    """Extract hot topic titles from Weibo JSON response."""
    titles: list[str] = []
    raw = data.get("data", {})
    band = raw.get("band_list") or raw.get("realtime") or []
    if isinstance(band, list):
        for item in band:
            word = (item.get("word") or item.get("note") or "").strip()
            if word:
                titles.append(word)
    return titles[:5]


def _extract_baidu_html(text: str) -> list[str]:
    """Extract hot topic titles from Baidu hot search HTML page."""
    import re
    titles: list[str] = []
    matches = re.findall(r'<div[^>]*class="c-single-text-ellipsis"[^>]*>(.*?)</div>', text)
    for m in matches[:5]:
        clean = re.sub(r"<[^>]+>", "", m).strip()
        if clean:
            titles.append(clean)
    if not titles:
        matches = re.findall(r'title="([^"]+)"', text)
        for m in matches:
            clean = m.strip()
            if clean and len(clean) < 60 and clean not in titles:
                titles.append(clean)
    return titles[:5]


def _extract_douyin(data: dict) -> list[str]:
    """Extract hot topic titles from Douyin JSON response."""
    titles: list[str] = []
    raw = data.get("word_list") or data.get("data", {}).get("word_list") or []
    if isinstance(raw, list):
        for item in raw:
            word = (item.get("word") or item.get("title") or "").strip()
            if word:
                titles.append(word)
    return titles[:5]


class PerceptionService:
    """采集真实世界数据。所有外部请求 5s 超时，失败降级不崩溃。"""

    def __init__(self, config: ConsciousnessConfig, location: str = "南宁") -> None:
        self.config = config
        self.location = location
        self._weather_cache: Optional[WeatherSnapshot] = None
        self._weather_cached_at: Optional[datetime] = None
        self._hot_topics_cache: list[str] = []
        self._hot_topics_cached_at: Optional[datetime] = None

    # ── weather ──────────────────────────────────────────────

    async def get_weather(self) -> WeatherSnapshot:
        now = _utcnow()
        if (
            self._weather_cache is not None
            and self._weather_cached_at is not None
            and (now - self._weather_cached_at).total_seconds() < TTL_WEATHER_MINUTES * 60
        ):
            return self._weather_cache

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                url = f"https://wttr.in/{self.location}?format=j1"
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                snap = self._parse_weather(data)
                self._weather_cache = snap
                self._weather_cached_at = now
                return snap
        except Exception:
            logger.warning("weather fetch failed for %s, using fallback", self.location)
            add_debug_event(
                trace_id=f"weather_{_utcnow().isoformat()}",
                module="perception",
                event="weather_fetch_failed",
                level="warn",
                success=False,
                reason=f"wttr.in request failed for {self.location}",
            )
            if self._weather_cache is not None:
                return self._weather_cache
            return WeatherSnapshot()

    def _parse_weather(self, data: dict) -> WeatherSnapshot:
        try:
            current = data.get("current_condition", [{}])[0]
            text = current.get("weatherDesc", [{}])[0].get("value", "") if current.get("weatherDesc") else ""
            temp_c = current.get("temp_C")
            temp = int(temp_c) if temp_c is not None else None
            condition = text
            rain = any(
                kw in (text or "").lower()
                for kw in ("rain", "drizzle", "shower", "thunder", "暴雨", "雨", "雪", "snow")
            )
            return WeatherSnapshot(text=text, temp=temp, condition=condition, rain=rain)
        except Exception:
            logger.warning("weather parse failed")
            return WeatherSnapshot()

    # ── hot topics ───────────────────────────────────────────

    async def get_hot_topics(self) -> list[str]:
        now = _utcnow()
        if (
            self._hot_topics_cache
            and self._hot_topics_cached_at is not None
            and (now - self._hot_topics_cached_at).total_seconds() < TTL_HOT_TOPICS_MINUTES * 60
        ):
            return self._hot_topics_cache

        for api in HOT_TOPIC_APIS:
            try:
                titles = await self._fetch_hot_topics(api)
                if titles:
                    self._hot_topics_cache = titles
                    self._hot_topics_cached_at = now
                    logger.info("hot topics fetched from %s: %d items", api["name"], len(titles))
                    return titles
            except Exception:
                logger.debug("hot topics api %s failed, trying next", api["name"])

        logger.warning("all hot topic APIs failed")
        add_debug_event(
            trace_id=f"hot_{_utcnow().isoformat()}",
            module="perception",
            event="hot_topics_all_failed",
            level="warn",
            success=False,
            reason="all hot topic APIs exhausted",
        )
        return self._hot_topics_cache

    async def _fetch_hot_topics(self, api_spec: dict) -> list[str]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            url = api_spec["url"]
            headers = api_spec.get("headers", {})
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

            extract = api_spec["extract"]
            if extract == "weibo_json":
                return _extract_weibo(resp.json())
            elif extract == "baidu_html":
                return _extract_baidu_html(resp.text)
            elif extract == "douyin_json":
                return _extract_douyin(resp.json())
            return []

    # ── perceive (parallel gather) ───────────────────────────

    async def perceive(self) -> WorldState:
        weather: WeatherSnapshot
        hot_topics: list[str]

        results = await asyncio.gather(
            self.get_weather(),
            self.get_hot_topics(),
            return_exceptions=True,
        )

        if isinstance(results[0], Exception):
            logger.warning("weather gather exception: %s", results[0])
            weather = self._weather_cache or WeatherSnapshot()
        else:
            weather = results[0]

        if isinstance(results[1], Exception):
            logger.warning("hot topics gather exception: %s", results[1])
            hot_topics = self._hot_topics_cache
        else:
            hot_topics = results[1]

        time_ctx = self.build_time_context()

        return WorldState(
            weather=weather,
            hot_topics=hot_topics,
            time_context=time_ctx,
            last_perception_at=_utcnow().isoformat(),
        )

    # ── time context ─────────────────────────────────────────

    @staticmethod
    def build_time_context(now: Optional[datetime] = None) -> str:
        if now is None:
            now = datetime.now()
        wd = WEEKDAY_LABELS[now.weekday()]
        h = now.hour
        m = now.minute

        if 6 <= h < 9:
            period = "早上"
        elif 9 <= h < 12:
            period = "上午"
        elif 12 <= h < 14:
            period = "中午"
        elif 14 <= h < 18:
            period = "下午"
        elif 18 <= h < 22:
            period = "晚上"
        elif 22 <= h < 24:
            period = "深夜"
        else:
            period = "凌晨"

        return f"周{wd}{period}{h:02d}:{m:02d}"
