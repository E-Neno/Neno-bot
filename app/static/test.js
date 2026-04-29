import { buildConsoleLayout } from "./js/layout.js";
import {
  bindDebugEvents,
  loadDebugEvents,
} from "./js/debug.js";
import {
  bindProactiveEvents,
  loadProactiveCandidates,
  loadProactiveConfig,
  loadProactiveEvents,
  loadProactiveStatus,
  loadProactiveTargets,
} from "./js/proactive.js";
import {
  bindChatEvents,
  renderUsedMemories,
} from "./js/chat.js";
import {
  bindConfigEvents,
  loadConfig,
  updateAdminTokenStatus,
} from "./js/config.js";
import {
  bindMemoryEvents,
  loadMemories,
} from "./js/memory.js";
import {
  bindRelationshipEvents,
  loadRelationshipState,
  renderRelationshipContext,
  renderRelationshipState,
} from "./js/relationship.js";
import {
  bindSessionEvents,
  loadSessionMessages,
  loadSessions,
} from "./js/sessions.js";
import {
  bindStatsEvents,
  loadStatsSummary,
} from "./js/stats.js";

function bindBaseEvents() {
  bindChatEvents({
    renderRelationshipState,
    renderRelationshipContext,
  });
  bindSessionEvents();
  bindConfigEvents({
    onTokenSaved: () => {
      loadStatsSummary();
      loadProactiveCandidates();
    },
    onTokenCleared: () => {
      loadProactiveCandidates();
    },
  });
  bindStatsEvents();
  bindRelationshipEvents();
  bindMemoryEvents();
}

function init() {
  buildConsoleLayout();
  bindBaseEvents();
  bindProactiveEvents();
  bindDebugEvents();
  loadConfig();
  loadSessions();
  loadMemories();
  loadSessionMessages();
  loadRelationshipState();
  renderUsedMemories([]);
  updateAdminTokenStatus();
  loadDebugEvents();
  loadStatsSummary();
  loadProactiveStatus();
  loadProactiveConfig();
  loadProactiveCandidates();
  loadProactiveTargets();
  loadProactiveEvents();
}

function finishInitialLoading() {
  document.body?.classList.remove("app-loading");
}

function showInitializationError(error) {
  const errorBox = document.createElement("div");
  errorBox.id = "appInitError";
  errorBox.className = "app-init-error";
  errorBox.setAttribute("role", "alert");
  errorBox.textContent = `页面初始化失败：${error instanceof Error ? error.message : String(error)}`;
  document.body?.prepend(errorBox);
}

function runInit() {
  try {
    init();
  } catch (err) {
    console.error("Neno test page initialization failed", err);
    showInitializationError(err);
  } finally {
    finishInitialLoading();
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", runInit);
} else {
  runInit();
}
