import { getAdminHeaders, requestJson } from "./api.js";
import { getSessionId } from "./chat.js";

const relationshipStagePresets = {
  stranger: {
    stage: 0,
    conversation_count: 0,
    familiarity_score: 0,
    trust_score: 0,
    emotional_depth_score: 0,
    boundary_score: 0,
  },
  familiar: {
    stage: 1,
    conversation_count: 12,
    familiarity_score: 8,
    trust_score: 1,
    emotional_depth_score: 0,
    boundary_score: 2,
  },
  stable: {
    stage: 2,
    conversation_count: 45,
    familiarity_score: 28,
    trust_score: 8,
    emotional_depth_score: 5,
    boundary_score: 10,
  },
  close: {
    stage: 3,
    conversation_count: 130,
    familiarity_score: 60,
    trust_score: 30,
    emotional_depth_score: 25,
    boundary_score: 20,
  },
  deep: {
    stage: 4,
    conversation_count: 300,
    familiarity_score: 120,
    trust_score: 80,
    emotional_depth_score: 70,
    boundary_score: 40,
  },
};

export function renderRelationshipState(state) {
  if (!state) {
    return;
  }

  document.getElementById("relStageLabel").textContent = state.stage_label || "-";
  document.getElementById("relConversationCount").textContent = state.conversation_count ?? 0;
  document.getElementById("relFamiliarityScore").textContent = state.familiarity_score ?? 0;
  document.getElementById("relTrustScore").textContent = state.trust_score ?? 0;
  document.getElementById("relEmotionalDepthScore").textContent = state.emotional_depth_score ?? 0;
  document.getElementById("relBoundaryScore").textContent = state.boundary_score ?? 0;
}

export function renderRelationshipContext(context) {
  const box = document.getElementById("relationshipContextBox");
  box.textContent = context || "暂无";
}

export async function loadRelationshipState() {
  const status = document.getElementById("relationshipStatus");
  status.textContent = "加载中...";

  try {
    const data = await requestJson(
      `/relationship/state?session_id=${encodeURIComponent(getSessionId())}`,
      undefined,
      "加载失败："
    );
    renderRelationshipState(data);
    status.textContent = "已刷新";
  } catch (err) {
    status.textContent = err.message;
  }
}

export async function resetRelationshipState() {
  const sessionId = getSessionId();

  if (!confirm(`确定重置 ${sessionId} 的关系状态吗？`)) {
    return;
  }

  const status = document.getElementById("relationshipStatus");
  status.textContent = "重置中...";

  try {
    const data = await requestJson(
      "/relationship/reset",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({ session_id: sessionId }),
      },
      "重置失败："
    );
    renderRelationshipState(data);
    status.textContent = "已重置";
  } catch (err) {
    status.textContent = err.message;
  }
}

export async function setRelationshipStagePreset(presetKey) {
  const preset = relationshipStagePresets[presetKey];
  const status = document.getElementById("relationshipStatus");

  if (!preset) {
    status.textContent = "未知关系阶段预设";
    return;
  }

  status.textContent = "设置中...";

  try {
    const data = await requestJson(
      "/relationship/update",
      {
        method: "POST",
        headers: getAdminHeaders(),
        body: JSON.stringify({
          session_id: getSessionId(),
          ...preset,
        }),
      },
      "设置失败："
    );
    renderRelationshipState(data);
    status.textContent = "已设置";
  } catch (err) {
    status.textContent = err.message;
  }
}

export function bindRelationshipEvents() {
  document.getElementById("loadRelationshipStateBtn").addEventListener("click", loadRelationshipState);
  document.getElementById("resetRelationshipStateBtn").addEventListener("click", resetRelationshipState);

  for (const button of document.querySelectorAll("[data-stage-preset]")) {
    button.addEventListener("click", () => setRelationshipStagePreset(button.dataset.stagePreset));
  }
}
