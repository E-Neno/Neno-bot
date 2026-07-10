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


def test_world_snapshot_adapter_prefers_backend_action_labels():
    module_uri = (STATIC / "js" / "worldViewAdapter.js").as_uri()
    script = f"""
      import {{ mapWorldSnapshot }} from {json.dumps(module_uri)};
      const result = mapWorldSnapshot({{
        location: "building_entrance",
        last: {{
          action: "move to building_entrance",
          action_label: "\\u524d\\u5f80\\u5c0f\\u533a\\u697c\\u4e0b"
        }},
        recent: [
          {{
            action: "move to cafe",
            action_label: "\\u524d\\u5f80\\u5496\\u5561\\u9986",
            ago_min: 10
          }}
        ]
      }});
      console.log(JSON.stringify(result));
    """

    result = _run_node_module(script)

    assert result["action"] == "前往小区楼下"
    assert result["thought"] == "前往小区楼下"
    assert result["moment"] == "前往小区楼下"
    assert result["recent"][0]["action_label"] == "前往咖啡馆"


def test_world_snapshot_adapter_renders_outside_places_without_clamping():
    """刀③：她在咖啡馆时不再被钳回客厅，且带 outside 标记。"""
    module_uri = (STATIC / "js" / "worldViewAdapter.js").as_uri()
    script = f"""
      import {{ mapWorldSnapshot, ROOM_ORDER }} from {json.dumps(module_uri)};
      const cafe = mapWorldSnapshot({{ location: "cafe", last: {{ action: "发呆" }} }});
      const home = mapWorldSnapshot({{ location: "bedroom", last: {{ action: "rest" }} }});
      console.log(JSON.stringify({{
        cafeKey: cafe.roomKey, cafeOutside: cafe.outside, cafeRoom: cafe.room,
        homeOutside: home.outside, kitchenIndex: ROOM_ORDER.indexOf("kitchen"),
      }}));
    """
    result = _run_node_module(script)
    assert result["cafeKey"] == "cafe"          # 不再 fallback 到 living_room
    assert result["cafeOutside"] is True
    assert result["cafeRoom"] > 3               # 排在家内 4 房间之后
    assert result["homeOutside"] is False
    assert result["kitchenIndex"] == 2          # 家内顺序不变（布局/旧测试依赖）


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


def test_world_view_keeps_controls_inside_observatory_stage():
    css = (STATIC / "world-view.css").read_text(encoding="utf-8")

    observatory_controls = (
        ".observatory-shell .world-step-controls {\n"
        "  gap:8px;\n"
        "  left:20px;\n"
        "  right:auto;\n"
        "  bottom:20px;\n"
        "  transform:none;\n"
        "}"
    )

    assert observatory_controls in css


def test_world_view_flips_sprite_without_flipping_thought_label():
    css = (STATIC / "world-view.css").read_text(encoding="utf-8")

    assert ".world-neno.face-left img { transform:scaleX(-1); }" in css
    assert ".world-neno.face-left { transform:scaleX(-1); }" not in css


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


def test_world_view_external_scene_assets_exist():
    """刀③：5 个外部场景插画（矢量）已就位，CSS 引用不空。"""
    world_assets = STATIC / "img" / "world"
    css = (STATIC / "world-view.css").read_text(encoding="utf-8")
    layout = (STATIC / "js" / "layout.js").read_text(encoding="utf-8")
    for filename, room in (
        ("scene-entryway-v1.svg", "entryway"),
        ("scene-building-entrance-v1.svg", "building_entrance"),
        ("scene-cafe-v1.svg", "cafe"),
        ("scene-convenience-store-v1.svg", "convenience_store"),
        ("scene-park-v1.svg", "park"),
    ):
        path = world_assets / filename
        assert path.is_file() and path.stat().st_size > 0, f"缺场景资产 {filename}"
        assert filename in css, f"CSS 未引用 {filename}"
        assert f'data-world-room="{room}"' in layout, f"场景条缺 {room}"


def test_console_redesign_has_observatory_design_tokens():
    css = (STATIC / "world-view.css").read_text(encoding="utf-8")

    for token in (
        "--obs-bg",
        "--obs-panel",
        "--obs-accent",
        "--obs-rose",
        "--obs-text",
    ):
        assert token in css

    assert ".observatory-shell" in css
    assert ".control-density-panel" in css
    assert ".world-stage-card::before" in css
    assert ".world-workspace::before" in css


def test_console_layout_marks_observatory_and_control_surfaces():
    layout = (STATIC / "js" / "layout.js").read_text(encoding="utf-8")

    assert 'world-console-shell observatory-shell' in layout
    assert 'control-workspace workspace-hidden control-framer-shell' in layout
    assert '<strong>Neno</strong>' in layout
    assert "Neno Living World" not in layout
    assert "持续生活观测台" not in layout
    assert 'world-panel-label">LIVING WORLD' in layout
    assert 'console-density-card' in layout


def test_control_center_uses_framer_product_sidebar_layout():
    layout = (STATIC / "js" / "layout.js").read_text(encoding="utf-8")
    css = (STATIC / "world-view.css").read_text(encoding="utf-8")

    for token in (
        "control-framer-shell",
        "control-product-sidebar",
        "control-runtime-identity",
        "control-panel-stage",
        "createFramerControlFrame",
    ):
        assert token in layout

    for selector in (
        ".control-framer-shell",
        ".control-product-sidebar",
        ".control-runtime-identity",
        ".control-panel-stage",
        ".control-panel-stage .console-panel.active",
    ):
        assert selector in css

    for token in (
        "--framer-page:#050609",
        "--framer-sidebar:#08090d",
        "--framer-panel:#0c1018",
        "--framer-glow:#87bfff",
    ):
        assert token in css

    assert "--framer-paper:#fbfbfa" not in css
    assert "--framer-page:#f6f6f3" not in css
    for removed in (
        "Default Workspace",
        "Open current panel",
        "control-workspace-select",
        "control-hero-widget",
        "control-glow-orbit",
    ):
        assert removed not in layout
        assert removed not in css
    assert "control-os-dock" not in layout
    assert "control-command-center" not in layout


def test_control_center_uses_studio_shell_not_dashboard_shell():
    layout = (STATIC / "js" / "layout.js").read_text(encoding="utf-8")
    css = (STATIC / "world-view.css").read_text(encoding="utf-8")

    for token in (
        "control-studio-shell",
        "control-stage-header",
        "control-stage-title",
        "control-stage-subtitle",
        "control-stage-status",
        "control-sidebar-footer",
    ):
        assert token in layout

    for selector in (
        ".control-studio-shell",
        ".control-studio-shell .control-stage-header",
        ".control-studio-shell .runtime-workbench",
        ".control-studio-shell .control-surface",
        ".control-studio-shell .control-binding-surface",
        ".control-studio-shell .control-chat-console",
    ):
        assert selector in css

    for removed in (
        "control-command-bar",
        "control-utility-rail",
        "control-rail-card",
    ):
        assert removed not in layout
        assert removed not in css


def test_control_center_keeps_all_debug_nodes_visible_for_redesign():
    layout = (STATIC / "js" / "layout.js").read_text(encoding="utf-8")
    css = (STATIC / "world-view.css").read_text(encoding="utf-8")

    for token in (
        "sessionCard",
        "configCard",
        "statsCard",
        "proactiveCard",
        "relationshipCard",
        "usedMemoryCard",
        "chatPreviewCard",
        "messageDebugCard",
        "sessionDebugCard",
        "candidateCard",
        "memoryCard",
        "routingCard",
        "debugGrid",
        "chatGrid",
    ):
        assert token in layout

    for visible_grouping in (
        "appendSurface(overviewRuntime.primary, statsCard",
        "overviewRuntime.evidence.appendChild(bridgeCard)",
        "overviewRuntime.raw.appendChild(quickCard)",
        "chatRuntime.primary.appendChild(chat)",
        "debugRuntime.raw.appendChild(debugEventsCard)",
        "appendSurface(memoryRuntime.primary, memoryCard",
        "appendSurface(configRuntime.primary, configCard",
    ):
        assert visible_grouping in layout

    assert "control-node-vault" not in layout
    assert ".control-node-vault" not in css


def test_control_center_rewrites_content_as_runtime_workbench():
    layout = (STATIC / "js" / "layout.js").read_text(encoding="utf-8")
    css = (STATIC / "world-view.css").read_text(encoding="utf-8")

    for token in (
        "createRuntimeWorkbench",
        "runtime-workbench",
        "runtime-primary",
        "runtime-evidence",
        "runtime-raw",
        "runtime-module-chip",
        "runtime-strip",
    ):
        assert token in layout

    for selector in (
        ".runtime-workbench",
        ".runtime-primary",
        ".runtime-evidence",
        ".runtime-raw",
        ".runtime-panel .panel-header",
        ".runtime-strip",
    ):
        assert selector in css

    assert "chat-workbench" in layout
    assert "debug-workbench" in layout


def test_control_center_rewrites_legacy_cards_into_control_surfaces():
    layout = (STATIC / "js" / "layout.js").read_text(encoding="utf-8")
    css = (STATIC / "world-view.css").read_text(encoding="utf-8")

    for token in (
        "adoptControlSurface",
        "appendSurface",
        "normalizeControlSurfaces",
        "control-binding-surface",
        "control-surface",
        "control-chat-console",
    ):
        assert token in layout

    for token in (
        "appendSurface(overviewRuntime.primary, statsCard",
        "appendSurface(chatSide, sessionCard",
        "appendSurface(chatRaw, relationshipCard",
        "appendSurface(memoryRuntime.primary, memoryCard",
        "appendSurface(configRuntime.primary, configCard",
    ):
        assert token in layout

    for selector in (
        ".control-surface",
        ".control-binding-surface",
        ".control-surface h3",
        ".control-chat-console",
    ):
        assert selector in css

    for forbidden in (
        ".runtime-workbench .card",
        ".control-framer-shell .card",
        ".control-panel-stage #chatPanel .chat-side-column .card",
    ):
        assert forbidden not in css
