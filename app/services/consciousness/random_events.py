"""Random daily-life event generator with time-slot probability."""
import hashlib
import random
from datetime import datetime
from typing import Optional

from .event_pool import EventIn

RANDOM_EVENT_POOL = [
    {"content": "路过一只橘猫，盯着我看了好久", "tags": ["萌宠"], "mood_impact": 0.4},
    {"content": "隔壁在装修，电钻声吵死了", "tags": ["抱怨"], "mood_impact": -0.2},
    {"content": "买了杯奶茶，踩雷了，甜得发腻", "tags": ["日常", "抱怨"], "mood_impact": -0.1},
    {"content": "刷到一条超好笑的视频，笑了好久", "tags": ["开心"], "mood_impact": 0.5},
    {"content": "发现一家新开的小店，看起来不错", "tags": ["日常"], "mood_impact": 0.2},
    {"content": "突然想起一首很久没听的歌", "tags": ["怀旧"], "mood_impact": 0.1},
    {"content": "窗外突然开始下雨，没带伞", "tags": ["天气", "抱怨"], "mood_impact": -0.15},
    {"content": "今天的外卖送得特别快", "tags": ["日常", "开心"], "mood_impact": 0.2},
    {"content": "手机没电了差点关机", "tags": ["抱怨"], "mood_impact": -0.1},
    {"content": "看到天边有漂亮的晚霞", "tags": ["风景", "治愈"], "mood_impact": 0.35},
    {"content": "无意间整理了一下房间，清爽多了", "tags": ["日常"], "mood_impact": 0.25},
    {"content": "买东西找不到钱包，急死了，后来发现在包里", "tags": ["日常", "抱怨"], "mood_impact": 0.1},
    {"content": "楼下便利店新上了我爱的冰淇淋口味", "tags": ["日常", "开心"], "mood_impact": 0.3},
    {"content": "公交上有人给我让座，有点不好意思", "tags": ["日常", "暖"], "mood_impact": 0.3},
    {"content": "今天的咖啡特别好喝，心情跟着好了", "tags": ["日常", "治愈"], "mood_impact": 0.25},
    {"content": "收到一条奇怪的骚扰短信", "tags": ["抱怨"], "mood_impact": -0.05},
    {"content": "耳机线又缠成一团了，解了半天", "tags": ["日常", "抱怨"], "mood_impact": -0.08},
    {"content": "路上闻到一股超香的烧烤味", "tags": ["日常"], "mood_impact": 0.15},
    {"content": "微博上又在吵架，看得心累", "tags": ["抱怨", "网络"], "mood_impact": -0.25},
    {"content": "朋友突然发来一张以前的合照", "tags": ["怀旧", "暖"], "mood_impact": 0.4},
]

HOUR_PROBABILITY = {
    **{h: 0.0 for h in range(1, 8)},
    **{h: 0.3 for h in range(8, 10)},
    **{h: 0.5 for h in range(10, 12)},
    **{h: 0.4 for h in range(12, 14)},
    **{h: 0.7 for h in range(14, 18)},
    **{h: 0.6 for h in range(18, 21)},
    **{h: 0.4 for h in range(21, 23)},
    0: 0.0,
    23: 0.1,
}


def _make_random_hash(content: str) -> str:
    return f"random_{hashlib.md5(content.encode()).hexdigest()[:8]}"


def maybe_generate_random_event(now: datetime) -> Optional[EventIn]:
    prob = HOUR_PROBABILITY.get(now.hour, 0.3)
    if random.random() > prob:
        return None
    chosen = random.choice(RANDOM_EVENT_POOL)
    topic_hash = _make_random_hash(chosen["content"])
    return EventIn(
        topic_hash=topic_hash,
        priority=2,
        content=chosen["content"],
        tags=chosen["tags"],
        mood_impact=chosen["mood_impact"],
        source="random",
    )
