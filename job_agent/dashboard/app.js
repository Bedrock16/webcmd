/**
 * app.js - Frontend application controller for the JobPilot GMI-Cloud inspired Dashboard.
 * Connects directly to local dashboard_server.py REST endpoints.
 */

let STATE = {
  applied: [],
  skipped: [],
  paused: [],
  stats: {}
};

let CURRENT_FILTER = "all";
let ACTIVE_LOG_COUNT = 0;

// Initialize dashboard on load
document.addEventListener("DOMContentLoaded", () => {
  fetchState();
  fetchStatus();
  fetchLogs();

  // Polling intervals for real-time telemetry
  setInterval(fetchState, 3000);
  setInterval(fetchStatus, 2500);
  setInterval(fetchLogs, 2000);
});

async function fetchState() {
  try {
    const res = await fetch("/api/state");
    if (!res.ok) return;
    const data = await res.json();
    STATE = data;
    updateKPIs(data.stats);
    renderTable();
  } catch (err) {
    console.debug("Failed fetching state:", err);
  }
}

async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const status = await res.json();

    const badge = document.getElementById("deck-status-badge");
    const runBtn = document.getElementById("run-agent-btn");

    if (status.agent_running) {
      badge.textContent = "EXECUTING BROWSER AGENT...";
      badge.className = "badge-online text-cyan";
      runBtn.disabled = true;
      runBtn.textContent = "SCRAPING & EVALUATING...";
      runBtn.style.opacity = "0.7";
    } else {
      badge.textContent = "READY";
      badge.className = "badge-online";
      runBtn.disabled = false;
      runBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5 3 19 12 5 21 5 3"></polygon>
        </svg>
        RUN SCRAPE &amp; AI EVALUATION
      `;
      runBtn.style.opacity = "1";
    }
  } catch (err) {
    console.debug("Failed fetching status:", err);
  }
}

async function fetchLogs() {
  try {
    const res = await fetch("/api/logs");
    if (!res.ok) return;
    const data = await res.json();
    const logs = data.logs || [];

    if (logs.length !== ACTIVE_LOG_COUNT) {
      ACTIVE_LOG_COUNT = logs.length;
      const terminalEl = document.getElementById("terminal-logs");
      terminalEl.innerHTML = "";

      logs.slice(-60).forEach(line => {
        const div = document.createElement("div");
        div.className = "log-entry";

        if (line.includes("ERROR")) {
          div.className += " text-rose";
        } else if (line.includes("PASS") || line.includes("Passed") || line.includes("applied")) {
          div.className += " text-lime";
        } else if (line.includes("STAGE") || line.includes("Processing")) {
          div.className += " text-cyan";
        } else if (line.includes("DEBUG")) {
          div.className += " text-muted";
        }
        div.textContent = line;
        terminalEl.appendChild(div);
      });

      // Auto scroll to bottom
      terminalEl.scrollTop = terminalEl.scrollHeight;

      // Extract current active URL from latest logs
      for (let i = logs.length - 1; i >= Math.max(0, logs.length - 25); i--) {
        const l = logs[i];
        if (l.includes("Navigating to: ")) {
          const u = l.split("Navigating to: ")[1]?.trim();
          if (u && document.getElementById("live-browser-url")) {
            document.getElementById("live-browser-url").textContent = u;
          }
          break;
        } else if (l.includes("Arrived at '")) {
          const u = l.split("Arrived at '")[1]?.split("'")[0]?.trim();
          if (u && document.getElementById("live-browser-url")) {
            document.getElementById("live-browser-url").textContent = u;
          }
          break;
        }
      }
    }
  } catch (err) {
    console.debug("Failed fetching logs:", err);
  }
}

function updateKPIs(stats = {}) {
  const total = stats.total_jobs || 0;
  const qualified = stats.applied_count || 0;
  const skipped = stats.skipped_count || 0;

  if (document.getElementById("kpi-total")) document.getElementById("kpi-total").textContent = total;
  if (document.getElementById("kpi-qualified")) document.getElementById("kpi-qualified").textContent = qualified;
  if (document.getElementById("kpi-skipped")) document.getElementById("kpi-skipped").textContent = skipped;
  if (document.getElementById("kpi-applied")) document.getElementById("kpi-applied").textContent = qualified;
  if (document.getElementById("kpi-paused")) document.getElementById("kpi-paused").textContent = stats.paused_count || 0;
  if (document.getElementById("kpi-pass-rate")) document.getElementById("kpi-pass-rate").textContent = stats.pass_rate || "0%";

  if (document.getElementById("count-all")) document.getElementById("count-all").textContent = total;
  if (document.getElementById("count-applied")) document.getElementById("count-applied").textContent = qualified;
  if (document.getElementById("count-skipped")) document.getElementById("count-skipped").textContent = skipped;
  if (document.getElementById("count-paused")) document.getElementById("count-paused").textContent = stats.paused_count || 0;
}

function setFilter(filter) {
  CURRENT_FILTER = filter;
  document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
  document.getElementById(`tab-${filter}`).classList.add("active");
  renderTable();
}

function renderTable() {
  const tbody = document.getElementById("job-table-body");
  const search = (document.getElementById("table-search-input").value || "").toLowerCase();

  let jobs = [];
  if (CURRENT_FILTER === "all") {
    jobs = [
      ...(STATE.applied || []).map(j => ({ ...j, category: "applied" })),
      ...(STATE.skipped || []).map(j => ({ ...j, category: "skipped" })),
      ...(STATE.paused || []).map(j => ({ ...j, category: "paused" }))
    ];
  } else if (CURRENT_FILTER === "applied") {
    jobs = (STATE.applied || []).map(j => ({ ...j, category: "applied" }));
  } else if (CURRENT_FILTER === "skipped") {
    jobs = (STATE.skipped || []).map(j => ({ ...j, category: "skipped" }));
  } else if (CURRENT_FILTER === "paused") {
    jobs = (STATE.paused || []).map(j => ({ ...j, category: "paused" }));
  }

  // Filter search
  if (search) {
    jobs = jobs.filter(j => 
      (j.title || "").toLowerCase().includes(search) || 
      (j.company || "").toLowerCase().includes(search) ||
      (j.url || "").toLowerCase().includes(search)
    );
  }

  tbody.innerHTML = "";

  if (jobs.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 40px;">
          No job entries found under "${CURRENT_FILTER.toUpperCase()}".
        </td>
      </tr>
    `;
    return;
  }

  jobs.forEach(job => {
    const tr = document.createElement("tr");

    // Status badge
    let statusClass = "status-applied";
    let statusText = "QUALIFIED";
    if (job.category === "skipped" || job.status === "skipped") {
      statusClass = "status-skipped";
      statusText = "FILTERED";
    } else if (job.category === "paused") {
      statusClass = "status-paused";
      statusText = "PAUSED";
    }

    // Score styling
    const scoreVal = parseFloat(job.score !== undefined ? job.score : 0);
    let scoreColor = "text-rose";
    if (scoreVal >= 7.0) scoreColor = "text-lime";
    else if (scoreVal >= 3.0) scoreColor = "text-muted";

    // Clean timestamp
    const dateStr = job.applied_at || job.paused_at || "";
    const formattedTime = dateStr ? new Date(dateStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "-";

    tr.innerHTML = `
      <td><span class="badge-status ${statusClass}">${statusText}</span></td>
      <td>
        <a href="${job.url}" target="_blank" rel="noopener" class="role-title">${escapeHtml(job.title || "Software Engineer")}</a>
        <span class="company-name">${escapeHtml(cleanCompany(job.company))}</span>
      </td>
      <td><span class="score-badge ${scoreColor}">${scoreVal.toFixed(1)} / 10</span></td>
      <td><span class="loc-tag">Remote</span></td>
      <td><span class="time-tag">${formattedTime}</span></td>
      <td>
        <button class="btn-details" onclick='openModal(${JSON.stringify(job).replace(/'/g, "&#39;")})'>VIEW</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function cleanCompany(raw = "") {
  if (!raw) return "Hiring Partner";
  return raw.split("\n")[0].replace("VERIFIED", "").trim();
}

async function launchAgentRun() {
  const role = document.getElementById("role-input").value.trim();
  const dryRun = document.getElementById("dry-run-toggle").checked;

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, dry_run: dryRun })
    });
    const result = await res.json();
    if (!result.ok) {
      alert("Error: " + result.error);
    } else {
      fetchStatus();
    }
  } catch (err) {
    alert("Failed to start agent: " + err);
  }
}

function triggerScanModal() {
  const role = prompt("Enter Target Role Query:", "Remote Junior Python Developer");
  if (role) {
    document.getElementById("role-input").value = role;
    launchAgentRun();
  }
}

function clearLogs() {
  document.getElementById("terminal-logs").innerHTML = "";
  ACTIVE_LOG_COUNT = 0;
}

async function resetDatabase() {
  if (!confirm("Are you sure you want to reset the database? This clears state.json so all scraped jobs can be re-tested and applied to again.")) return;
  try {
    const res = await fetch("/api/reset-state", { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      fetchState();
      alert("Database reset cleanly! You can now launch the pipeline to re-evaluate all jobs.");
    } else {
      alert("Failed to reset database: " + data.error);
    }
  } catch (err) {
    alert("Error resetting database: " + err);
  }
}

// Modal handling
function openModal(job) {
  document.getElementById("modal-job-title").textContent = job.title || "Job Details";
  document.getElementById("modal-job-company").textContent = cleanCompany(job.company);

  const scoreVal = parseFloat(job.score !== undefined ? job.score : 0);
  const scoreEl = document.getElementById("modal-job-score");
  scoreEl.textContent = `${scoreVal.toFixed(1)} / 10`;
  scoreEl.className = "meta-value " + (scoreVal >= 7.0 ? "text-lime" : "text-rose");

  document.getElementById("modal-job-status").textContent = (job.status || job.category || "EVALUATED").toUpperCase();
  document.getElementById("modal-job-time").textContent = job.applied_at || job.paused_at || "Recent run";

  const reasonsList = document.getElementById("modal-job-reasons");
  reasonsList.innerHTML = "";
  const reasons = job.reasons || ["Evaluated against user scoring rules (+3 remote, +3 junior, -5 senior)."];
  reasons.forEach(r => {
    const li = document.createElement("li");
    li.textContent = r;
    reasonsList.appendChild(li);
  });

  const urlEl = document.getElementById("modal-job-url");
  urlEl.href = job.url || "#";

  document.getElementById("detail-modal").classList.add("open");
}

function closeModal(event) {
  if (!event || event.target.id === "detail-modal" || event.target.classList.contains("modal-close")) {
    document.getElementById("detail-modal").classList.remove("open");
  }
}

function openPopoutWindow() {
  const width = 840;
  const height = 620;
  const left = Math.max(0, window.screen.width - width - 40);
  const top = 60;
  window.open(
    "/preview.html",
    "WebcmdLiveBrowserWindow",
    `width=${width},height=${height},left=${left},top=${top},resizable=yes,scrollbars=no,status=no,toolbar=no,menubar=no`
  );
}

async function openDesktopWindow() {
  try {
    const res = await fetch("/api/open-preview-window", { method: "POST" });
    const data = await res.json();
    if (!data.ok) {
      openPopoutWindow();
    }
  } catch (e) {
    openPopoutWindow();
  }
}

function refreshLivePreview() {
  const img = document.getElementById("live-screen-img");
  if (img) {
    img.src = "live_screen.png?t=" + Date.now();
  }
}

// Ensure periodic live preview updates
setInterval(refreshLivePreview, 1500);

function escapeHtml(str = "") {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
