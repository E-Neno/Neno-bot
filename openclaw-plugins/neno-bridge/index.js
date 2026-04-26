import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ENDPOINT = "http://127.0.0.1:8000/platform/openclaw/message";
const PROACTIVE_HOST = "127.0.0.1";
const PROACTIVE_PORT = 18793;
const PROACTIVE_SEND_QQ_PATH = "/proactive/send-qq";
const PROACTIVE_MAX_BODY_BYTES = 8 * 1024;
const PROACTIVE_MAX_MESSAGE_LENGTH = 500;
const FAILURE_REPLY = "Neno 后端这会儿没接住。";
const MISSING_USER_REPLY = "没拿到用户信息，先不回。";
const WX_MISSING_USER_REPLY = "这条消息我暂时处理不了。";
const UNSUPPORTED_MESSAGE_REPLY = "这个我现在还看不了。";
const QQ_NOT_ALLOWED_REPLY = "这个机器人暂时不开放。";
const WX_NOT_ALLOWED_REPLY = "这个机器人暂时不开放。";
const QQ_FACE_PLACEHOLDER_RE = /<faceType=\d+,faceId="([^"]*)",ext="[^"]*">/g;
const WX_DEBUG_LIMIT = 5;
const PLUGIN_DIR = path.dirname(fileURLToPath(import.meta.url));
const QQ_FACE_MAP_PATH = path.join(PLUGIN_DIR, "qq_face_map.json");
const ALLOWED_QQ_USERS_PATH = path.join(PLUGIN_DIR, "allowed_qq_users.json");
const ALLOWED_WX_USERS_PATH = path.join(PLUGIN_DIR, "allowed_wx_users.json");
let wxDebugCount = 0;

function assertEndpointAllowed() {
  const url = new URL(ENDPOINT);
  const allowedHost = url.hostname === "127.0.0.1" || url.hostname === "localhost";
  if (url.protocol !== "http:" || !allowedHost || url.pathname !== "/platform/openclaw/message") {
    throw new Error("neno-bridge endpoint is outside the allowed local Neno message path");
  }
}

function isObject(value) {
  return value !== null && typeof value === "object";
}

function getPath(obj, path) {
  let cur = obj;
  for (const key of path) {
    if (!isObject(cur) || !(key in cur)) return undefined;
    cur = cur[key];
  }
  return cur;
}

function firstString(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return "";
}

function detectChannel(event, ctx) {
  return firstString(
    event?.channel,
    event?.channelId,
    getPath(event, ["source", "channel"]),
    getPath(event, ["channel", "id"]),
    ctx?.channelId
  );
}

function extractText(event) {
  return firstString(
    event?.content,
    event?.text,
    getPath(event, ["message", "content"]),
    getPath(event, ["raw", "content"]),
    getPath(event, ["body", "content"])
  );
}

function itemListText(items) {
  if (!Array.isArray(items)) return "";
  return items
    .map((item) => firstString(getPath(item, ["text_item", "text"])))
    .join("")
    .trim();
}

function extractWxText(event) {
  return firstString(
    event?.content,
    event?.text,
    getPath(event, ["message", "content"]),
    getPath(event, ["raw", "content"]),
    getPath(event, ["body", "content"]),
    itemListText(event?.item_list),
    itemListText(getPath(event, ["raw", "item_list"])),
    itemListText(getPath(event, ["payload", "item_list"])),
    getPath(event, ["data", "content"]),
    getPath(event, ["data", "text"]),
    getPath(event, ["data", "message", "content"]),
    itemListText(getPath(event, ["data", "item_list"])),
    getPath(event, ["msg", "content"]),
    getPath(event, ["msg", "text"]),
    getPath(event, ["input", "text"]),
    getPath(event, ["input", "content"]),
    getPath(event, ["detail", "content"]),
    getPath(event, ["detail", "text"])
  );
}

function normalizeQqText(text, qqFaceMap) {
  const trimmed = String(text || "").trim();
  if (!trimmed) return "";

  const normalized = trimmed.replace(QQ_FACE_PLACEHOLDER_RE, (_match, faceId) => {
    const label = qqFaceMap[String(faceId)];
    return label ? `[QQ表情：${label}]` : `[QQ表情 faceId=${faceId}]`;
  }).trim();
  if (!normalized && QQ_FACE_PLACEHOLDER_RE.test(trimmed)) return "[QQ表情]";
  return normalized || trimmed;
}

function extractUserId(event, ctx) {
  return firstString(
    getPath(event, ["author", "user_openid"]),
    getPath(event, ["author", "id"]),
    event?.senderId,
    event?.userId,
    getPath(event, ["peer", "id"]),
    getPath(event, ["from", "id"]),
    ctx?.senderId
  );
}

function extractGroupIdFromConversationId(value) {
  const text = firstString(value);
  if (!text) return "";

  const prefixed = text.match(/^qqbot:(group|guild|channel):(.+)$/i);
  if (prefixed) return prefixed[2];

  const bare = text.match(/^(group|guild|channel):(.+)$/i);
  if (bare) return bare[2];

  return "";
}

function extractGroupId(event, ctx) {
  return firstString(
    event?.group_id,
    event?.groupId,
    event?.guildId,
    getPath(event, ["conversation", "groupId"]),
    getPath(event, ["peer", "groupId"]),
    getPath(event, ["metadata", "group_id"]),
    getPath(event, ["metadata", "groupId"]),
    getPath(event, ["metadata", "guildId"]),
    extractGroupIdFromConversationId(ctx?.conversationId),
    extractGroupIdFromConversationId(ctx?.chatId)
  );
}

function extractWxUserId(event) {
  return extractWxUserIdentity(event).userId;
}

function extractIdentityField(value, fields) {
  const direct = firstString(value);
  if (direct) return { id: direct, field: "" };
  if (!isObject(value) || Array.isArray(value)) return { id: "", field: "" };

  for (const field of fields) {
    const id = firstString(getPath(value, [field]));
    if (id) return { id, field };
  }
  return { id: "", field: "" };
}

const WX_ID_FIELDS = [
  "id",
  "userId",
  "user_id",
  "openid",
  "openId",
  "unionid",
  "unionId",
  "contactId",
  "peerId",
  "value",
  "raw",
  "key",
  "wxid",
  "wechatId"
];

const WX_SESSION_FIELD = "session" + "Key";

const WX_SESSION_ID_FIELDS = [
  "id",
  "userId",
  "user_id",
  "openid",
  "openId",
  "contactId",
  "peerId",
  "value",
  "raw",
  "key",
  "wxid",
  "wechatId"
];

function extractWxUserIdentity(event) {
  const candidates = [
    ["from_user_id", event?.from_user_id],
    ["senderId", event?.senderId],
    ["userId", event?.userId],
    ["author.id", getPath(event, ["author", "id"])],
    ["peer.id", getPath(event, ["peer", "id"])],
    ["from.id", getPath(event, ["from", "id"])],
    ["raw.from_user_id", getPath(event, ["raw", "from_user_id"])],
    ["payload.from_user_id", getPath(event, ["payload", "from_user_id"])],
    ["data.from_user_id", getPath(event, ["data", "from_user_id"])],
    ["data.senderId", getPath(event, ["data", "senderId"])],
    ["data.userId", getPath(event, ["data", "userId"])],
    ["msg.from_user_id", getPath(event, ["msg", "from_user_id"])],
    ["msg.senderId", getPath(event, ["msg", "senderId"])],
    ["detail.from_user_id", getPath(event, ["detail", "from_user_id"])],
    ["detail.senderId", getPath(event, ["detail", "senderId"])],
    ["contact.id", getPath(event, ["contact", "id"])],
    ["sender.id", getPath(event, ["sender", "id"])]
  ];

  for (const [source, value] of candidates) {
    const id = firstString(value);
    if (id) return { userId: id, source };
  }

  const sender = extractIdentityField(event?.senderId, WX_ID_FIELDS);
  if (sender.id) {
    return { userId: sender.id, source: sender.field ? `senderId.${sender.field}` : "senderId" };
  }

  const session = extractWxSessionId(event);
  if (session.id) {
    return { userId: session.id, source: session.source };
  }

  return { userId: "", source: "" };
}

function extractWxSessionId(event) {
  const session = extractIdentityField(event?.[WX_SESSION_FIELD], WX_SESSION_ID_FIELDS);
  if (session.id) {
    return { id: session.id, source: session.field ? `${WX_SESSION_FIELD}.${session.field}` : WX_SESSION_FIELD };
  }
  return { id: "", source: "" };
}

function extractWxGroupId(event) {
  return firstString(
    event?.group_id,
    event?.groupId,
    event?.room_id,
    event?.roomId,
    getPath(event, ["conversation", "groupId"]),
    getPath(event, ["peer", "groupId"]),
    getPath(event, ["raw", "room_id"]),
    getPath(event, ["payload", "room_id"]),
    getPath(event, ["data", "room_id"]),
    getPath(event, ["data", "group_id"]),
    getPath(event, ["msg", "room_id"]),
    getPath(event, ["detail", "room_id"]),
    getPath(event, ["room", "id"]),
    getPath(event, ["chat", "id"])
  );
}

function isGroupChat(event, groupId) {
  const chatType = firstString(event?.chatType, getPath(event, ["metadata", "chatType"])).toLowerCase();
  const peerKind = firstString(getPath(event, ["peer", "kind"]), getPath(event, ["conversation", "kind"])).toLowerCase();
  return event?.isGroup === true ||
    Boolean(groupId) ||
    chatType === "group" ||
    chatType === "guild" ||
    peerKind === "group" ||
    peerKind === "guild";
}

function maskId(value) {
  const text = String(value || "");
  if (text.length <= 8) return text ? "***" : "unknown";
  return `${text.slice(0, 4)}...${text.slice(-4)}`;
}

function loadJsonFile(filePath, fallback) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

function loadQqFaceMap() {
  const data = loadJsonFile(QQ_FACE_MAP_PATH, {});
  if (!isObject(data) || Array.isArray(data)) return {};

  const map = {};
  for (const [faceId, label] of Object.entries(data)) {
    if (typeof label === "string" && label.trim()) {
      map[String(faceId)] = label.trim();
    }
  }
  return map;
}

function loadAllowedQqUsers() {
  const data = loadJsonFile(ALLOWED_QQ_USERS_PATH, null);
  if (!Array.isArray(data)) return new Set();

  return new Set(
    data
      .filter((userId) => typeof userId === "string" && userId.trim())
      .map((userId) => userId.trim())
  );
}

function loadAllowedWxUsers() {
  const data = loadJsonFile(ALLOWED_WX_USERS_PATH, null);
  if (!Array.isArray(data)) return new Set();

  return new Set(
    data
      .filter((userId) => typeof userId === "string" && userId.trim())
      .map((userId) => userId.trim())
  );
}

function formatMaskedUserList(userIds) {
  return [...userIds].map(maskId).join(", ") || "none";
}

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body)
  });
  res.end(body);
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let raw = "";

    req.setEncoding("utf8");
    req.on("data", (chunk) => {
      raw += chunk;
      if (Buffer.byteLength(raw) > PROACTIVE_MAX_BODY_BYTES) {
        reject(new Error("request body too large"));
        req.destroy();
      }
    });
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        reject(new Error("invalid json"));
      }
    });
    req.on("error", reject);
  });
}

function normalizeCandidateId(value) {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value === "number" && Number.isInteger(value) && value > 0) return value;
  if (typeof value === "string" && /^\d+$/.test(value.trim())) return Number(value.trim());
  return undefined;
}

function sanitizeErrorMessage(err) {
  const text = err?.message || String(err || "send failed");
  return text.replace(/[A-Za-z0-9_-]{16,}/g, "***").slice(0, 120);
}

function validateProactiveSendQqPayload(payload) {
  if (!isObject(payload) || Array.isArray(payload)) {
    return { ok: false, status: 400, error: "request body must be a JSON object" };
  }

  if (typeof payload.dry_run !== "boolean") {
    return { ok: false, status: 400, error: "dry_run must be a boolean" };
  }

  const candidateId = normalizeCandidateId(payload.candidate_id);
  if (candidateId === undefined) {
    return { ok: false, status: 400, error: "candidate_id must be a positive integer" };
  }

  if (typeof payload.message !== "string") {
    return { ok: false, status: 400, error: "message must be a string" };
  }

  const message = payload.message.trim();
  if (!message) {
    return { ok: false, status: 400, error: "message must not be empty" };
  }
  if (message.length > PROACTIVE_MAX_MESSAGE_LENGTH) {
    return { ok: false, status: 400, error: `message must be ${PROACTIVE_MAX_MESSAGE_LENGTH} characters or fewer` };
  }

  return { ok: true, candidateId, message, dryRun: payload.dry_run };
}

async function handleProactiveSendQq(req, res, api) {
  let payload;
  try {
    payload = await readJsonBody(req);
  } catch (err) {
    sendJson(res, 400, { success: false, error: err?.message || "invalid request" });
    return;
  }

  const validation = validateProactiveSendQqPayload(payload);
  if (!validation.ok) {
    sendJson(res, validation.status, { success: false, error: validation.error });
    return;
  }

  const allowedQqUsers = loadAllowedQqUsers();
  if (allowedQqUsers.size !== 1) {
    sendJson(res, 400, {
      success: false,
      error: "qq allowlist must contain exactly one user"
    });
    return;
  }

  const [openid] = [...allowedQqUsers];
  const target = ["qqbot", "c2c", openid].join(":");
  const targetLabel = maskId(openid);

  if (validation.dryRun) {
    api.logger?.info?.(
      `[neno-bridge] proactive qq dry_run candidate=${validation.candidateId ?? "none"} target=${targetLabel} len=${validation.message.length}`
    );

    sendJson(res, 200, {
      success: true,
      dry_run: true,
      target_label: targetLabel,
      message_len: validation.message.length,
      would_send: true
    });
    return;
  }

  api.logger?.info?.(
    `[neno-bridge] proactive qq send candidate=${validation.candidateId ?? "none"} target=${targetLabel} len=${validation.message.length}`
  );

  try {
    const outbound = await api.runtime.channel.outbound.loadAdapter("qqbot");
    if (!outbound?.sendText) {
      throw new Error("qqbot outbound adapter unavailable");
    }

    const result = await outbound.sendText({
      cfg: api.config,
      to: target,
      text: validation.message,
      accountId: "default"
    });
    const sendError = result?.meta?.error;
    if (sendError) {
      throw new Error(String(sendError));
    }

    api.logger?.info?.(`[neno-bridge] proactive qq send ok candidate=${validation.candidateId ?? "none"}`);
    sendJson(res, 200, {
      success: true,
      dry_run: false,
      sent: true,
      target_label: targetLabel,
      message_len: validation.message.length
    });
  } catch (err) {
    api.logger?.warn?.(
      `[neno-bridge] proactive qq send failed candidate=${validation.candidateId ?? "none"} error=${sanitizeErrorMessage(err)}`
    );
    sendJson(res, 500, { success: false, error: "send failed" });
  }
}

function startProactiveServer(api) {
  const server = http.createServer((req, res) => {
    const requestUrl = new URL(req.url || "/", `http://${PROACTIVE_HOST}:${PROACTIVE_PORT}`);
    if (req.method !== "POST" || requestUrl.pathname !== PROACTIVE_SEND_QQ_PATH) {
      sendJson(res, 404, { success: false, error: "not found" });
      return;
    }

    handleProactiveSendQq(req, res, api).catch((err) => {
      api.logger?.warn?.(`[neno-bridge] proactive qq request failed: ${sanitizeErrorMessage(err)}`);
      if (!res.headersSent) {
        sendJson(res, 500, { success: false, error: "send failed" });
      } else {
        res.end();
      }
    });
  });

  server.on("error", (err) => {
    api.logger?.warn?.(`[neno-bridge] proactive server unavailable: ${sanitizeErrorMessage(err)}`);
  });

  server.listen(PROACTIVE_PORT, PROACTIVE_HOST, () => {
    api.logger?.info?.(`[neno-bridge] proactive server listening on ${PROACTIVE_HOST}:${PROACTIVE_PORT}`);
  });

  return server;
}

function safeLogSummary(event, ctx) {
  return {
    channel: detectChannel(event, ctx) || "unknown",
    hasContent: Boolean(extractText(event)),
    sender: maskId(extractUserId(event, ctx)),
    isGroup: event?.isGroup === true
  };
}

function describeSafeValue(value) {
  if (value === undefined) return { present: false };
  if (value === null) return { present: true, type: "null" };
  if (typeof value === "string") {
    return { present: true, type: "string", len: value.length };
  }
  if (Array.isArray(value)) {
    return {
      present: true,
      type: "array",
      len: value.length,
      itemKeys: value.map((item) => isObject(item) ? Object.keys(item) : [])
    };
  }
  if (isObject(value)) {
    return { present: true, type: "object", keys: Object.keys(value) };
  }
  return { present: true, type: typeof value };
}

function describeSafeObjectFields(value) {
  if (!isObject(value) || Array.isArray(value)) return {};
  const summary = {};
  for (const [key, child] of Object.entries(value)) {
    summary[key] = describeSafeValue(child);
  }
  return summary;
}

function safeInspectWxEvent(event) {
  const paths = {
    content: ["content"],
    text: ["text"],
    message: ["message"],
    "message.content": ["message", "content"],
    raw: ["raw"],
    "raw.content": ["raw", "content"],
    body: ["body"],
    "body.content": ["body", "content"],
    payload: ["payload"],
    "payload.content": ["payload", "content"],
    item_list: ["item_list"],
    "raw.item_list": ["raw", "item_list"],
    "payload.item_list": ["payload", "item_list"],
    data: ["data"],
    "data.content": ["data", "content"],
    "data.item_list": ["data", "item_list"],
    msg: ["msg"],
    "msg.content": ["msg", "content"],
    input: ["input"],
    "input.text": ["input", "text"]
  };
  const pathSummary = {};
  for (const [name, keys] of Object.entries(paths)) {
    pathSummary[name] = describeSafeValue(getPath(event, keys));
  }

  return {
    topKeys: isObject(event) ? Object.keys(event) : [],
    eventSummary: {
      channel: describeSafeValue(event?.channel),
      type: describeSafeValue(event?.type),
      eventType: describeSafeValue(event?.eventType),
      kind: describeSafeValue(event?.kind),
      name: describeSafeValue(event?.name),
      senderId: describeSafeValue(event?.senderId),
      senderIdFields: describeSafeObjectFields(event?.senderId),
      [WX_SESSION_FIELD]: describeSafeValue(event?.[WX_SESSION_FIELD]),
      [`${WX_SESSION_FIELD}Fields`]: describeSafeObjectFields(event?.[WX_SESSION_FIELD]),
      isGroup: {
        present: isObject(event) && "isGroup" in event,
        type: typeof event?.isGroup,
        value: event?.isGroup
      }
    },
    pathSummary
  };
}

function logWxDebug(api, reason, event) {
  if (wxDebugCount >= WX_DEBUG_LIMIT) {
    if (wxDebugCount === WX_DEBUG_LIMIT) {
      api.logger?.warn?.("[neno-bridge][wx-debug] suppressed");
    }
    wxDebugCount += 1;
    return;
  }

  wxDebugCount += 1;
  const summary = safeInspectWxEvent(event);
  api.logger?.warn?.(`[neno-bridge][wx-debug] extraction failed: ${reason}`);
  api.logger?.warn?.(`[neno-bridge][wx-debug] topKeys=${JSON.stringify(summary.topKeys)}`);
  api.logger?.warn?.(`[neno-bridge][wx-debug] eventSummary=${JSON.stringify(summary.eventSummary)}`);
  api.logger?.warn?.(`[neno-bridge][wx-debug] pathSummary=${JSON.stringify(summary.pathSummary)}`);
}

async function postToNeno(payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);
  const headers = { "Content-Type": "application/json" };

  try {
    const response = await fetch(ENDPOINT, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal
    });
    const raw = await response.text();
    let data = {};
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch {
      data = {};
    }
    if (!response.ok) {
      throw new Error(`Neno returned HTTP ${response.status}`);
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

async function qqAdapter({ event, ctx, api, qqFaceMap, allowedQqUsers }) {
  const userId = extractUserId(event, ctx);
  if (!userId) {
    api.logger?.warn?.(`[neno-bridge] missing user info ${JSON.stringify(safeLogSummary(event, ctx))}`);
    return { handled: true, text: MISSING_USER_REPLY };
  }

  if (!allowedQqUsers.has(userId)) {
    api.logger?.warn?.(`[neno-bridge] rejected qq user=${maskId(userId)} not in allowlist`);
    return { handled: true, text: QQ_NOT_ALLOWED_REPLY };
  }

  const rawText = extractText(event);
  const text = normalizeQqText(rawText, qqFaceMap);
  if (!text) {
    api.logger?.info?.(`[neno-bridge] handled unsupported qq message ${JSON.stringify(safeLogSummary(event, ctx))}`);
    return { handled: true, text: UNSUPPORTED_MESSAGE_REPLY };
  }

  const groupIdRaw = extractGroupId(event, ctx);
  const chatType = isGroupChat(event, groupIdRaw) ? "group" : "private";
  const groupId = chatType === "group" ? groupIdRaw || null : null;

  api.logger?.info?.(
    `[neno-bridge] received qq text from user=${maskId(userId)} chat_type=${chatType} len=${text.length}`
  );

  return sendToNeno(api, {
    platform: "qq",
    user_id: userId,
    chat_type: chatType,
    group_id: groupId,
    message: text
  });
}

async function wxAdapter({ event, api, allowedWxUsers }) {
  const text = extractWxText(event);
  if (!text) {
    logWxDebug(api, "no text", event);
    return { handled: true, text: UNSUPPORTED_MESSAGE_REPLY };
  }

  const identity = extractWxUserIdentity(event);
  const userId = identity.userId;
  if (!userId) {
    logWxDebug(api, "no user_id", event);
    return { handled: true, text: WX_MISSING_USER_REPLY };
  }

  if (identity.source.startsWith(WX_SESSION_FIELD)) {
    logWxDebug(api, "senderId unresolved; using session fallback", event);
    api.logger?.info?.(`[neno-bridge] using wx session fallback for user=${maskId(userId)}`);
  }

  if (!allowedWxUsers.has(userId)) {
    api.logger?.warn?.(`[neno-bridge] blocked wx user=${maskId(userId)}`);
    return { handled: true, text: WX_NOT_ALLOWED_REPLY };
  }

  const session = extractWxSessionId(event);
  const chatType = event?.isGroup === true ? "group" : "private";
  const groupId = chatType === "group" ? extractWxGroupId(event) || session.id || null : null;

  api.logger?.info?.(
    `[neno-bridge] received wx text from user=${maskId(userId)} chat_type=${chatType} len=${text.length}`
  );

  return sendToNeno(api, {
    platform: "wx",
    user_id: userId,
    chat_type: chatType,
    group_id: groupId,
    message: text
  });
}

async function sendToNeno(api, payload) {
  try {
    const data = await postToNeno(payload);
    const reply = typeof data?.reply === "string" ? data.reply.trim() : "";
    if (data?.success === true && reply) {
      api.logger?.info?.(`[neno-bridge] replied len=${reply.length}`);
      return { handled: true, text: reply };
    }
    api.logger?.warn?.("[neno-bridge] Neno response missing success=true or reply");
    return { handled: true, text: FAILURE_REPLY };
  } catch (err) {
    api.logger?.warn?.(`[neno-bridge] Neno request failed: ${err?.message || String(err)}`);
    return { handled: true, text: FAILURE_REPLY };
  }
}

function channelAdapter(channel) {
  if (channel === "qqbot") return qqAdapter;
  if (channel === "openclaw-weixin") return wxAdapter;
  return null;
}

assertEndpointAllowed();

const plugin = {
  id: "neno-bridge",
  name: "Neno Bridge",
  description: "Forward QQBot and Weixin text messages to local Neno backend.",
  register(api) {
    const qqFaceMap = loadQqFaceMap();
    const allowedQqUsers = loadAllowedQqUsers();
    const allowedWxUsers = loadAllowedWxUsers();
    let proactiveServer = null;

    api.logger?.info?.("[neno-bridge] loaded");
    api.logger?.info?.(`[neno-bridge] loaded qq face map count=${Object.keys(qqFaceMap).length}`);
    api.logger?.info?.(
      `[neno-bridge] loaded qq allowlist count=${allowedQqUsers.size} users=${formatMaskedUserList(allowedQqUsers)}`
    );
    api.logger?.info?.(
      `[neno-bridge] loaded wx allowlist count=${allowedWxUsers.size} users=${formatMaskedUserList(allowedWxUsers)}`
    );

    api.on("before_dispatch", async (event, ctx) => {
      const channel = detectChannel(event, ctx);
      const adapter = channelAdapter(channel);
      if (!adapter) return undefined;

      return adapter({ event, ctx, api, qqFaceMap, allowedQqUsers, allowedWxUsers });
    });

    api.registerService?.({
      id: "neno-bridge-proactive",
      start() {
        proactiveServer = startProactiveServer(api);
      },
      stop() {
        if (!proactiveServer) return;
        const server = proactiveServer;
        proactiveServer = null;
        return new Promise((resolve) => {
          server.close(() => resolve());
        });
      }
    });
  }
};

export default plugin;
