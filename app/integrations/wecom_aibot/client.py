from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

import websockets
from dotenv import load_dotenv

from .dedupe import MessageDeduper
from .protocol import build_subscribe_frame, build_text_reply_frame, normalize_callback


NENO_ENDPOINT = "http://127.0.0.1:8000/platform/openclaw/message"
logger = logging.getLogger(__name__)


class WeComAibotClient:
    def __init__(
        self,
        *,
        bot_id: str,
        secret: str,
        neno_endpoint: str = NENO_ENDPOINT,
        on_message: Callable[[dict[str, Any]], Awaitable[str]] | None = None,
        heartbeat_seconds: float = 30.0,
    ) -> None:
        self.bot_id = bot_id
        self.secret = secret
        self.neno_endpoint = neno_endpoint
        self.on_message = on_message
        self.heartbeat_seconds = heartbeat_seconds
        self.deduper = MessageDeduper()

    async def run_once(self, *, receive_timeout: float | None = None) -> dict[str, Any]:
        async with websockets.connect(
            "wss://openws.work.weixin.qq.com",
            ping_interval=None,
            close_timeout=5,
        ) as ws:
            req_id = f"aibot_subscribe_{uuid.uuid4().hex}"
            await ws.send(json.dumps(build_subscribe_frame(self.bot_id, self.secret, req_id=req_id)))
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            auth = json.loads(raw)
            if auth.get("errcode") != 0:
                raise RuntimeError(f"WeCom authentication failed: {auth.get('errmsg', auth.get('errcode'))}")
            logger.info("WeCom subscription authenticated")

            if receive_timeout is not None:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=receive_timeout)
                except asyncio.TimeoutError:
                    pass
            return {"authenticated": True, "req_id": req_id, "frame": auth}

    async def serve_forever(self) -> None:
        while True:
            try:
                await self._serve_connection()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("WeCom connection ended; reconnecting")
                await asyncio.sleep(2)

    async def _serve_connection(self) -> None:
        async with websockets.connect(
            "wss://openws.work.weixin.qq.com",
            ping_interval=None,
            close_timeout=5,
        ) as ws:
            auth_req_id = f"aibot_subscribe_{uuid.uuid4().hex}"
            await ws.send(json.dumps(build_subscribe_frame(self.bot_id, self.secret, req_id=auth_req_id)))
            auth = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if auth.get("errcode") != 0:
                raise RuntimeError(f"WeCom authentication failed: {auth.get('errmsg', auth.get('errcode'))}")
            logger.info("WeCom subscription authenticated; waiting for callbacks")

            heartbeat = asyncio.create_task(self._heartbeat(ws))
            try:
                async for raw in ws:
                    frame = json.loads(raw)
                    if frame.get("cmd") != "aibot_msg_callback":
                        logger.info(
                            "WeCom received non-message callback: cmd=%s errcode=%s errmsg=%s",
                            frame.get("cmd") or "ack",
                            frame.get("errcode"),
                            frame.get("errmsg"),
                        )
                        continue
                    callback = normalize_callback(frame)
                    if self.deduper.seen(callback["external_message_id"]):
                        logger.info("WeCom duplicate message ignored")
                        continue
                    logger.info("WeCom message accepted: type=%s chat_type=%s", callback["message_type"], callback["chat_type"])
                    reply = await self._dispatch(callback)
                    if reply:
                        await ws.send(json.dumps(build_text_reply_frame(callback["req_id"], reply)))
                        logger.info("WeCom text reply sent")
                    else:
                        logger.info("WeCom message produced no immediate reply")
            finally:
                heartbeat.cancel()

    async def _heartbeat(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            await ws.send(json.dumps({"cmd": "ping", "headers": {"req_id": f"ping_{uuid.uuid4().hex}"}}))

    async def _dispatch(self, callback: dict[str, Any]) -> str:
        if self.on_message is not None:
            return await self.on_message(callback)

        import httpx

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                self.neno_endpoint,
                json={key: callback[key] for key in ("platform", "account_id", "user_id", "real_user_id", "chat_type", "group_id", "message", "message_type")},
            )
            response.raise_for_status()
            logger.info("Neno platform request completed: status=%s", response.status_code)
            return str(response.json().get("reply") or "")


def client_from_environment() -> WeComAibotClient:
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    return WeComAibotClient(
        bot_id=os.environ["WECOM_AIBOT_ID"],
        secret=os.environ["WECOM_AIBOT_SECRET"],
        neno_endpoint=os.getenv("WECOM_NENO_ENDPOINT", NENO_ENDPOINT),
    )
