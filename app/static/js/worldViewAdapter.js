// 前 4 个是家内房间，顺序不可变（kitchen 必须是 index 2，前端测试与布局依赖）。
// 刀③ 外部场所追加在后面：玄关(门槛) → 小区楼下(hub) → 咖啡馆/便利店/公园。
export const ROOM_ORDER = [
  "bedroom", "living_room", "kitchen", "balcony",
  "entryway", "building_entrance", "cafe", "convenience_store", "park",
];

export const ROOM_NAME = {
  bedroom: "卧室",
  living_room: "客厅",
  kitchen: "厨房",
  balcony: "阳台",
  entryway: "玄关",
  building_entrance: "小区楼下",
  cafe: "咖啡馆",
  convenience_store: "便利店",
  park: "小公园",
};

export const DEFAULT_X = {
  bedroom: 0.58,
  living_room: 0.52,
  kitchen: 0.42,
  balcony: 0.72,
  entryway: 0.50,
  building_entrance: 0.50,
  cafe: 0.46,
  convenience_store: 0.50,
  park: 0.54,
};

// 哪些场景算「在外面」（出了家门）——前端据此显示外出标记。
export const OUTSIDE_ROOMS = new Set([
  "building_entrance", "cafe", "convenience_store", "park",
]);

// ── 反应式物品层（第一刀：厨房）─────────────────────────────────────────────
// 每个房间里"会变状态、值得画出来"的物品摆哪。x/y 是房间内百分比，size 是字号(px)，
// idle 是常驻微动。坐标先手调，日后可做拖拽编辑器。其余房间暂不配 = 不渲染物品层。
export const OBJECT_SLOTS = {
  kitchen: {
    fridge:        { x: 15, y: 52, size: 46 },
    kettle:        { x: 36, y: 62, size: 30, idle: "breathe" },
    mug:           { x: 50, y: 66, size: 24, idle: "breathe" },
    tea_tin:       { x: 62, y: 64, size: 22 },
    cutting_board: { x: 75, y: 67, size: 26 },
    dish_towel:    { x: 87, y: 60, size: 22, idle: "sway" },
  },
  living_room: {
    ceiling_light: { x: 50, y: 13, size: 26, idle: "swing" },
    tv:            { x: 84, y: 54, size: 32 },
    record_player: { x: 90, y: 42, size: 22 },
    sketchbook:    { x: 30, y: 70, size: 20, idle: "breathe" },
    book:          { x: 47, y: 73, size: 20 },
    floor_cushion: { x: 64, y: 78, size: 26 },
  },
};

// 物品在某状态下的视觉差异（只写"和默认不一样"的：换 emoji / 加蒸汽 / 倒下 / 变暗）。
// 默认字形用快照里 object.emoji；这里只覆盖。
const STATE_FX = {
  kettle:        { boiling: { steam: true } },
  mug:           { broken: { tip: true }, dirty: { dim: true } },
  tea_tin:       { empty: { dim: true } },
  dish_towel:    { needs_wash: { dim: true } },
  plants:        { wilting: { emoji: "🥀" }, dead: { emoji: "🥀", dim: true } },
  ceiling_light: { off: { dim: true } },
  lamp:          { off: { dim: true } },
  record_player: { off: { dim: true }, paused: { dim: true } },
  book:          { closed: { dim: true }, finished: { dim: true } },
  sketchbook:    { closed: { dim: true }, finished: { dim: true } },
};

// 真实抠图贴片：把物品/状态映射到真实 PNG（透明底）。有图就用图、没图回退 emoji。
// 一个个加，不用一次配满。格式：
//   kettle: { _base: "/static/img/world/obj/kettle.png", boiling: "/static/img/world/obj/kettle-boiling.png" }
// _base 是默认图（所有状态），具体状态可单独覆盖（如 boiling 那张带蒸汽的）。
const OBJECT_IMG = {
  // 例（出了图再填）：
  // kettle: { _base: "/static/img/world/obj/kettle.png", boiling: "/static/img/world/obj/kettle-boiling.png" },
  // plants: { _base: "/static/img/world/obj/plant-fresh.png", wilting: "/static/img/world/obj/plant-wilting.png", dead: "/static/img/world/obj/plant-dead.png" },
};

function objectImg(key, state) {
  const conf = OBJECT_IMG[key];
  if (!conf) return null;
  return conf[state] || conf._base || null;
}

// 给定物品 key 和当前状态，返回该状态的视觉覆盖（emoji 覆盖 / 真实贴片 / 效果）。
export function objectFx(key, state) {
  const fx = (STATE_FX[key] && STATE_FX[key][state]) || {};
  const img = objectImg(key, state);
  return img ? { ...fx, img } : fx;
}

// 自动布局：按类别把物品分到不同高度带（灯在顶、家具在中下、地毯杂物在地面），
// 同一带里横向均匀铺开。没配 slot 的物品据此自动落位，省去手摆 100+ 个。
const TIER_Y = {
  light: 13, window: 28, decor: 33,
  plant: 50, nature: 50,
  device: 55, media: 55, book: 55, drinkware: 57, pantry: 57, household: 57, fixture: 55,
  appliance: 60, furniture: 66,
  textile: 80, rack: 80,
};
const TIER_DEFAULT = 62;

export function autoLayout(objects) {
  const count = {};
  for (const o of objects) {
    const y = TIER_Y[o.category] ?? TIER_DEFAULT;
    count[y] = (count[y] || 0) + 1;
  }
  const idx = {};
  const out = {};
  for (const o of objects) {
    const y = TIER_Y[o.category] ?? TIER_DEFAULT;
    const n = count[y];
    const i = idx[y] || 0;
    idx[y] = i + 1;
    const x = n === 1 ? 50 : 8 + (i / (n - 1)) * 84;
    out[o.key] = { x: Math.round(x * 10) / 10, y, size: 22 };
  }
  return out;
}

const ACTION_ZH = {
  read_book: "读书",
  make_tea: "泡茶",
  boil_water: "烧水",
  cook: "做饭",
  water_plant: "浇花",
  clean: "收拾屋子",
  rest: "休息",
  eat: "吃东西",
  look_window: "望向窗外",
  sleep: "睡觉",
  organize: "整理",
  // 世界 LLM 偶尔吐英文动作 key，这里兜底翻译，免得长卷显示生肉
  turn_on_light: "开灯",
  turn_off_light: "关灯",
  turn_on_tv: "打开电视",
  turn_off_tv: "关掉电视",
  listen_music: "听音乐",
  play_music: "放音乐",
  use_phone: "看手机",
  check_phone: "看手机",
  move_to_kitchen: "去厨房",
  move_to_living_room: "去客厅",
  move_to_bedroom: "回卧室",
  move_to_balcony: "去阳台",
  go_out: "出门",
  walk: "走动",
  nap: "小憩",
  tidy_up: "收拾",
  wash_dishes: "洗碗",
  draw: "画画",
  sketch: "画速写",
};

// snake_case 英文 key 兜底：表里没有时，至少去掉下划线显示得像句话
function humanizeKey(value) {
  if (/^[a-z][a-z0-9_]*$/.test(value)) return value.replace(/_/g, " ");
  return value;
}

const SEAT_ANCHOR = {
  read_book: { kind: "seat", object: "sofa", x: 0.52, y: 0.72 },
  sleep: { kind: "seat", object: "bed", x: 0.30, y: 0.62 },
  water_plant: { kind: "use", object: "plant", x: 0.78, y: 0.58 },
};

const LIGHT_KEYS = new Set(["lamp", "ceiling_light", "floor_lamp", "desk_lamp", "bedside_lamp"]);

export function actionLabel(action) {
  if (!action) return "发呆";
  return ACTION_ZH[action] || humanizeKey(action);
}

export function poseOf(action) {
  const value = String(action || "");
  if (/read|读|书/.test(value)) return "reading";
  if (/sleep|睡/.test(value)) return "sleeping";
  if (/^去|^回|walk|move/.test(value)) return "walk";
  return "idle";
}

function formatDrift(drift) {
  return (drift || [])
    .map((item) => Array.isArray(item) ? `${item[0]} ${item[1]}→${item[2]}` : String(item))
    .filter(Boolean);
}

export function dayGrade(hhmm) {
  const h = parseInt(String(hhmm || "12:00").split(":")[0], 10);
  if (h < 5) return { phase: "deep_night", color: "#0e1430", opacity: 0.55, blend: "multiply" };
  if (h < 8) return { phase: "morning", color: "#ffcaa0", opacity: 0.22, blend: "soft-light" };
  if (h < 16) return { phase: "day", color: "#fff4e0", opacity: 0.06, blend: "soft-light" };
  if (h < 19) return { phase: "dusk", color: "#ff9e6b", opacity: 0.30, blend: "soft-light" };
  if (h < 22) return { phase: "evening", color: "#2a2350", opacity: 0.38, blend: "multiply" };
  return { phase: "late_night", color: "#0e1430", opacity: 0.52, blend: "multiply" };
}

function isNight(hhmm) {
  const h = parseInt(String(hhmm || "12:00").split(":")[0], 10);
  return h >= 19 || h < 6;
}

function activeLights(rooms, hhmm) {
  if (!isNight(hhmm)) return [];
  return Object.entries(rooms || {})
    .filter(([, room]) => (room.objects || []).some(
      (object) => LIGHT_KEYS.has(object.key) && object.state === "on"
    ))
    .map(([roomKey]) => roomKey);
}

function anchorFor(action) {
  return SEAT_ANCHOR[action] || null;
}

export function mapWorldSnapshot(world = {}) {
  const roomKey = ROOM_ORDER.includes(world.location) ? world.location : "living_room";
  const room = ROOM_ORDER.indexOf(roomKey);
  const last = world.last || {};
  const action = actionLabel(last.action);
  const pose = last.sleeping ? "sleeping" : poseOf(last.action);
  const anchor = anchorFor(last.action);
  const kitchenObjects = world.rooms?.kitchen?.objects || [];
  const steam = kitchenObjects.some(
    (object) => object.key === "kettle" && object.state === "boiling"
  );
  const change = last.event || formatDrift(last.drift).join("；");

  return {
    room,
    roomKey,
    outside: OUTSIDE_ROOMS.has(roomKey),
    x: anchor?.x ?? DEFAULT_X[roomKey] ?? 0.5,
    y: anchor?.y ?? 0.50,
    anchor,
    action,
    thought: last.micro || action,
    inner: last.reasoning || "",
    mood: world.mood || "—",
    moodValence: world.mood_valence ?? 0,
    energy: world.energy ?? "—",
    energyStatus: world.energy_status || "—",
    duration: "",
    time: world.sim_time || "--:--",
    daylight: dayGrade(world.sim_time),
    activeLights: activeLights(world.rooms, world.sim_time),
    phase: last.phase || "",
    change,
    moment: action,
    steam,
    pose,
    walk: pose === "walk",
    sleeping: Boolean(last.sleeping),
    plan: Array.isArray(world.plan) ? world.plan : [],
    carriedOver: Array.isArray(world.carried_over) ? world.carried_over : [],
    recent: Array.isArray(world.recent) ? world.recent : [],
    gone: Array.isArray(world.gone) ? world.gone : [],
    threads: Array.isArray(world.threads) ? world.threads : [],
    money: world.money ?? "—",
    rooms: world.rooms || {},
    wake: Boolean(last.wake),
    pressure: last.pressure ?? 0,
  };
}
