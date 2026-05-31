"""Long-term memory keyword recall for the consciousness layer."""
import asyncio
import logging
from app.storage.db import fetch_all, execute_write
from .config import ConsciousnessConfig

logger = logging.getLogger(__name__)


class MemoryRecall:
    """
    长期记忆关键词召回。
    数据量小时用关键词匹配，无需向量库。
    接口预留 embedding 扩展点，将来可无痛替换。
    """

    def __init__(self, db, config: ConsciousnessConfig) -> None:
        self._db = db
        self._cfg = config

    async def recall(self, query: str, subject: str | None = None) -> list[str]:
        """
        根据 query 关键词从 long_term_memory 表召回 Top-K 条记忆。
        匹配逻辑：
          1. 若 subject 不为空，优先匹配 subject 字段
          2. 对 content 和 tags 做关键词分词匹配
          3. 按 salience DESC 排序，取前 cfg.memory_recall_top_k 条
          4. 返回 content 字符串列表（供直接注入 prompt）
        失败时返回 []，不 raise。
        """
        try:
            keywords = _tokenize(query)
            if not keywords:
                return []

            clauses: list[str] = []
            params: list[str] = []

            if subject:
                clauses.append("subject LIKE ?")
                params.append(f"%{subject}%")

            for kw in keywords:
                clauses.append("(content LIKE ? OR tags LIKE ?)")
                params.extend([f"%{kw}%", f"%{kw}%"])

            where = " OR ".join(clauses)
            sql = (
                f"SELECT content FROM long_term_memory "
                f"WHERE {where} "
                f"ORDER BY salience DESC "
                f"LIMIT ?"
            )
            params.append(str(self._cfg.memory_recall_top_k))

            rows = await asyncio.to_thread(fetch_all, sql, tuple(params))
            return [row["content"] for row in rows] if rows else []
        except Exception:
            logger.exception("memory_recall.recall failed")
            return []

    async def add_memory(self, content: str, tags: list[str],
                         subject: str | None, salience: float = 0.5) -> int:
        """写入一条长期记忆，返回 id。Phase 4 梦境服务使用。"""
        import json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        tags_json = json.dumps(tags, ensure_ascii=False)
        return await asyncio.to_thread(
            execute_write,
            "INSERT INTO long_term_memory (content, tags, subject, salience, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (content, tags_json, subject or "", salience, now),
        )

    async def update_salience(self, memory_id: int, delta: float) -> None:
        """调整记忆重要度（梦境沉淀时用）"""
        try:
            await asyncio.to_thread(
                execute_write,
                "UPDATE long_term_memory SET salience = MAX(0, MIN(1, salience + ?)) "
                "WHERE id = ?",
                (delta, memory_id),
            )
        except Exception:
            logger.exception("memory_recall.update_salience failed")


def _tokenize(text: str) -> list[str]:
    """简单中文关键词提取：按标点分词，去停用词，取长度>=2的词"""
    import re

    STOPWORDS = {
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
        "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
        "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
        "什么", "怎么", "这个", "那个", "还", "而", "被", "让", "给", "吧",
        "啊", "呢", "吗", "哦", "嗯", "哈", "呀", "哇", "嘛",
    }
    cleaned = re.sub(r"[，,。！!？?、；;：:\s]+", " ", text)
    words = cleaned.split()
    return [w for w in words if w not in STOPWORDS and len(w) > 1]
