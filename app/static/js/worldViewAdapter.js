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

const SEAT_ANCHOR = {
  read_book: { kind: "seat", object: "sofa", x: 0.52, y: 0.72 },
  sleep: { kind: "seat", object: "bed", x: 0.30, y: 0.62 },
  water_plant: { kind: "use", object: "plant", x: 0.78, y: 0.58 },
};

const LIGHT_KEYS = new Set(["lamp", "ceiling_light", "floor_lamp", "desk_lamp", "bedside_lamp"]);

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
