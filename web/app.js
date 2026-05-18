const state = {
  scenarios: [],
  selectedService: "checkout-api",
  lastReport: ""
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

function setHealth(data) {
  const badge = $("healthBadge");
  badge.classList.toggle("ok", data.splunk_ok);
  badge.classList.toggle("bad", !data.splunk_ok);
  badge.textContent = data.splunk_ok
    ? `Splunk ${data.splunk.version} healthy`
    : "Splunk unavailable";
  $("aiMode").textContent = data.ai_mode;
  $("mcpMode").textContent = data.mcp_configured ? "configured" : "not configured";
  $("indexName").textContent = data.index;
}

function renderScenarios() {
  const list = $("scenarioList");
  list.innerHTML = "";
  for (const scenario of state.scenarios) {
    const button = document.createElement("button");
    button.className = `scenario ${scenario.service === state.selectedService ? "active" : ""}`;
    button.innerHTML = `<strong>${escapeHtml(scenario.title)}</strong><span>${escapeHtml(scenario.description)}</span>`;
    button.addEventListener("click", () => {
      state.selectedService = scenario.service;
      $("serviceInput").value = scenario.service;
      renderScenarios();
    });
    list.appendChild(button);
  }
}

function markdownToHtml(markdown) {
  const lines = markdown.split("\n");
  let html = "";
  let inList = false;
  for (const line of lines) {
    if (line.startsWith("## ")) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      html += `<h2>${inline(line.slice(3))}</h2>`;
    } else if (/^\d+\.\s+/.test(line) || line.startsWith("- ")) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${inline(line.replace(/^\d+\.\s+/, "").replace(/^-\s+/, ""))}</li>`;
    } else if (line.startsWith("> ")) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      html += `<blockquote>${inline(line.slice(2))}</blockquote>`;
    } else if (line.trim()) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      html += `<p>${inline(line)}</p>`;
    }
  }
  if (inList) {
    html += "</ul>";
  }
  return html;
}

function inline(value) {
  return escapeHtml(value).replace(/`([^`]+)`/g, "<code>$1</code>");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderEvidence(evidence) {
  const container = $("evidenceList");
  container.innerHTML = "";
  for (const item of evidence) {
    const wrapper = document.createElement("div");
    wrapper.className = "evidence-item";
    const rows = item.results || [];
    const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).slice(0, 7);
    wrapper.innerHTML = `
      <div class="evidence-title">
        <strong>${escapeHtml(item.title)}</strong>
        <span class="count">${rows.length} rows</span>
      </div>
      <code class="spl">${escapeHtml(item.spl)}</code>
      ${item.error ? `<p class="empty">${escapeHtml(item.error)}</p>` : renderTable(rows, keys)}
    `;
    container.appendChild(wrapper);
  }
}

function renderTable(rows, keys) {
  if (!rows.length) {
    return `<p class="empty">No rows returned.</p>`;
  }
  const header = keys.map((key) => `<th>${escapeHtml(key)}</th>`).join("");
  const body = rows.slice(0, 8).map((row) => {
    return `<tr>${keys.map((key) => `<td>${escapeHtml(row[key] ?? "")}</td>`).join("")}</tr>`;
  }).join("");
  return `<table class="result-table"><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
}

async function runInvestigation() {
  const button = $("runButton");
  button.disabled = true;
  button.textContent = "Investigating";
  $("reportTitle").textContent = $("serviceInput").value;
  $("report").innerHTML = "<p>Running Splunk searches and preparing report...</p>";
  $("evidenceList").innerHTML = "";
  try {
    const data = await api("/api/investigate", {
      method: "POST",
      body: JSON.stringify({
        service: $("serviceInput").value.trim(),
        window_minutes: Number($("windowInput").value),
        question: $("questionInput").value.trim()
      })
    });
    state.lastReport = data.report;
    $("report").innerHTML = markdownToHtml(data.report);
    $("aiMode").textContent = data.ai_used ? "openai" : "local-summary";
    $("mcpMode").textContent = data.mcp_configured ? "configured" : "not configured";
    renderEvidence(data.evidence);
  } catch (error) {
    $("report").innerHTML = `<blockquote>${escapeHtml(error.message)}</blockquote>`;
  } finally {
    button.disabled = false;
    button.textContent = "Run Investigation";
  }
}

async function init() {
  try {
    setHealth(await api("/api/health"));
  } catch (error) {
    setHealth({ splunk_ok: false, splunk: {}, ai_mode: "-", mcp_configured: false, index: "-" });
  }
  const scenarioData = await api("/api/scenarios");
  state.scenarios = scenarioData.scenarios;
  renderScenarios();
  $("runButton").addEventListener("click", runInvestigation);
  $("copyButton").addEventListener("click", async () => {
    await navigator.clipboard.writeText(state.lastReport || $("report").innerText);
    $("copyButton").textContent = "Copied";
    setTimeout(() => ($("copyButton").textContent = "Copy Report"), 1000);
  });
}

init();

