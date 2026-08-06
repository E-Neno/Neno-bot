from __future__ import annotations

from collections import OrderedDict


class MessageDeduper:
    def __init__(self, max_entries: int = 4096) -> None:
        self.max_entries = max(1, int(max_entries))
        self._seen: OrderedDict[str, None] = OrderedDict()

    def seen(self, message_id: str) -> bool:
        key = str(message_id or "").strip()
        if not key:
            return False
        if key in self._seen:
            self._seen.move_to_end(key)
            return True
        self._seen[key] = None
        while len(self._seen) > self.max_entries:
            self._seen.popitem(last=False)
        return False
