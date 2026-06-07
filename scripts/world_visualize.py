"""Living World 竖切1 可视化生成器（非破坏性，只读）。

读取当前世界 → 计算"下一步 tick 预览"（漂移+mock决策+校验，不写库）
→ 生成自包含 HTML 户型图到 data/world_view.html，双击即可在浏览器打开。

运行：PYTHONPATH=. python scripts/world_visualize.py
"""
from __future__ import annotations

import json
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from app.storage.db import init_db
from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.world_model import apply_op, load_world_def, WorldOp
from app.services.consciousness.world_store import WorldStore
from app.services.consciousness.world_drift import apply_drift
from app.services.consciousness.action_validator import validate_ops
from app.services.consciousness.world_brain import WorldBrain

import asyncio

ROOM_LABELS = {
    "bedroom": "卧室",
    "kitchen": "厨房",
    "living_room": "客厅",
    "balcony": "阳台",
}
OBJ_EMOJI = {
    "bed": "🛏️", "desk": "🪟", "bookshelf": "📚", "phone": "📱",
    "window_bed": "🪟", "lamp": "💡", "kettle": "🫖", "mug": "☕",
    "fridge": "🧊", "sofa": "🛋️", "book": "📖", "tv": "📺",
    "ceiling_light": "💡", "chair": "🪑", "plants": "🪴",
}


async def build_snapshot() -> dict:
    init_db()
    cfg = ConsciousnessConfig()
    wd = load_world_def()
    store = WorldStore(wd)
    brain = WorldBrain(wd, cfg)

    state = await store.read()

    # 下一步预览（非破坏：复制后演算，不 store.write）
    preview = state.model_copy(deep=True)
    # 制造可观测漂移：若水壶已冷，先设 warm 演示它会变凉
    if preview.object_states.get("kettle") == "cold":
        preview.object_states["kettle"] = "warm"
    drifted, drift_changes = apply_drift(wd, preview, elapsed_minutes=45, config=cfg)

    plan = await brain.decide(drifted)
    op_log: list[dict] = []
    sim = drifted
    for op in plan.world_ops:
        accepted, rejected = validate_ops(wd, sim, [op])
        if accepted:
            sim = apply_op(wd, sim, op)
            op_log.append({
                "op": op.op,
                "target": op.object or op.to_room,
                "state": op.state,
                "result": "accept",
                "reason": op.reason,
            })
        else:
            op_log.append({
                "op": op.op,
                "target": op.object or op.to_room,
                "state": op.state,
                "result": "reject",
                "reason": rejected[0][1],
            })
    bad = WorldOp(op="set_state", object="dragon", state="boiling")
    _, rej = validate_ops(wd, sim, [bad])
    op_log.append({
        "op": "set_state", "target": "dragon", "state": "boiling",
        "result": "reject", "reason": rej[0][1],
    })

    rooms_out: dict[str, dict] = {}
    for room, spec in wd.rooms.items():
        rooms_out[room] = {
            "label": ROOM_LABELS.get(room, room),
            "objects": [
                {
                    "key": o,
                    "label": wd.objects[o].label if o in wd.objects else o,
                    "emoji": OBJ_EMOJI.get(o, "▫️"),
                    "state": state.object_states.get(o, "?"),
                }
                for o in spec.get("objects", [])
            ],
        }

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "home": wd.home,
        "location": state.location,
        "rooms": rooms_out,
        "preview": {
            "drift": drift_changes,
            "action": plan.action,
            "reasoning": plan.reasoning,
            "micro_event": plan.micro_event,
            "ops": op_log,
            "next_location": sim.location,
        },
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Neno 的家 · Living World 竖切1</title>
<style>
  :root{ --bg:#15171c; --card:#1e2128; --edge:#2c303a; --txt:#e6e8ec; --dim:#8b90a0; --accent:#6ea8fe; }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
  .wrap{max-width:1000px;margin:0 auto;padding:24px}
  header{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:18px}
  h1{font-size:20px;margin:0;font-weight:650}
  .meta{color:var(--dim);font-size:13px}
  .here{color:var(--accent);font-weight:600}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  .room{background:var(--card);border:1px solid var(--edge);border-radius:14px;padding:14px 16px;position:relative;transition:border-color .2s}
  .room.active{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
  .room h2{font-size:15px;margin:0 0 10px;display:flex;align-items:center;gap:8px}
  .neno{margin-left:auto;font-size:12px;background:var(--accent);color:#0b0d12;padding:2px 8px;border-radius:99px;font-weight:700}
  .objs{display:flex;flex-direction:column;gap:7px}
  .obj{display:flex;align-items:center;gap:9px;font-size:14px}
  .obj .em{width:22px;text-align:center}
  .obj .nm{flex:1;color:var(--txt)}
  .badge{font-size:12px;padding:2px 9px;border-radius:99px;font-weight:600;color:#0b0d12}
  .panel{margin-top:20px;background:var(--card);border:1px solid var(--edge);border-radius:14px;padding:16px}
  .panel h3{margin:0 0 12px;font-size:14px;color:var(--dim);font-weight:600;letter-spacing:.04em}
  .line{font-size:14px;margin:6px 0;line-height:1.5}
  .k{color:var(--dim)}
  .chg{color:#e8a33d}
  .accept{color:#4fc97f;font-weight:600}
  .reject{color:#e0664f;font-weight:600}
  .micro{font-style:italic;color:#b9bdc9;margin-top:8px;padding-left:10px;border-left:2px solid var(--edge)}
  .legend{margin-top:14px;color:var(--dim);font-size:12px;display:flex;gap:14px;flex-wrap:wrap}
  .legend i{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:5px;vertical-align:middle}
  footer{margin-top:18px;color:var(--dim);font-size:12px;text-align:center}
  code{background:#0d0f13;padding:1px 6px;border-radius:5px;color:#b9bdc9}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🏠 Neno 的家 <span class="meta">· __HOME__</span></h1>
    <div class="meta">Neno 现在在 <span class="here" id="loc"></span> · 快照 __TIME__</div>
  </header>
  <div class="grid" id="grid"></div>

  <div class="panel">
    <h3>下一步 TICK 预览（只读，不改库）</h3>
    <div id="preview"></div>
  </div>

  <footer>Living World 竖切1 · 封闭世界 · 决策为 mock 规则（竖切3 接真实 GPT-4o-mini）· 不调真实模型</footer>
</div>
<script>
const DATA = __DATA__;
const STATE_COLOR = {
  cold:"#5b8def", warm:"#e8a33d", boiling:"#e0533d",
  fresh:"#4fc97f", needs_water:"#e8a33d", wilting:"#b07a3d", dead:"#6a6a6a",
  clean:"#4fc97f", dirty:"#b07a3d", broken:"#e0533d",
  tidy:"#4fc97f", rumpled:"#e8a33d",
  silent:"#7a7f8c", has_unread:"#e0533d",
  closed:"#7a7f8c", reading:"#5b8def", finished:"#4fc97f",
  bright:"#e8c33d", dim:"#9a8b3d", dark:"#555",
  off:"#6a6a6a", on:"#e8c33d",
};
const c = s => STATE_COLOR[s] || "#7a7f8c";

document.getElementById("loc").textContent =
  (DATA.rooms[DATA.location]?.label || DATA.location);

const grid = document.getElementById("grid");
for (const [key, room] of Object.entries(DATA.rooms)){
  const active = key === DATA.location;
  const el = document.createElement("div");
  el.className = "room" + (active ? " active" : "");
  const objs = room.objects.map(o =>
    `<div class="obj"><span class="em">${o.emoji}</span>`+
    `<span class="nm">${o.label}</span>`+
    `<span class="badge" style="background:${c(o.state)}">${o.state}</span></div>`
  ).join("");
  el.innerHTML =
    `<h2>${room.label}${active?'<span class="neno">Neno 在这</span>':''}</h2>`+
    `<div class="objs">${objs}</div>`;
  grid.appendChild(el);
}

const p = DATA.preview;
const pe = document.getElementById("preview");
let html = "";
if (p.drift.length){
  html += `<div class="line"><span class="k">世界漂移（没人碰也在变）：</span></div>`;
  for (const [o,f,t] of p.drift)
    html += `<div class="line">　${o}: <span class="chg">${f} → ${t}</span></div>`;
} else {
  html += `<div class="line"><span class="k">世界漂移：</span>无</div>`;
}
html += `<div class="line"><span class="k">决策：</span>${p.action} — ${p.reasoning}</div>`;
html += `<div class="line"><span class="k">执行 + 守门：</span></div>`;
for (const op of p.ops){
  const cls = op.result === "accept" ? "accept" : "reject";
  const tag = op.result === "accept" ? "✔ ACCEPT" : "✘ REJECT";
  const tgt = op.state ? `${op.target}→${op.state}` : op.target;
  html += `<div class="line">　<span class="${cls}">${tag}</span> ${op.op} ${tgt} <span class="k">(${op.reason})</span></div>`;
}
if (p.micro_event) html += `<div class="micro">💭 ${p.micro_event}</div>`;
pe.innerHTML = html;
</script>
</body>
</html>
"""


def main() -> None:
    snapshot = asyncio.run(build_snapshot())
    html = (
        HTML_TEMPLATE
        .replace("__DATA__", json.dumps(snapshot, ensure_ascii=False))
        .replace("__HOME__", snapshot["home"])
        .replace("__TIME__", snapshot["generated_at"])
    )
    out = Path("data") / "world_view.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"已生成可视化：{out.resolve()}")
    try:
        webbrowser.open(out.resolve().as_uri())
        print("已尝试在默认浏览器打开。")
    except Exception:
        print("请手动双击上面的 HTML 文件打开。")


if __name__ == "__main__":
    main()
