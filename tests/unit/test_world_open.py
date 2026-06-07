from app.services.consciousness.world_model import (
    load_world_def, seed_world_state, apply_op, WorldOp,
    obj_exists, obj_category, obj_room, legal_states_of, objects_in_room, room_count,
)


def _setup():
    wd = load_world_def()
    st = seed_world_state(wd)
    return wd, st


def test_defaults_present():
    wd, st = _setup()
    assert st.money == 120
    assert st.dyn_objects == {}
    assert st.gone_log == []
    assert st.removed == []


def test_static_object_accessors():
    wd, st = _setup()
    assert obj_exists(wd, st, "kettle")
    assert obj_category(wd, st, "kettle") == "appliance"
    assert obj_room(wd, st, "kettle") == "kitchen"
    assert "boiling" in legal_states_of(wd, st, "kettle")
    assert not obj_exists(wd, st, "dragon")


def test_create_object_adds_dynamic_and_deducts_money():
    wd, st = _setup()
    op = WorldOp(op="create_object", object="tulips", category="plant",
                 room="balcony", label="郁金香", cost=25)
    out = apply_op(wd, st, op)
    assert obj_exists(wd, out, "tulips")
    assert obj_category(wd, out, "tulips") == "plant"
    assert obj_room(wd, out, "tulips") == "balcony"
    assert out.object_states["tulips"] == "fresh"     # 类别默认态
    assert out.money == 95                              # 120 - 25
    assert "tulips" in objects_in_room(wd, out, "balcony")


def test_destroy_dynamic_object_logs_gone():
    wd, st = _setup()
    st = apply_op(wd, st, WorldOp(op="create_object", object="tulips",
                                  category="plant", room="balcony", label="郁金香", cost=25))
    out = apply_op(wd, st, WorldOp(op="destroy_object", object="tulips", cause="枯死"))
    assert not obj_exists(wd, out, "tulips")
    assert "tulips" not in objects_in_room(wd, out, "balcony")
    assert out.gone_log and out.gone_log[-1]["object"] == "tulips"
    assert out.gone_log[-1]["cause"] == "枯死"


def test_destroy_static_object_uses_removed():
    wd, st = _setup()
    assert "mug" in objects_in_room(wd, st, "kitchen")
    out = apply_op(wd, st, WorldOp(op="destroy_object", object="mug", cause="摔碎扔了"))
    assert "mug" in out.removed
    assert "mug" not in objects_in_room(wd, out, "kitchen")
    assert not obj_exists(wd, out, "mug")
    assert out.gone_log[-1]["object"] == "mug"


def test_room_count_and_objects_in_room():
    wd, st = _setup()
    base = room_count(wd, st, "balcony")
    st = apply_op(wd, st, WorldOp(op="create_object", object="cactus",
                                  category="plant", room="balcony", label="仙人掌", cost=10))
    assert room_count(wd, st, "balcony") == base + 1
