let activeExperimentId = null;
let metricsSocket = null;

function setActiveExperiment(expId) {
  activeExperimentId = expId;
  document.getElementById("selected-exp-label").innerText = expId;
  
  if (metricsSocket) {
    metricsSocket.close();
  }
  
  fetchExperimentMetrics(expId);
  loadExperimentGoal(expId);
  connectWebSocket(expId);
}

function setGoalControl(goal) {
  const select = document.getElementById("goal-disposition");
  const custom = document.getElementById("custom-goal");
  const known = Array.from(select.options).some((option) => option.value === goal);
  select.value = known ? goal : "__custom__";
  custom.hidden = known;
  if (!known) custom.value = goal || "";
}

async function loadExperimentGoal(expId) {
  try {
    const res = await fetch(`/api/experiments/${expId}`);
    if (res.ok && activeExperimentId === expId) setGoalControl((await res.json()).primary_disposition);
  } catch (err) { console.error("Failed loading experiment goal:", err); }
}

function onGoalSelectionChanged() {
  const isCustom = document.getElementById("goal-disposition").value === "__custom__";
  document.getElementById("custom-goal").hidden = !isCustom;
  if (!isCustom) savePrimaryGoal();
}

function getSelectedPrimaryGoal() {
  const select = document.getElementById("goal-disposition");
  return select.value === "__custom__" ? document.getElementById("custom-goal").value.trim() : select.value;
}

async function savePrimaryGoal() {
  if (!activeExperimentId) return alert("Select an experiment first.");
  const goal = getSelectedPrimaryGoal();
  if (!goal) return alert("Enter a non-empty disposition label.");
  const button = document.getElementById("btn-save-goal");
  button.disabled = true;
  try {
    const res = await fetch(`/api/experiments/${activeExperimentId}/goal`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ primary_disposition: goal })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not save goal");
    setGoalControl(data.primary_disposition);
    await fetchExperimentMetrics(activeExperimentId);
    const panel = document.getElementById("replay-results");
    panel.style.display = "block";
    panel.textContent = `Primary goal saved: ${data.primary_disposition}`;
  } catch (err) { alert(`Could not save goal: ${err.message || err}`); }
  finally { button.disabled = false; }
}

async function fetchExperimentMetrics(expId) {
  try {
    const res = await fetch(`/api/experiments/${expId}/metrics`);
    if (res.ok) {
      const data = await res.json();
      updateDashboardUI(data);
    }
  } catch (err) {
    console.error("Failed fetching metrics:", err);
  }
}

function connectWebSocket(expId) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/metrics/${expId}`;
  
  metricsSocket = new WebSocket(wsUrl);
  
  metricsSocket.onmessage = function(event) {
    const data = JSON.parse(event.data);
    updateDashboardUI(data);
  };
  
  metricsSocket.onclose = function() {
    console.log("WebSocket closed. Reconnecting in 3s...");
    setTimeout(() => {
      if (activeExperimentId === expId) connectWebSocket(expId);
    }, 3000);
  };
}

function updateDashboardUI(data) {
  if (!data || !data.metrics) return;

  const varA = data.metrics.variant_A;
  const varB = data.metrics.variant_B;
  const splitAudit = data.traffic_split_audit;
  const lift = data.metrics.lift;
  const guardrail = data.metrics.guardrail;
  const configuredTraffic = data.configured_traffic || { A: 0.9, B: 0.1 };
  const primaryGoal = data.primary_goal || "BL Enriched";

  const decisionBadge = document.getElementById("current-decision");
  decisionBadge.innerText = data.current_decision || data.status || "—";
  decisionBadge.className = data.status === "RUNNING" ? "badge badge-running" : "badge badge-concluded";
  document.getElementById("confidence-threshold").innerText = `▲ ${(data.confidence_level * 100).toFixed(1)}% Threshold`;
  document.getElementById("goal-label-a").innerText = primaryGoal;
  document.getElementById("goal-label-b").innerText = primaryGoal;

  // Variant A UI
  document.getElementById("val-calls-a").innerText = varA.total_calls;
  document.getElementById("val-goal-a").innerText = varA.goal_successes;
  document.getElementById("val-rate-a").innerText = `${(varA.conversion_rate * 100).toFixed(1)}%`;
  const ciA = varA.conversion_credible_interval || [0, 1];
  document.getElementById("interval-a").innerText = `95% credible interval: ${(ciA[0] * 100).toFixed(1)}–${(ciA[1] * 100).toFixed(1)}%`;
  document.getElementById("val-duration-a").innerText = varA.duration_samples ? `${varA.avg_duration_sec}s` : "N/A";

  // Variant B UI
  document.getElementById("val-calls-b").innerText = varB.total_calls;
  document.getElementById("val-goal-b").innerText = varB.goal_successes;
  document.getElementById("val-rate-b").innerText = `${(varB.conversion_rate * 100).toFixed(1)}%`;
  const ciB = varB.conversion_credible_interval || [0, 1];
  document.getElementById("interval-b").innerText = `95% credible interval: ${(ciB[0] * 100).toFixed(1)}–${(ciB[1] * 100).toFixed(1)}%`;
  document.getElementById("val-duration-b").innerText = varB.duration_samples ? `${varB.avg_duration_sec}s` : "N/A";

  // Split Audit
  document.getElementById("val-conf-split").innerText = `${(splitAudit.configured_b_share * 100).toFixed(0)}% B`;
  document.getElementById("val-ach-split").innerText = `${(splitAudit.achieved_b_share * 100).toFixed(1)}% B`;
  document.getElementById("traffic-label-a").innerText = `${(configuredTraffic.A * 100).toFixed(0)}% Traffic`;
  document.getElementById("traffic-label-b").innerText = `${(configuredTraffic.B * 100).toFixed(0)}% Traffic`;
  document.getElementById("guardrail-limit").innerText = `Limit: Max +${guardrail.max_allowed_delta}s increase over control.`;
  
  const splitStatus = document.getElementById("split-alignment-badge");
  if (splitAudit.is_aligned) {
    splitStatus.innerText = "ALIGNED ✅";
    splitStatus.className = "badge badge-running";
  } else {
    splitStatus.innerText = "DRIFT DETECTED ⚠️";
    splitStatus.className = "badge badge-stopped";
  }

  // Bayesian Win Probability Meter
  const pWin = data.bayesian_p_b_wins !== undefined ? data.bayesian_p_b_wins : 0.50;
  const pWinPct = (pWin * 100).toFixed(1);
  const meterFill = document.getElementById("meter-confidence-fill");
  meterFill.style.width = `${Math.min(Math.max(pWin * 100, 5), 100)}%`;
  meterFill.innerText = `${pWinPct}%`;
  document.getElementById("val-p-win").innerText = `P(B > A) = ${pWin.toFixed(3)}`;

  // Guardrail Status
  const guardrailBadge = document.getElementById("guardrail-badge");
  if (!guardrail.available) {
    guardrailBadge.innerText = "UNAVAILABLE (NO VALID DURATION DATA)";
    guardrailBadge.className = "badge badge-concluded";
  } else if (guardrail.is_safe) {
    guardrailBadge.innerText = `SAFE (+${guardrail.duration_delta_sec}s)`;
    guardrailBadge.className = "badge badge-running";
  } else {
    guardrailBadge.innerText = `BREACHED (+${guardrail.duration_delta_sec}s)`;
    guardrailBadge.className = "badge badge-stopped";
  }
}

async function triggerSimulator() {
  if (!activeExperimentId) {
    alert("Please select or create an experiment first!");
    return;
  }
  const btn = document.getElementById("btn-run-sim");
  const panel = document.getElementById("replay-results");
  btn.disabled = true;
  btn.innerText = "Starting full CSV replay…";
  panel.style.display = "block";
  panel.textContent = "Starting replay for all remaining calls in sample_calls.csv. Sarvam is attempted first; CSV fallback is labeled separately. This may take some time…";

  try {
    const res = await fetch(`/api/simulator/replay-demo?experiment_id=${encodeURIComponent(activeExperimentId)}`, { method: "POST" });
    let job = await res.json();
    if (!res.ok) throw new Error(job.detail || job.message || "Replay failed");
    while (job.status === "queued" || job.status === "running") {
      if (activeExperimentId === job.experiment_id) {
        btn.innerText = `Replaying ${job.completed}/${job.total} calls…`;
        panel.innerHTML = `<strong>Full CSV replay: ${job.completed}/${job.total}</strong><br>${escapeHtml(formatReplayCounts(job.counts))}`;
      }
      await new Promise((resolve) => setTimeout(resolve, 1500));
      const statusRes = await fetch(`/api/simulator/replay-demo/${encodeURIComponent(job.job_id)}`);
      job = await statusRes.json();
      if (!statusRes.ok) throw new Error(job.detail || "Could not read replay progress");
    }
    if (job.status !== "completed") throw new Error(job.error || `Replay ended with status ${job.status}`);
    const rows = (job.recent_results || []).map((item) => {
      if (item.status === "skipped") return `${item.call_id || "Call"}: already replayed`;
      if (item.status === "routed") return `${item.call_id || "Call"}: not evaluated — ${item.message || "experiment is not running"}`;
      if (item.status !== "success") return `${item.call_id || "Call"}: ${item.error_message || "failed"}`;
      const source = item.evaluation_mode === "historical_csv_fallback" ? "CSV fallback" : "Sarvam estimate";
      return `${item.call_id || "Call"}: Variant ${item.assigned_variant} · ${item.disposition} · ${source}`;
    });
    panel.innerHTML = `<strong>Full CSV replay complete: ${job.completed}/${job.total} remaining calls processed.</strong><br>${escapeHtml(formatReplayCounts(job.counts))}<br><br><strong>Most recent calls</strong>${rows.map((row) => `<div>${escapeHtml(row)}</div>`).join("")}<div class="muted">${escapeHtml(job.note || "")}</div>`;
    if (activeExperimentId === job.experiment_id) await fetchExperimentMetrics(activeExperimentId);
  } catch (err) {
    panel.textContent = `Replay failed: ${err.message || err}`;
  } finally {
    btn.disabled = false;
    btn.innerText = "▶ Replay Sample Calls";
  }
}

function formatReplayCounts(counts = {}) {
  return `Sarvam estimates: ${counts.simulated_counterfactual || 0} · Historical CSV fallbacks: ${counts.historical_csv_fallback || 0} · Routed: ${counts.routed || 0} · Failed: ${counts.error || 0}`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

async function runDecisionScenarios() {
  if (!confirm("Create isolated synthetic experiments for winner, early-stop, and inconclusive demos?")) return;
  try {
    const res = await fetch("/api/simulator/demo-scenarios", { method: "POST" });
    const result = await res.json();
    if (!res.ok) throw new Error(result.detail || result.message || "Scenario run failed");
    const lines = (result.scenarios || []).map((item) =>
      `${item.scenario}: ${item.decision || item.status}${item.reason ? ` — ${item.reason}` : ""}`
    );
    alert(`${result.message}\n\n${lines.join("\n")}`);
    window.location.reload();
  } catch (err) {
    alert(`Scenario run failed: ${err.message || err}`);
  }
}

async function triggerDecisionEvaluation() {
  if (!activeExperimentId) return;
  try {
    const res = await fetch(`/api/experiments/${activeExperimentId}/evaluate`, { method: "POST" });
    const decision = await res.json();
    alert(`Decision: ${decision.decision}\nReason: ${decision.reason}`);
    window.location.reload();
  } catch (err) {
    alert("Evaluation failed: " + err);
  }
}

async function updateStatus(action) {
  if (!activeExperimentId) return;
  try {
    const res = await fetch(`/api/experiments/${activeExperimentId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: action })
    });
    const result = await res.json();
    alert(result.message);
    window.location.reload();
  } catch (err) {
    alert("Action failed: " + err);
  }
}

// Auto-select first experiment if available
document.addEventListener("DOMContentLoaded", () => {
  const select = document.getElementById("experiment-selector");
  if (select && select.value) {
    setActiveExperiment(select.value);
  }
});
