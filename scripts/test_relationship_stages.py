#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_URL = "http://127.0.0.1:8000"
OUTPUT_PATH = Path("outputs/relationship_stage_test.md")
TIMEOUT_SECONDS = 60
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

TEST_MESSAGES = [
    "今天有点烦",
    "我是不是有点麻烦",
    "你是不是不想理我",
    "突然不太想说话了",
    "我刚刚那样是不是有点怪",
    "你记不记得我之前说过我不喜欢太AI",
    "如果我以后经常来找你呢",
    "我有时候其实挺拧巴的",
]

STAGE_PRESETS = [
    {
        "stage": 0,
        "stage_label": "陌生",
        "conversation_count": 0,
        "familiarity_score": 0,
        "trust_score": 0,
        "emotional_depth_score": 0,
        "boundary_score": 0,
    },
    {
        "stage": 2,
        "stage_label": "稳定聊天对象",
        "conversation_count": 45,
        "familiarity_score": 28,
        "trust_score": 8,
        "emotional_depth_score": 5,
        "boundary_score": 10,
    },
    {
        "stage": 4,
        "stage_label": "深度陪伴",
        "conversation_count": 300,
        "familiarity_score": 120,
        "trust_score": 80,
        "emotional_depth_score": 70,
        "boundary_score": 40,
    },
]


def post_json(path: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {
        "Content-Type": "application/json",
        **(headers or {}),
    }
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        headers=request_headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request failed: {exc.reason}") from exc

    if not raw:
        return {}
    return json.loads(raw)


def to_markdown_json(value: Any) -> str:
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=False, indent=2)


def quote_reply(reply: str | None) -> list[str]:
    if not reply:
        return ["> "]
    return [f"> {line}" if line else ">" for line in reply.splitlines()]


def write_report(results: list[dict[str, Any]]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Relationship Stage Test V2",
        "",
        f"- Base URL: `{BASE_URL}`",
        f"- Generated at: `{datetime.now().isoformat(timespec='seconds')}`",
        "",
    ]

    for message_result in results:
        lines.extend([f"## 输入：{message_result['message']}", ""])

        for item in message_result["stages"]:
            stage = item["stage"]
            stage_label = item.get("stage_label") or item.get("preset_stage_label") or ""
            session_id = item["session_id"]
            update_error = item.get("update_error")

            lines.extend(
                [
                    f"### Stage {stage} - {stage_label}",
                    "",
                    f"- Session: `{session_id}`",
                    "",
                ]
            )

            if update_error:
                lines.extend(["关系更新错误：", "", "```text", update_error, "```", ""])
                continue

            if item.get("error"):
                lines.extend(["请求错误：", "", "```text", item["error"], "```", ""])
                continue

            lines.extend(["回复：", ""])
            lines.extend(quote_reply(item.get("reply")))
            lines.append("")
            lines.extend(
                [
                    "关系提示：",
                    "",
                    "```text",
                    item.get("relationship_context") or "",
                    "```",
                    "",
                    "Used memories：",
                    "",
                    "```json",
                    to_markdown_json(item.get("used_memories")),
                    "```",
                    "",
                    "Candidate memory：",
                    "",
                    "```json",
                    to_markdown_json(item.get("candidate_memory")),
                    "```",
                    "",
                ]
            )

    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")


def run() -> int:
    if not ADMIN_TOKEN:
        print("ADMIN_TOKEN not found. Please export ADMIN_TOKEN=...")
        return 1

    results: list[dict[str, Any]] = []
    admin_headers = {"X-Admin-Token": ADMIN_TOKEN}

    for message_index, message in enumerate(TEST_MESSAGES, start=1):
        message_result: dict[str, Any] = {
            "message": message,
            "stages": [],
        }
        print(f"\n[{message}]")

        for preset in STAGE_PRESETS:
            stage = preset["stage"]
            session_id = f"stage-test-{stage}-{message_index}"
            update_payload = {
                key: value
                for key, value in preset.items()
                if key != "stage_label"
            }
            update_payload["session_id"] = session_id
            item: dict[str, Any] = {
                "message": message,
                "session_id": session_id,
                "stage": stage,
                "preset_stage_label": preset["stage_label"],
            }

            try:
                updated_state = post_json(
                    "/relationship/update",
                    update_payload,
                    headers=admin_headers,
                )
                item["updated_state"] = updated_state
            except Exception as exc:
                item["update_error"] = str(exc)
                print(f"stage {stage} -> relationship update failed: {exc}")
                message_result["stages"].append(item)
                continue

            try:
                data = post_json(
                    "/chat",
                    {
                        "session_id": session_id,
                        "message": message,
                    },
                )
                relationship_state = data.get("relationship_state") or {}
                item.update(
                    {
                        "reply": data.get("reply"),
                        "stage_label": relationship_state.get("stage_label"),
                        "relationship_context": data.get("relationship_context"),
                        "used_memories": data.get("used_memories"),
                        "candidate_memory": data.get("candidate_memory"),
                    }
                )
                reply = (data.get("reply") or "").replace("\n", " ")
                print(f"stage {stage} -> {reply[:80]}")
            except Exception as exc:
                item["error"] = str(exc)
                print(f"stage {stage} -> request failed: {exc}")

            message_result["stages"].append(item)

        results.append(message_result)

    write_report(results)
    print(f"\nReport written to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
