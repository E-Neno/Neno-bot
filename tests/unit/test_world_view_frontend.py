import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "app" / "static"


def _run_node_module(script: str) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def test_world_snapshot_adapter_maps_backend_shape():
    module_uri = (STATIC / "js" / "worldViewAdapter.js").as_uri()
    script = f"""
      import {{ mapWorldSnapshot }} from {json.dumps(module_uri)};
      const result = mapWorldSnapshot({{
        sim_time: "18:42",
        location: "kitchen",
        rooms: {{
          kitchen: {{ objects: [{{ key: "kettle", state: "boiling" }}] }}
        }},
        money: 86,
        plan: [{{ intent: "读完一章", done: false }}],
        gone: ["杯子"],
        energy: 54,
        mood: "不安",
        last: {{
          action: "boil_water",
          reasoning: "想喝点热的",
          micro: "等水烧开",
          drift: [["kettle", "warm", "boiling"]]
        }}
      }});
      console.log(JSON.stringify(result));
    """

    result = _run_node_module(script)

    assert result["room"] == 2
    assert result["roomKey"] == "kitchen"
    assert result["action"] == "烧水"
    assert result["thought"] == "等水烧开"
    assert result["inner"] == "想喝点热的"
    assert result["steam"] is True
    assert result["pose"] == "idle"
    assert result["plan"] == [{"intent": "读完一章", "done": False}]
    assert result["gone"] == ["杯子"]
    assert "kettle warm→boiling" in result["change"]


def test_world_snapshot_adapter_supports_chinese_walk_and_sleep_actions():
    module_uri = (STATIC / "js" / "worldViewAdapter.js").as_uri()
    script = f"""
      import {{ mapWorldSnapshot }} from {json.dumps(module_uri)};
      const walking = mapWorldSnapshot({{
        location: "balcony", last: {{ action: "去阳台" }}
      }});
      const sleeping = mapWorldSnapshot({{
        location: "bedroom", last: {{ action: "睡觉", sleeping: true }}
      }});
      console.log(JSON.stringify({{ walking, sleeping }}));
    """

    result = _run_node_module(script)

    assert result["walking"]["pose"] == "walk"
    assert result["walking"]["walk"] is True
    assert result["sleeping"]["pose"] == "sleeping"


def test_world_snapshot_adapter_derives_daylight_and_active_lights():
    module_uri = (STATIC / "js" / "worldViewAdapter.js").as_uri()
    script = f"""
      import {{ mapWorldSnapshot }} from {json.dumps(module_uri)};
      const night = mapWorldSnapshot({{
        sim_time: "23:15",
        location: "bedroom",
        rooms: {{
          bedroom: {{ objects: [{{ key: "lamp", state: "on" }}] }},
          kitchen: {{ objects: [{{ key: "ceiling_light", state: "off" }}] }}
        }},
        last: {{ action: "rest" }}
      }});
      const afternoon = mapWorldSnapshot({{
        sim_time: "14:05",
        location: "living_room",
        rooms: {{
          living_room: {{ objects: [{{ key: "lamp", state: "on" }}] }}
        }},
        last: {{ action: "read_book" }}
      }});
      console.log(JSON.stringify({{ night, afternoon }}));
    """

    result = _run_node_module(script)

    assert result["night"]["daylight"]["phase"] == "late_night"
    assert result["night"]["daylight"]["color"] == "#0e1430"
    assert result["night"]["daylight"]["opacity"] == 0.52
    assert result["night"]["daylight"]["blend"] == "multiply"
    assert result["night"]["activeLights"] == ["bedroom"]
    assert result["afternoon"]["daylight"]["phase"] == "day"
    assert result["afternoon"]["activeLights"] == []


def test_world_snapshot_adapter_uses_furniture_anchors_for_reading_and_sleep():
    module_uri = (STATIC / "js" / "worldViewAdapter.js").as_uri()
    script = f"""
      import {{ mapWorldSnapshot }} from {json.dumps(module_uri)};
      const reading = mapWorldSnapshot({{
        sim_time: "20:30",
        location: "living_room",
        last: {{ action: "read_book" }}
      }});
      const sleeping = mapWorldSnapshot({{
        sim_time: "23:40",
        location: "bedroom",
        last: {{ action: "sleep", sleeping: true }}
      }});
      console.log(JSON.stringify({{ reading, sleeping }}));
    """

    result = _run_node_module(script)

    assert result["reading"]["anchor"] == {
        "kind": "seat",
        "object": "sofa",
        "x": 0.52,
        "y": 0.72,
    }
    assert result["reading"]["x"] == 0.52
    assert result["reading"]["y"] == 0.72
    assert result["sleeping"]["anchor"]["object"] == "bed"
    assert result["sleeping"]["pose"] == "sleeping"


def test_console_contains_world_engine_and_control_center_workspaces():
    layout = (STATIC / "js" / "layout.js").read_text(encoding="utf-8")
    consciousness = (STATIC / "js" / "consciousness.js").read_text(encoding="utf-8")
    html = (STATIC / "test.html").read_text(encoding="utf-8")

    assert "worldWorkspace" in layout
    assert "controlWorkspace" in layout
    assert "世界引擎" in layout
    assert "控制中枢" in layout
    assert "world-view.css" in html

    for function_name in (
        "ensureWorldPanel",
        "renderWorldLive",
        "loadWorldLive",
        "worldTickOnce",
    ):
        assert function_name in consciousness

    assert "/debug/consciousness/world-live" in consciousness
    assert "/debug/consciousness/world-tick" in consciousness
    assert "const states =" not in consciousness


def test_world_view_has_phase2_light_and_anchor_layers():
    layout = (STATIC / "js" / "layout.js").read_text(encoding="utf-8")
    consciousness = (STATIC / "js" / "consciousness.js").read_text(encoding="utf-8")
    css = (STATIC / "world-view.css").read_text(encoding="utf-8")

    assert 'id="worldDaylight"' in layout
    assert 'id="worldLampGlow"' in layout
    assert "worldDaylight" in consciousness
    assert "activeLights" in consciousness
    assert "style.bottom" in consciousness
    assert ".world-daylight" in css
    assert ".world-lamp-glow.on" in css
    assert ".world-neno.anchored" in css


def test_world_view_has_ambient_environment_layers():
    layout = (STATIC / "js" / "layout.js").read_text(encoding="utf-8")
    consciousness = (STATIC / "js" / "consciousness.js").read_text(encoding="utf-8")
    css = (STATIC / "world-view.css").read_text(encoding="utf-8")

    assert 'id="worldCityLights"' in layout
    assert 'id="worldAirMotion"' in layout
    assert 'dataset.dayPhase' in consciousness
    assert ".world-city-lights.on" in css
    assert ".world-air-motion.on" in css
    assert "@keyframes world-city-twinkle" in css
    assert "@keyframes world-air-drift" in css


def test_world_view_assets_are_served_from_static_directory():
    world_assets = STATIC / "img" / "world"

    for filename in (
        "room-bedroom-v1.png",
        "room-living-v1.png",
        "room-kitchen-v1.png",
        "room-balcony-v1.png",
        "neno-idle-v1.png",
    ):
        path = world_assets / filename
        assert path.is_file()
        assert path.stat().st_size > 0
