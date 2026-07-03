(function () {
  "use strict";

  var panel = null;
  var rowsEl = null;
  var resultsEl = null;
  var calcBtn = null;
  var calcLabel = null;
  var addRowBtn = null;
  var resetBtn = null;
  var billingRule = "cms_8_minute";
  var isLoading = false;
  var resolveApiUrl = null;
  var escapeHtmlFn = null;
  var rowCounter = 0;
  var lastResult = null;

  function $(id) {
    return document.getElementById(id);
  }

  function refreshElements() {
    panel = $("llm-unit-calculator-panel");
    rowsEl = $("llm-editable-rows");
    resultsEl = $("llm-panel-results");
    calcBtn = $("btn-llm-calculate");
    calcLabel = $("btn-llm-calculate-label");
    addRowBtn = $("btn-llm-add-row");
    resetBtn = $("btn-llm-reset");
  }

  function showPanel(visible) {
    refreshElements();
    if (panel) panel.classList.toggle("hidden", !visible);
  }

  function getSelectedBillingRule() {
    var selected = document.querySelector('input[name="llm-billing-rule"]:checked');
    return selected ? selected.value : billingRule;
  }

  function createRowData(cpt, duration, region) {
    rowCounter += 1;
    return {
      id: "llm-row-" + rowCounter,
      cpt: cpt || "",
      duration: duration || 15,
      region: region || "",
    };
  }

  function bindRowEvents() {
    refreshElements();
    if (!rowsEl) return;

    rowsEl.querySelectorAll(".llm-remove-row").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        var rowNode = e.currentTarget.closest(".llm-edit-row");
        if (!rowNode || rowsEl.querySelectorAll(".llm-edit-row").length <= 1) return;
        rowNode.remove();
      });
    });
  }

  function renderEditableRows(rows) {
    refreshElements();
    if (!rowsEl) return;

    if (!rows.length) {
      rows = [createRowData("97110", 15, "")];
    }

    rowsEl.innerHTML = rows
      .map(function (row) {
        return (
          "<div class=\"llm-edit-row grid grid-cols-[0.9fr_0.6fr_1fr_auto] gap-2 items-end rounded-lg border border-slate-200/80 bg-slate-50/50 p-2\" data-row-id=\"" +
          escapeHtmlFn(row.id) +
          "\">" +
          "<label class=\"block\"><span class=\"mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-400\">CPT</span>" +
          "<input type=\"text\" class=\"llm-input-cpt w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs font-mono text-slate-700 focus:border-ast-blue/40 focus:outline-none focus:ring-2 focus:ring-ast-blue/20\" value=\"" +
          escapeHtmlFn(row.cpt) +
          "\" placeholder=\"97110\" /></label>" +
          "<label class=\"block\"><span class=\"mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-400\">Min</span>" +
          "<input type=\"number\" min=\"1\" step=\"1\" class=\"llm-input-duration w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-ast-blue/40 focus:outline-none focus:ring-2 focus:ring-ast-blue/20\" value=\"" +
          escapeHtmlFn(String(row.duration)) +
          "\" /></label>" +
          "<label class=\"block\"><span class=\"mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-400\">Region</span>" +
          "<input type=\"text\" class=\"llm-input-region w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-ast-blue/40 focus:outline-none focus:ring-2 focus:ring-ast-blue/20\" value=\"" +
          escapeHtmlFn(row.region) +
          "\" placeholder=\"Optional\" /></label>" +
          "<button type=\"button\" class=\"llm-remove-row flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-400 hover:border-red-200 hover:bg-red-50 hover:text-red-500\" aria-label=\"Remove row\">✕</button>" +
          "</div>"
        );
      })
      .join("");

    bindRowEvents();
  }

  function ensureDefaultRows() {
    refreshElements();
    if (!rowsEl || !rowsEl.querySelector(".llm-edit-row")) {
      renderEditableRows([createRowData("97110", 15, "")]);
    }
  }

  function collectCodes() {
    refreshElements();
    if (!rowsEl) return [];
    var codes = [];
    rowsEl.querySelectorAll(".llm-edit-row").forEach(function (rowNode) {
      var cpt = rowNode.querySelector(".llm-input-cpt")?.value.trim();
      var minutes = parseFloat(rowNode.querySelector(".llm-input-duration")?.value || "0");
      if (!cpt || minutes <= 0) return;
      codes.push({
        cpt: cpt,
        minutes: minutes,
        region: rowNode.querySelector(".llm-input-region")?.value.trim() || "",
      });
    });
    return codes;
  }

  function clearResults() {
    refreshElements();
    if (!resultsEl) return;
    resultsEl.innerHTML = "";
    lastResult = null;
  }

  function setLoading(loading) {
    isLoading = loading;
    if (calcBtn) calcBtn.disabled = loading;
    if (calcLabel) {
      calcLabel.textContent = loading ? "Calculating units..." : "Calculate Units";
    }
  }

  function renderResults(result) {
    refreshElements();
    if (!resultsEl || !result) return;
    lastResult = result;

    var rows = (result.codes || [])
      .map(function (row) {
        return (
          "<tr class=\"bg-white\">" +
          "<td class=\"px-2 py-2 font-mono text-xs font-semibold text-ast-navy\">" + escapeHtmlFn(row.cpt) + "</td>" +
          "<td class=\"px-2 py-2 text-center text-xs\">" + escapeHtmlFn(String(row.minutes)) + "</td>" +
          "<td class=\"px-2 py-2 text-center text-xs font-bold text-ast-navy\">" + escapeHtmlFn(String(row.units)) + "</td>" +
          "<td class=\"px-2 py-2 text-[11px] leading-relaxed text-slate-600\">" + escapeHtmlFn(row.explanation || "") + "</td>" +
          "</tr>"
        );
      })
      .join("");

    resultsEl.innerHTML =
      "<div class=\"rounded-xl border border-slate-200/80 bg-slate-50/50 p-3\">" +
      "<div class=\"mb-3 flex items-center justify-between gap-2\">" +
      "<p class=\"text-xs font-bold text-ast-navy\">Calculated Units</p>" +
      "<span class=\"rounded-full border border-ast-blue/20 bg-ast-tint px-2 py-0.5 text-[10px] font-bold text-ast-blue\">" +
      escapeHtmlFn(result.rule_label || result.rule_applied || "") +
      "</span></div>" +
      "<div class=\"mb-3 rounded-lg border border-slate-100 bg-white px-3 py-2\">" +
      "<p class=\"text-[10px] font-bold uppercase tracking-wider text-slate-400\">Total Units</p>" +
      "<p class=\"text-2xl font-extrabold text-ast-navy\">" + escapeHtmlFn(String(result.total_units)) + "</p></div>" +
      "<div class=\"overflow-x-auto overflow-y-hidden rounded-lg border border-slate-200/80\">" +
      "<table class=\"min-w-full text-xs\"><thead class=\"bg-slate-100/80\"><tr>" +
      "<th class=\"px-2 py-2 text-left font-bold text-slate-500\">CPT</th>" +
      "<th class=\"px-2 py-2 text-center font-bold text-slate-500\">Minutes</th>" +
      "<th class=\"px-2 py-2 text-center font-bold text-slate-500\">Units</th>" +
      "<th class=\"px-2 py-2 text-left font-bold text-slate-500\">Explanation</th>" +
      "</tr></thead><tbody class=\"divide-y divide-slate-100\">" + rows + "</tbody></table></div>" +
      (result.notes
        ? "<p class=\"mt-3 text-[11px] leading-relaxed text-slate-500\">" + escapeHtmlFn(result.notes) + "</p>"
        : "") +
      "</div>";
  }

  function formatError(data, fallback) {
    var detail = data && data.detail;
    if (detail && typeof detail === "object" && detail.message) {
      var html =
        "<div class=\"rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700\">" +
        "<p class=\"font-semibold mb-1\">" + escapeHtmlFn(detail.message) + "</p>";
      if (detail.category) {
        html += "<p class=\"text-[10px] uppercase tracking-wide text-red-500/80 mb-1\">" +
          escapeHtmlFn(String(detail.category).replace(/_/g, " ")) + "</p>";
      }
      if (detail.model) {
        html += "<p class=\"text-[10px] text-red-600/80\">Model: " + escapeHtmlFn(detail.model) + "</p>";
      }
      if (detail.retry_after_seconds) {
        html += "<p class=\"text-[10px] text-red-600/80\">Retry after ~" +
          escapeHtmlFn(String(Math.ceil(detail.retry_after_seconds))) + "s</p>";
      }
      if (detail.technical_detail) {
        html += "<p class=\"mt-2 text-[10px] leading-relaxed text-red-600/90 break-words\">" +
          escapeHtmlFn(detail.technical_detail) + "</p>";
      }
      html += "</div>";
      return html;
    }
    if (typeof detail === "string") {
      return "<div class=\"rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700\">" +
        escapeHtmlFn(detail) + "</div>";
    }
    return "<div class=\"rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700\">" +
      escapeHtmlFn(fallback) + "</div>";
  }

  async function runCalculation() {
    refreshElements();
    if (!resolveApiUrl) return;

    var codes = collectCodes();
    if (!codes.length) {
      if (resultsEl) {
        resultsEl.innerHTML =
          "<div class=\"rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700\">Add at least one CPT code with a duration greater than 0.</div>";
      }
      return;
    }

    billingRule = getSelectedBillingRule();
    setLoading(true);
    clearResults();

    try {
      var response = await fetch(resolveApiUrl("/billing/llm-calculate-units"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          billing_rule: billingRule,
          codes: codes,
        }),
      });
      var data = await response.json().catch(function () { return {}; });
      if (!response.ok) {
        refreshElements();
        if (resultsEl) {
          resultsEl.innerHTML = formatError(data, response.statusText || "Calculation failed.");
        }
        return;
      }
      renderResults(data);
    } catch (err) {
      refreshElements();
      if (resultsEl) {
        resultsEl.innerHTML =
          "<div class=\"rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700\">" +
          escapeHtmlFn(err.message || String(err)) +
          "</div>";
      }
    } finally {
      setLoading(false);
    }
  }

  function resetCalculator() {
    billingRule = "cms_8_minute";
    var cmsRadio = document.querySelector('input[name="llm-billing-rule"][value="cms_8_minute"]');
    if (cmsRadio) cmsRadio.checked = true;
    clearResults();
    renderEditableRows([createRowData("97110", 15, "")]);
  }

  function collectCurrentRows() {
    refreshElements();
    var current = [];
    if (!rowsEl) return current;
    rowsEl.querySelectorAll(".llm-edit-row").forEach(function (rowNode) {
      current.push(
        createRowData(
          rowNode.querySelector(".llm-input-cpt").value,
          parseFloat(rowNode.querySelector(".llm-input-duration").value) || 15,
          rowNode.querySelector(".llm-input-region")?.value || "",
        ),
      );
    });
    return current;
  }

  window.LlmUnitCalculator = {
    init: function (apiUrlResolver, escapeHtml) {
      resolveApiUrl = apiUrlResolver;
      escapeHtmlFn = escapeHtml;
      refreshElements();

      if (calcBtn) calcBtn.addEventListener("click", runCalculation);
      if (resetBtn) resetBtn.addEventListener("click", resetCalculator);
      if (addRowBtn) {
        addRowBtn.addEventListener("click", function () {
          var current = collectCurrentRows();
          current.push(createRowData("", 15, ""));
          renderEditableRows(current);
        });
      }

      document.querySelectorAll('input[name="llm-billing-rule"]').forEach(function (radio) {
        radio.addEventListener("change", function () {
          billingRule = getSelectedBillingRule();
        });
      });

      ensureDefaultRows();
    },

    onReviewShown: function () {
      showPanel(true);
      ensureDefaultRows();
      if (lastResult) {
        renderResults(lastResult);
      }
    },

    hide: function () {
      showPanel(false);
    },

    onSessionCleared: function () {
      showPanel(false);
    },
  };
})();
