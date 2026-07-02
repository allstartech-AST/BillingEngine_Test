const content = document.getElementById("content");
const runStatus = document.getElementById("run-status");
const btnRun = document.getElementById("btn-run");
const API_BASE = (window.location.protocol === "http:" || window.location.protocol === "https:")
  ? window.location.origin
  : null;

function apiUrl(path) {
  if (!API_BASE) {
    throw new Error("Open this page at http://127.0.0.1:8000/prototype — not as a local file.");
  }
  return API_BASE + path;
}

function setStatus(message, type) {
  const elements = document.querySelectorAll('.run-status');
  elements.forEach(el => {
    el.textContent = message;
    el.className = "run-status" + (type ? " " + type : "");
  });
  const visibleStatus = Array.from(elements).find(el => el.offsetParent !== null);
  if (visibleStatus) {
    visibleStatus.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

async function checkServerOnLoad() {
  if (!API_BASE) {
    content.innerHTML =
      '<div class="error"><strong>Wrong page URL.</strong> Open ' +
      '<a href="http://127.0.0.1:8000/prototype">http://127.0.0.1:8000/prototype</a> ' +
      'after starting the server (<code>python -m uvicorn app.main:app --reload</code>).</div>';
    setStatus("Not running through the billing server.", "error");
    return false;
  }
  try {
    const response = await fetch(apiUrl("/health"));
    const data = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      throw new Error(formatApiError(data.detail || response.statusText));
    }
    if (!data.live_api) {
      content.innerHTML =
        '<div class="error"><strong>Outdated server.</strong> The API on this port does not include live session routes. ' +
        'Stop all uvicorn processes and restart from ProperData:<br><code>python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000</code></div>';
      setStatus("Server missing live API — restart required.", "error");
      return false;
    }
    setStatus("Connected to billing engine.", "success");
    return true;
  } catch (err) {
    content.innerHTML =
      '<div class="error"><strong>Cannot reach billing engine.</strong> ' +
      escapeHtml(err.message) +
      '<br>Start the server: <code>python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000</code></div>';
    setStatus("Server not reachable.", "error");
    return false;
  }
}

function formatApiError(detail, status) {
  if (status === 404 && (detail === "Not Found" || !detail)) {
    return "API route not found (404). Restart uvicorn from ProperData so /live/session routes are loaded.";
  }
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map(function (item) {
      var loc = (item.loc || []).join(".");
      return (loc ? loc + ": " : "") + (item.msg || JSON.stringify(item));
    }).join("; ");
  }
  return JSON.stringify(detail);
}

function normalizeSessionPayload(raw) {
  if (raw && raw.client_info && raw.session_metadata && raw.detected_cpt_codes) {
    return raw;
  }
  if (raw && raw.diagnosis_validation && raw.ui_display) {
    throw new Error(
      "This looks like an API response, not session input. Paste the INPUT JSON with client_info, session_metadata, diagnoses, and detected_cpt_codes (see tests/fixtures/*.json)."
    );
  }
  throw new Error(
    "Missing required fields. Session JSON must include client_info, session_metadata, diagnoses, and detected_cpt_codes."
  );
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function renderIcdCard(card) {
  const review = card.card_style === "review" ? " review" : "";
  const codes = (card.detected_icd10_codes && card.detected_icd10_codes.length)
    ? card.detected_icd10_codes
    : [card.icd10_code];
  const codeLine = codes.map(function (c) { return escapeHtml(c); }).join(", ");
  const primary = card.is_primary ? '<span class="badge-primary">Primary</span>' : "";
  const suggestions = card.suggestions.length
    ? `<ul class="suggestion-list">${card.suggestions.map(s => `<li>${escapeHtml(s.summary)}</li>`).join("")}</ul>`
    : "";
  const linked = card.linked_cpt_codes.length
    ? `Linked CPTs: ${card.linked_cpt_codes.join(", ")}`
    : "Linked CPTs: none";
  return `
        <div class="icd-card${review}">
          <div class="card-title">ICD-10 Detected: ${codeLine}${primary}</div>
          ${card.label ? `<div class="card-meta">${escapeHtml(card.label)}</div>` : ""}
          <div class="card-meta">Status: <strong>${escapeHtml(card.transcript_support)}</strong></div>
          <div class="card-meta">${escapeHtml(linked)} · ${escapeHtml(card.crosswalk_summary)}</div>
          ${suggestions}
          ${card.acknowledge_enabled ? '<div class="card-actions"><button class="btn-text">Acknowledge</button></div>' : ""}
        </div>`;
}

function renderModifierPills(modifiers) {
  if (!modifiers || !modifiers.length) return "";
  return '<div class="modifier-pills">' + modifiers.map(function (m) {
    return '<span class="modifier-pill">-' + escapeHtml(m) + '</span>';
  }).join("") + '</div>';
}

function renderCptCard(card) {
  const review = card.card_style === "review" ? " review" : "";
  const badge = card.badge ? `<span class="badge-black">${escapeHtml(card.badge)}</span>` : "";
  const conflict = card.conflict_message
    ? `<div class="conflict-text">${escapeHtml(card.conflict_message)}</div>`
    : "";
  const modifierPills = renderModifierPills(card.applied_modifiers);
  const isEnded = card.duration_display && card.duration_display !== "—";
  const extraSuggestions = card.suggestions
    .filter(function (s) {
      if (s.type === "ncci_bundling" || s.type === "temporal_overlap") return false;
      if (isEnded && (s.type === "rule_applicability" || s.type === "awaiting_end")) return false;
      return true;
    })
    .map(s => `<li>${escapeHtml(s.summary)}</li>`).join("");
  const suggestionList = extraSuggestions
    ? `<ul class="suggestion-list">${extraSuggestions}</ul>` : "";
  const actions = (card.actions.approve_enabled || card.actions.reject_enabled)
    ? `<div class="card-actions" style="display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 10px;">
            ${card.actions.reject_enabled ? '<button class="btn-text reject" data-action="reject">✕ Reject</button>' : ""}
            ${card.actions.approve_enabled ? `
              <span style="font-size: 13px; font-weight: 500;">Resolve with:</span>
              <button class="btn-text modifier-btn" data-action="approve" data-modifier="59">59</button>
              <button class="btn-text modifier-btn" data-action="approve" data-modifier="XE">XE</button>
              <button class="btn-text modifier-btn" data-action="approve" data-modifier="XP">XP</button>
              <button class="btn-text modifier-btn" data-action="approve" data-modifier="XS">XS</button>
              <button class="btn-text modifier-btn" data-action="approve" data-modifier="XU">XU</button>
              <input type="text" class="custom-modifier-input" placeholder="Custom..." style="width: 70px; padding: 2px 6px; font-size: 13px;">
              <button class="btn-text custom-modifier-apply" data-action="approve">Apply</button>
            ` : ""}
           </div>` : "";
  const unitsHtml = card.is_timed
    ? `Unit(s): <strong><span id="units-display-${escapeHtml(card.cpt_code)}">${card.units_display}</span></strong>`
    : `<del>Unit(s)</del> <span style="font-size: 0.85em; color: var(--muted);">(Must update manually: not a timed code)</span>`;

  let startDisabled = "";
  let startTooltip = "";
  if (card.duration_display !== "—") {
    if (card.status === "manual") {
      startDisabled = 'style="display: none;"';
    } else {
      startDisabled = "disabled";
      startTooltip = 'title="Timer already recorded"';
    }
  } else {
    startDisabled = 'style="background: #16a34a; color: white; padding: 4px 10px; border-radius: 6px;"';
  }

  return `
        <div class="cpt-card${review}" data-cpt="${escapeHtml(card.cpt_code)}" data-is-timed="${card.is_timed}"${card.conflict_id ? ' data-conflict-id="' + escapeHtml(card.conflict_id) + '"' : ""}>
          <div class="card-title" style="display: flex; justify-content: space-between; align-items: flex-start;">
            <span>${escapeHtml(card.cpt_code)} — ${escapeHtml(card.short_label)}</span>
            ${(card.duration_display === "—") ? `
            <div class="timer-actions" style="display: flex; align-items: center; gap: 8px;">
              <span class="timer-countdown" style="font-size: 12px; color: var(--muted); display: none;"></span>
              <span class="timer-display" style="font-family: monospace; font-size: 16px; font-weight: 700; color: #2563eb; display: none;">00:00</span>
              <button class="btn-demo" data-action="start-timer" ${startDisabled} ${startTooltip}>Start</button>
              <button class="btn-demo" data-action="pause-timer" style="background: #f59e0b; color: white; padding: 4px 10px; border-radius: 6px; display: none; cursor: pointer;">Pause</button>
              <button class="btn-demo" data-action="stop-timer" style="background: #dc2626; color: white; padding: 4px 10px; border-radius: 6px; display: none; cursor: pointer;">Stop</button>
            </div>` : `<span class="edit-icon">✎</span>`}
          </div>
          <div class="card-meta">${unitsHtml} &nbsp;&nbsp; Duration: <strong><span id="duration-display-${escapeHtml(card.cpt_code)}">${escapeHtml(card.duration_display)}</span></strong></div>
          
          ${badge}
          ${conflict}
          ${modifierPills}
          ${suggestionList}
          ${actions}
        </div>`;
}

function renderRemoved(item) {
  return `<div class="removed-row"><strong>${escapeHtml(item.cpt_code)}</strong> — ${escapeHtml(item.reason)}: ${escapeHtml(item.details)}</div>`;
}

function renderUi(ui, onModifierAction) {
  const h = ui.session_header;
  const s = ui.summary_cards;

  document.getElementById("session-title").textContent = h.session_title;
  document.getElementById("status-pill").textContent = h.status_label;
  document.getElementById("meta-row").innerHTML = `
        <span>📅 ${escapeHtml(h.session_datetime)}</span>
        <span>Patient ID: #${escapeHtml(h.patient_id.replace(/^#/, ""))}</span>
        <span>Duration: ${escapeHtml(h.duration_display)}</span>
        <span id="header-units-display">Unit(s): ${h.units_total}</span>`;

  const eightMin = s.eight_minute_rule
    ? '<span class="pill-green">8 Minute Rule</span>' : "";

  let html = `
        <div class="summary-row">
          <div class="summary-card">
            <h3>Session Time</h3>
            <p class="summary-value">${escapeHtml(s.session_time_display)}</p>
            ${s.threshold_note ? `<p class="summary-sub">${escapeHtml(s.threshold_note)}</p>` : ""}
          </div>
          <div class="summary-card">
            <span class="info-icon" title="Pooled 8-minute rule across timed CPTs">i</span>
            <h3>Session Units</h3>
            <p class="summary-value" id="summary-units-display">${s.session_units_total} Units</p>
            ${eightMin}
          </div>
        </div>`;

  if (ui.icd_cards.length) {
    html += `<div class="section-heading"><h2>Diagnoses (ICD-10)</h2></div>`;
    html += ui.icd_cards.map(renderIcdCard).join("");
  }

  html += `
        <div class="section-heading">
          <h2>CPT Codes Detected</h2>
          <span class="add-link">+ Add more CPTs</span>
        </div>`;
  html += ui.cpt_cards.map(renderCptCard).join("");

  if (ui.removed_section.length) {
    html += `<div class="removed-section"><h2>Removed automatically</h2>`;
    html += ui.removed_section.map(renderRemoved).join("");
    html += `</div>`;
  }

  content.innerHTML = html;

  content.querySelectorAll("[data-action]").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      const card = e.target.closest(".cpt-card");
      const cpt = card?.dataset.cpt;
      const action = e.target.dataset.action;

      if (action === "start-timer") {
        try {
          await liveCptStart(cpt);
          startCptTimer(cpt);
        } catch (err) {
          // error shown in liveCptStart
        }
        return;
      }
      if (action === "stop-timer") {
        if (window.activeCptTimers && window.activeCptTimers[cpt]) {
          await window.activeCptTimers[cpt].stop();
        }
        return;
      }
      if (action === "pause-timer") {
        if (window.activeCptTimers && window.activeCptTimers[cpt]) {
          const timer = window.activeCptTimers[cpt];
          if (!timer.isPaused) {
            // Pause it
            try {
              await liveApi("/live/session/" + liveSessionId + "/cpt/pause", "POST", { cpt_code: cpt, duration_minutes: timer.secondsElapsed });
              timer.isPaused = true;
              updateTimerUI(cpt, timer.secondsElapsed);
            } catch (err) { setStatus(err.message, "error"); }
          } else {
            // Resume it
            try {
              await liveApi("/live/session/" + liveSessionId + "/cpt/resume", "POST", { cpt_code: cpt });
              timer.isPaused = false;
              updateTimerUI(cpt, timer.secondsElapsed);
            } catch (err) { setStatus(err.message, "error"); }
          }
        }
        return;
      }

      const conflictId = card?.dataset.conflictId;

      let modifier = e.target.dataset.modifier || null;
      if (e.target.classList.contains("custom-modifier-apply")) {
        const input = card.querySelector(".custom-modifier-input");
        modifier = input ? input.value.trim() : null;
        if (!modifier) {
          setStatus("Please enter a valid modifier code.", "error");
          return;
        }
      }

      await handleAction(cpt, action, conflictId, modifier);
    });
  });

  if (window.activeCptTimers) {
    for (const [cptKey, timer] of Object.entries(window.activeCptTimers)) {
      updateTimerUI(cptKey, timer.secondsElapsed);
    }
  }
}

let liveSessionId = null;
let sessionFinalized = false;
let lastLiveUi = null;

function patientInitials(name) {
  const parts = (name || "").trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return "??";
}

function showEditMode() {
  document.getElementById("edit-mode").hidden = false;
  document.getElementById("review-mode").hidden = true;
}

function showReviewMode() {
  document.getElementById("edit-mode").hidden = true;
  document.getElementById("review-mode").hidden = false;
}

function updateReviewPatientHeader(finalize, ui) {
  const name = ui?.session_header?.patient_name
    || document.getElementById("live-patient-name").value.trim()
    || "Patient";
  const mrn = (ui?.session_header?.patient_id || document.getElementById("live-patient-id").value || "—")
    .replace(/^#/, "");
  document.getElementById("patient-name").textContent = name;
  document.getElementById("patient-avatar").textContent = patientInitials(name);
  document.getElementById("patient-mrn").textContent = mrn;
  document.getElementById("session-timer").textContent = finalize.session_time_display;
}

function updateFinalizeBar(data) {
  const bar = document.getElementById("finalize-bar");
  if (!bar) return;
  const show = liveSessionId && !sessionFinalized && data?.session?.status !== "ended";
  bar.hidden = !show;
}

function renderFinalizedBilling(finalize, ui) {
  if (!finalize) return;
  sessionFinalized = true;
  lastLiveUi = ui;
  showReviewMode();
  updateFinalizeBar(null);
  updateReviewPatientHeader(finalize, ui);

  const reviewContent = document.getElementById("review-content");
  const rows = finalize.lines.map(function (line) {
    return `
          <tr>
            <td><a href="#" class="cpt-code-link" onclick="return false;">${escapeHtml(line.cpt_code)}</a></td>
            <td>${escapeHtml(line.description)}</td>
            <td><span class="unit-badge">${line.units}</span></td>
            <td>${escapeHtml(line.duration_display)}</td>
            <td>${escapeHtml(line.region)}</td>
          </tr>`;
  }).join("");

  const rejectedRows = finalize.rejected_lines && finalize.rejected_lines.length ? finalize.rejected_lines.map(function (line) {
    return `
          <tr class="rejected-row" style="opacity: 0.6; background-color: var(--bg-alt);">
            <td><span class="cpt-code-link">${escapeHtml(line.cpt_code)}</span></td>
            <td>${escapeHtml(line.description)} <strong style="color: var(--color-red);">(Rejected/Removed)</strong></td>
            <td><span class="unit-badge" style="background: #999;">0</span></td>
            <td>${escapeHtml(line.duration_display)}</td>
            <td>${escapeHtml(line.region)}</td>
          </tr>`;
  }).join("") : "";

  const rejectedSection = rejectedRows ? `
          <div class="billing-summary-header" style="margin-top: 30px;">
            <h2 style="color: var(--color-red);">Rejected / Removed Codes</h2>
          </div>
          <div class="billing-table-wrap">
            <table class="billing-table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Description</th>
                  <th>Units</th>
                  <th>Duration</th>
                  <th>Region</th>
                </tr>
              </thead>
              <tbody>
                ${rejectedRows}
              </tbody>
            </table>
          </div>
      ` : "";

  reviewContent.innerHTML = `
        <div class="finalized-view">
          <div class="finalize-stats">
            <div class="stat-card stat-blue">
              <h3>Session Time</h3>
              <p class="stat-value">${escapeHtml(finalize.session_time_display)}</p>
            </div>
            <div class="stat-card stat-green">
              <h3>Billable Units</h3>
              <p class="stat-value">${finalize.billable_units_total}</p>
            </div>
            <div class="stat-card stat-yellow">
              <h3>CPT Codes</h3>
              <p class="stat-value">${finalize.cpt_code_count}</p>
            </div>
          </div>
          <div class="billing-summary-header">
            <h2>Billing Summary</h2>
            <button type="button" class="btn-copy-table" id="btn-copy-table">Copy table</button>
          </div>
          <div class="billing-table-wrap">
            <table class="billing-table" id="billing-summary-table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Description</th>
                  <th>Units</th>
                  <th>Duration</th>
                  <th>Region</th>
                </tr>
              </thead>
              <tbody>
                ${rows}
                <tr class="total-row">
                  <td colspan="2"><strong>Total</strong></td>
                  <td><span class="unit-badge">${finalize.billable_units_total}</span></td>
                  <td colspan="2">${escapeHtml(finalize.total_duration_display)}</td>
                </tr>
              </tbody>
            </table>
          </div>
          ${rejectedSection}
          <button type="button" class="btn-sign" id="btn-sign-document">Sign &amp; Finalize Document</button>
        </div>`;

  document.getElementById("btn-copy-table").addEventListener("click", copyBillingTable);
  document.getElementById("btn-sign-document").addEventListener("click", function () {
    setStatus("Document signed and finalized (prototype).", "success");
    document.getElementById("btn-sign-document").disabled = true;
  });
}

function clearSessionForNewInput() {
  liveSessionId = null;
  lastLiveUi = null;
  sessionFinalized = false;

  if (document.getElementById("live-icd")) document.getElementById("live-icd").value = "";
  if (document.getElementById("live-cpt")) document.getElementById("live-cpt").value = "";
  if (document.getElementById("live-duration")) document.getElementById("live-duration").value = "16";
  if (document.getElementById("live-session-id")) document.getElementById("live-session-id").textContent = "";
  syncLiveCptInputs(null);

  const ruleEl = document.getElementById("transcript-billing-rule");
  if (ruleEl) ruleEl.disabled = false;

  document.getElementById("session-title").textContent = "Live Therapy Session";
  document.getElementById("status-pill").textContent = "Live Session";
  document.getElementById("meta-row").innerHTML = "";

  content.innerHTML =
    '<div class="loading">Session cleared — enter ICDs and CPT codes below to start a new session.</div>';

  document.getElementById("finalize-bar").hidden = true;
  document.getElementById("review-content").innerHTML = "";
}

async function backToEditMode() {
  clearSessionForNewInput();
  showEditMode();
  const el = document.getElementById("transcript-section");
  if (el) el.hidden = false;
  setStatus("Ready for a new session — previous codes cleared.", "info");
}

function copyBillingTable() {
  const table = document.getElementById("billing-summary-table");
  if (!table) return;
  const text = Array.from(table.querySelectorAll("tr")).map(function (row) {
    return Array.from(row.cells).map(function (cell) {
      return cell.innerText.trim();
    }).join("\t");
  }).join("\n");
  navigator.clipboard.writeText(text).then(function () {
    setStatus("Billing table copied to clipboard.", "success");
  }).catch(function () {
    setStatus("Could not copy table.", "error");
  });
}

async function liveApi(path, method, body) {
  const opts = { method: method || "POST", headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const response = await fetch(apiUrl(path), opts);
  const data = await response.json().catch(function () { return {}; });
  if (!response.ok) {
    throw new Error(formatApiError(data.detail || response.statusText, response.status));
  }
  return data;
}

function handleLiveResponse(data) {
  if (!data || !data.ui_display) {
    throw new Error("Server returned no ui_display.");
  }
  if (data.session && data.session.session_id) {
    liveSessionId = data.session.session_id;
    const idEl = document.getElementById("live-session-id");
    if (idEl) idEl.textContent = "Session: " + liveSessionId.slice(0, 8) + "…";
  }
  if (data.finalize_display) {
    renderFinalizedBilling(data.finalize_display, data.ui_display);
    setStatus(data.event_message || "Billing finalized.", "success");
    return;
  }
  syncLiveCptInputs(data.open_cpt_code);
  lastLiveUi = data.ui_display;
  renderUi(data.ui_display);
  updateFinalizeBar(data);
  setStatus(data.event_message || "Updated.", data.session?.status === "blocked" ? "error" : "success");
}

function syncLiveCptInputs(openCptCode) {
  const cptInput = document.getElementById("live-cpt");
  const detectBtn = document.getElementById("btn-live-detect");
  if (!cptInput || !detectBtn) return;
  if (openCptCode) {
    cptInput.value = openCptCode;
    cptInput.readOnly = true;
    detectBtn.disabled = true;
    detectBtn.title = "End the current CPT with duration before detecting another.";
  } else {
    cptInput.readOnly = false;
    detectBtn.disabled = false;
    detectBtn.title = "";
  }
}

async function handleAction(cpt, action, conflictId, modifier) {
  if (conflictId) {
    await ensureLiveSession();
    try {
      const payload = { conflict_id: conflictId, action: action };
      if (modifier) {
        payload.modifier = modifier;
      }
      const data = await liveApi("/live/session/" + liveSessionId + "/modifier", "POST", payload);
      handleLiveResponse(data);
    } catch (err) {
      setStatus(err.message, "error");
    }
  } else {
    if (action !== "start-timer" && action !== "stop-timer") {
      alert(`${action === "approve" ? "Approved" : "Rejected"} review for CPT ${cpt} (prototype only).`);
    }
  }
}

async function startLiveSession() {
  content.innerHTML = '<div class="loading">Starting live session...</div>';
  try {
    const ruleEl = document.getElementById("transcript-billing-rule");
    const data = await liveApi("/live/session", "POST", {
      client_name: document.getElementById("live-patient-name").value.trim() || "Live Demo Patient",
      client_id: document.getElementById("live-patient-id").value.trim() || "LIVE-001",
      billing_rule: ruleEl.value
    });

    handleLiveResponse(data);
  } catch (err) {
    setStatus(err.message, "error");
    content.innerHTML = '<div class="error">' + escapeHtml(err.message) + '</div>';
    throw err;
  }
}

async function ensureLiveSession() {
  if (liveSessionId) return liveSessionId;
  await startLiveSession();
  return liveSessionId;
}


let parsedSentences = [];
let currentSentenceIndex = 0;

document.getElementById("btn-parse-sentences").addEventListener("click", () => {
  const text = document.getElementById("live-transcript").value;
  const rawText = text.trim();
  let lines = rawText.split(/\r?\n/).filter(line => line.trim().length > 0);
  parsedSentences = [];
  lines.forEach(line => {
    const speakerMatch = line.match(/^([A-Za-z0-9_-]+):\s*(.*)/);
    let speakerPrefix = "";
    let textToSplit = line;
    if (speakerMatch) {
      speakerPrefix = speakerMatch[1] + ": ";
      textToSplit = speakerMatch[2];
    }
    const sentences = textToSplit.match(/[^.!?]+[.!?]+(?:\s+|$)/g) || [textToSplit];
    sentences.forEach(s => {
      if (s.trim().length > 0) {
        parsedSentences.push(speakerPrefix + s.trim());
      }
    });
  });
  currentSentenceIndex = 0;
  const fedContainer = document.getElementById("fed-sentences");
  if (fedContainer) fedContainer.innerHTML = "";

  if (parsedSentences.length > 0) {
    document.getElementById("sentence-feed-container").style.display = "block";
    updateSentenceDisplay();
    setStatus(`Parsed ${parsedSentences.length} sentences. Ready to feed.`, "success");
    const ruleEl = document.getElementById("transcript-billing-rule");
    if (ruleEl) ruleEl.disabled = true;
  } else {
    setStatus("No sentences found in transcript.", "error");
  }
});

function updateSentenceDisplay() {
  const titleEl = document.getElementById("next-sentence-title");
  if (currentSentenceIndex < parsedSentences.length) {
    let batchSize = Math.min(4, parsedSentences.length - currentSentenceIndex);
    let upcoming = [];
    for (let i = 0; i < batchSize; i++) {
      upcoming.push(parsedSentences[currentSentenceIndex + i]);
    }
    document.getElementById("next-sentence-display").innerHTML = upcoming.map(s => escapeHtml(s)).join("<br>");
    if (titleEl) {
      titleEl.textContent = `NEXT ${batchSize} SENTENCE${batchSize > 1 ? 'S' : ''}:`;
    }
    document.getElementById("sentences-remaining").textContent = `${parsedSentences.length - currentSentenceIndex} remaining`;
    document.getElementById("btn-feed-sentence").disabled = false;
  } else {
    document.getElementById("next-sentence-display").innerHTML = "All sentences fed.";
    if (titleEl) titleEl.textContent = "DONE:";
    document.getElementById("sentences-remaining").textContent = "";
    document.getElementById("btn-feed-sentence").disabled = true;
  }
}

function appendFedSentence(sentenceText) {
  const fedContainer = document.getElementById("fed-sentences");
  if (!fedContainer) return;

  let speakerHtml = "";
  const speakerMatch = sentenceText.match(/^([A-Za-z0-9_-]+):\s*(.*)/);
  if (speakerMatch) {
    const speaker = speakerMatch[1];
    sentenceText = speakerMatch[2];
    const isTherapist = speaker.toLowerCase().includes("therapist");
    const color = isTherapist ? "#2563eb" : "#16a34a";
    speakerHtml = `<strong style="color: ${color};">${escapeHtml(speaker)}:</strong> `;
  }

  const div = document.createElement("div");
  div.style.cssText = `margin-bottom: 8px; padding: 10px; background: white; border-left: 4px solid ${speakerHtml ? (speakerHtml.includes('#2563eb') ? '#3b82f6' : '#22c55e') : '#e2e8f0'}; border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);`;
  div.innerHTML = `${speakerHtml}${escapeHtml(sentenceText)}`;
  fedContainer.appendChild(div);
  fedContainer.scrollTop = fedContainer.scrollHeight;
}

document.getElementById("btn-feed-sentence").addEventListener("click", async (e) => {
  if (currentSentenceIndex >= parsedSentences.length) return;
  const btn = e.currentTarget;
  btn.disabled = true;

  let batch = [];
  for (let i = 0; i < 4; i++) {
    if (currentSentenceIndex + i < parsedSentences.length) {
      const sentence = parsedSentences[currentSentenceIndex + i];
      batch.push(sentence);
      appendFedSentence(sentence);
    }
  }

  await ensureLiveSession();
  try {
    const combined = batch.join(" ");
    handleLiveResponse(await liveApi("/live/session/" + liveSessionId + "/transcript/sentence", "POST", { sentence: combined }));
    currentSentenceIndex += batch.length;
  } catch (err) { setStatus(err.message, "error"); }
  finally {
    updateSentenceDisplay();
  }
});

async function liveCptStart(cpt) {
  await ensureLiveSession();
  try {
    handleLiveResponse(await liveApi("/live/session/" + liveSessionId + "/cpt/start", "POST", { cpt_code: cpt }));
  } catch (err) {
    setStatus(err.message, "error");
    throw err;
  }
}

async function liveCptEndWithDuration(cpt, durationMinutes) {
  await ensureLiveSession();
  try {
    handleLiveResponse(await liveApi("/live/session/" + liveSessionId + "/cpt/end", "POST", {
      cpt_code: cpt,
      duration_minutes: durationMinutes,
    }));
  } catch (err) { setStatus(err.message, "error"); }
}

function formatTimerDisplay(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = (seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

window.activeCptTimers = window.activeCptTimers || {};

function startCptTimer(cpt) {
  if (window.activeCptTimers[cpt] && window.activeCptTimers[cpt].intervalId) {
    clearInterval(window.activeCptTimers[cpt].intervalId);
  }

  let secondsElapsed = (window.activeCptTimers[cpt])
    ? window.activeCptTimers[cpt].secondsElapsed
    : 0;

  window.activeCptTimers[cpt] = {
    cpt: cpt,
    secondsElapsed: secondsElapsed,
    isPaused: false,
    stop: async () => {
      clearInterval(window.activeCptTimers[cpt].intervalId);
      const durationMinutes = window.activeCptTimers[cpt].secondsElapsed;
      delete window.activeCptTimers[cpt];
      // treat seconds as minutes per requirement
      if (durationMinutes === 0) {
        setStatus("Timer ran for 0 seconds (minutes). Recording 1 minute minimum for testing.", "info");
        await liveCptEndWithDuration(cpt, 1);
      } else {
        await liveCptEndWithDuration(cpt, durationMinutes);
      }
    }
  };

  window.activeCptTimers[cpt].intervalId = setInterval(() => {
    if (window.activeCptTimers[cpt] && !window.activeCptTimers[cpt].isPaused) {
      window.activeCptTimers[cpt].secondsElapsed++;
      updateTimerUI(cpt, window.activeCptTimers[cpt].secondsElapsed);
    }
  }, 1000);

  updateTimerUI(cpt, secondsElapsed);
}

function recalculateTotalLiveUnits() {
  let base = 0;
  if (lastLiveUi && lastLiveUi.summary_cards) {
    base = lastLiveUi.summary_cards.session_units_total;
  }
  let live = 0;
  document.querySelectorAll('[data-live-units]').forEach(el => {
    live += parseInt(el.getAttribute("data-live-units") || "0", 10);
  });
  const summaryEl = document.getElementById("summary-units-display");
  if (summaryEl) {
    summaryEl.textContent = (base + live) + " Units";
  }
  const headerEl = document.getElementById("header-units-display");
  if (headerEl) {
    headerEl.textContent = "Unit(s): " + (base + live);
  }
}

function updateTimerUI(cpt, secondsElapsed) {
  const card = document.querySelector('.cpt-card[data-cpt="' + escapeHtml(cpt) + '"]');
  if (!card) return;

  const btnStart = card.querySelector('[data-action="start-timer"]');
  const btnStop = card.querySelector('[data-action="stop-timer"]');
  const btnPause = card.querySelector('[data-action="pause-timer"]');
  const display = card.querySelector('.timer-display');
  const countdown = card.querySelector('.timer-countdown');
  const durationText = card.querySelector('#duration-display-' + cpt);

  const isTimed = card.getAttribute("data-is-timed") === "true";
  if (btnStart) btnStart.style.display = 'none';
  if (btnStop) btnStop.style.display = 'inline-block';
  if (btnPause) {
    btnPause.style.display = 'inline-block';
    if (window.activeCptTimers && window.activeCptTimers[cpt] && window.activeCptTimers[cpt].isPaused) {
      btnPause.textContent = "Resume";
      btnPause.style.background = "#10b981"; // green
    } else {
      btnPause.textContent = "Pause";
      btnPause.style.background = "#f59e0b"; // orange
    }
  }
  if (display) display.style.display = 'inline-block';
  if (countdown && isTimed) countdown.style.display = 'inline-block';

  card.style.borderColor = '#2563eb';
  card.style.boxShadow = '0 0 0 2px #bfdbfe';

  if (display) display.textContent = formatTimerDisplay(secondsElapsed);
  if (durationText) durationText.textContent = secondsElapsed + " min (running)";

  if (countdown && isTimed) {
    let target = 8;
    let units = 0;
    if (secondsElapsed >= 8) {
      let k = secondsElapsed - 8;
      units = 1 + Math.floor(k / 15);
      target = 8 + units * 15;
    }
    let remaining = target - secondsElapsed;
    countdown.textContent = `(${remaining}s to next unit)`;

    const unitsText = card.querySelector('#units-display-' + escapeHtml(cpt));
    if (unitsText && unitsText.textContent !== "Manual") {
      const oldUnits = parseInt(unitsText.getAttribute("data-live-units") || "0", 10);
      unitsText.textContent = units;
      unitsText.setAttribute("data-live-units", units);

      if (oldUnits !== units) {
        recalculateTotalLiveUnits();
      }
    }
  }
}


async function liveFinalize() {
  await ensureLiveSession();
  try {
    const data = await liveApi("/live/session/" + liveSessionId + "/end", "POST");
    handleLiveResponse(data);
    if (!data.finalize_display) {
      setStatus(data.event_message || "Cannot finalize yet.", "error");
    }
  } catch (err) {
    setStatus(err.message, "error");
  }
}

document.getElementById("btn-finalize").addEventListener("click", liveFinalize);
document.getElementById("btn-back").addEventListener("click", backToEditMode);

document.getElementById("tab-transcript").addEventListener("click", function () {
  showEditMode();
  document.getElementById("transcript-section").hidden = false;
  document.getElementById("tab-transcript").classList.add("active");
  updateFinalizeBar({ session: { status: sessionFinalized ? "ended" : "active" } });
});

const params = new URLSearchParams(window.location.search);
const fixtureParam = params.get("fixture");
checkServerOnLoad().then(function (ok) {
  if (ok && fixtureParam) {
    evaluateFixture("/static/fixtures/" + fixtureParam.replace(/^\/+/, ""));
  }
});