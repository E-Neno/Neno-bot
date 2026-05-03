from __future__ import annotations

from pathlib import Path
import time

from dotenv import load_dotenv

load_dotenv(Path("/home/admin/emotion-bot/.env"))

from app.schemas import MediaAttachment
from app.services.chat.multimodal_input_service import normalize_multimodal_message
from app.services.chat.turn_orchestrator import run_chat_turn
from app.storage.db import init_db
from app.storage.relationship import init_relationship_tables

IMAGE_URL = "https://upload.wikimedia.org/wikipedia/commons/3/3a/Cat03.jpg"
RUN_TOKEN = str(int(time.time()))


def run_case(name: str, message: str | None) -> dict[str, str]:
    session_id = f"live-verify:{RUN_TOKEN}:{name}"
    trace_id = f"live-{name}-{RUN_TOKEN[-4:]}"
    attachments = [
        MediaAttachment(
            kind="image",
            url=IMAGE_URL,
            source="wx",
        )
    ]

    normalized = normalize_multimodal_message(
        message=message,
        attachments=attachments,
        trace_id=trace_id,
    )
    result = run_chat_turn(session_id, normalized, trace_id=trace_id)
    reply = result["reply"].strip()

    print(f"== {name} ==")
    print("-- normalized --")
    print(normalized)
    print("-- reply --")
    print(reply)
    print()

    return {
        "name": name,
        "normalized": normalized,
        "reply": reply,
    }


def main() -> None:
    init_db()
    init_relationship_tables()

    cases = [
        ("pure_image", None),
        ("image_with_question", "这张图你能看到什么？"),
        ("image_with_comment", "这张图氛围怎么样"),
    ]
    results = [run_case(name, message) for name, message in cases]

    print("== summary ==")
    for item in results:
        print(item["name"])
        print(item["normalized"].splitlines()[0])
        print(item["reply"])
        print()


if __name__ == "__main__":
    main()
