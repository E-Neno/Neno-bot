"""Living World 竖切5 实时演示服务器（融合意识层 + 完整的一天）。

独立运行，不接主程序/生产 scheduler。一个常驻 async 事件循环里跑融合 tick：
  时段判定 → 睡眠/醒来(跨天反思+计划) → 世界漂移 → 取(状态+记忆+计划+最近行动)
  → WorldBrain 决策 → 校验执行 → 落账 + 写经历/episode + 反馈精力情绪
浏览器访问 http://localhost:PORT 自动轮询，看 Neno 过一整天。

决策默认 mock；设 CONSCIOUSNESS_WORLD_LLM_ENABLED=1（可选 _PLANNER_ENABLED=1）用真实 GPT-4o-mini。
运行：PYTHONPATH=. python scripts/world_live_server.py   停止：Ctrl+C
"""
from __future__ import annotations

import asyncio
import json
import random
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv

load_dotenv()  # 必须在导入 app.config（读 env）之前

from app.storage.db import init_db
from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.world_model import (
    apply_op, load_world_def, objects_in_room, WorldOp,
)
from app.services.consciousness.world_store import WorldStore
from app.services.consciousness.world_drift import apply_drift
from app.services.consciousness.action_validator import validate_ops
from app.services.consciousness.world_brain import WorldBrain
from app.services.consciousness.life_events import LifeEventSource
from app.services.consciousness.daily_planner import DailyPlanner, DailyPlan
from app.services.consciousness.day_cycle import DayCycle
from app.services.consciousness.state_store import StateStore
from app.services.consciousness.experience_recorder import ExperienceRecorder, InnerExperienceIn
from app.services.consciousness.memory_recall import MemoryRecall
from app.services.consciousness.reflection_engine import ReflectionEngine
from app.services.consciousness.activity_episode_store import ActivityEpisodeStore

PORT = 8777
SIM_MINUTES_PER_TICK = 30        # 每步 = 世界里 30 分钟
START_SIM_MINUTES = 7 * 60       # 从早上 7:00 起
ENERGY_DROP_PER_TICK = 3.0       # 醒着每步消耗精力
INTERVAL_ROUTINE = 1.5
INTERVAL_LLM = 6.0

ROOM_LABELS = {"bedroom": "卧室", "kitchen": "厨房", "living_room": "客厅", "balcony": "阳台"}
OBJ_EMOJI = {
    "bed": "🛏️", "desk": "🖊️", "bookshelf": "📚", "phone": "📱",
    "window_bed": "🪟", "lamp": "💡", "kettle": "🫖", "mug": "☕",
    "fridge": "🧊", "sofa": "🛋️", "book": "📖", "tv": "📺",
    "ceiling_light": "💡", "chair": "🪑", "plants": "🪴",
}
PHASE_ZH = {"morning": "上午", "afternoon": "下午", "evening": "傍晚", "night": "夜里"}

_LOCK = threading.Lock()
_LATEST: dict = {"booting": True}


def _routine_decide(wd, state, phase):
    """LLM 关闭时的作息 mock。用"上一步动作"防止被漂移拖入重复（如反复烧水）。"""
    loc = state.location
    os_ = state.object_states
    last = state.recent_actions[-1]["action"] if state.recent_actions else ""
    if loc == "bedroom":
        if os_.get("bed") == "rumpled" and last != "整理床铺":
            return ("整理床铺", "起床先整理床", [WorldOp(op="set_state", object="bed", state="tidy")], "睡得还行")
        return ("去厨房", "想喝点热的", [WorldOp(op="move", to_room="kitchen")], "有点渴")
    if loc == "kitchen":
        if os_.get("kettle") != "boiling" and last != "烧水":
            return ("烧水", "水壶凉了烧点水", [WorldOp(op="set_state", object="kettle", state="boiling")], "等水开")
        return ("去客厅", "端着热水去客厅", [WorldOp(op="move", to_room="living_room")], None)
    if loc == "living_room":
        book = os_.get("book")
        if book == "closed" and last != "读完一章":
            return ("翻开书", "坐下读书", [WorldOp(op="set_state", object="book", state="reading")], "读得入神")
        if book == "reading":
            return ("读完一章", "读完这部分", [WorldOp(op="set_state", object="book", state="finished")], "有成就感")
        return ("去阳台", "读累了透透气", [
            WorldOp(op="set_state", object="book", state="closed"),
            WorldOp(op="move", to_room="balcony"),
        ], "伸了个懒腰")
    if loc == "balcony":
        if os_.get("plants") in {"needs_water", "wilting"}:
            return ("浇花", "盆栽该浇水了", [WorldOp(op="set_state", object="plants", state="fresh")], "叶子精神了")
        return ("回卧室", "站累了回房间", [
            WorldOp(op="move", to_room="bedroom"),
            WorldOp(op="set_state", object="bed", state="rumpled"),
        ], "想歇会儿")
    return ("发呆", "不知做什么", [], None)


def _obj_label(wd, state, o):
    if o in state.dyn_objects:
        return state.dyn_objects[o].get("label", o)
    return wd.objects[o].label if o in wd.objects else o


def _snapshot(wd, state, nstate, *, tick, sim_minutes, phase, mode, sleeping,
              action, reason, drift, op_log, micro, memories, event):
    rooms_out = {}
    for room in wd.rooms:
        rooms_out[room] = {
            "label": ROOM_LABELS.get(room, room),
            "objects": [
                {"key": o, "label": _obj_label(wd, state, o),
                 "emoji": OBJ_EMOJI.get(o, "🆕" if o in state.dyn_objects else "▫️"),
                 "state": state.object_states.get(o, "?")}
                for o in objects_in_room(wd, state, room)
            ],
        }
    hh = (sim_minutes // 60) % 24
    mm = sim_minutes % 60
    plan = state.daily_plan or {}
    return {
        "booting": False, "tick": tick, "mode": mode, "sleeping": sleeping,
        "sim_time": f"{hh:02d}:{mm:02d}", "phase": PHASE_ZH.get(phase, phase),
        "location": state.location, "rooms": rooms_out,
        "energy": round(float(nstate.energy.value), 0),
        "energy_status": nstate.energy.status,
        "mood": nstate.mood.label,
        "mood_valence": round(float(nstate.mood.valence), 2),
        "money": state.money,
        "plan": plan.get("items", []),
        "carried_over": plan.get("carried_over", []),
        "recent": state.recent_actions[-6:],
        "memories": [m.get("content", "") for m in (memories or [])][:3],
        "gone": [g.get("label") or g.get("object", "") for g in state.gone_log[-5:]],
        "event": (event.content if event is not None else None),
        "last": {"action": action, "reasoning": reason, "drift": drift,
                 "ops": op_log, "micro": micro},
    }


async def tick_main():
    init_db()
    cfg = ConsciousnessConfig(
        reflection_enabled=True,
        world_plant_dry_minutes=240, world_plant_wilt_minutes=240,
    )
    use_llm = cfg.world_llm_enabled
    mode = "LLM" if use_llm else "作息规则"
    interval = INTERVAL_LLM if use_llm else INTERVAL_ROUTINE

    wd = load_world_def()
    world_store = WorldStore(wd)
    state_store = StateStore(db=None, config=cfg)
    await state_store.start()
    brain = WorldBrain(wd, cfg)
    planner = DailyPlanner(wd, cfg)
    dc = DayCycle(cfg)
    recorder = ExperienceRecorder()
    recall = MemoryRecall(db=None, config=cfg)
    episode_store = ActivityEpisodeStore()
    reflection = ReflectionEngine(state_store, recorder, recall, cfg, episode_store)

    # 初始化模拟时钟与首日计划
    ws = await world_store.read()
    if not ws.sim_minutes:
        ws.sim_minutes = START_SIM_MINUTES
    if not ws.daily_plan:
        plan = await planner.make_plan(date="day1", residue="", carried_over=[])
        ws.daily_plan = plan.model_dump()
    await world_store.write(ws)

    src = LifeEventSource(cfg)
    rng = random.Random()

    print(f"决策模式：{mode} · 计划:{'LLM' if cfg.world_planner_enabled else 'mock'} · 反思:on · 事件:on")

    global _LATEST
    n = 0
    sim_minutes = ws.sim_minutes
    day_no = 1
    prev_action = ""

    while True:
        try:
            hour = (sim_minutes // 60) % 24
            phase = dc.phase_of(hour)
            nstate = await state_store.read()

            transition = dc.check_sleep_wake(nstate, phase, hour)
            sleeping = False
            action = reason = ""
            micro = None
            drift = []
            op_log = []
            memories = []
            event = None
            event_mood = 0.0

            if transition == "fall_asleep":
                await dc.on_sleep(state_store)
                await asyncio.sleep(0.05)  # 让 writer 落账，显示即时正确
                nstate = await state_store.read()
                sleeping = True
                action, reason = "睡觉", "困了，回房间睡下"
            elif transition == "wake_up":
                day_no += 1
                # 演示里所有模拟日都落在真实今天，反思按真实当天日期才能找到 episode
                real_day = datetime.now(timezone(timedelta(hours=8))).date()
                await dc.on_wake(
                    state_store, reflection, world_store, planner,
                    today=f"day{day_no}", yesterday=real_day,
                )
                await asyncio.sleep(0.05)  # 让 writer 落账，显示即时正确
                nstate = await state_store.read()
                action, reason = "醒来", "睡醒了，看看今天的计划"
            else:
                nstate2 = await state_store.read()
                if nstate2.energy.status == "sleeping":
                    sleeping = True
                    action, reason = "睡着", "还在睡"

            ws = await world_store.read()

            if not sleeping and action == "":
                # 正常活动 tick
                drifted, drift = apply_drift(
                    wd, ws, elapsed_minutes=SIM_MINUTES_PER_TICK, config=cfg
                )
                # 意外事件注入（决策前发生在她身上）
                event = src.maybe_emit(
                    world_def=wd, world_state=drifted, nstate=nstate, phase=phase, rng=rng
                )
                if event is not None:
                    if event.world_op is not None:
                        acc, _ = validate_ops(wd, drifted, [event.world_op])
                        if acc:
                            drifted = apply_op(wd, drifted, event.world_op)
                    event_mood = event.mood_delta
                plan_obj = None
                if use_llm:
                    plan_dp = DailyPlan.model_validate(ws.daily_plan) if ws.daily_plan else None
                    q_parts = [drifted.location]
                    if plan_dp:
                        for it in plan_dp.items:
                            if it.phase == phase:
                                q_parts.append(it.intent)
                    memories = await recall.recall_weighted(" ".join(q_parts), now=datetime.now(timezone.utc))
                    recent_ctx = [
                        {"action": r.get("action", ""), "ago_min": r.get("ago_min", "?")}
                        for r in drifted.recent_actions[-6:]
                    ]
                    plan_obj = await brain.decide(
                        drifted, nstate=nstate, phase=phase, plan=plan_dp,
                        memories=memories, recent=recent_ctx, event=event,
                    )
                    action, reason = plan_obj.action, plan_obj.reasoning
                    micro = plan_obj.micro_event
                    ops = plan_obj.world_ops
                else:
                    action, reason, ops, micro = _routine_decide(wd, drifted, phase)

                sim = drifted
                for op in ops:
                    acc, rej = validate_ops(wd, sim, [op])
                    if acc:
                        sim = apply_op(wd, sim, op)
                        op_log.append({"r": "accept", "t": op.object or op.to_room, "s": op.state})
                    else:
                        op_log.append({"r": "reject", "t": op.object or op.to_room, "s": rej[0][1]})

                # 最近行动（防绕圈），截断 8
                sim.recent_actions = (sim.recent_actions + [{"action": action, "ago_min": 0}])[-8:]
                for r in sim.recent_actions[:-1]:
                    r["ago_min"] = r.get("ago_min", 0) + SIM_MINUTES_PER_TICK
                sim.sim_minutes = sim_minutes
                # 标记当前时段计划项完成（粗略：动作里包含意图关键词时）
                if sim.daily_plan:
                    for it in sim.daily_plan.get("items", []):
                        if it["phase"] == phase and not it.get("done"):
                            if any(w and w in (action + reason) for w in [it["intent"][:2]]):
                                it["done"] = True
                await world_store.write(sim)
                ws = sim

                # 写经历（记忆流）+ episode（供跨天反思）
                await recorder.record(InnerExperienceIn(
                    trace_id="life_world", source="life_simulation", kind="micro_event",
                    content=(micro or action), salience=0.45,
                    metadata={"place": sim.location, "time_phase": phase},
                ))
                if action != prev_action and action not in {"去厨房", "去客厅", "去阳台", "回卧室"}:
                    try:
                        await episode_store.start_episode(
                            activity_key=action, activity_label=action,
                            place=sim.location, time_phase=phase, reason=reason,
                        )
                    except Exception:
                        pass
                prev_action = action

                # 反馈精力/情绪
                energy = nstate.energy.model_copy(deep=True)
                energy.value = max(0.0, energy.value - ENERGY_DROP_PER_TICK)
                from app.services.consciousness.models import StateMutation
                await state_store.submit_mutation(StateMutation(
                    energy=energy, mood_valence_delta=0.01 + event_mood,
                    reason="life_world tick"))
                await asyncio.sleep(0)  # 让 writer 落账，情绪即时反映
                nstate = await state_store.read()
            else:
                # 睡眠态也要持久化时钟
                ws.sim_minutes = sim_minutes
                await world_store.write(ws)

            n += 1
            sim_minutes += SIM_MINUTES_PER_TICK
            snap = _snapshot(
                wd, ws, nstate, tick=n, sim_minutes=sim_minutes, phase=phase,
                mode=mode, sleeping=sleeping, action=action, reason=reason,
                drift=drift, op_log=op_log, micro=micro, memories=memories,
                event=event,
            )
            with _LOCK:
                _LATEST = snap
        except Exception as exc:  # noqa: BLE001
            print("tick error:", repr(exc))
        await asyncio.sleep(interval)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/state"):
            with _LOCK:
                body = json.dumps(_LATEST, ensure_ascii=False).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        else:
            body = PAGE.encode("utf-8")
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Neno 的一天</title>
<style>
:root{--bg:#15171c;--card:#1e2128;--edge:#2c303a;--txt:#e6e8ec;--dim:#8b90a0;--accent:#6ea8fe}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:22px}
header{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}
h1{font-size:20px;margin:0}.meta{color:var(--dim);font-size:13px}.here{color:var(--accent);font-weight:600}
.top{display:grid;grid-template-columns:1.3fr 1fr;gap:14px;margin:12px 0}
.panel{background:var(--card);border:1px solid var(--edge);border-radius:12px;padding:12px 14px}
.panel h3{margin:0 0 8px;font-size:12px;color:var(--dim);letter-spacing:.05em}
.banner b{color:var(--accent)}.micro{font-style:italic;color:#b9bdc9;margin-top:6px}
.bar{height:8px;background:#0d0f13;border-radius:6px;overflow:hidden;margin:4px 0 10px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,#e0533d,#e8c33d,#4fc97f)}
.plan div,.mem div,.rec div{font-size:13px;margin:3px 0}.done{color:var(--dim);text-decoration:line-through}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.room{background:var(--card);border:1px solid var(--edge);border-radius:12px;padding:12px 14px;transition:border-color .3s,box-shadow .3s}
.room.active{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.room h2{font-size:14px;margin:0 0 8px;display:flex;gap:8px}.neno{margin-left:auto;font-size:11px;background:var(--accent);color:#0b0d12;padding:1px 7px;border-radius:99px;font-weight:700}
.obj{display:flex;align-items:center;gap:8px;font-size:13px;margin:4px 0}.obj .em{width:20px}.obj .nm{flex:1}
.badge{font-size:11px;padding:1px 8px;border-radius:99px;color:#0b0d12;font-weight:600}
.sleep{opacity:.45}.zzz{font-size:13px;color:var(--accent)}
footer{margin-top:16px;color:var(--dim);font-size:12px;text-align:center}
</style></head><body><div class="wrap">
<header><h1>🏠 Neno 的一天</h1><div class="meta">🕐 <span id="t">--:--</span> <span id="ph"></span> · 在 <span class="here" id="loc"></span> · tick <span id="tk">0</span> · <span id="md"></span></div></header>
<div class="banner panel" id="banner">连接中…</div>
<div class="top">
  <div class="panel"><h3>今日计划</h3><div class="plan" id="plan"></div><div id="carry" class="meta"></div></div>
  <div class="panel"><h3>状态</h3>
    <div class="meta">精力 <span id="en">-</span> · <span id="enst"></span> · 心情 <span id="mood"></span>(<span id="val">0</span>) · 💰<span id="money">-</span></div>
    <div class="bar"><i id="enbar" style="width:0%"></i></div>
    <h3>此刻想起</h3><div class="mem" id="mem"></div>
    <h3>最近做过</h3><div class="rec" id="rec"></div>
    <h3>失去的东西</h3><div class="rec" id="gone"></div>
  </div>
</div>
<div class="grid" id="grid"></div>
<footer>融合演示 · 漂移+记忆+计划+睡眠跨天 · 决策 mock/LLM 可切 · 不接聊天不碰红线</footer>
</div><script>
const SC={cold:"#5b8def",warm:"#e8a33d",boiling:"#e0533d",fresh:"#4fc97f",needs_water:"#e8a33d",wilting:"#b07a3d",dead:"#6a6a6a",clean:"#4fc97f",dirty:"#b07a3d",broken:"#e0533d",tidy:"#4fc97f",rumpled:"#e8a33d",silent:"#7a7f8c",has_unread:"#e0533d",closed:"#7a7f8c",reading:"#5b8def",finished:"#4fc97f",bright:"#e8c33d",dim:"#9a8b3d",dark:"#555",off:"#6a6a6a",on:"#e8c33d"};
const col=s=>SC[s]||"#7a7f8c";
async function refresh(){
 try{const d=await (await fetch("/state")).json();if(d.booting)return;
 t.textContent=d.sim_time;ph.textContent=d.phase;loc.textContent=d.rooms[d.location]?.label||d.location;tk.textContent=d.tick;md.textContent="决策:"+d.mode;
 en.textContent=d.energy;enst.textContent=d.energy_status;mood.textContent=d.mood;val.textContent=d.mood_valence;money.textContent=d.money;enbar.style.width=Math.max(0,Math.min(100,d.energy))+"%";
 const L=d.last;let dr="";if(L.drift&&L.drift.length)dr=" · 漂移 "+L.drift.map(x=>`${x[0]}:${x[1]}→${x[2]}`).join("，");
 const evLine=d.event?`<div style="color:#e8a33d">⚡ ${d.event}</div>`:"";
 banner.innerHTML=evLine+`<b>${L.action||"—"}</b> ${L.reasoning?("— "+L.reasoning):""}${dr}`+(L.micro?`<div class="micro">💭 ${L.micro}</div>`:"")+(d.sleeping?` <span class="zzz">💤 睡着了</span>`:"");
 gone.innerHTML=(d.gone||[]).slice().reverse().map(x=>`<div>🗑 ${x}</div>`).join("")||'<div class="meta">（暂无）</div>';
 plan.innerHTML=(d.plan||[]).map(p=>`<div class="${p.done?'done':''}">· [${p.phase}] ${p.intent}${p.done?' ✓':''}</div>`).join("")||'<div class="meta">（暂无）</div>';
 carry.textContent=(d.carried_over&&d.carried_over.length)?("↩ 昨天没做完："+d.carried_over.join("；")):"";
 mem.innerHTML=(d.memories||[]).map(m=>`<div>· ${m}</div>`).join("")||'<div class="meta">（暂无）</div>';
 rec.innerHTML=(d.recent||[]).slice().reverse().map(r=>`<div>· ${r.action}（${r.ago_min}分钟前）</div>`).join("")||'<div class="meta">（暂无）</div>';
 const g=document.getElementById("grid");g.innerHTML="";
 for(const [k,r] of Object.entries(d.rooms)){const act=k===d.location;const el=document.createElement("div");el.className="room"+(act?" active":"")+(d.sleeping&&act?" sleep":"");
  el.innerHTML=`<h2>${r.label}${act?'<span class="neno">Neno 在这</span>':''}</h2>`+r.objects.map(o=>`<div class="obj"><span class="em">${o.emoji}</span><span class="nm">${o.label}</span><span class="badge" style="background:${col(o.state)}">${o.state}</span></div>`).join("");
  g.appendChild(el);}
 }catch(e){}}
setInterval(refresh,1000);refresh();
</script></body></html>
"""


def main():
    threading.Thread(target=lambda: asyncio.run(tick_main()), daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"实时演示已启动：{url}  (Ctrl+C 停止)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        server.shutdown()


if __name__ == "__main__":
    main()
