import {
  checkProactiveNow,
  loadProactiveStatus,
  renderProactiveAutoStatus,
  renderProactiveChecks,
  renderProactiveDecision,
} from "./proactiveStatus.js";
import {
  loadProactiveConfig,
  organizeProactiveConfigForm,
  saveProactiveConfig,
} from "./proactiveConfig.js";
import {
  dismissProactiveCandidate,
  dryRunSendCandidate,
  generateProactiveCandidate,
  generateProactiveTestCandidate,
  loadProactiveCandidates,
  loadProactiveTargets,
  rerenderProactiveCandidateViews,
  rerenderProactiveTargetViews,
  renderProactiveCandidates,
  renderProactiveTargets,
  sendCandidate,
} from "./proactiveCandidates.js";
import {
  loadProactiveEvents,
  rerenderProactiveEventViews,
  renderProactiveEvents,
  runProactiveOnce,
} from "./proactiveTimeline.js";

export {
  checkProactiveNow,
  dismissProactiveCandidate,
  dryRunSendCandidate,
  generateProactiveCandidate,
  generateProactiveTestCandidate,
  loadProactiveCandidates,
  loadProactiveConfig,
  loadProactiveEvents,
  loadProactiveStatus,
  loadProactiveTargets,
  organizeProactiveConfigForm,
  renderProactiveAutoStatus,
  renderProactiveCandidates,
  renderProactiveChecks,
  renderProactiveDecision,
  renderProactiveEvents,
  renderProactiveTargets,
  runProactiveOnce,
  saveProactiveConfig,
  sendCandidate,
};

export function bindProactiveEvents() {
  organizeProactiveConfigForm();
  document.getElementById("generateProactiveTestCandidateBtn").addEventListener("click", function () {
    generateProactiveTestCandidate(this, false);
  });
  document.getElementById("forceGenerateProactiveTestCandidateBtn").addEventListener("click", function () {
    generateProactiveTestCandidate(this, true);
  });
  document.getElementById("generateProactiveCandidateBtn").addEventListener("click", function () {
    generateProactiveCandidate(this);
  });
  document.getElementById("loadProactiveCandidatesBtn").addEventListener("click", function () {
    loadProactiveCandidates(this);
  });
  document.getElementById("loadProactiveTargetsBtn").addEventListener("click", function () {
    loadProactiveTargets(this);
  });
  document.getElementById("loadProactiveEventsBtn").addEventListener("click", function () {
    loadProactiveEvents(this);
  });
  document.getElementById("checkProactiveNowBtn").addEventListener("click", function () {
    checkProactiveNow(this);
  });
  document.getElementById("runProactiveOnceBtn").addEventListener("click", function () {
    runProactiveOnce(this);
  });
  document.getElementById("loadProactiveConfigBtn").addEventListener("click", loadProactiveConfig);
  document.getElementById("saveProactiveConfigBtn").addEventListener("click", saveProactiveConfig);
  document.getElementById("proactiveAllowedHashesInput").addEventListener("input", function () {
    this.dataset.dirty = "true";
  });
  document.getElementById("proactiveCandidatePlatformFilter")?.addEventListener("change", rerenderProactiveCandidateViews);
  document.getElementById("proactiveTargetPlatformFilter")?.addEventListener("change", rerenderProactiveTargetViews);
  document.getElementById("proactiveEventPlatformFilter")?.addEventListener("change", rerenderProactiveEventViews);
}
