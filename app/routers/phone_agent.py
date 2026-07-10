import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.phone_agent_schemas import AgentHello

router = APIRouter(tags=["phone-agent"])


@router.websocket("/agent/ws")
@router.websocket("/mobile/agent/ws")
async def phone_agent_websocket(
    websocket: WebSocket,
    device_id: str = Query(..., min_length=1, max_length=120),
):
    await websocket.accept()
    await websocket.send_json(
        AgentHello(
            device_id="controller",
            client="pc-console",
        ).model_dump()
    )

    while True:
        try:
            message = await asyncio.wait_for(websocket.receive_json(), timeout=15)
        except asyncio.TimeoutError:
            await websocket.send_json({"type": "presence", "device_id": device_id, "state": "idle"})
            continue
        except WebSocketDisconnect:
            break

        if message == "ping":
            await websocket.send_json({"type": "pong", "device_id": device_id})
            continue
        if not isinstance(message, dict):
            await websocket.send_json({"type": "ignored", "device_id": device_id})
            continue

        if message.get("type") == "ping":
            await websocket.send_json({"type": "pong", "device_id": device_id})
            continue
        if message.get("type") == "observation":
            await websocket.send_json({"type": "observation_ack", "device_id": device_id})
