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
