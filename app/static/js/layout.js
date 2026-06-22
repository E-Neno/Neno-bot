import { createElement, setOptionalText } from "./dom.js";

export const panelDefinitions = [
  ["overviewPanel", "总览"],
  ["chatPanel", "聊天"],
  ["consciousnessPanel", "大脑"],
  ["proactivePanel", "主动"],
  ["memoryPanel", "记忆"],
  ["configPanel", "配置"],
  ["debugPanel", "日志"],
];

// 导航图标（内联 SVG，stroke=currentColor，不依赖在线图标字体）
const NAV_ICONS = {
  overviewPanel: '<path d="M4 4h7v7H4z"/><path d="M13 4h7v4h-7z"/><path d="M13 11h7v9h-7z"/><path d="M4 14h7v6H4z"/>',
  chatPanel: '<path d="M4 6h16v10H8l-4 3z"/>',
  consciousnessPanel: '<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-1 5 3 3 0 0 0 2 4 3 3 0 0 0 5 1V4z"/><path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 1 5 3 3 0 0 1-2 4 3 3 0 0 1-5 1"/>',
  proactivePanel: '<path d="M6 8a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  memoryPanel: '<path d="M6 4h11a2 2 0 0 1 2 2v14l-6-3-6 3V4z"/>',
  configPanel: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
  debugPanel: '<path d="M4 5h16v14H4z"/><path d="M8 9l3 3-3 3M13 15h4"/>',
};

export function getCardByElementId(id) {
  return document.getElementById(id)?.closest(".card") || null;
}

export function createPanel(id, title, subtitle) {
  const panel = createElement("section", "console-panel");
  panel.id = id;
  panel.dataset.panelTitle = title;
  panel.dataset.panelSubtitle = subtitle;

  const header = createElement("div", "panel-header");
  const textBox = createElement("div");
  textBox.append(
    createElement("div", "panel-title", title),
    createElement("div", "panel-subtitle", subtitle)
  );
  header.appendChild(textBox);
  panel.appendChild(header);

  return { panel, header };
}

let _panelActivateCallbacks = {};

export function onPanelActivate(panelId, callback) {
  _panelActivateCallbacks[panelId] = callback;
}

export function setActivePanel(panelId) {
  const prev = document.querySelector(".console-panel.active");
  const prevId = prev?.id;

  for (const panel of document.querySelectorAll(".console-panel")) {
    panel.classList.toggle("active", panel.id === panelId);
  }
  for (const button of document.querySelectorAll(".console-nav [data-panel-target]")) {
    button.classList.toggle("active", button.dataset.panelTarget === panelId);
  }
  const isChatPanel = panelId === "chatPanel";
  document.body.classList.toggle("chat-panel-active", isChatPanel);
  document.querySelector(".app")?.classList.toggle("chat-panel-active", isChatPanel);

  const activePanel = document.getElementById(panelId);
  const activeTitle = activePanel?.dataset.panelTitle || activePanel?.querySelector(".panel-title")?.textContent || panelId;
  const activeSubtitle = activePanel?.dataset.panelSubtitle || activePanel?.querySelector(".panel-header .panel-subtitle")?.textContent || "";
  setOptionalText("controlActiveTitle", activeTitle);
  setOptionalText("controlActiveSubtitle", activeSubtitle);
  setOptionalText("controlRailPanelName", activeTitle);
  setOptionalText("controlSidebarPanelName", activeTitle);
  setOptionalText("controlStageTitle", activeTitle);
  setOptionalText("controlStageSubtitle", activeSubtitle);

  if (prevId && prevId !== panelId && _panelActivateCallbacks[`${prevId}:deactivate`]) {
    _panelActivateCallbacks[`${prevId}:deactivate`]();
  }
  if (_panelActivateCallbacks[`${panelId}:activate`]) {
    _panelActivateCallbacks[`${panelId}:activate`]();
  }
}

export function appendStatusMetric(grid, label, id) {
  const item = createElement("div", "status-item");
  item.append(
    createElement("div", "status-label", label),
    createElement("div", "status-value", "-")
  );
  item.lastChild.id = id;
  grid.appendChild(item);
}

function addButtonClasses(button, ...classes) {
  if (button) {
    button.classList.add(...classes);
  }
}

function createProactiveSectionNav() {
  const nav = createElement("div", "proactive-section-nav");
  for (const label of ["测试区", "自动区", "候选", "目标", "时间线", "配置", "诊断"]) {
    nav.appendChild(createElement("span", "", label));
  }
  return nav;
}

function createPlatformFilter(id) {
  const wrap = createElement("div", "config-field");
  wrap.appendChild(createElement("label", "", "平台筛选"));
  const select = createElement("select");
  select.id = id;
  for (const [value, label] of [["", "全部"], ["qq", "QQ"], ["wx", "WX"]]) {
    const option = createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }
  wrap.appendChild(select);
  return wrap;
}

export function buildProactivePanel(panel, header) {
  const proactiveCard = getCardByElementId("proactiveCandidateList");
  const statusNode = document.getElementById("proactiveCandidateStatus");
  const refreshButton = document.getElementById("loadProactiveCandidatesBtn");
  const refreshTargetsButton = document.getElementById("loadProactiveTargetsBtn");
  const refreshEventsButton = document.getElementById("loadProactiveEventsBtn");
  const generateButton = document.getElementById("generateProactiveCandidateBtn");
  const generateTestButton = document.getElementById("generateProactiveTestCandidateBtn");
  const forceGenerateTestButton = document.getElementById("forceGenerateProactiveTestCandidateBtn");
  const platformForm = document.getElementById("proactivePlatformSelect")?.closest(".config-form");
  const autoStatus = document.getElementById("proactiveAutoStatus");
  const pendingList = document.getElementById("proactiveCandidateList");
  const configDetails = document.querySelector(".config-panel");

  addButtonClasses(refreshButton, "secondary", "auxiliary");
  addButtonClasses(refreshTargetsButton, "secondary", "auxiliary");
  addButtonClasses(refreshEventsButton, "secondary", "auxiliary");
  addButtonClasses(generateButton, "secondary");
  addButtonClasses(forceGenerateTestButton, "secondary");

  header.appendChild(createProactiveSectionNav());

  if (refreshButton) {
    const actions = createElement("div", "row");
    actions.appendChild(refreshButton);
    header.appendChild(actions);
  }

  if (statusNode) {
    statusNode.classList.add("panel-status");
    panel.appendChild(statusNode);
  }

  const grid = createElement("div", "console-grid");
  panel.appendChild(grid);

  const testCard = createElement("div", "control-surface");
  testCard.appendChild(createElement("h3", "", "测试区"));
  testCard.appendChild(createElement(
    "div",
    "config-help",
    "用于手动测试：生成 pending 候选，不受随机概率、最近聊天、时间窗影响，不会自动发送。QQ 仍检查 allowed/hash；WX 仍检查真实目标与权限。"
  ));
  const testRow = createElement("div", "row");
  if (generateTestButton) {
    testRow.appendChild(generateTestButton);
  }
  if (forceGenerateTestButton) {
    testRow.appendChild(forceGenerateTestButton);
  }
  testCard.appendChild(testRow);
  testCard.appendChild(createElement(
    "div",
    "config-help",
    "已有同平台 pending 候选时，自动调度不会继续生成；你仍可手动发送、丢弃，或强制生成测试候选。"
  ));
  grid.appendChild(testCard);

  const statusCard = createElement("div", "control-surface");
  statusCard.appendChild(createElement("h3", "", "自动区"));
  statusCard.appendChild(createElement(
    "div",
    "config-help",
    "这里是后台自动调度规则，不等于手动测试；自动调度优先按 PROACTIVE_MODE 运行，并受硬冷却、连续失败暂停、时间窗、每日上限、最小间隔、最近聊天、随机概率、平台权限和 pending 候选保护。"
  ));
  if (autoStatus) {
    statusCard.appendChild(autoStatus);
  }
  const statusGrid = createElement("div", "status-grid");
  appendStatusMetric(statusGrid, "当前模式", "proactiveStatusMode");
  appendStatusMetric(statusGrid, "开关", "proactiveStatusEnabled");
  appendStatusMetric(statusGrid, "任务", "proactiveStatusRunning");
  appendStatusMetric(statusGrid, "今日发送", "proactiveStatusToday");
  appendStatusMetric(statusGrid, "自动真实发送", "proactiveStatusAutoSend");
  appendStatusMetric(statusGrid, "自动 dry_run", "proactiveStatusAutoDryRun");
  appendStatusMetric(statusGrid, "自动发送今日", "proactiveStatusAutoSentToday");
  appendStatusMetric(statusGrid, "硬冷却", "proactiveStatusHardCooldown");
  appendStatusMetric(statusGrid, "连续失败", "proactiveStatusFailurePause");
  appendStatusMetric(statusGrid, "目标 allowed", "proactiveStatusAutoRequireAllowed");
  appendStatusMetric(statusGrid, "当前判断平台", "proactiveStatusDecisionPlatform");
  appendStatusMetric(statusGrid, "当前判断目标", "proactiveStatusDecisionTarget");
  appendStatusMetric(statusGrid, "最近目标", "proactiveStatusLatestTargets");
  appendStatusMetric(statusGrid, "最近发送", "proactiveStatusLastSent");
  appendStatusMetric(statusGrid, "最近检查", "proactiveStatusLastCheck");
  statusCard.appendChild(statusGrid);
  statusCard.appendChild(createElement("div", "small", "上次检查结果：-"));
  statusCard.lastChild.id = "proactiveLastResult";
  statusCard.appendChild(createElement("div", "small", "规则摘要未加载"));
  statusCard.lastChild.id = "proactiveRulesSummary";
  grid.appendChild(statusCard);

  const runOnceCard = createElement("div", "control-surface");
  runOnceCard.appendChild(createElement("h3", "", "手动执行自动调度"));
  runOnceCard.appendChild(createElement(
    "div",
    "config-help",
    "这是手动触发自动调度流程，用于测试；默认不会真实发送，可能命中 QQ 或 WX。"
  ));
  const runOnceForm = createElement("div", "config-form");
  for (const option of [
    ["proactiveRunIgnoreRandomInput", "忽略随机概率", true],
    ["proactiveRunIgnoreRecentChatInput", "忽略最近聊天", false],
    ["proactiveRunIgnoreActiveWindowInput", "忽略时间窗", false],
    ["proactiveRunForceInput", "强制生成", false],
    ["proactiveRunDryRunOnlyInput", "只 dry_run，不真实发送", true],
  ]) {
    const label = createElement("label");
    const input = createElement("input");
    input.type = "checkbox";
    input.id = option[0];
    input.checked = option[2];
    label.append(input, ` ${option[1]}`);
    runOnceForm.appendChild(label);
  }
  const runOnceRow = createElement("div", "row");
  runOnceRow.appendChild(createElement("button", "", "执行一轮自动调度"));
  runOnceRow.lastChild.id = "runProactiveOnceBtn";
  runOnceCard.append(runOnceForm, runOnceRow);
  runOnceCard.appendChild(createElement("div", "small", "尚未执行"));
  runOnceCard.lastChild.id = "proactiveRunOnceResult";
  grid.appendChild(runOnceCard);

  const eventsCard = createElement("div", "control-surface");
  eventsCard.appendChild(createElement("h3", "", "调度时间线"));
  eventsCard.appendChild(createElement("div", "config-help", "最近主动消息调度和手动操作事件；不显示完整 session_id/openid。"));
  if (refreshEventsButton) {
    const eventRow = createElement("div", "row");
    eventRow.appendChild(refreshEventsButton);
    eventRow.appendChild(createPlatformFilter("proactiveEventPlatformFilter"));
    eventsCard.appendChild(eventRow);
  }
  eventsCard.appendChild(createElement("div", "small panel-list", "还没加载"));
  eventsCard.lastChild.id = "proactiveEventList";
  grid.appendChild(eventsCard);

  const targetsCard = createElement("div", "control-surface");
  targetsCard.appendChild(createElement("h3", "", "主动目标"));
  targetsCard.appendChild(createElement("div", "config-help", "最近 QQ / WX 私聊会自动记录为主动目标；页面不显示完整 session_id。QQ 会显示 allowed，WX 会显示真实目标是否已保存。"));
  if (refreshTargetsButton) {
    const targetRow = createElement("div", "row");
    targetRow.appendChild(refreshTargetsButton);
    targetRow.appendChild(createPlatformFilter("proactiveTargetPlatformFilter"));
    targetsCard.appendChild(targetRow);
  }
  targetsCard.appendChild(createElement("div", "small panel-list", "还没加载"));
  targetsCard.lastChild.id = "proactiveTargetList";
  grid.appendChild(targetsCard);

  const decisionCard = createElement("div", "control-surface");
  decisionCard.appendChild(createElement("h3", "", "自动调度当前判断"));
  decisionCard.appendChild(createElement("div", "config-help", "check-now 只刷新后台自动调度判断，不会发送消息。"));
  decisionCard.appendChild(createElement("div", "status-value", "-"));
  decisionCard.lastChild.id = "proactiveCanSendNow";
  decisionCard.appendChild(createElement("div", "small", "尚未检查"));
  decisionCard.lastChild.id = "proactiveCanSendReason";
  const checkRow = createElement("div", "row");
  checkRow.appendChild(createElement("button", "", "检查现在会不会发"));
  checkRow.lastChild.id = "checkProactiveNowBtn";
  checkRow.lastChild.classList.add("secondary", "auxiliary");
  if (generateButton) {
    checkRow.appendChild(generateButton);
  }
  decisionCard.appendChild(checkRow);
  if (platformForm) {
    decisionCard.appendChild(platformForm);
  }
  decisionCard.appendChild(createElement("div", "proactive-check-grid", "还没有检查结果"));
  decisionCard.lastChild.id = "proactiveCheckNowChecks";
  grid.appendChild(decisionCard);

  const pendingCard = createElement("div", "control-surface");
  pendingCard.appendChild(createElement("h3", "", "待处理候选 pending"));
  pendingCard.appendChild(createElement("div", "config-help", "候选支持 QQ / WX。dry_run 只验证链路；真实发送需要二次确认，成功后才写入 messages。"));
  pendingCard.appendChild(createPlatformFilter("proactiveCandidatePlatformFilter"));
  if (pendingList) {
    pendingCard.appendChild(pendingList);
  }
  grid.appendChild(pendingCard);

  const history = createElement("details", "card");
  history.appendChild(createElement("summary", "", "显示历史"));
  history.appendChild(createElement("div", "config-help", "历史记录 sent / dismissed / failed，支持 QQ / WX。"));
  history.appendChild(createElement("div", "proactive-history-list", "还没加载"));
  history.lastChild.id = "proactiveHistoryList";
  grid.appendChild(history);

  const configCard = createElement("div", "control-surface");
  configCard.appendChild(createElement("h3", "", "自动配置"));
  if (configDetails) {
    const nodes = Array.from(configDetails.childNodes);
    for (const node of nodes) {
      if (node.nodeType === Node.ELEMENT_NODE && node.tagName === "SUMMARY") {
        node.remove();
        continue;
      }
      configCard.appendChild(node);
    }
    const form = configCard.querySelector(".config-form");
    if (form) {
      form.classList.add("proactive-config-grid");
    }
  }
  grid.appendChild(configCard);

  // 板块重排：常用置顶（状态 / 待处理 / 时间线），调试下沉（判断 / 手动 / 测试 / 目标 / 历史 / 配置）。
  // 重新 appendChild 已挂载节点会原地移动它，故此处仅按新顺序重排并插入分隔。
  const proactiveDivider = createElement("div", "rail-divider", "调试 / 高级");
  for (const node of [
    statusCard,
    pendingCard,
    eventsCard,
    proactiveDivider,
    decisionCard,
    runOnceCard,
    testCard,
    targetsCard,
    history,
    configCard,
  ]) {
    grid.appendChild(node);
  }

  proactiveCard?.remove();
}

export function buildConsciousnessPanel(panel, header) {
  const grid = createElement("div", "console-grid");
  panel.appendChild(grid);

  // ── Phase 1: Body State Card ──
  const bodyCard = createElement("div", "control-surface");
  bodyCard.appendChild(createElement("h3", "", "生命体征"));
  bodyCard.appendChild(createElement("div", "config-help", "精力 / 情绪 / 表达欲 实时值，每秒自动刷新。"));
  const refreshRow = createElement("div", "row");
  const refreshBtn = createElement("button", "secondary auxiliary", "刷新状态");
  refreshBtn.id = "cRefreshStateBtn";
  refreshRow.appendChild(refreshBtn);
  bodyCard.appendChild(refreshRow);

  const stateGrid = createElement("div", "vitals-grid");

  const makeVital = (kind, label, valueId, barId, metaNode) => {
    const v = createElement("div", `vital vital-${kind}`);
    const top = createElement("div", "vital-top");
    const num = createElement("span", "vital-num", "-");
    num.id = valueId;
    top.append(createElement("span", "vital-label", label), num);
    const bar = createElement("div", "vital-bar");
    bar.id = barId;
    v.append(top, bar, metaNode);
    return v;
  };

  // 精力
  const eMeta = createElement("div", "vital-meta");
  const eStatus = createElement("span", "", "-");
  eStatus.id = "cEnergyStatus";
  const eDesc = createElement("span", "", "");
  eDesc.id = "cEnergyDesc";
  eMeta.append(createElement("span", "vital-meta-key", "状态 "), eStatus, document.createTextNode(" · "), eDesc);
  stateGrid.append(makeVital("energy", "精力", "cEnergyValue", "cEnergyBar", eMeta));

  // 情绪
  const mMeta = createElement("div", "vital-meta");
  const mDetail = createElement("span", "", "-");
  mDetail.id = "cMoodDetail";
  const mDesc = createElement("span", "", "");
  mDesc.id = "cMoodDesc";
  mMeta.append(mDetail, document.createTextNode(" · "), mDesc);
  stateGrid.append(makeVital("mood", "情绪", "cMoodValue", "cMoodBar", mMeta));

  // 表达欲
  const dMeta = createElement("div", "vital-meta");
  const dExpress = createElement("span", "", "-");
  dExpress.id = "cDesireExpress";
  dMeta.append(createElement("span", "vital-meta-key", "上次表达 "), dExpress);
  stateGrid.append(makeVital("desire", "表达欲", "cDesireValue", "cDesireBar", dMeta));

  bodyCard.appendChild(stateGrid);

  // Interaction info
  const interactGrid = createElement("div", "status-grid");
  interactGrid.style.marginTop = "10px";
  appendStatusMetric(interactGrid, "上次互动用户", "cLastUser");
  appendStatusMetric(interactGrid, "互动摘要", "cLastSummary");
  appendStatusMetric(interactGrid, "revision", "cRevision");
  appendStatusMetric(interactGrid, "updated_at", "cUpdatedAt");
  bodyCard.appendChild(interactGrid);

  bodyCard.appendChild(createElement("div", "status", ""));
  bodyCard.lastChild.id = "consciousnessStateStatus";

  grid.append(bodyCard);


  // ── 事件池 ──
  const eventsCard = createElement("div", "control-surface");
  eventsCard.appendChild(createElement("h3", "", "事件池"));
  eventsCard.appendChild(createElement("div", "config-help", "event_log 中的 pending/consumed/expressed 事件。"));
  const eventListBox = createElement("div", "small panel-list");
  eventListBox.id = "cEventList";
  eventListBox.textContent = "暂无事件";
  eventsCard.appendChild(eventListBox);
  eventsCard.appendChild(createElement("div", "status", ""));
  eventsCard.lastChild.id = "cEventStatus";

  grid.append(eventsCard);

  // ── Phase 3a: Think Card ──
  const thinkCard = createElement("div", "control-surface");
  thinkCard.appendChild(createElement("h3", "", "思考过程"));
  thinkCard.appendChild(createElement("div", "config-help", "手动注入测试事件，触发 Neno 三步决策（规则过滤 → 判断 → 生成），结果仅预览不发送。"));

  // Inject form
  const injectGroup = createElement("div");
  injectGroup.style.marginBottom = "12px";
  injectGroup.appendChild(createElement("div", "status-label", "注入测试事件"));
  const injectRow = createElement("div", "row");
  injectRow.style.gap = "6px";
  injectRow.style.alignItems = "center";

  const contentInput = createElement("input");
  contentInput.id = "cInjectContent";
  contentInput.type = "text";
  contentInput.placeholder = "输入测试事件内容，如：南宁突降暴雨";
  contentInput.style.flex = "1";
  contentInput.style.minWidth = "0";
  injectRow.appendChild(contentInput);

  const prioritySelect = createElement("select");
  prioritySelect.id = "cInjectPriority";
  for (const [val, label] of [["0", "P0 紧急"], ["1", "P1 高"], ["2", "P2 普通"], ["3", "P3 低"]]) {
    const opt = createElement("option", "", label);
    opt.value = val;
    prioritySelect.appendChild(opt);
  }
  prioritySelect.value = "2";
  injectRow.appendChild(prioritySelect);

  const injectBtn = createElement("button", "secondary", "注入");
  injectBtn.id = "cInjectBtn";
  injectRow.appendChild(injectBtn);
  injectGroup.appendChild(injectRow);
  injectGroup.appendChild(createElement("div", "status", ""));
  injectGroup.lastChild.id = "cInjectStatus";
  thinkCard.appendChild(injectGroup);

  // Think button
  const thinkRow = createElement("div", "row");
  const thinkBtn = createElement("button", "", "触发思考");
  thinkBtn.id = "cThinkBtn";
  thinkRow.appendChild(thinkBtn);
  thinkCard.appendChild(thinkRow);
  thinkCard.appendChild(createElement("div", "status", ""));
  thinkCard.lastChild.id = "cThinkStatus";

  // Result area
  const thinkResult = createElement("div");
  thinkResult.id = "cThinkResult";
  thinkResult.style.marginTop = "12px";
  thinkResult.textContent = "点击「触发思考」查看三步决策过程";
  thinkCard.appendChild(thinkResult);

  grid.appendChild(thinkCard);

  // ── Phase 3b: Preflight Card ──
  const preflightCard = createElement("div", "control-surface");
  preflightCard.appendChild(createElement("h3", "", "Phase 3b 预检"));
  preflightCard.appendChild(createElement("div", "config-help", "只读检查 brain intent 发送链路就绪状态。不发送、不创建候选、不改状态。"));

  const preflightRow = createElement("div", "row");
  preflightRow.style.gap = "6px";
  const preflightBtn = createElement("button", "secondary", "刷新预检");
  preflightBtn.id = "cPreflightBtn";
  const enqueueBtn = createElement("button", "secondary", "插入测试 intent");
  enqueueBtn.id = "cEnqueueTestBtn";
  enqueueBtn.title = "往 proactive_intent 写入一条 queued 测试意图，不发送";
  preflightRow.append(preflightBtn, enqueueBtn);
  const dropBtn = createElement("button", "secondary", "清理所有 queued");
  dropBtn.id = "cDropQueuedBtn";
  dropBtn.title = "将所有 queued intent 标记为 dropped（不仅是测试数据）";
  preflightRow.appendChild(dropBtn);
  preflightCard.appendChild(preflightRow);

  const preflightResult = createElement("div");
  preflightResult.id = "cPreflightResult";
  preflightResult.style.marginTop = "12px";
  preflightResult.textContent = "点击「刷新预检」查看当前发送链路状态";
  preflightCard.appendChild(preflightResult);
  preflightCard.appendChild(createElement("div", "status", ""));
  preflightCard.lastChild.id = "cPreflightStatus";

  grid.appendChild(preflightCard);

  // Phase 4: Living World read-only debug view
  const livingCard = createElement("div", "control-surface");
  livingCard.appendChild(createElement("h3", "", "Phase 4 / 生活验收面板"));
  livingCard.appendChild(createElement("div", "config-help", "只读查看 Neno 此刻的虚拟生活：她在哪、在做什么、为什么这样，以及反思余波如何影响下一轮。"));
  const livingRow = createElement("div", "row");
  const livingRefreshBtn = createElement("button", "secondary auxiliary", "刷新生活状态");
  livingRefreshBtn.id = "cLivingWorldRefreshBtn";
  livingRow.appendChild(livingRefreshBtn);
  livingCard.appendChild(livingRow);

  const livingNowTitle = createElement("div", "status-label", "此刻");
  livingNowTitle.style.marginTop = "10px";
  livingCard.appendChild(livingNowTitle);
  const livingStateGrid = createElement("div", "status-grid");
  livingStateGrid.style.gridTemplateColumns = "repeat(2, minmax(0, 1fr))";
  appendStatusMetric(livingStateGrid, "在哪", "cLivingWhere");
  appendStatusMetric(livingStateGrid, "做什么", "cLivingActivityLabel");
  appendStatusMetric(livingStateGrid, "为什么", "cLivingActivityReason");
  appendStatusMetric(livingStateGrid, "时间段", "cLivingTimePhase");
  appendStatusMetric(livingStateGrid, "注意力", "cLivingLifeAttention");
  appendStatusMetric(livingStateGrid, "内部状态", "cLivingLifeMode");
  livingCard.appendChild(livingStateGrid);

  livingCard.appendChild(createElement("div", "status-label", "连续性"));
  livingCard.appendChild(createElement("div", "small panel-list", "还没加载"));
  livingCard.lastChild.id = "cLivingContinuity";
  livingCard.appendChild(createElement("div", "status-label", "反思余波"));
  livingCard.appendChild(createElement("div", "small panel-list", "还没加载"));
  livingCard.lastChild.id = "cLivingLifeResidue";
  livingCard.appendChild(createElement("div", "status-label", "下一轮预览"));
  livingCard.appendChild(createElement("div", "small panel-list", "还没加载"));
  livingCard.lastChild.id = "cLivingLoopPreview";
  livingCard.appendChild(createElement("div", "status-label", "最近经历"));
  livingCard.appendChild(createElement("div", "small panel-list", "还没加载"));
  livingCard.lastChild.id = "cLivingExperiences";
  livingCard.appendChild(createElement("div", "status-label", "最近梦境总结"));
  livingCard.appendChild(createElement("div", "small panel-list", "还没加载"));
  livingCard.lastChild.id = "cLivingReflections";
  livingCard.appendChild(createElement("div", "status-label", "长期记忆影响"));
  livingCard.appendChild(createElement("div", "small panel-list", "还没加载"));
  livingCard.lastChild.id = "cLivingMemories";
  livingCard.appendChild(createElement("div", "status", ""));
  livingCard.lastChild.id = "cLivingWorldStatus";

  grid.appendChild(livingCard);
}

function createWorldWorkspace() {
  const workspace = createElement("section", "world-workspace");
  workspace.id = "worldWorkspace";
  workspace.innerHTML = `
    <aside class="world-scene-rail">
      <div class="world-rail-label">世界场景</div>
      <button class="world-scene-button active" id="worldSceneHomeBtn" type="button"><strong>家</strong><span>四个房间</span></button>
      <button class="world-scene-button" id="worldSceneOutBtn" type="button"><strong>外面</strong><span>玄关·楼下·店·公园</span></button>
      <button class="world-scene-button future" type="button"><strong>地图</strong><span>后续开放</span></button>
      <div class="world-rail-spacer"></div>
      <div class="world-rail-foot">场景<br>登记册</div>
    </aside>
    <section class="world-stage-card">
      <div class="world-panel-label">LIVING WORLD</div>
      <div class="world-viewport" id="worldViewport">
        <div class="world-room-strip" id="worldRoomStrip">
          <article class="world-room bedroom" data-world-room="bedroom"><span class="world-room-label">卧室</span></article>
          <article class="world-room living_room active" data-world-room="living_room"><span class="world-room-label">客厅</span></article>
          <article class="world-room kitchen" data-world-room="kitchen">
            <span class="world-room-label">厨房</span>
            <div class="world-steam" id="worldSteam"><i></i><i></i><i></i></div>
          </article>
          <article class="world-room balcony" data-world-room="balcony"><span class="world-room-label">阳台</span></article>
          <article class="world-room entryway" data-world-room="entryway"><span class="world-room-label">玄关</span></article>
          <article class="world-room building_entrance" data-world-room="building_entrance"><span class="world-room-label">小区楼下</span></article>
          <article class="world-room cafe" data-world-room="cafe"><span class="world-room-label">咖啡馆</span></article>
          <article class="world-room convenience_store" data-world-room="convenience_store"><span class="world-room-label">便利店</span></article>
          <article class="world-room park" data-world-room="park"><span class="world-room-label">小公园</span></article>
          <div class="world-neno" id="worldNeno">
            <div class="world-thought" id="worldThought"></div>
            <img src="/static/img/world/neno-idle-v1.png" alt="Neno">
          </div>
        </div>
        <div class="world-daylight" id="worldDaylight"></div>
        <div class="world-lamp-glow" id="worldLampGlow"></div>
        <div class="world-city-lights" id="worldCityLights" aria-hidden="true">
          <i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i>
        </div>
        <div class="world-air-motion" id="worldAirMotion" aria-hidden="true"><i></i><i></i><i></i></div>
        <div class="world-vignette"></div>
        <div class="world-stage-meta"><small id="worldSceneTag">场景 · Neno 的家</small><h1 id="worldSceneTitle">Neno 的家</h1></div>
        <div class="world-minimap" aria-label="房间位置">
          <span data-world-map-room="bedroom">卧</span>
          <span class="active" data-world-map-room="living_room">厅</span>
          <span data-world-map-room="kitchen">厨</span>
          <span data-world-map-room="balcony">台</span>
          <span class="world-map-gap" aria-hidden="true">·</span>
          <span data-world-map-room="entryway">关</span>
          <span data-world-map-room="building_entrance">楼</span>
          <span data-world-map-room="cafe">啡</span>
          <span data-world-map-room="convenience_store">店</span>
          <span data-world-map-room="park">园</span>
        </div>
        <div class="world-step-controls">
          <button class="world-step-button" id="cWorldStepBtn" type="button">走一步</button>
          <button class="world-step-button" id="cWorldWakeBtn" type="button">叫醒她</button>
          <button class="world-step-button" id="worldEditBtn" type="button">编辑布局</button>
          <button class="world-step-button" id="worldEditExport" type="button" style="display:none;">导出坐标</button>
        </div>
        <div class="world-stage-clock"><strong id="worldClock">--:--</strong><span id="worldPhase">等待世界数据</span></div>
      </div>
    </section>
    <aside class="world-story">
      <div class="world-story-time" id="worldStoryTime">等待世界数据</div>
      <h2 id="worldStoryAction">Neno 的生活正在加载</h2>
      <blockquote id="worldStoryInner">读取真实世界快照后，这里会显示她此刻为什么这样做。</blockquote>
      <div class="world-self" id="worldSelfBox">
        <small>此刻的她 · 她自己感觉到的</small>
        <p id="worldSelfContext">还没生成（self_context 开关关着，或刚启动）。</p>
        <p class="world-self-pending" id="worldSelfPending"></p>
      </div>
      <div class="world-mood">
        <div class="world-mood-swatch" id="worldMoodSwatch"></div>
        <div><small>此刻心情</small><strong id="worldMoodText">—</strong></div>
      </div>
      <div class="world-stats">
        <div class="world-stat"><span>精力</span><b id="worldEnergy">—</b></div>
        <div class="world-stat"><span>钱包</span><b id="worldMoney">—</b></div>
        <div class="world-stat"><span>状态</span><b id="worldEnergyStatus">—</b></div>
      </div>
      <div class="world-plan-title">今天想做的</div>
      <ul class="world-plan" id="worldPlan"><li>等待计划数据</li></ul>
      <div class="world-self-facts">
        <div class="world-self-facts-title">她活成的自己 <small>从经历结晶</small></div>
        <ul class="world-self-fact-list" id="worldSelfFacts"><li class="world-self-empty">还没沉淀出自我事实（要她真反复做点什么 + 反思跑过）。</li></ul>
      </div>
      <div class="world-soul-feed">
        <div class="world-soul-feed-title">魂时刻 <small>你看得见她在活</small></div>
        <ul class="world-soul-feed-list" id="worldSoulFeed"><li class="world-soul-empty">还没有可见的魂事件（她学了/挪了/买了、或收到你的话时，会出现在这里）。</li></ul>
      </div>
      <div class="world-change" id="worldChange">世界暂时没有新的变化。</div>
      <div class="world-status" id="cWorldLiveStatus">等待连接真实世界引擎。</div>
    </aside>
    <section class="world-chronicle">
      <div class="world-chronicle-head">
        <strong>今天的生活长卷</strong>
        <span id="worldChronicleRange">今天 · 等待数据</span>
      </div>
      <div class="world-chronicle-content">
        <div class="world-timeline" id="worldTimeline">
          <div class="world-moment"><time>—</time>等待最近活动</div>
          <div class="world-moment current" id="worldCurrentMoment"><time>--:--</time>正在加载</div>
        </div>
        <div class="world-threads">
          <span>心里还挂着</span>
          <div class="world-thread-list" id="worldThreadList">
            <div class="world-thread-empty">此刻没有特别惦记的事</div>
          </div>
          <div class="world-thread world-thread-pending"><b>未完计划</b><span id="worldPendingThread">等待计划数据</span></div>
        </div>
      </div>
    </section>
  `;
  return workspace;
}

function createWorkspaceTopbar() {
  const topbar = createElement("header", "world-workspace-topbar");
  topbar.innerHTML = `
    <div class="world-brand neno-product-brand">
      <div class="world-brand-mark">N</div>
      <strong>Neno</strong>
    </div>
    <nav class="world-workspace-switch" aria-label="控制台工作区">
      <button class="active" id="worldWorkspaceButton" type="button">世界引擎</button>
      <button id="controlWorkspaceButton" type="button">控制中枢</button>
    </nav>
    <div class="world-runtime" id="worldRuntimeStatus">等待世界状态</div>
  `;
  return topbar;
}

function bindWorkspaceSwitch(worldWorkspace, controlWorkspace) {
  const worldButton = document.getElementById("worldWorkspaceButton");
  const controlButton = document.getElementById("controlWorkspaceButton");
  const activate = (name) => {
    const showWorld = name === "world";
    worldWorkspace.classList.toggle("workspace-hidden", !showWorld);
    controlWorkspace.classList.toggle("workspace-hidden", showWorld);
    worldButton?.classList.toggle("active", showWorld);
    controlButton?.classList.toggle("active", !showWorld);
    window.dispatchEvent(new CustomEvent("neno:workspace-change", { detail: { workspace: name } }));
  };
  worldButton?.addEventListener("click", () => activate("world"));
  controlButton?.addEventListener("click", () => activate("control"));
}

function createControlCommandBar() {
  const bar = createElement("section", "retired-command-shell");
  const titleBox = createElement("div", "control-command-heading");
  titleBox.append(
    createElement("div", "control-command-kicker", "CONTROL CENTER"),
    createElement("h1", "control-command-title", "聊天")
  );
  titleBox.lastChild.id = "controlActiveTitle";
  titleBox.appendChild(createElement("p", "control-command-subtitle", "跟她对话、切换会话、查看真实输入预览与会话调试。"));
  titleBox.lastChild.id = "controlActiveSubtitle";

  const status = createElement("div", "control-command-status");
  for (const label of ["LOCAL RUNTIME", "ADMIN GATED", "LIVE DEBUG"]) {
    status.appendChild(createElement("span", "control-status-pill", label));
  }
  bar.append(titleBox, status);
  return bar;
}

function createControlUtilityRail() {
  const rail = createElement("aside", "retired-utility-shell");
  const contextCard = createElement("div", "retired-rail-box");
  contextCard.append(
    createElement("span", "retired-rail-kicker", "ACTIVE MODULE"),
    createElement("strong", "", "聊天"),
    createElement("p", "", "当前只显示一个任务面板；其余模块保持在左侧导航中。")
  );
  contextCard.querySelector("strong").id = "controlRailPanelName";

  const routeCard = createElement("div", "retired-rail-box");
  routeCard.append(
    createElement("span", "retired-rail-kicker", "SESSION"),
    createElement("strong", "", "web-test"),
    createElement("p", "", "会话、记忆、真实输入预览和调试卡片继续使用原绑定节点。")
  );

  const safetyCard = createElement("div", "retired-rail-box retired-rail-box-warn");
  safetyCard.append(
    createElement("span", "retired-rail-kicker", "BOUNDARY"),
    createElement("strong", "", "UI ONLY"),
    createElement("p", "", "这层只重写控制台结构，不改聊天 prompt、世界状态或 digest 游标。")
  );
  rail.append(contextCard, routeCard, safetyCard);
  return rail;
}

function createFramerControlFrame() {
  const sidebar = createElement("aside", "control-product-sidebar");
  const studioBrand = createElement("div", "control-studio-brand");
  studioBrand.append(
    createElement("div", "control-studio-mark", "N"),
    createElement("div", "control-studio-name")
  );
  studioBrand.lastChild.append(
    createElement("strong", "", "Neno"),
    createElement("span", "", "local runtime console")
  );

  const runtimeIdentity = createElement("div", "control-runtime-identity");
  runtimeIdentity.append(
    createElement("strong", "", "Neno Local Runtime"),
    createElement("span", "", "web-test · admin · live debug")
  );

  const panelHint = createElement("div", "control-sidebar-hint");
  panelHint.append(
    createElement("span", "", "CURRENT"),
    createElement("b", "", "聊天")
  );
  panelHint.querySelector("b").id = "controlSidebarPanelName";
  const sidebarFooter = createElement("div", "control-sidebar-footer");
  sidebarFooter.append(
    createElement("span", "", "web-test"),
    createElement("span", "", "admin"),
    createElement("span", "", "live debug")
  );
  sidebar.append(studioBrand, runtimeIdentity, panelHint);

  const stage = createElement("main", "control-panel-stage console-main");
  const stageHeader = createElement("header", "control-stage-header");
  const stageCopy = createElement("div", "control-stage-copy");
  stageCopy.append(
    createElement("span", "control-stage-kicker", "CONTROL CENTER"),
    createElement("h1", "control-stage-title", "鑱婂ぉ"),
    createElement("p", "control-stage-subtitle", "璺熷ス瀵硅瘽銆佸垏鎹細璇濄€佹煡鐪嬬湡瀹炶緭鍏ラ瑙堜笌浼氳瘽璋冭瘯銆?")
  );
  stageCopy.querySelector(".control-stage-title").id = "controlStageTitle";
  stageCopy.querySelector(".control-stage-subtitle").id = "controlStageSubtitle";
  const stageStatus = createElement("div", "control-stage-status");
  for (const label of ["LOCAL", "GATED", "TRACE"]) {
    stageStatus.appendChild(createElement("span", "", label));
  }
  stageHeader.append(stageCopy, stageStatus);
  const workbench = createElement("div", "control-panel-deck");
  stage.append(stageHeader, workbench);

  return { sidebar, stage, workbench, sidebarFooter };
}

function adoptControlSurface(node, className = "") {
  if (!node) {
    return null;
  }
  node.classList.remove("card", "console-density-card");
  node.classList.add("control-binding-surface");
  for (const name of className.split(" ").filter(Boolean)) {
    node.classList.add(name);
  }
  normalizeControlSurfaces(node);
  return node;
}

function normalizeControlSurfaces(root) {
  if (!root) {
    return;
  }
  const legacyCards = root.classList?.contains("card")
    ? [root, ...root.querySelectorAll(".card")]
    : Array.from(root.querySelectorAll(".card"));
  for (const card of legacyCards) {
    card.classList.remove("card", "console-density-card");
    card.classList.add("control-surface");
  }
}

function appendSurface(parent, node, className = "") {
  const surface = adoptControlSurface(node, className);
  if (surface) {
    parent.appendChild(surface);
  }
}

function createRuntimeWorkbench(panel, className = "", label = "runtime") {
  panel.classList.add("runtime-panel");
  const header = panel.querySelector(".panel-header");
  if (header && !header.querySelector(".runtime-module-chip")) {
    header.prepend(createElement("div", "runtime-module-chip", label));
  }

  const workbench = createElement("div", `runtime-workbench ${className}`.trim());
  const primary = createElement("section", "runtime-column runtime-primary");
  const evidence = createElement("aside", "runtime-column runtime-evidence");
  const raw = createElement("section", "runtime-column runtime-raw");
  workbench.append(primary, evidence, raw);
  panel.appendChild(workbench);
  return { workbench, primary, evidence, raw };
}

function moveLoosePanelChildren(panel, runtime) {
  const looseChildren = Array.from(panel.children).filter((child) =>
    !child.classList.contains("panel-header") && !child.classList.contains("runtime-workbench")
  );
  for (const [index, child] of looseChildren.entries()) {
    normalizeControlSurfaces(child);
    if (index === 0) {
      runtime.primary.appendChild(child);
    } else if (index < 3) {
      runtime.evidence.appendChild(child);
    } else {
      runtime.raw.appendChild(child);
    }
  }
}

export function buildConsoleLayout() {
  const app = document.querySelector(".app");
  const chat = document.querySelector(".chat");
  const side = document.querySelector(".side");
  if (!app || !chat || !side) {
    return;
  }

  const sessionCard = getCardByElementId("sessionList");
  const configCard = getCardByElementId("configBox");
  const statsCard = getCardByElementId("statsToday");
  const proactiveCard = getCardByElementId("proactiveCandidateList");
  const relationshipCard = getCardByElementId("relationshipStatus");
  const usedMemoryCard = getCardByElementId("usedMemories");
  const chatPreviewCard = getCardByElementId("chatPreviewBox");
  const messageDebugCard = getCardByElementId("messageDebugBox");
  const sessionDebugCard = getCardByElementId("sessionDebugBox");
  const candidateCard = getCardByElementId("candidateBox");
  const memoryCard = getCardByElementId("memoryList");

  const controlFrame = createFramerControlFrame();
  const sidebar = controlFrame.sidebar;
  const brand = createElement("div", "console-brand");
  brand.append(
    createElement("div", "console-brand-title", "Neno 控制台"),
    createElement("div", "console-brand-subtitle", "本地测试与调试")
  );
  const nav = createElement("nav", "console-nav");
  nav.setAttribute("aria-label", "Neno 测试页导航");
  for (const [panelId, label] of panelDefinitions) {
    const button = createElement("button", "nav-btn");
    const icon = NAV_ICONS[panelId] || "";
    button.innerHTML =
      `<svg class="nav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icon}</svg>` +
      `<span>${label}</span>`;
    button.type = "button";
    button.dataset.panelTarget = panelId;
    button.addEventListener("click", () => setActivePanel(panelId));
    nav.appendChild(button);
  }
  sidebar.appendChild(nav);
  sidebar.appendChild(controlFrame.sidebarFooter);

  const main = controlFrame.stage;
  const panelStack = controlFrame.workbench;
  const overview = createPanel("overviewPanel", "总览", "运行状态、快捷入口和当前调试概况。");
  const overviewRuntime = createRuntimeWorkbench(overview.panel, "overview-workbench", "status / launch");
  appendSurface(overviewRuntime.primary, statsCard, "overview-stats-surface");
  // 她此刻：桥接世界引擎的一瞥（点击跳到世界引擎 tab）
  const bridgeCard = createElement("div", "control-surface bridge-card");
  bridgeCard.id = "overviewBridgeCard";
  bridgeCard.setAttribute("role", "button");
  bridgeCard.setAttribute("tabindex", "0");
  const bridgeHead = createElement("div", "bridge-head");
  bridgeHead.append(
    createElement("span", "bridge-title", "她此刻"),
    createElement("span", "bridge-jump", "去世界引擎 →")
  );
  bridgeCard.appendChild(bridgeHead);
  const bridgeLine = createElement("div", "bridge-line", "读取世界状态…");
  bridgeLine.id = "overviewBridgeLine";
  bridgeCard.appendChild(bridgeLine);
  const bridgeStats = createElement("div", "bridge-stats");
  bridgeStats.innerHTML =
    '<span>精力 <b id="overviewBridgeEnergy">—</b></span>' +
    '<span>心情 <b id="overviewBridgeMood">—</b></span>' +
    '<span>压力 <b id="overviewBridgePressure">—</b></span>';
  bridgeCard.appendChild(bridgeStats);
  const jumpWorld = () => document.getElementById("worldWorkspaceButton")?.click();
  bridgeCard.addEventListener("click", jumpWorld);
  bridgeCard.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); jumpWorld(); } });
  overviewRuntime.evidence.appendChild(bridgeCard);

  const quickCard = createElement("div", "control-surface console-command-surface");
  quickCard.appendChild(createElement("h3", "", "快捷入口"));
  const quickActions = createElement("div", "overview-actions");
  for (const [panelId, label] of [
    ["chatPanel", "打开聊天"],
    ["consciousnessPanel", "打开大脑"],
    ["proactivePanel", "打开主动"],
    ["memoryPanel", "打开记忆"],
    ["debugPanel", "打开日志"],
  ]) {
    const button = createElement("button", "secondary", label);
    button.type = "button";
    button.dataset.panelTarget = panelId;
    button.addEventListener("click", () => setActivePanel(panelId));
    quickActions.appendChild(button);
  }
  quickCard.appendChild(quickActions);
  overviewRuntime.raw.appendChild(quickCard);

  const chatPanel = createPanel("chatPanel", "聊天", "跟她对话、切换会话、查看真实输入预览与会话调试。");
  const currentSession = createElement("div", "panel-subtitle", "当前打开 session：-");
  currentSession.id = "currentSessionStatus";
  chatPanel.header.appendChild(currentSession);
  const chatRuntime = createRuntimeWorkbench(chatPanel.panel, "chat-workbench", "session / trace");
  const chatGrid = createElement("div", "runtime-strip chat-strip");
  chatGrid.append(
    createElement("span", "", "live session"),
    createElement("b", "", "web-test")
  );
  chat.classList.add("console-chat", "control-chat-console");
  chatRuntime.primary.appendChild(chatGrid);
  chatRuntime.primary.appendChild(chat);
  const chatSide = createElement("div", "runtime-stack chat-side-column");
  const sessionSummaryCard = createElement("div", "control-surface session-summary-surface");
  sessionSummaryCard.appendChild(createElement("h3", "", "当前上下文"));
  sessionSummaryCard.appendChild(createElement("div", "config-help", "右键输入消息可查看这条真实输入对应的完整模型预览。"));
  const sessionSummaryGrid = createElement("div", "status-grid session-context-grid");
  appendStatusMetric(sessionSummaryGrid, "当前 session", "currentSessionSidebarId");
  appendStatusMetric(sessionSummaryGrid, "已载入消息", "currentSessionMessageCount");
  appendStatusMetric(sessionSummaryGrid, "预览入口", "currentSessionPreviewMode");
  sessionSummaryCard.appendChild(sessionSummaryGrid);
  // 当前上下文卡在下方按新顺序统一插入
  const routingCard = createElement("div", "control-surface routing-surface");
  routingCard.appendChild(createElement("h3", "", "Session Routing Control"));
  routingCard.appendChild(createElement("div", "config-help", "查询当前平台来源 routing 状态，直接设置 override 到指定 session，或 clear 恢复自动归属。只影响后续入站消息。"));
  const routingForm = createElement("div", "config-form");
  for (const [id, label, type] of [
    ["routingPlatformInput", "platform", "text"],
    ["routingAccountInput", "account_id", "text"],
    ["routingUserInput", "user_id", "text"],
    ["routingChatTypeInput", "chat_type", "text"],
    ["routingGroupInput", "group_id", "text"],
    ["routingOverrideSessionInput", "override session_id", "text"],
  ]) {
    const field = createElement("div", "config-field");
    field.appendChild(createElement("label", "", label));
    const input = createElement("input");
    input.id = id;
    input.type = type;
    if (id === "routingPlatformInput") input.placeholder = "wx";
    if (id === "routingAccountInput") input.placeholder = "default";
    if (id === "routingUserInput") input.placeholder = "通常无需手填，优先自动带入";
    if (id === "routingChatTypeInput") input.placeholder = "private / group";
    if (id === "routingGroupInput") input.placeholder = "group only";
    if (id === "routingOverrideSessionInput") input.placeholder = "wx:private:...";
    field.appendChild(input);
    if (id === "routingUserInput") {
      field.appendChild(createElement("div", "config-help", "user_id 通常不需要手填；系统会优先从当前会话最近一条平台入站消息自动带入。"));
    }
    routingForm.appendChild(field);
  }
  routingCard.appendChild(routingForm);
  const routingActions = createElement("div", "row");
  for (const [id, label, className] of [
    ["routingAutofillBtn", "带入最近平台消息", "secondary"],
    ["routingQueryBtn", "查询状态", "secondary"],
    ["routingSetBtn", "设置 Override", ""],
    ["routingClearBtn", "Clear Override", "danger"],
  ]) {
    const button = createElement("button", className, label);
    button.id = id;
    routingActions.appendChild(button);
  }
  routingCard.appendChild(routingActions);
  routingCard.appendChild(createElement("div", "status", "尚未查询"));
  routingCard.lastChild.id = "routingStatus";
  routingCard.appendChild(createElement("div", "small", "当前来源摘要：-"));
  routingCard.lastChild.id = "routingSourceSummary";
  const routingSummaryGrid = createElement("div", "status-grid session-context-grid");
  appendStatusMetric(routingSummaryGrid, "routing_key", "routingKeyValue");
  appendStatusMetric(routingSummaryGrid, "auto_session_id", "routingAutoSessionValue");
  appendStatusMetric(routingSummaryGrid, "final_session_id", "routingFinalSessionValue");
  appendStatusMetric(routingSummaryGrid, "routing_mode", "routingModeValue");
  appendStatusMetric(routingSummaryGrid, "routing_reason", "routingReasonValue");
  appendStatusMetric(routingSummaryGrid, "override active", "routingOverrideActiveValue");
  routingCard.appendChild(routingSummaryGrid);
  routingCard.appendChild(createElement("div", "small", "自动带入状态：尚未判断"));
  routingCard.lastChild.id = "routingSourceHint";
  routingCard.appendChild(createElement("div", "small", "尚无 explain"));
  routingCard.lastChild.id = "routingExplainBox";
  // ── 重排：常用置顶（会话/上下文/Live Gate/记忆），调试下沉 ──
  appendSurface(chatSide, sessionCard, "session-list-surface");
  chatSide.appendChild(sessionSummaryCard);
  appendSurface(chatSide, sessionDebugCard, "session-debug-surface");
  appendSurface(chatSide, usedMemoryCard, "memory-evidence-surface");
  appendSurface(chatSide, candidateCard, "candidate-surface");
  chatSide.appendChild(createElement("div", "rail-divider", "调试 / 高级"));
  chatRuntime.evidence.appendChild(chatSide);
  const chatRaw = createElement("div", "runtime-stack chat-raw-column");
  chatRaw.appendChild(createElement("div", "rail-divider", "璋冭瘯 / 楂樼骇"));
  appendSurface(chatRaw, relationshipCard, "relationship-surface");
  chatRaw.appendChild(routingCard);
  appendSurface(chatRaw, chatPreviewCard, "chat-preview-surface");
  appendSurface(chatRaw, messageDebugCard, "message-debug-surface");
  chatRuntime.raw.appendChild(chatRaw);

  const proactivePanel = createPanel("proactivePanel", "主动", "她主动找人聊：当前状态、待处理候选、调度时间线，调试工具在下方。");
  if (proactiveCard) {
    buildProactivePanel(proactivePanel.panel, proactivePanel.header);
  }
  const proactiveRuntime = createRuntimeWorkbench(proactivePanel.panel, "proactive-workbench", "scheduler / gate");
  moveLoosePanelChildren(proactivePanel.panel, proactiveRuntime);

  const consciousnessPanel = createPanel("consciousnessPanel", "大脑", "她的生命体征、事件池与思考过程——意识引擎实时状态。");
  buildConsciousnessPanel(consciousnessPanel.panel, consciousnessPanel.header);
  const consciousnessRuntime = createRuntimeWorkbench(consciousnessPanel.panel, "consciousness-workbench", "state / mind");
  moveLoosePanelChildren(consciousnessPanel.panel, consciousnessRuntime);

  const memoryPanel = createPanel("memoryPanel", "记忆库", "查看、编辑、启用和停用记忆。");
  const memoryRuntime = createRuntimeWorkbench(memoryPanel.panel, "memory-workbench", "memory / policy");
  appendSurface(memoryRuntime.primary, memoryCard, "memory-list-surface");

  const configPanel = createPanel("configPanel", "配置", "Admin Token 和模型/上下文配置。");
  const configRuntime = createRuntimeWorkbench(configPanel.panel, "config-workbench", "config / model");
  appendSurface(configRuntime.primary, configCard, "config-form-surface");

  const debugPanel = createPanel("debugPanel", "日志 / 调试", "查看最近结构化事件、错误和 trace 链路。");
  const debugRuntime = createRuntimeWorkbench(debugPanel.panel, "debug-workbench", "events / trace");
  const debugGrid = createElement("div", "runtime-strip debug-summary-strip");

  const diagnosisCard = createElement("div", "control-surface diagnosis-surface");
  diagnosisCard.appendChild(createElement("h3", "", "当前诊断"));
  const diagnosisActions = createElement("div", "row");
  const refreshDiagnosisButton = createElement("button", "secondary auxiliary", "刷新诊断");
  refreshDiagnosisButton.id = "loadDebugDiagnoseBtn";
  diagnosisActions.appendChild(refreshDiagnosisButton);
  diagnosisCard.appendChild(diagnosisActions);
  diagnosisCard.appendChild(createElement("div", "diagnosis-overall info", "诊断未加载"));
  diagnosisCard.lastChild.id = "debugDiagnosisOverall";
  diagnosisCard.appendChild(createElement("div", "diagnosis-card-grid"));
  diagnosisCard.lastChild.id = "debugDiagnosisCards";
  diagnosisCard.appendChild(createElement("div", "status"));
  diagnosisCard.lastChild.id = "debugDiagnosisStatus";
  debugGrid.appendChild(diagnosisCard);

  const debugSummaryCard = createElement("div", "control-surface debug-summary-surface");
  debugSummaryCard.appendChild(createElement("h3", "", "事件摘要"));
  const debugSummaryGrid = createElement("div", "status-grid");
  appendStatusMetric(debugSummaryGrid, "最近事件", "debugTotalReturned");
  appendStatusMetric(debugSummaryGrid, "最新时间", "debugLatestEventAt");
  appendStatusMetric(debugSummaryGrid, "错误数", "debugErrorCount");
  appendStatusMetric(debugSummaryGrid, "proactive", "debugProactiveCount");
  appendStatusMetric(debugSummaryGrid, "platform", "debugPlatformCount");
  appendStatusMetric(debugSummaryGrid, "chat", "debugChatCount");
  appendStatusMetric(debugSummaryGrid, "openrouter", "debugOpenrouterCount");
  debugSummaryCard.appendChild(debugSummaryGrid);
  debugGrid.appendChild(debugSummaryCard);

  const debugFilterCard = createElement("div", "control-surface debug-filter-surface");
  debugFilterCard.appendChild(createElement("h3", "", "筛选"));
  const debugFilterForm = createElement("div", "config-form debug-filter-grid");
  const moduleField = createElement("div", "config-field");
  const moduleLabel = createElement("label", "", "module");
  moduleLabel.setAttribute("for", "debugModuleInput");
  const moduleSelect = createElement("select");
  moduleSelect.id = "debugModuleInput";
  for (const [value, label] of [
    ["", "全部"],
    ["platform", "platform"],
    ["chat", "chat"],
    ["openrouter", "openrouter"],
    ["proactive", "proactive"],
  ]) {
    const option = createElement("option", "", label);
    option.value = value;
    moduleSelect.appendChild(option);
  }
  moduleField.append(moduleLabel, moduleSelect);

  for (const [id, label, type, value] of [
    ["debugEventInput", "event", "text", ""],
    ["debugTraceInput", "trace_id", "text", ""],
    ["debugLimitInput", "limit", "number", "100"],
  ]) {
    const field = createElement("div", "config-field");
    const fieldLabel = createElement("label", "", label);
    fieldLabel.setAttribute("for", id);
    const input = createElement("input");
    input.id = id;
    input.type = type;
    input.value = value;
    if (id === "debugLimitInput") {
      input.min = "1";
      input.max = "300";
    }
    field.append(fieldLabel, input);
    debugFilterForm.appendChild(field);
  }
  debugFilterForm.prepend(moduleField);
  const debugActions = createElement("div", "row");
  const refreshDebugButton = createElement("button", "", "刷新日志");
  refreshDebugButton.id = "loadDebugEventsBtn";
  debugActions.appendChild(refreshDebugButton);
  debugFilterCard.append(debugFilterForm, debugActions, createElement("div", "status"));
  debugFilterCard.lastChild.id = "debugStatus";
  debugRuntime.evidence.appendChild(debugFilterCard);

  const debugEventsCard = createElement("div", "control-surface debug-events-surface");
  debugEventsCard.appendChild(createElement("h3", "", "事件列表"));
  debugEventsCard.appendChild(createElement("div", "debug-event-list", "还没加载"));
  debugEventsCard.lastChild.id = "debugEventList";
  debugRuntime.raw.appendChild(debugEventsCard);
  debugRuntime.primary.appendChild(debugGrid);

  panelStack.append(
    overview.panel,
    chatPanel.panel,
    consciousnessPanel.panel,
    proactivePanel.panel,
    memoryPanel.panel,
    configPanel.panel,
    debugPanel.panel
  );
  main.appendChild(panelStack);

  const controlWorkspace = createElement("section", "control-workspace workspace-hidden control-framer-shell control-studio-shell");
  controlWorkspace.id = "controlWorkspace";
  controlWorkspace.append(sidebar, main);
  const worldWorkspace = createWorldWorkspace();
  const topbar = createWorkspaceTopbar();

  side.remove();
  document.body.classList.add("world-console-active");
  app.className = `${app.className} app-shell world-console-shell observatory-shell`.trim();
  app.replaceChildren(topbar, worldWorkspace, controlWorkspace);
  bindWorkspaceSwitch(worldWorkspace, controlWorkspace);
  setActivePanel("chatPanel");
}

export function updateCurrentSessionStatus(sessionId, fallbackSessionId) {
  const value = sessionId || fallbackSessionId || "web-test";
  setOptionalText("currentSessionStatus", `当前打开 session：${value}`);
  setOptionalText("currentSessionSidebarId", value);
  setOptionalText("currentSessionPreviewMode", "右键真实消息");
}

export function updateSessionMessageCount(count) {
  setOptionalText("currentSessionMessageCount", count ?? 0);
}
