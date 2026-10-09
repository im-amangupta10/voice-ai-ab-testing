let activeExperimentId = null;
let metricsSocket = null;

function setActiveExperiment(expId) {
  activeExperimentId = expId;
  document.getElementById("selected-exp-label").innerText = expId;
  
  if (metricsSocket) {
    metricsSocket.close();
  }
  
  fetchExperimentMetrics(expId);
  connectWebSocket(expId);
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

  // Variant A UI
  document.getElementById("val-calls-a").innerText = varA.total_calls;
  document.getElementById("val-meetings-a").innerText = varA.meetings_fixed;
  document.getElementById("val-rate-a").innerText = `${(varA.conversion_rate * 100).toFixed(1)}%`;
  document.getElementById("val-duration-a").innerText = `${varA.avg_duration_sec}s`;

  // Variant B UI
  document.getElementById("val-calls-b").innerText = varB.total_calls;
  document.getElementById("val-meetings-b").innerText = varB.meetings_fixed;
  document.getElementById("val-rate-b").innerText = `${(varB.conversion_rate * 100).toFixed(1)}%`;
  document.getElementById("val-duration-b").innerText = `${varB.avg_duration_sec}s`;

  // Split Audit
  document.getElementById("val-conf-split").innerText = `${(splitAudit.configured_b_share * 100).toFixed(0)}% B`;
  document.getElementById("val-ach-split").innerText = `${(splitAudit.achieved_b_share * 100).toFixed(1)}% B`;
  
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
  if (guardrail.is_safe) {
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
  btn.disabled = true;
  btn.innerText = "Replaying Calls...";

  try {
    const res = await fetch(`/api/simulator/replay-demo?experiment_id=${activeExperimentId}`, { method: "POST" });
    const result = await res.json();
    alert(result.message);
  } catch (err) {
    alert("Failed triggering simulator: " + err);
  } finally {
    btn.disabled = false;
    btn.innerText = "▶ Replay Sample Calls";
    fetchExperimentMetrics(activeExperimentId);
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
