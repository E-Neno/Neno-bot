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
    # 快照房间应与世界定义一致（刀③已扩到含外部场所的多房间，别再写死 4 间）
    from app.services.consciousness.world_model import load_world_def
    assert set(world["rooms"].keys()) == set(load_world_def().rooms.keys())
    # 家内四间始终在
    assert {"bedroom", "kitchen", "living_room", "balcony"} <= set(world["rooms"].keys())
    # loop_enabled 反映运行时配置（.env 可开），快照端点测试不该和运维开关耦合 → 只验类型
    assert isinstance(data["loop_enabled"], bool)


def test_world_live_includes_self_block(client, admin_headers):
    # 「魂」层：此刻的你 / 自我库 / 攒着的消息——前端面板的数据源
    resp = client.get("/debug/consciousness/world-live", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "self" in data
    s = data["self"]
    assert "context" in s and isinstance(s["context"], str)      # self_context「此刻的你」
    assert "facts" in s and isinstance(s["facts"], list)         # subject="neno" 自我库
    assert "pending_count" in s and isinstance(s["pending_count"], int)
    assert "events" in s and isinstance(s["events"], list)       # 魂事件流（学/挪/买/收到你的话）


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
