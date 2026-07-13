(function () {
  "use strict";

  var resolveApiUrl = null;
  var escapeHtmlFn = null;
  var billingRule = "cms_8_minute";
  var lastValidation = null;
  var lastFinalize = null;
  var lastUi = null;

  function $(id) {
    return document.getElementById(id);
  }

  function ensureElements() {
    return {
      resultsEl: $("summary-validation-results"),
      ruleEl: $("summary-validation-rule"),
      overallEl: $("summary-validation-overall"),
    };
  }

  function isEightMinuteCptRule(cptBillingRule) {
    return cptBillingRule === "8_minute_rule";
  }

  function ruleTypeLabel(cptBillingRule, cptBillingRuleLabel) {
    if (cptBillingRuleLabel) {
      return cptBillingRuleLabel;
    }
    if (cptBillingRule === "8_minute_rule") {
      return billingRule === "ama_rule_of_8" ? "AMA Rule of 8" : "8-Minute Rule";
    }
    if (!cptBillingRule) {
      return "Unset";
    }
    return String(cptBillingRule).replace(/_/g, " ").replace(/\b\w/g, function (c) {
      return c.toUpperCase();
    });
  }

  function parseDurationToMinutes(display) {
    if (!display || display === "—" || display === "flat" || display === "Manual") {
      return 0;
    }
    var text = String(display).trim().toLowerCase();
    var minMatch = text.match(/^(\d+(?:\.\d+)?)\s*min/);
    if (minMatch) return parseFloat(minMatch[1]);
    var parts = String(display).split(":");
    if (parts.length === 3 && parts.every(function (p) { return /^\d+$/.test(p); })) {
      return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10) + parseInt(parts[2], 10) / 60;
    }
    var numeric = parseFloat(text);
    return isNaN(numeric) ? 0 : numeric;
  }

  function ruleLabel(rule) {
    return rule === "ama_rule_of_8" ? "AMA Rule of Eight" : "Medicare 8-Minute Rule";
  }

  function auditorLabel(auditor) {
    if (auditor === "openai") return "OpenAI independent audit";
    if (auditor === "auto") return "OpenAI with local fallback";
    return "Local billing engine";
  }

  function warningIcon() {
    return (
      "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" " +
      "class=\"inline h-3.5 w-3.5 text-red-500 flex-shrink-0\" aria-hidden=\"true\">" +
      "<path d=\"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3\"/>" +
      "<path d=\"M12 9v4\"/><path d=\"M12 17h.01\"/></svg>"
    );
  }

  function passedBadge() {
    return "<span class=\"rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase text-emerald-700\">PASSED</span>";
  }

  function failedBadge() {
    return "<span class=\"rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-[10px] font-bold uppercase text-red-700\">FAILED</span>";
  }

  function highlightSummaryTableRows(validation) {
    var table = document.getElementById("billing-summary-table");
    if (!table || !validation) return;

    var failedCpts = {};
    (validation.rows || []).forEach(function (row) {
      if (row.status === "FAILED") failedCpts[row.cpt] = true;
    });

    table.querySelectorAll("tbody tr[data-summary-cpt]").forEach(function (tr) {
      var cpt = tr.getAttribute("data-summary-cpt");
      var failed = !!failedCpts[cpt];
      tr.classList.toggle("bg-red-50/80", failed);
      tr.classList.toggle("summary-unit-mismatch", failed);

      var unitsCell = tr.querySelector("[data-summary-units-cell]");
      if (unitsCell && failed) {
        var existing = unitsCell.querySelector(".summary-unit-warning");
        if (!existing) {
          unitsCell.insertAdjacentHTML(
            "beforeend",
            " <span class=\"summary-unit-warning inline-flex items-center ml-1\" title=\"Unit mismatch\">" +
              warningIcon() +
              "</span>"
          );
        }
      } else if (unitsCell) {
        var warn = unitsCell.querySelector(".summary-unit-warning");
        if (warn) warn.remove();
      }
    });
  }

  function bindOpenAiAuditButton() {
    var btn = document.getElementById("btn-summary-openai-audit");
    if (!btn || btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", function () {
      if (lastFinalize) {
        runValidation(lastFinalize, lastUi, "openai");
      }
    });
  }

  function finalizeRuleLabelForCpt(cpt) {
    if (!lastFinalize || !lastFinalize.lines) {
      return null;
    }
    var match = lastFinalize.lines.find(function (line) {
      return line.cpt_code === cpt;
    });
    return match ? match.billing_rule_label : null;
  }

  function renderIdleState(finalize, ui) {
    lastFinalize = finalize;
    lastUi = ui;

    var els = ensureElements();
    if (!els.resultsEl) return;

    billingRule =
      (ui && ui.summary_cards && ui.summary_cards.billing_rule) || billingRule;

    if (els.ruleEl) {
      els.ruleEl.textContent = "Rule set: " + ruleLabel(billingRule);
    }
    if (els.overallEl) {
      els.overallEl.innerHTML = "";
    }

    els.resultsEl.innerHTML =
      "<div class=\"rounded-xl border border-slate-200/80 bg-slate-50/50 p-4\">" +
      "<div class=\"flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between\">" +
      "<div>" +
      "<p class=\"text-xs font-bold text-ast-navy\">Independent LLM Unit Audit</p>" +
      "<p class=\"text-[11px] leading-relaxed text-slate-500\">Run the LLM audit to compare summary-assigned units against independently calculated expected units.</p>" +
      "</div>" +
      "<button type=\"button\" id=\"btn-summary-openai-audit\" class=\"rounded-lg border border-slate-300 bg-white px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-slate-700 hover:bg-slate-50\">Run LLM Audit</button>" +
      "</div>" +
      "</div>";

    bindOpenAiAuditButton();
  }

  function renderValidationResults(validation) {
    var els = ensureElements();
    if (!els.resultsEl || !validation) return;
    lastValidation = validation;

    var overallPassed = validation.overall_status === "PASSED";
    if (els.overallEl) {
      els.overallEl.innerHTML = overallPassed ? passedBadge() : failedBadge();
    }

    var rows = (validation.rows || [])
      .map(function (row) {
        var failed = row.status === "FAILED";
        var rowClass = failed ? "bg-red-50/90" : "bg-white";
        var statusHtml = failed
          ? "<span class=\"inline-flex items-center gap-1 text-[10px] font-bold text-red-600\">" + warningIcon() + " FAILED</span>"
          : "<span class=\"text-[10px] font-bold text-emerald-600\">PASSED</span>";
        var timedLabel = ruleTypeLabel(row.billing_rule, finalizeRuleLabelForCpt(row.cpt));

        return (
          "<tr class=\"" + rowClass + "\">" +
          "<td class=\"px-2 py-2 font-mono text-xs font-semibold text-ast-navy\">" + escapeHtmlFn(row.cpt) + "</td>" +
          "<td class=\"px-2 py-2 text-center text-xs\">" + escapeHtmlFn(String(row.duration_minutes)) + " min</td>" +
          "<td class=\"px-2 py-2 text-center text-[10px] text-slate-500\">" + timedLabel + "</td>" +
          "<td class=\"px-2 py-2 text-center text-xs font-semibold\">" + escapeHtmlFn(String(row.expected_units)) + "</td>" +
          "<td class=\"px-2 py-2 text-center text-xs font-semibold\">" + escapeHtmlFn(String(row.summary_units)) + "</td>" +
          "<td class=\"px-2 py-2 text-center\">" + statusHtml + "</td>" +
          "</tr>" +
          (failed
            ? "<tr class=\"bg-red-50/60\"><td colspan=\"6\" class=\"px-2 py-2 text-[11px] leading-relaxed text-red-700\">" +
              warningIcon() + " " + escapeHtmlFn(row.message) + "</td></tr>"
            : "")
        );
      })
      .join("");

    els.resultsEl.innerHTML =
      "<div class=\"rounded-xl border border-slate-200/80 bg-slate-50/50 p-3\">" +
      "<div class=\"mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between\">" +
      "<div>" +
      "<p class=\"text-xs font-bold text-ast-navy\">Summary Unit Audit</p>" +
      "<p class=\"text-[10px] text-slate-500\">Auditor: " + escapeHtmlFn(auditorLabel(validation.auditor)) + "</p>" +
      "</div>" +
      "<div class=\"flex flex-wrap items-center gap-2\">" +
      (overallPassed ? passedBadge() : failedBadge()) +
      "</div>" +
      "</div>" +
      (validation.fallback_message
        ? "<div class=\"mb-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800\">" +
          escapeHtmlFn(validation.fallback_message) +
          "</div>"
        : "") +
      (!overallPassed && !validation.fallback_message
        ? "<div class=\"mb-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700\">" +
          warningIcon() +
          "<span>One or more CPT rows in the generated summary have incorrect unit assignments based on documented durations.</span></div>"
        : "") +
      "<div class=\"overflow-x-auto overflow-y-hidden rounded-lg border border-slate-200/80\">" +
      "<table class=\"min-w-full text-xs\"><thead class=\"bg-slate-100/80\"><tr>" +
      "<th class=\"px-2 py-2 text-left font-bold text-slate-500\">CPT</th>" +
      "<th class=\"px-2 py-2 text-center font-bold text-slate-500\">Duration</th>" +
      "<th class=\"px-2 py-2 text-center font-bold text-slate-500\">Type</th>" +
      "<th class=\"px-2 py-2 text-center font-bold text-slate-500\">Expected</th>" +
      "<th class=\"px-2 py-2 text-center font-bold text-slate-500\">Summary</th>" +
      "<th class=\"px-2 py-2 text-center font-bold text-slate-500\">Status</th>" +
      "</tr></thead><tbody class=\"divide-y divide-slate-100\">" + rows + "</tbody></table></div>" +
      "</div>";

    highlightSummaryTableRows(validation);
  }

  function buildPayloadFromFinalize(finalize) {
    return (finalize.lines || []).map(function (line) {
      var duration = parseDurationToMinutes(line.duration_display);
      var summaryUnits = line.units;
      if (!isEightMinuteCptRule(line.billing_rule)) {
        var manualInput = document.querySelector(
          '.manual-unit-input[data-cpt="' + line.cpt_code + '"]'
        );
        if (manualInput) {
          summaryUnits = parseInt(manualInput.value, 10) || 0;
        }
      }
      return {
        cpt: line.cpt_code,
        duration_minutes: duration,
        summary_units: summaryUnits,
        billing_rule: line.billing_rule || null,
      };
    });
  }

  function showLoadingState(auditor) {
    var els = ensureElements();
    if (!els.resultsEl) return;
    var message =
      auditor === "openai"
        ? "Running independent validation via OpenAI..."
        : "Running local billing engine validation...";
    els.resultsEl.innerHTML =
      "<div class=\"flex items-center justify-center gap-2 rounded-xl border border-slate-200/80 bg-slate-50/50 py-8 text-xs text-slate-500\">" +
      "<svg class=\"h-4 w-4 animate-spin text-ast-blue\" xmlns=\"http://www.w3.org/2000/svg\" fill=\"none\" viewBox=\"0 0 24 24\">" +
      "<circle class=\"opacity-25\" cx=\"12\" cy=\"12\" r=\"10\" stroke=\"currentColor\" stroke-width=\"4\"></circle>" +
      "<path class=\"opacity-75\" fill=\"currentColor\" d=\"M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z\"></path></svg>" +
      message +
      "</div>";
  }

  async function runValidation(finalize, ui, auditor) {
    auditor = auditor || "local";
    lastFinalize = finalize;
    lastUi = ui;

    var els = ensureElements();
    if (!finalize || !finalize.lines || !finalize.lines.length || !resolveApiUrl) {
      if (els.resultsEl) {
        els.resultsEl.innerHTML =
          "<div class=\"rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-4 text-xs text-slate-500 text-center\">No CPT lines available to validate.</div>";
      }
      return;
    }

    billingRule =
      (ui && ui.summary_cards && ui.summary_cards.billing_rule) || billingRule;

    if (els.ruleEl) {
      els.ruleEl.textContent = "Rule set: " + ruleLabel(billingRule);
    }

    showLoadingState(auditor);

    try {
      var response = await fetch(resolveApiUrl("/billing/validate-summary-units"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lines: buildPayloadFromFinalize(finalize),
          billing_rule: billingRule,
          auditor: auditor,
        }),
      });
      var data = await response.json().catch(function () { return {}; });
      if (!response.ok) {
        var detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || "Validation failed.");
        els = ensureElements();
        if (els.resultsEl) {
          els.resultsEl.innerHTML =
            "<div class=\"rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700\">" +
            escapeHtmlFn(detail) + "</div>";
        }
        return;
      }
      renderValidationResults(data);
    } catch (err) {
      els = ensureElements();
      if (els.resultsEl) {
        els.resultsEl.innerHTML =
          "<div class=\"rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700\">" +
          escapeHtmlFn(err.message || String(err)) + "</div>";
      }
    }
  }

  window.SummaryValidation = {
    init: function (apiUrlResolver, escapeHtml) {
      resolveApiUrl = apiUrlResolver;
      escapeHtmlFn = escapeHtml;
    },

    validateFromReview: function (finalize, ui) {
      renderIdleState(finalize, ui);
    },

    revalidate: function (finalize, ui) {
      renderIdleState(finalize, ui);
    },

    runOpenAiAudit: function (finalize, ui) {
      runValidation(finalize, ui, "openai");
    },

    hide: function () {
      lastValidation = null;
      lastFinalize = null;
      lastUi = null;
      var els = ensureElements();
      if (els.resultsEl) els.resultsEl.innerHTML = "";
      if (els.ruleEl) els.ruleEl.textContent = "";
      if (els.overallEl) els.overallEl.innerHTML = "";
    },

    onSessionCleared: function () {
      this.hide();
      billingRule = "cms_8_minute";
    },
  };
})();

