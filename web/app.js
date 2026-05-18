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
  let inCode = false;
  let codeLines = [];
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (line.trim().startsWith("```")) {
      if (inCode) {
        html += `<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`;
        codeLines = [];
        inCode = false;
      } else {
        if (inList) {
          html += "</ul>";
          inList = false;
        }
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (isTableStart(lines, index)) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      const parsed = parseTable(lines, index);
      html += parsed.html;
      index = parsed.nextIndex - 1;
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      const level = heading[1].length >= 3 ? 3 : 2;
      html += `<h${level}>${inline(heading[2])}</h${level}>`;
    } else if (line.trim() === "---") {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      html += "<hr />";
    } else if (/^\s*(?:\d+\.\s+|[-*]\s+)/.test(line)) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${inline(line.replace(/^\s*(?:\d+\.\s+|[-*]\s+)/, ""))}</li>`;
    } else if (/^\s*>\s+/.test(line)) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      html += `<blockquote>${inline(line.replace(/^\s*>\s+/, ""))}</blockquote>`;
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
  if (inCode) {
    html += `<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`;
  }
  return html;
}

function inline(value) {
  return escapeHtml(value)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function isTableStart(lines, index) {
  const current = lines[index]?.trim() || "";
  const next = lines[index + 1]?.trim() || "";
  return current.startsWith("|") && current.endsWith("|") && /^\|[\s:-|]+\|$/.test(next);
}

function parseTable(lines, index) {
  const header = splitTableRow(lines[index]);
  let cursor = index + 2;
  const rows = [];
  while (cursor < lines.length) {
    const line = lines[cursor].trim();
    if (!line.startsWith("|") || !line.endsWith("|")) {
      break;
    }
    rows.push(splitTableRow(line));
    cursor += 1;
  }
  const head = header.map((cell) => `<th>${inline(cell)}</th>`).join("");
  const body = rows.map((row) => `<tr>${row.map((cell) => `<td>${inline(cell)}</td>`).join("")}</tr>`).join("");
  return {
    html: `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`,
    nextIndex: cursor
  };
}

function splitTableRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
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
