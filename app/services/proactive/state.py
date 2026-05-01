import asyncio
from typing import Any

scheduler_task: asyncio.Task | None = None
last_check_at: str | None = None
last_result: dict[str, Any] | None = None
