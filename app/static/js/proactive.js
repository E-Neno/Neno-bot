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
  dryRunSendQqCandidate,
  generateProactiveCandidate,
  generateProactiveTestCandidate,
  loadProactiveCandidates,
  loadProactiveTargets,
  renderProactiveCandidates,
  renderProactiveTargets,
  sendQqCandidate,
} from "./proactiveCandidates.js";
import {
  loadProactiveEvents,
  renderProactiveEvents,
  runProactiveOnce,
} from "./proactiveTimeline.js";

export {
  checkProactiveNow,
  dismissProactiveCandidate,
  dryRunSendQqCandidate,
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
  sendQqCandidate,
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
}
