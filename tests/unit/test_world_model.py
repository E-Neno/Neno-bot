from app.services.consciousness.world_model import (
    load_world_def,
    seed_world_state,
    apply_op,
    reachable_rooms,
    is_outside,
    WorldOp,
)


def test_world_def_loads_and_indexes():
    wd = load_world_def()
    assert wd.room_of("kettle") == "kitchen"
    assert "cold" in wd.legal_states("kettle")
    assert wd.default_state("kettle") == "cold"


def test_seed_state_uses_defaults():
    wd = load_world_def()
    st = seed_world_state(wd)
    assert st.object_states["plants"] == "fresh"
    assert st.location in wd.rooms


def test_old_world_state_data_gets_self_context_defaults():
    from app.services.consciousness.world_model import WorldState

    st = WorldState.model_validate({
        "location": "bedroom",
        "object_states": {"bed": "made"},
    })
    assert st.self_context == ""
    assert st.self_context_basis is None
    assert st.self_context_updated_at == ""


def test_apply_set_state_returns_changed_copy():
    wd = load_world_def()
    st = seed_world_state(wd)
    out = apply_op(wd, st, WorldOp(op="set_state", object="kettle", state="boiling"))
    assert out.object_states["kettle"] == "boiling"
    assert st.object_states["kettle"] == "cold"  # 原对象不被改（纯函数）


def test_apply_move_changes_location():
    wd = load_world_def()
    st = seed_world_state(wd)
    out = apply_op(wd, st, WorldOp(op="move", to_room="balcony"))
    assert out.location == "balcony"


# ── 刀③ 可达性 / 在外面 ──────────────────────────────────────────────────────

def test_home_rooms_fully_interconnected():
    """四个家内房间互通——保住现有 mock/滑行的所有室内 move 不被 gating 断掉。"""
    wd = load_world_def()
    st = seed_world_state(wd)
    home = {"bedroom", "kitchen", "living_room", "balcony"}
    for r in home:
        reach = set(reachable_rooms(wd, st, r))
        assert home - {r} <= reach, f"{r} 无法直达全部其他家内房间：{reach}"


def test_reachability_is_undirected():
    wd = load_world_def()
    st = seed_world_state(wd)
    # adjacency 只写了 living_room->entryway；反向也要可达
    assert "entryway" in reachable_rooms(wd, st, "living_room")
    assert "living_room" in reachable_rooms(wd, st, "entryway")


def test_outside_gated_behind_door():
    """出门要过玄关：家内房间不能一步到外部场所；玄关也不直达店铺。"""
    wd = load_world_def()
    st = seed_world_state(wd)
    assert "cafe" not in reachable_rooms(wd, st, "bedroom")
    assert "cafe" not in reachable_rooms(wd, st, "living_room")
    assert "cafe" not in reachable_rooms(wd, st, "entryway")
    # 小区楼下是外部 hub，从这里才能去咖啡馆/便利店/公园
    assert "cafe" in reachable_rooms(wd, st, "building_entrance")
    assert "convenience_store" in reachable_rooms(wd, st, "building_entrance")
    # 玄关连着小区楼下（出了门）
    assert "building_entrance" in reachable_rooms(wd, st, "entryway")


def test_empty_adjacency_falls_back_to_all_rooms():
    """旧世界没有 adjacency 时退回「全连通」，不破坏老行为。"""
    wd = load_world_def()
    st = seed_world_state(wd)
    wd.adjacency = {}
    reach = set(reachable_rooms(wd, st, "bedroom"))
    assert reach == set(wd.rooms) - {"bedroom"}


def test_is_outside_flags_external_places():
    wd = load_world_def()
    assert is_outside(wd, "cafe") is True
    assert is_outside(wd, "park") is True
    assert is_outside(wd, "building_entrance") is True
    assert is_outside(wd, "bedroom") is False
    assert is_outside(wd, "entryway") is False  # 玄关是门槛，不算在外面
