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

function isEightMinuteRule(billingRule) {
  return billingRule === "8_minute_rule";
}

function needsManualUnitsInput(billingRule) {
  return false;
}

function billingRuleLabel(line, ui) {
  if (line.billing_rule_label) {
    return line.billing_rule_label;
  }
  if (isEightMinuteRule(line.billing_rule)) {
    const sessionRule = ui && ui.summary_cards && ui.summary_cards.billing_rule;
    return sessionRule === "ama_rule_of_8" ? "AMA Rule of 8" : "8-Minute Rule";
  }
  if (!line.billing_rule) {
    return "—";
  }
  return String(line.billing_rule).replace(/_/g, " ").replace(/\b\w/g, function (c) {
    return c.toUpperCase();
  });
}

function defaultTimerMeta(card) {
  return {
    timer_mode: isEightMinuteRule(card.billing_rule) ? "duration_units" : "occurrence",
    block_minutes: null,
    increment_minutes: null,
    time_band_min: null,
    time_band_max: null,
    area_threshold_sq_cm: null,
    increment_sq_cm: null,
    session_billing_rule: "cms_8_minute",
    area_sq_cm: 0,
    occurrence_count: 1,
    auto_units: isEightMinuteRule(card.billing_rule),
  };
}

function cardTimerMeta(card) {
  return card.timer_meta || defaultTimerMeta(card);
}

function amaUnitsFromMinutes(minutes) {
  const whole = Math.floor(minutes);
  const base = Math.floor(whole / 15);
  const remainder = whole % 15;
  return remainder >= 8 ? base + 1 : base;
}

function cmsUnitsFromMinutes(minutes) {
  if (minutes <= 7) return 0;
  return 1 + Math.floor((minutes - 8) / 15);
}

function minutesInBand(minutes, low, high) {
  if (minutes < low) return false;
  if (high == null) return true;
  return minutes <= high;
}

function computeLiveTimerState(meta, elapsedSec, billingRule) {
  const elapsed = elapsedSec;
  const result = {
    displayMmSs: formatTimerDisplay(elapsed),
    countdownText: "",
    previewUnits: 0,
    showCountdown: false,
    durationLabel: elapsed + " min (running)",
  };

  if (meta.timer_mode === "duration_units") {
    result.showCountdown = true;
    if (billingRule === "8_minute_rule") {
      const isAma = meta.session_billing_rule === "ama_rule_of_8";
      const units = isAma ? amaUnitsFromMinutes(elapsed) : cmsUnitsFromMinutes(elapsed);
      result.previewUnits = units;
      if (isAma) {
        const nextThreshold = units === 0 ? 8 : (units * 15 + (units > 0 ? 0 : 8));
        const target = units === 0 ? 8 : units * 15 + (elapsed % 15 >= 8 ? 15 : 8);
        const rem = (units === 0 ? 8 : (Math.floor(elapsed / 15) + 1) * 15 + (elapsed % 15 < 8 ? 8 - (elapsed % 15) : 0)) - elapsed;
        result.countdownText = `(${Math.max(0, rem)}s to next unit — AMA)`;
      } else {
        let target = 8;
        if (elapsed >= 8) {
          const k = elapsed - 8;
          const u = 1 + Math.floor(k / 15);
          target = 8 + u * 15;
        }
        result.countdownText = `(${target - elapsed}s to next unit)`;
      }
    } else if (billingRule === "full_block_required") {
      if (meta.increment_minutes) {
        const inc = meta.increment_minutes;
        result.previewUnits = Math.floor(elapsed / inc);
        const next = (result.previewUnits + 1) * inc;
        result.countdownText = `(${Math.max(0, next - elapsed)}s to next unit — ${inc} min each)`;
      } else {
        const block = meta.block_minutes || 0;
        result.previewUnits = block && elapsed >= block ? 1 : 0;
        result.countdownText = block
          ? `(${Math.max(0, block - elapsed)}s to 1 unit — need ${block} min)`
          : "(full block required)";
      }
    } else if (billingRule === "time_band_select") {
      const low = meta.time_band_min != null ? meta.time_band_min : 0;
      const high = meta.time_band_max;
      const inBand = minutesInBand(elapsed, low, high);
      result.previewUnits = inBand ? 1 : 0;
      const bandLabel = high != null ? `${low}–${high} min` : `${low}+ min`;
      result.countdownText = inBand
        ? `(band ${bandLabel} matches)`
        : `(need ${bandLabel}, currently ${elapsed} min)`;
    }
  } else if (meta.timer_mode === "occurrence") {
    result.previewUnits = meta.occurrence_count || 1;
    result.countdownText = "(occurrence-based — timer optional)";
  } else if (meta.timer_mode === "area") {
    const area = meta.area_sq_cm || 0;
    if (meta.increment_sq_cm && area > 0) {
      result.previewUnits = Math.floor(area / meta.increment_sq_cm);
    } else if (meta.area_threshold_sq_cm && area > 0) {
      result.previewUnits = area >= meta.area_threshold_sq_cm ? 1 : 0;
    } else if (area > 0) {
      result.previewUnits = 1;
    }
    result.countdownText = "(area-based — enter sq cm)";
  }

  return result;
}

function usesDurationUnits(meta) {
  return meta.timer_mode === "duration_units";
}

function cardNeedsArea(meta) {
  return meta.timer_mode === "area";
}

function cardShowsTimer(meta) {
  return meta.timer_mode === "duration_units" || meta.timer_mode === "duration_doc" || meta.timer_mode === "occurrence" || meta.timer_mode === "area";
}

function setStatus(message, type) {
  const elements = document.querySelectorAll('.run-status');
  const showMessage = type === "error";
  elements.forEach(el => {
    el.textContent = showMessage ? message : "";
    el.className = "run-status" + (showMessage && type ? " " + type : "");
  });
  if (!showMessage) {
    return;
  }
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
        'Stop all uvicorn processes and restart from the backend folder:<br><code>cd backend &amp;&amp; python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000</code></div>';
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
    return "API route not found (404). Restart uvicorn from the backend folder so /live/session routes are loaded.";
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

function renderBadges(card) {
  const parts = [];
  if (card.badge) {
    parts.push(`<span class="badge-black">${escapeHtml(card.badge)}</span>`);
  }
  if (card.ai_verified) {
    const confidence = card.ai_confidence != null ? ` ${card.ai_confidence}%` : "";
    parts.push(`<span class="badge-ai-verified">✓ AI Verified${escapeHtml(confidence)}</span>`);
  }
  return parts.length ? `<div class="cpt-badges">${parts.join("")}</div>` : "";
}

function renderOverlapConflictSuggestion(s) {
  const heading = s.heading || (s.conflict_with_cpt ? `Overlap with ${s.conflict_with_cpt}` : "Temporal overlap");
  const conflictId = s.conflict_id || "";
  return `<li class="suggestion-callout-item">
      <div class="ncci-conflict-block">
        <div class="ncci-conflict-heading">${escapeHtml(heading)}</div>
        <p class="ncci-conflict-text">${escapeHtml(s.summary)}</p>
        <div class="ncci-conflict-actions">
          <button type="button" class="btn-glass btn-glass-muted" data-action="reject" data-conflict-id="${escapeHtml(conflictId)}">Reject</button>
          <button type="button" class="btn-glass btn-glass-ok" data-action="approve" data-conflict-id="${escapeHtml(conflictId)}">Approve</button>
        </div>
      </div>
    </li>`;
}

function renderConflictSuggestion(s) {
  if (s.type === "temporal_overlap") {
    return renderOverlapConflictSuggestion(s);
  }
  return renderNcciConflictSuggestion(s);
}

function renderNcciConflictSuggestion(s) {
  const heading = s.heading || (s.conflict_with_cpt ? `Conflict with ${s.conflict_with_cpt}` : "NCCI bundle conflict");
  const mods = s.modifiers && s.modifiers.length ? s.modifiers : [];
  const conflictId = s.conflict_id || "";
  const canApprove = mods.length > 0;
  const modButtons = canApprove
    ? mods.map(function (m) {
        return `<button type="button" class="btn-glass btn-glass-mod" data-action="approve" data-modifier="${escapeHtml(m)}" data-conflict-id="${escapeHtml(conflictId)}">${escapeHtml(m)}</button>`;
      }).join("") +
      `<input type="text" class="custom-modifier-input glass-input" placeholder="Custom" maxlength="4">` +
      `<button type="button" class="btn-glass btn-glass-ok custom-modifier-apply" data-action="approve" data-conflict-id="${escapeHtml(conflictId)}">Apply</button>`
    : "";
  return `<li class="suggestion-callout-item">
      <div class="ncci-conflict-block">
        <div class="ncci-conflict-heading">${escapeHtml(heading)}</div>
        <p class="ncci-conflict-text">${escapeHtml(s.summary)}</p>
        <div class="ncci-conflict-actions">
          <button type="button" class="btn-glass btn-glass-muted" data-action="reject" data-conflict-id="${escapeHtml(conflictId)}">Reject</button>
          ${modButtons}
        </div>
      </div>
    </li>`;
}

function renderSuggestionItem(s) {
  if (s.type === "transcript_weak") {
    return `<li class="suggestion-callout-item">
        <div class="ai-suggestion-callout ai-suggestion-callout--warning">
          <div class="ai-suggestion-callout__header">
            <span class="ai-suggestion-badge">AI Insight</span>
          </div>
          <p class="ai-suggestion-callout__text">${escapeHtml(s.summary)}</p>
          <button type="button" class="btn-glass btn-glass-warn" data-action="reject" data-conflict-id="${escapeHtml(s.conflict_id || "")}">Accept &amp; Remove</button>
        </div>
      </li>`;
  }
  if (s.type === "ai_suggested") {
    return `<li class="suggestion-callout-item">
        <div class="ai-suggestion-callout ai-suggestion-callout--suggest">
          <div class="ai-suggestion-callout__header">
            <span class="ai-suggestion-badge">✨ AI Suggested</span>
          </div>
          <p class="ai-suggestion-callout__text">${escapeHtml(s.summary)}</p>
          <div class="ai-suggestion-callout__actions">
            <button type="button" class="btn-glass btn-glass-muted" data-action="reject" data-conflict-id="${escapeHtml(s.conflict_id || "")}">Reject</button>
            <button type="button" class="btn-glass btn-glass-ok" data-action="approve" data-conflict-id="${escapeHtml(s.conflict_id || "")}">Approve</button>
          </div>
        </div>
      </li>`;
  }
  return `<li class="suggestion-advisory-item">${escapeHtml(s.summary)}</li>`;
}

function renderCptCard(card) {
  const review = card.card_style === "review" ? " review" : card.card_style === "ai_suggested" ? " ai-suggested" : "";
  const badges = renderBadges(card);
  const conflict = card.conflict_message
    ? `<div class="conflict-text">${escapeHtml(card.conflict_message)}</div>`
    : "";
  const modifierPills = renderModifierPills(card.applied_modifiers);
  const isEnded = card.duration_display && card.duration_display !== "—";
  const ncciSuggestions = card.suggestions.filter(function (s) {
    return s.type === "ncci_bundling" || s.type === "temporal_overlap";
  });
  const otherSuggestions = card.suggestions.filter(function (s) {
    if (s.type === "ncci_bundling" || s.type === "temporal_overlap") return false;
    if (isEnded && (s.type === "rule_applicability" || s.type === "awaiting_end")) return false;
    return true;
  });
  const ncciList = ncciSuggestions.map(renderConflictSuggestion).join("");
  const extraSuggestions = otherSuggestions.map(renderSuggestionItem).join("");
  const suggestionList = (ncciList || extraSuggestions)
    ? `<ul class="suggestion-list">${ncciList}${extraSuggestions}</ul>` : "";
  const hasPerConflictActions = ncciSuggestions.length > 0;
  const actions = !hasPerConflictActions && (card.actions.approve_enabled || card.actions.reject_enabled)
    ? `<div class="card-actions" style="display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 10px;">
            ${card.actions.reject_enabled ? '<button type="button" class="btn-glass btn-glass-muted" data-action="reject">Reject</button>' : ""}
            ${card.actions.approve_enabled ? `
              <span style="font-size: 11px; font-weight: 600; color: #64748b;">Resolve with</span>
              ${(card.modifiers_suggested && card.modifiers_suggested.length > 0 ? card.modifiers_suggested : ['59', 'XE', 'XP', 'XS', 'XU']).map(m => `<button type="button" class="btn-glass btn-glass-mod" data-action="approve" data-modifier="${escapeHtml(m)}">${escapeHtml(m)}</button>`).join('\n              ')}
              <input type="text" class="custom-modifier-input glass-input" placeholder="Custom" maxlength="4">
              <button type="button" class="btn-glass btn-glass-ok custom-modifier-apply" data-action="approve">Apply</button>
            ` : ""}
           </div>` : "";
  const timerMeta = cardTimerMeta(card);
  const timerMetaJson = escapeHtml(JSON.stringify(timerMeta));
  const autoUnits = timerMeta.auto_units;
  const unitsHtml = autoUnits
    ? `Unit(s): <strong><span id="units-display-${escapeHtml(card.cpt_code)}" data-live-units="${card.units_display}">${card.units_display}</span></strong>`
    : `<del>Unit(s)</del> <span style="font-size: 0.85em; color: var(--muted);">(Manual entry at finalize)</span>`;

  const areaInputHtml = cardNeedsArea(timerMeta)
    ? `<div class="area-input-row" style="margin-top: 8px; display: flex; align-items: center; gap: 8px;">
         <label style="font-size: 12px; font-weight: 600; color: #475569;">Area (sq cm):</label>
         <input type="number" class="area-sqcm-input" data-cpt="${escapeHtml(card.cpt_code)}" value="${timerMeta.area_sq_cm || ""}" min="0" step="0.1" placeholder="sq cm" style="width: 90px; padding: 4px 8px; border: 1px solid #cbd5e1; border-radius: 8px;">
       </div>`
    : "";

  let startDisabled = "";
  let startTooltip = "";
  if (card.duration_display !== "—") {
    startDisabled = "disabled";
    startTooltip = 'title="Timer already recorded"';
  } else {
    startDisabled = 'style="background: rgba(255,255,255,0.72); color: #1e293b; border: 1px solid #cbd5e1; padding: 4px 10px; border-radius: 8px; box-shadow: 0 6px 14px rgba(51,65,85,0.08);"';
  }

  const showTimer = cardShowsTimer(timerMeta) && card.duration_display === "—";

  const removeConflictId = "therapist_remove_" + card.cpt_code;
  return `
        <div class="cpt-card${review}" data-cpt="${escapeHtml(card.cpt_code)}" data-billing-rule="${escapeHtml(card.billing_rule || "")}" data-timer-meta="${timerMetaJson}"${card.conflict_id ? ' data-conflict-id="' + escapeHtml(card.conflict_id) + '"' : ""}>
          <div class="card-title" style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
            <span>${escapeHtml(card.cpt_code)} — ${escapeHtml(card.short_label)}</span>
            <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
            <button type="button" class="btn-glass btn-glass-danger" data-action="remove-cpt" data-conflict-id="${escapeHtml(removeConflictId)}" title="Remove this CPT code">Remove</button>
            ${showTimer ? `
            <div class="timer-actions" style="display: flex; align-items: center; gap: 8px;">
              <span class="timer-countdown" style="font-size: 12px; color: var(--muted); display: none;"></span>
              <span class="timer-display" style="font-family: monospace; font-size: 16px; font-weight: 700; color: #334155; display: none;">00:00</span>
              <button class="btn-demo" data-action="start-timer" ${startDisabled} ${startTooltip}>Start</button>
              <button class="btn-demo" data-action="pause-timer" style="background: rgba(255,255,255,0.72); color: #334155; border: 1px solid #cbd5e1; padding: 4px 10px; border-radius: 8px; display: none; cursor: pointer; box-shadow: 0 6px 14px rgba(51,65,85,0.08);">Pause</button>
              <button class="btn-demo" data-action="stop-timer" style="background: rgba(255,255,255,0.72); color: #334155; border: 1px solid #cbd5e1; padding: 4px 10px; border-radius: 8px; display: none; cursor: pointer; box-shadow: 0 6px 14px rgba(51,65,85,0.08);">Stop</button>
            </div>` : (card.duration_display !== "—" ? `<span class="edit-icon">✎</span>` : "")}
            </div>
          </div>
          <div class="card-meta">${unitsHtml} &nbsp;&nbsp; Duration: <strong><span id="duration-display-${escapeHtml(card.cpt_code)}">${escapeHtml(card.duration_display)}</span></strong></div>
          ${areaInputHtml}
          ${badges}
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
        <span class="inline-flex items-center rounded-full border border-white/70 bg-white/65 px-3 py-1 shadow-sm">Date: ${escapeHtml(h.session_datetime)}</span>
        <span class="inline-flex items-center rounded-full border border-white/70 bg-white/65 px-3 py-1 shadow-sm">Patient ID: #${escapeHtml(h.patient_id.replace(/^#/, ""))}</span>
        <span class="inline-flex items-center rounded-full border border-white/70 bg-white/65 px-3 py-1 shadow-sm">Duration: ${escapeHtml(h.duration_display)}</span>
        <span id="header-units-display" class="inline-flex items-center rounded-full border border-blue-200 bg-blue-50/80 px-3 py-1 font-semibold text-blue-700 shadow-sm">Unit(s): ${h.units_total}</span>`;

  let ruleLabel = "";
  let ruleTooltip = "";
  if (s.eight_minute_rule) {
    if (s.billing_rule === "ama_rule_of_8") {
      ruleLabel = '<span class="pill-green" style="background-color: var(--color-purple-light); color: var(--color-purple);">AMA Rule of 8</span>';
      ruleTooltip = "AMA Rule of 8 (Time is NOT pooled)";
    } else {
      ruleLabel = '<span class="pill-green">CMS 8-Minute Rule</span>';
      ruleTooltip = "Pooled 8-minute rule across timed CPTs";
    }
  }

  let html = `
        <div class="summary-row">
          <div class="summary-card">
            <h3>Session Time</h3>
            <p class="summary-value">${escapeHtml(s.session_time_display)}</p>
            ${s.threshold_note ? `<p class="summary-sub">${escapeHtml(s.threshold_note)}</p>` : ""}
          </div>
          <div class="summary-card">
            ${ruleTooltip ? `<span class="info-icon" title="${ruleTooltip}">i</span>` : ""}
            <h3>Session Units</h3>
            <p class="summary-value" id="summary-units-display">${s.session_units_total} Units</p>
            ${ruleLabel}
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
      e.preventDefault();
      e.stopPropagation();
      const actionBtn = e.currentTarget;
      const card = actionBtn.closest(".cpt-card");
      const cpt = card?.dataset.cpt;
      const action = actionBtn.dataset.action;

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

      const conflictId = actionBtn.dataset.conflictId || card?.dataset.conflictId || "";

      let modifier = actionBtn.dataset.modifier || null;
      if (actionBtn.classList.contains("custom-modifier-apply")) {
        const scope = actionBtn.closest(".ncci-conflict-actions, .card-actions, .cpt-card") || card;
        const input = scope.querySelector(".custom-modifier-input");
        modifier = input ? input.value.trim() : null;
        if (!modifier) {
          setStatus("Please enter a valid modifier code.", "error");
          return;
        }
      }

      if (!action) {
        setStatus("No action available for this control.", "error");
        return;
      }

      await handleAction(cpt, action, conflictId, modifier);
    });
  });

  if (window.activeCptTimers) {
    for (const [cptKey, timer] of Object.entries(window.activeCptTimers)) {
      updateTimerUI(cptKey, timer.secondsElapsed);
    }
  }

  content.querySelectorAll(".area-sqcm-input").forEach(function (input) {
    input.addEventListener("change", async function () {
      const cptCode = input.getAttribute("data-cpt");
      const area = parseFloat(input.value, 10);
      if (!cptCode || Number.isNaN(area) || area < 0) return;
      await ensureLiveSession();
      try {
        handleLiveResponse(await liveApi("/live/session/" + liveSessionId + "/cpt/area", "POST", {
          cpt_code: cptCode,
          area_sq_cm: area,
        }));
      } catch (err) {
        setStatus(err.message, "error");
      }
    });
  });
}

let liveSessionId = null;
let sessionFinalized = false;
let lastLiveUi = null;
let lastFinalizeDisplay = null;

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
  const calcPanel = document.getElementById("llm-unit-calculator-panel");
  if (calcPanel) calcPanel.classList.add("hidden");
  if (window.SummaryValidation) {
    SummaryValidation.hide();
  }
  if (window.LlmUnitCalculator) {
    LlmUnitCalculator.hide();
  }
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
  lastFinalizeDisplay = finalize;
  showReviewMode();
  updateFinalizeBar(null);
  updateReviewPatientHeader(finalize, ui);

  const reviewContent = document.getElementById("review-content");
  const rows = finalize.lines.map(function (line) {
    let unitsHtml = `<span class="unit-badge">${line.units}</span>`;
    if (needsManualUnitsInput(line.billing_rule)) {
      unitsHtml = `<input type="number" class="manual-unit-input" data-cpt="${escapeHtml(line.cpt_code)}" value="${line.units}" min="0" style="width: 60px; padding: 4px; border: 2px solid var(--color-orange); border-radius: 4px; font-weight: bold; text-align: center;">`;
    }
    return `
          <tr data-summary-cpt="${escapeHtml(line.cpt_code)}" ${needsManualUnitsInput(line.billing_rule) ? 'style="background-color: #fffbeb;"' : ''}>
            <td><a href="#" class="cpt-code-link" onclick="return false;">${escapeHtml(line.cpt_code)}</a></td>
            <td>${escapeHtml(line.description)}</td>
            <td>${escapeHtml(billingRuleLabel(line, ui))}</td>
            <td>${(line.applied_modifiers && line.applied_modifiers.length) ? escapeHtml(line.applied_modifiers.join(", ")) : "None"}</td>
            <td data-summary-units-cell>${unitsHtml}</td>
            <td>${escapeHtml(line.duration_display)}</td>
            <td><input type="text" class="region-input" data-cpt="${escapeHtml(line.cpt_code)}" value="${line.region === '--' ? '' : escapeHtml(line.region)}" placeholder="ex. spine, knee, head, etc" style="width: 100%; max-width: 150px; border: 1px solid var(--border); padding: 4px; border-radius: 4px;"></td>
          </tr>`;
  }).join("");

  const rejectedRows = finalize.rejected_lines && finalize.rejected_lines.length ? finalize.rejected_lines.map(function (line) {
    return `
          <tr class="rejected-row" style="opacity: 0.6; background-color: var(--bg-alt);">
            <td><span class="cpt-code-link">${escapeHtml(line.cpt_code)}</span></td>
            <td>${escapeHtml(line.description)} <strong style="color: var(--color-red);">(Rejected/Removed)</strong></td>
            <td>${escapeHtml(billingRuleLabel(line, ui))}</td>
            <td>${(line.applied_modifiers && line.applied_modifiers.length) ? escapeHtml(line.applied_modifiers.join(", ")) : "None"}</td>
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
                  <th>Billing Rule</th>
                  <th>Modifiers</th>
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
              <p class="stat-value" id="finalize-stat-units">${finalize.billable_units_total}</p>
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
                  <th>Billing Rule</th>
                  <th>Modifiers</th>
                  <th>Units</th>
                  <th>Duration</th>
                  <th>Region</th>
                </tr>
              </thead>
              <tbody>
                ${rows}
                <tr class="total-row">
                  <td colspan="4"><strong>Total</strong></td>
                  <td><span class="unit-badge" id="finalize-table-total-units">${finalize.billable_units_total}</span></td>
                  <td colspan="2">${escapeHtml(finalize.total_duration_display)}</td>
                </tr>
              </tbody>
            </table>
          </div>
          ${rejectedSection}
          <section class="summary-validation-section mt-8 border-t border-slate-200 pt-6">
            <div class="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p class="text-[10px] font-bold uppercase tracking-widest text-slate-400">Duration → Units Check</p>
                <h2 class="text-lg font-extrabold text-ast-navy">Summary Unit Validation</h2>
                <p class="mt-1 text-xs text-slate-500">Run an independent LLM audit to compare expected units against the generated summary.</p>
              </div>
              <div id="summary-validation-overall"></div>
            </div>
            <div id="summary-validation-rule" class="mb-3 rounded-xl border border-slate-100 bg-slate-50/80 px-3 py-2 text-xs font-semibold text-slate-600"></div>
            <div id="summary-validation-results" aria-live="polite"></div>
          </section>
          <button type="button" class="btn-sign" id="btn-sign-document">Sign &amp; Finalize Document</button>
        </div>`;

  document.getElementById("btn-copy-table").addEventListener("click", copyBillingTable);
  document.getElementById("btn-sign-document").addEventListener("click", function () {
    setStatus("Document signed and finalized (prototype).", "success");
    document.getElementById("btn-sign-document").disabled = true;
  });

  if (window.SummaryValidation) {
    SummaryValidation.validateFromReview(finalize, ui);
  }

  if (window.LlmUnitCalculator) {
    LlmUnitCalculator.onReviewShown(finalize, ui);
  }

  const manualInputs = reviewContent.querySelectorAll(".manual-unit-input");
  manualInputs.forEach(input => {
    input.addEventListener("input", function() {
      let total = 0;
      finalize.lines.forEach(line => {
        if (!needsManualUnitsInput(line.billing_rule)) {
           total += line.units;
        }
      });
      manualInputs.forEach(inp => {
        total += (parseInt(inp.value, 10) || 0);
      });
      const statUnits = document.getElementById("finalize-stat-units");
      const tableTotalUnits = document.getElementById("finalize-table-total-units");
      if (statUnits) statUnits.textContent = total;
      if (tableTotalUnits) tableTotalUnits.textContent = total;

      if (window.SummaryValidation && lastFinalizeDisplay) {
        SummaryValidation.revalidate(lastFinalizeDisplay, lastLiveUi);
      }
    });
  });
}

function clearSessionForNewInput() {
  liveSessionId = null;
  lastLiveUi = null;
  lastFinalizeDisplay = null;
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
  if (window.SummaryValidation) {
    SummaryValidation.onSessionCleared();
  }
  if (window.LlmUnitCalculator) {
    LlmUnitCalculator.onSessionCleared();
  }
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

function handleLiveResponse(data, silent = false) {
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
    if (!silent) setStatus(data.event_message || "Billing finalized.", "success");
    return;
  }
  syncLiveCptInputs(data.open_cpt_code);
  lastLiveUi = data.ui_display;
  renderUi(data.ui_display);
  updateFinalizeBar(data);
  if (!silent) setStatus(data.event_message || "Updated.", data.session?.status === "blocked" ? "error" : "success");
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

function clearCptTimer(cpt) {
  if (!cpt || !window.activeCptTimers || !window.activeCptTimers[cpt]) return;
  clearInterval(window.activeCptTimers[cpt].intervalId);
  delete window.activeCptTimers[cpt];
}

async function handleAction(cpt, action, conflictId, modifier) {
  const isRemove = action === "reject" || action === "remove-cpt";
  if (isRemove && !conflictId && cpt) {
    conflictId = "therapist_remove_" + cpt;
  }

  if (conflictId) {
    await ensureLiveSession();
    try {
      if (isRemove) {
        clearCptTimer(cpt);
      }
      const payload = {
        conflict_id: conflictId,
        action: isRemove ? "reject" : action,
      };
      if (modifier) {
        payload.modifier = modifier;
      }
      const data = await liveApi("/live/session/" + liveSessionId + "/modifier", "POST", payload);
      handleLiveResponse(data);
    } catch (err) {
      setStatus(err.message, "error");
    }
  } else if (action !== "start-timer" && action !== "stop-timer" && action !== "pause-timer") {
    setStatus(`No action available for CPT ${cpt}.`, "error");
  }
}

let pollingInterval = null;
function startPolling() {
  if (pollingInterval) return;
  pollingInterval = setInterval(async () => {
    if (liveSessionId && !sessionFinalized) {
      // Don't refresh if the user is typing in an input
      if (document.activeElement && document.activeElement.tagName === "INPUT") return;
      try {
        const data = await liveApi("/live/session/" + liveSessionId, "GET");
        handleLiveResponse(data, true);
      } catch (err) {
        // ignore
      }
    }
  }, 2000);
}

async function startLiveSession() {
  startPolling();
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
const SENTENCES_PER_FEED_BATCH = 5;

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
    let batchSize = Math.min(SENTENCES_PER_FEED_BATCH, parsedSentences.length - currentSentenceIndex);
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
  for (let i = 0; i < SENTENCES_PER_FEED_BATCH; i++) {
    if (currentSentenceIndex + i < parsedSentences.length) {
      const sentence = parsedSentences[currentSentenceIndex + i];
      batch.push(sentence);
      appendFedSentence(sentence);
    }
  }

  await ensureLiveSession();
  try {
    const combined = batch.join(" ");
    handleLiveResponse(await liveApi("/live/session/" + liveSessionId + "/transcript/sentence", "POST", {
      sentence: combined,
      sentence_count: batch.length,
    }));
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

  let meta;
  try {
    meta = JSON.parse(card.getAttribute("data-timer-meta") || "{}");
  } catch (e) {
    meta = defaultTimerMeta({ billing_rule: card.getAttribute("data-billing-rule") });
  }
  const billingRule = card.getAttribute("data-billing-rule") || "";
  const state = computeLiveTimerState(meta, secondsElapsed, billingRule);

  if (btnStart) btnStart.style.display = 'none';
  if (btnStop) btnStop.style.display = 'inline-block';
  if (btnPause) {
    btnPause.style.display = 'inline-block';
    if (window.activeCptTimers && window.activeCptTimers[cpt] && window.activeCptTimers[cpt].isPaused) {
      btnPause.textContent = "Resume";
      btnPause.style.background = "#10b981";
    } else {
      btnPause.textContent = "Pause";
      btnPause.style.background = "#f59e0b";
    }
  }
  if (display) display.style.display = 'inline-block';
  if (countdown && state.showCountdown) countdown.style.display = 'inline-block';

  card.style.borderColor = '#2563eb';
  card.style.boxShadow = '0 0 0 2px #bfdbfe';

  if (display) display.textContent = state.displayMmSs;
  if (durationText) durationText.textContent = state.durationLabel;

  if (countdown && state.countdownText) {
    countdown.textContent = state.countdownText;
  }

  const unitsText = card.querySelector('#units-display-' + escapeHtml(cpt));
  if (unitsText && meta.auto_units) {
    const oldUnits = parseInt(unitsText.getAttribute("data-live-units") || "0", 10);
    unitsText.textContent = state.previewUnits;
    unitsText.setAttribute("data-live-units", state.previewUnits);
    if (oldUnits !== state.previewUnits) {
      recalculateTotalLiveUnits();
    }
  }
}


async function liveFinalize() {
  await ensureLiveSession();

  if (lastLiveUi && lastLiveUi.cpt_cards) {
    const incomplete = lastLiveUi.cpt_cards.find(function (c) {
      if (c.duration_display !== "—") return false;
      const meta = cardTimerMeta(c);
      if (usesDurationUnits(meta)) return true;
      if (cardNeedsArea(meta) && !(meta.area_sq_cm > 0)) return true;
      if (meta.timer_mode === "occurrence") return true;
      return false;
    });
    if (incomplete) {
      setStatus("Cannot finalize yet: complete all detected codes (duration, area, or occurrence).", "error");
      return;
    }
  }

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

const tabTranscript = document.getElementById("tab-transcript");
if (tabTranscript) {
  tabTranscript.addEventListener("click", function () {
    showEditMode();
    document.getElementById("transcript-section").hidden = false;
    tabTranscript.classList.add("active");
    updateFinalizeBar({ session: { status: sessionFinalized ? "ended" : "active" } });
  });
}

const params = new URLSearchParams(window.location.search);
const fixtureParam = params.get("fixture");
checkServerOnLoad().then(function (ok) {
  if (window.SummaryValidation) {
    SummaryValidation.init(apiUrl, escapeHtml);
  }
  if (window.LlmUnitCalculator) {
    LlmUnitCalculator.init(apiUrl, escapeHtml);
  }
  if (ok && fixtureParam) {
    evaluateFixture("/static/fixtures/" + fixtureParam.replace(/^\/+/, ""));
  }
});