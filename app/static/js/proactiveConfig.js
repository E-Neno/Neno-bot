import { getAdminHeaders, getAdminToken, requestJson } from "./api.js";
import { createElement, setOptionalText } from "./dom.js";
import { loadProactiveStatus } from "./proactiveStatus.js";

function setInputValue(id, value) {
  const input = document.getElementById(id);
  if (input) {
    input.value = value ?? "";
  }
}

function readNumberInput(id) {
  const value = document.getElementById(id).value;
  return Number(value);
}

const proactiveModeInfo = {
  off: {
    description: "关闭，不生成不发送",
    usage: "临时停用、维护或确认配置时使用",
    risk: "低",
  },
  observe: {
    description: "只观察，只记录判断",
    usage: "验证规则是否会命中，不产生候选",
    risk: "低",
  },
  candidate: {
    description: "只生成 pending 候选",
    usage: "先人工审核内容，再手动处理",
    risk: "中低",
  },
  dry_run: {
    description: "演习发送，不真实发消息",
    usage: "验证自动发送链路和保护规则",
    risk: "中",
  },
  auto: {
    description: "自动真实发送（当前按 QQ-first 收口）",
    usage: "确认 QQ 主路径、权限、上限和冷却后使用；不要把 WX 视为已完成 auto 平台化",
    risk: "高",
  },
};

const proactiveFieldHelpTexts = {
  proactiveModeInput: "主配置。off 关闭；observe 只记录；candidate 只生成 pending；dry_run 演习；auto 才会自动真实发送。当前合并边界按 QQ-first 收口。",
  proactiveActiveStartInput: "每天从这个时间以后才允许主动调度。",
  proactiveActiveEndInput: "每天超过这个时间后不再主动调度。",
  proactiveRecentSkipInput: "最近聊过就跳过，避免打扰。",
  proactiveMinIntervalInput: "两次主动消息之间至少间隔这么久。",
  proactiveDailyLimitInput: "每天最多自动主动发送几条。",
  proactiveHardCooldownInput: "生成、发送或 dry_run 后的额外冷却时间。",
  proactiveFailurePauseThresholdInput: "连续失败达到阈值后，自动调度会暂停。",
  proactiveAutoSendMaxPerDayInput: "自动真实发送的每日上限。",
  proactiveAutoSendRequireAllowedInput: "自动真实发送前是否要求目标 allowed。当前这个开关主要约束 QQ auto 路径。",
  proactiveRandomProbabilityInput: "每次检查进入后续判断的随机概率。",
  proactiveAllowedHashesInput: "允许自动发送的 QQ 目标 hash，多个用英文逗号分隔。当前 auto 收口按 QQ-first，这里仍是主约束。",
  proactiveBridgeUrlInput: "Neno Bridge 本地 QQ 发送接口地址。当前配置面板里的 auto 说明主要围绕 QQ 主路径。",
  proactiveEnabledInput: "旧兼容开关。实际运行优先看 PROACTIVE_MODE。",
  proactiveAutoSendInput: "旧兼容开关。实际运行优先看 PROACTIVE_MODE。",
  proactiveAutoSendDryRunInput: "旧兼容开关。实际运行优先看 PROACTIVE_MODE。",
  proactiveCheckIntervalInput: "后台自动调度的检查频率，不是发送间隔。",
};

const proactiveConfigGroups = [
  {
    title: "模式卡片",
    description: "PROACTIVE_MODE 决定主动消息的运行层级。",
    fieldIds: ["proactiveModeInput"],
    modeCard: true,
    open: true,
  },
  {
    title: "常用设置",
    description: "日常最常调整的时间窗、频率和冷却规则。",
    fieldIds: [
      "proactiveActiveStartInput",
      "proactiveActiveEndInput",
      "proactiveRecentSkipInput",
      "proactiveMinIntervalInput",
      "proactiveDailyLimitInput",
      "proactiveHardCooldownInput",
    ],
    open: true,
  },
  {
    title: "自动发送保护",
    description: "这些是自动发送的保险措施，主要在 dry_run / auto 模式下生效。",
    fieldIds: [
      "proactiveFailurePauseThresholdInput",
      "proactiveAutoSendMaxPerDayInput",
      "proactiveAutoSendRequireAllowedInput",
    ],
    open: true,
  },
  {
    title: "高级与兼容",
    description: "一般不用改，主要用于兼容旧逻辑或排查问题。",
    fieldIds: [
      "proactiveRandomProbabilityInput",
      "proactiveAllowedHashesInput",
      "proactiveBridgeUrlInput",
      "proactiveEnabledInput",
      "proactiveAutoSendInput",
      "proactiveAutoSendDryRunInput",
      "proactiveCheckIntervalInput",
    ],
    extraNodeIds: ["proactiveAllowedHashesPreview"],
    open: false,
  },
];

function setConfigFieldHelpText(field, fieldId) {
  const help = field?.querySelector(".config-help");
  const text = proactiveFieldHelpTexts[fieldId];
  if (help && text) {
    help.textContent = text;
  }
}

function findConfigFieldByInputId(id) {
  const field = document.getElementById(id)?.closest(".config-field") || null;
  setConfigFieldHelpText(field, id);
  return field;
}

function appendModeInfoRow(container, label, valueId) {
  const row = document.createElement("div");
  row.className = "candidate-meta";
  const name = document.createElement("b");
  name.textContent = `${label}：`;
  const value = document.createElement("span");
  value.id = valueId;
  value.textContent = "-";
  row.append(name, value);
  container.appendChild(row);
}

function updateProactiveModeCard() {
  const mode = document.getElementById("proactiveModeInput")?.value || "off";
  const info = proactiveModeInfo[mode] || proactiveModeInfo.off;
  setOptionalText("proactiveModeCardCurrent", mode);
  setOptionalText("proactiveModeCardDescription", info.description);
  setOptionalText("proactiveModeCardUsage", info.usage);
  setOptionalText("proactiveModeCardRisk", info.risk);
}

function createProactiveModeSummary() {
  const summary = createElement("div", "config-help");
  appendModeInfoRow(summary, "当前 PROACTIVE_MODE", "proactiveModeCardCurrent");
  appendModeInfoRow(summary, "中文说明", "proactiveModeCardDescription");
  appendModeInfoRow(summary, "推荐用途", "proactiveModeCardUsage");
  appendModeInfoRow(summary, "风险等级", "proactiveModeCardRisk");

  const priority = document.createElement("div");
  priority.textContent = "PROACTIVE_MODE 是主配置，优先于 enabled / auto send / auto send dry_run 旧兼容开关。";
  summary.appendChild(priority);

  const allModes = document.createElement("div");
  allModes.textContent = "模式：off 关闭，不生成不发送；observe 只观察，只记录判断；candidate 只生成 pending 候选；dry_run 演习发送，不真实发消息；auto 自动真实发送，但当前分支按 QQ-first 收口。";
  summary.appendChild(allModes);

  return summary;
}

function createConfigSection(group) {
  if (group.modeCard) {
    const section = document.createElement("div");
    section.appendChild(createElement("div", "status-value", group.title));
    section.appendChild(createElement("div", "config-help", group.description));

    const grid = createElement("div", "proactive-config-grid");
    for (const fieldId of group.fieldIds) {
      const field = findConfigFieldByInputId(fieldId);
      if (field) {
        grid.appendChild(field);
      }
    }
    section.appendChild(grid);
    section.appendChild(createProactiveModeSummary());
    return section;
  }

  const details = document.createElement("details");
  details.open = group.open === true;

  const summary = document.createElement("summary");
  summary.textContent = group.title;
  details.appendChild(summary);
  details.appendChild(createElement("div", "config-help", group.description));

  const grid = createElement("div", "proactive-config-grid");
  for (const fieldId of group.fieldIds) {
    const field = findConfigFieldByInputId(fieldId);
    if (field) {
      grid.appendChild(field);
    }
  }
  details.appendChild(grid);

  for (const nodeId of group.extraNodeIds || []) {
    const node = document.getElementById(nodeId);
    if (node) {
      details.appendChild(node);
    }
  }

  return details;
}

function appendConfigGroup(container, group) {
  container.appendChild(createConfigSection(group));
}

export function organizeProactiveConfigForm() {
  const form = document.getElementById("proactiveModeInput")?.closest(".config-form");
  if (!form || form.dataset.organized === "true") {
    return;
  }

  form.dataset.organized = "true";
  form.classList.remove("proactive-config-grid");

  const groups = document.createElement("div");
  groups.className = "config-form";

  for (const group of proactiveConfigGroups) {
    appendConfigGroup(groups, group);
  }

  form.replaceChildren(groups);
  document.getElementById("proactiveModeInput")?.addEventListener("change", updateProactiveModeCard);
  updateProactiveModeCard();
}

function renderProactiveConfig(data) {
  const config = data.config || {};
  const hashesInput = document.getElementById("proactiveAllowedHashesInput");
  const hashesPreview = document.getElementById("proactiveAllowedHashesPreview");
  const labels = config.PROACTIVE_QQ_ALLOWED_TARGET_HASHES_LABELS || [];

  setInputValue("proactiveEnabledInput", config.PROACTIVE_ENABLED || "false");
  setInputValue("proactiveModeInput", config.PROACTIVE_MODE || "off");
  setInputValue("proactiveCheckIntervalInput", config.PROACTIVE_CHECK_INTERVAL_SECONDS);
  setInputValue("proactiveDailyLimitInput", config.PROACTIVE_DAILY_LIMIT);
  setInputValue("proactiveMinIntervalInput", config.PROACTIVE_MIN_INTERVAL_MINUTES);
  setInputValue("proactiveRecentSkipInput", config.PROACTIVE_RECENT_CHAT_SKIP_MINUTES);
  setInputValue("proactiveHardCooldownInput", config.PROACTIVE_HARD_COOLDOWN_MINUTES || "10");
  setInputValue("proactiveFailurePauseThresholdInput", config.PROACTIVE_FAILURE_PAUSE_THRESHOLD || "3");
  setInputValue("proactiveActiveStartInput", config.PROACTIVE_ACTIVE_START);
  setInputValue("proactiveActiveEndInput", config.PROACTIVE_ACTIVE_END);
  setInputValue("proactiveRandomProbabilityInput", config.PROACTIVE_RANDOM_PROBABILITY);
  setInputValue("proactiveAutoSendInput", config.PROACTIVE_AUTO_SEND || "false");
  setInputValue("proactiveAutoSendDryRunInput", config.PROACTIVE_AUTO_SEND_DRY_RUN || "false");
  setInputValue("proactiveAutoSendRequireAllowedInput", config.PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET || "true");
  setInputValue("proactiveAutoSendMaxPerDayInput", config.PROACTIVE_AUTO_SEND_MAX_PER_DAY || "1");
  setInputValue("proactiveBridgeUrlInput", config.NENO_BRIDGE_SEND_QQ_URL);

  if (hashesInput) {
    hashesInput.value = "";
    hashesInput.dataset.dirty = "false";
    hashesInput.placeholder = labels.length ? "留空保留当前白名单；输入逗号分隔 hash 覆盖" : "为空；输入逗号分隔 hash 覆盖";
  }

  if (hashesPreview) {
    hashesPreview.textContent = labels.length
      ? `当前白名单：${labels.join(", ")}`
      : "当前白名单为空";
  }

  updateProactiveModeCard();
}

export async function loadProactiveConfig() {
  const status = document.getElementById("proactiveConfigStatus");
  const token = getAdminToken();

  if (!token) {
    status.textContent = "需要 Admin Token";
    return;
  }

  status.textContent = "加载配置中...";
  try {
    const data = await requestJson(
      "/proactive/config",
      {
        method: "GET",
        headers: getAdminHeaders(),
      },
      "加载配置失败："
    );
    renderProactiveConfig(data);
    status.textContent = "配置已刷新";
    loadProactiveStatus();
  } catch (err) {
    status.textContent = err.message;
  }
}

export async function saveProactiveConfig() {
  const status = document.getElementById("proactiveConfigStatus");
  const token = getAdminToken();

  if (!token) {
    status.textContent = "需要 Admin Token";
    return;
  }

  const hashesInput = document.getElementById("proactiveAllowedHashesInput");
  const payload = {
    PROACTIVE_ENABLED: document.getElementById("proactiveEnabledInput").value === "true",
    PROACTIVE_MODE: document.getElementById("proactiveModeInput").value,
    PROACTIVE_CHECK_INTERVAL_SECONDS: readNumberInput("proactiveCheckIntervalInput"),
    PROACTIVE_DAILY_LIMIT: readNumberInput("proactiveDailyLimitInput"),
    PROACTIVE_MIN_INTERVAL_MINUTES: readNumberInput("proactiveMinIntervalInput"),
    PROACTIVE_RECENT_CHAT_SKIP_MINUTES: readNumberInput("proactiveRecentSkipInput"),
    PROACTIVE_HARD_COOLDOWN_MINUTES: readNumberInput("proactiveHardCooldownInput"),
    PROACTIVE_FAILURE_PAUSE_THRESHOLD: readNumberInput("proactiveFailurePauseThresholdInput"),
    PROACTIVE_ACTIVE_START: document.getElementById("proactiveActiveStartInput").value,
    PROACTIVE_ACTIVE_END: document.getElementById("proactiveActiveEndInput").value,
    PROACTIVE_RANDOM_PROBABILITY: Number(document.getElementById("proactiveRandomProbabilityInput").value),
    PROACTIVE_AUTO_SEND: document.getElementById("proactiveAutoSendInput").value === "true",
    PROACTIVE_AUTO_SEND_DRY_RUN: document.getElementById("proactiveAutoSendDryRunInput").value === "true",
    PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET: document.getElementById("proactiveAutoSendRequireAllowedInput").value === "true",
    PROACTIVE_AUTO_SEND_MAX_PER_DAY: readNumberInput("proactiveAutoSendMaxPerDayInput"),
    NENO_BRIDGE_SEND_QQ_URL: document.getElementById("proactiveBridgeUrlInput").value.trim(),
  };

  if (hashesInput?.dataset.dirty === "true") {
    payload.PROACTIVE_QQ_ALLOWED_TARGET_HASHES = hashesInput.value.trim();
  }

  status.textContent = "保存配置中...";
  try {
    await requestJson(
      "/proactive/config",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify(payload),
      },
      "保存配置失败："
    );
    await loadProactiveConfig();
    status.textContent = "已保存，需要执行 nereboot 或 sudo systemctl restart emotion-bot.service 生效。重启后刷新状态。";
  } catch (err) {
    status.textContent = err.message;
  }
}
