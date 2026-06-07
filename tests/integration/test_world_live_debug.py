"""Living World 竖切7：控制台世界端点集成测试。"""
from __future__ import annotations


def test_world_live_requires_admin_token(client):
    resp = client.get("/debug/consciousness/world-live")
    assert resp.status_code in (401, 403)


def test_world_live_returns_snapshot(client, admin_headers):
    resp = client.get("/debug/consciousness/world-live", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    world = data["world"]
    assert "rooms" in world
    assert "money" in world
    assert "plan" in world
    # 种子世界：4 个房间
    assert set(world["rooms"].keys()) == {"bedroom", "kitchen", "living_room", "balcony"}
    assert data["loop_enabled"] is False  # 默认关


def test_world_tick_requires_admin_token(client):
    resp = client.post("/debug/consciousness/world-tick")
    assert resp.status_code in (401, 403)


def test_world_tick_advances_world(client, admin_headers):
    resp = client.post("/debug/consciousness/world-tick", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True, data
    world = data["world"]
    assert world["last"].get("action")  # 这一步她做了点什么

    # 再读一次，状态已持久（sim 时钟推进）
    after = client.get("/debug/consciousness/world-live", headers=admin_headers).json()
    assert after["world"]["sim_time"] != "00:00"
