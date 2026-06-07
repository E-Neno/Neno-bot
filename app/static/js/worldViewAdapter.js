export const ROOM_ORDER = ["bedroom", "living_room", "kitchen", "balcony"];

export const ROOM_NAME = {
  bedroom: "卧室",
  living_room: "客厅",
  kitchen: "厨房",
  balcony: "阳台",
};

export const DEFAULT_X = {
  bedroom: 0.58,
  living_room: 0.52,
  kitchen: 0.42,
  balcony: 0.72,
};

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
};

export function actionLabel(action) {
  return ACTION_ZH[action] || action || "发呆";
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

export function mapWorldSnapshot(world = {}) {
  const roomKey = ROOM_ORDER.includes(world.location) ? world.location : "living_room";
  const room = ROOM_ORDER.indexOf(roomKey);
  const last = world.last || {};
  const action = actionLabel(last.action);
  const pose = last.sleeping ? "sleeping" : poseOf(last.action);
  const kitchenObjects = world.rooms?.kitchen?.objects || [];
  const steam = kitchenObjects.some(
    (object) => object.key === "kettle" && object.state === "boiling"
  );
  const change = last.event || formatDrift(last.drift).join("；");

  return {
    room,
    roomKey,
    x: DEFAULT_X[roomKey] ?? 0.5,
    action,
    thought: last.micro || action,
    inner: last.reasoning || "",
    mood: world.mood || "—",
    moodValence: world.mood_valence ?? 0,
    energy: world.energy ?? "—",
    energyStatus: world.energy_status || "—",
    duration: "",
    time: world.sim_time || "--:--",
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
    money: world.money ?? "—",
    rooms: world.rooms || {},
  };
}
