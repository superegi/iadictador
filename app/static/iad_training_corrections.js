// IAD_TRAINING_CORRECTIONS_UI_V2
(function () {
  "use strict";

  if (window.__iadTrainingCorrectionsUiV2) return;
  window.__iadTrainingCorrectionsUiV2 = true;

  function txt(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v.trim();
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v).trim(); }
  }

  function esc(s) {
    s = (s === null || s === undefined) ? "" : String(s);
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function short(s, n) {
    s = (s === null || s === undefined) ? "" : String(s);
    return s.length > n ? s.slice(0, n) + "..." : s;
  }

  function getFinalArea() {
    return document.getElementById("iad-real-final-report")
      || document.getElementById("finalReport")
      || document.querySelector("textarea[name='resultado_revisado']");
  }

  function getSourceText() {
    var el = document.getElementById("sourceText")
      || document.querySelector("textarea[name='input_text_final']");
    return el ? (el.value || "") : "";
  }

  function getTemplateName() {
    var el = document.getElementById("iad-real-template")
      || document.getElementById("iad-native-final-template");

    var v = el ? txt(el.textContent || el.value || "") : "";
    if (v && v !== "—") return v;

    var payload = window.__iadTrainingLastPayloadV2 || window.__iadRealFinalPayloadV3 || {};
    return txt(
      (payload.plantilla_sugerida && payload.plantilla_sugerida.nombre)
      || payload.plantilla_nombre
      || payload.template_name
      || payload.template
      || ""
    );
  }

  function getOriginalAiReport() {
    var payload = window.__iadTrainingLastPayloadV2 || {};
    return txt(
      window.__iadTrainingOriginalReportV2
      || payload.informe_final_inteligente
      || payload.informe_final_deterministico
      || payload.informe_final_modelo
      || payload.informe_final_antes_structured_mapper
      || payload.informe_final
      || payload.final_report
      || ""
    );
  }

  function getModelName() {
    var payload = window.__iadTrainingLastPayloadV2 || {};
    return txt(
      (payload.intelligence_editor && payload.intelligence_editor.model)
      || payload.modelo_usado
      || payload.model
      || ""
    );
  }

  function capturePayload(data) {
    if (!data || typeof data !== "object") return;

    var report = txt(data.informe_final || data.final_report || data.resultado_revisado || "");
    if (report && !window.__iadTrainingOriginalReportV2) {
      window.__iadTrainingOriginalReportV2 = report;
    }

    if (
      report
      || data.hallazgos_estructurados
      || data.structured_mapper
      || data.intelligence_editor
      || data.mapa_aplicacion
    ) {
      window.__iadTrainingLastPayloadV2 = data;
    }
  }

  function ensureTrainingButton() {
    var area = getFinalArea();
    if (!area) return;

    var panel = document.getElementById("iad-real-final-panel")
      || area.closest("section")
      || area.parentElement;

    if (!panel) return;
    if (document.getElementById("iad-save-training-correction-v2")) return;

    var actions = panel.querySelector(".iad-real-actions")
      || panel.querySelector(".iad-native-final-actions");

    if (!actions) {
      actions = document.createElement("div");
      actions.className = "iad-real-actions";
      actions.style.display = "flex";
      actions.style.gap = "8px";
      actions.style.flexWrap = "wrap";
      actions.style.marginTop = "10px";
      panel.appendChild(actions);
    }

    var btn = document.createElement("button");
    btn.type = "button";
    btn.id = "iad-save-training-correction-v2";
    btn.textContent = "Guardar corrección para Training IA";
    btn.style.border = "0";
    btn.style.borderRadius = "10px";
    btn.style.padding = "8px 12px";
    btn.style.fontWeight = "700";
    btn.style.cursor = "pointer";

    var status = document.createElement("span");
    status.id = "iad-save-training-correction-status-v2";
    status.style.alignSelf = "center";
    status.style.color = "#9fb0c4";
    status.style.fontSize = ".86rem";

    btn.addEventListener("click", async function () {
      var finalArea = getFinalArea();
      var corrected = finalArea ? finalArea.value || "" : "";

      if (!corrected.trim()) {
        status.textContent = "No hay informe corregido para guardar.";
        return;
      }

      var payload = window.__iadTrainingLastPayloadV2 || {};

      var body = {
        template_name: getTemplateName(),
        dictado_original: getSourceText(),
        transcripcion: payload.transcripcion || payload.transcription || "",
        clinical_json: payload.hallazgos_estructurados || payload.structured_findings || {},
        informe_ia: getOriginalAiReport(),
        informe_corregido: corrected,
        modelo_usado: getModelName(),
        source: "work_v2_final_report_button_v2",
        hallazgos_estructurados: payload.hallazgos_estructurados || [],
        mapa_aplicacion: payload.mapa_aplicacion || [],
        advertencias: payload.advertencias || [],
        metadata_json: payload
      };

      btn.disabled = true;
      var old = btn.textContent;
      btn.textContent = "Guardando...";
      status.textContent = "";

      try {
        var res = await fetch("/iad/api/training/corrections/save.json", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(body)
        });

        var data = await res.json();

        if (!res.ok || !data.ok) {
          throw new Error(data.error || data.detail || "No se pudo guardar");
        }

        btn.textContent = "Guardado";
        status.textContent = "Corrección guardada para Training IA.";
        setTimeout(function () {
          btn.textContent = old;
          status.textContent = "";
        }, 1800);
      } catch (e) {
        btn.textContent = old;
        status.textContent = "Error: " + (e && e.message ? e.message : e);
      } finally {
        btn.disabled = false;
      }
    });

    actions.appendChild(btn);
    actions.appendChild(status);
  }

  function isTrainingPage() {
    var p = (window.location.pathname || "").toLowerCase();
    return p.includes("training") || p.includes("entrenamiento");
  }

  async function loadCorrections(root) {
    var body = root.querySelector("[data-iad-training-body]");
    if (!body) return;

    body.innerHTML = "Cargando correcciones...";

    try {
      var res = await fetch("/iad/api/training/corrections/list.json?limit=50");
      var data = await res.json();

      if (!res.ok || !data.ok) {
        throw new Error(data.error || data.detail || "No se pudo cargar");
      }

      if (!data.items || !data.items.length) {
        body.innerHTML = "<p>No hay correcciones guardadas todavía.</p>";
        return;
      }

      var html = "";
      html += "<table style='width:100%;border-collapse:collapse;font-size:.88rem'>";
      html += "<thead><tr>";
      html += "<th style='text-align:left;border-bottom:1px solid rgba(148,163,184,.25);padding:6px'>Fecha</th>";
      html += "<th style='text-align:left;border-bottom:1px solid rgba(148,163,184,.25);padding:6px'>Plantilla</th>";
      html += "<th style='text-align:left;border-bottom:1px solid rgba(148,163,184,.25);padding:6px'>Informe corregido</th>";
      html += "</tr></thead><tbody>";

      data.items.forEach(function (item) {
        html += "<tr>";
        html += "<td style='vertical-align:top;border-bottom:1px solid rgba(148,163,184,.14);padding:6px'>" + esc(item.created_at || "") + "</td>";
        html += "<td style='vertical-align:top;border-bottom:1px solid rgba(148,163,184,.14);padding:6px'>" + esc(item.template_name || "") + "</td>";
        html += "<td style='vertical-align:top;border-bottom:1px solid rgba(148,163,184,.14);padding:6px;white-space:pre-wrap;font-family:monospace'>" + esc(short(item.informe_corregido || "", 900)) + "</td>";
        html += "</tr>";
      });

      html += "</tbody></table>";
      body.innerHTML = html;
    } catch (e) {
      body.innerHTML = "<p>Error cargando correcciones: " + esc(e && e.message ? e.message : e) + "</p>";
    }
  }

  function mountTrainingPagePanel() {
    if (!isTrainingPage()) return;
    if (document.getElementById("iad-training-corrections-panel-v2")) return;

    var host = document.querySelector("main")
      || document.querySelector(".content")
      || document.body;

    var panel = document.createElement("section");
    panel.id = "iad-training-corrections-panel-v2";
    panel.style.marginTop = "16px";
    panel.style.border = "1px solid rgba(125,211,252,.30)";
    panel.style.borderRadius = "14px";
    panel.style.background = "#101d2d";
    panel.style.padding = "14px";
    panel.style.color = "#e5edf7";

    panel.innerHTML =
      "<h2 style='margin-top:0'>Correcciones guardadas para Training IA</h2>" +
      "<p style='color:#9fb0c4'>Cada corrección guarda dictado, informe IA e informe corregido para reutilizarlo como ejemplo.</p>" +
      "<div style='display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px'>" +
        "<button type='button' data-iad-refresh-training>Actualizar</button>" +
        "<a href='/iad/api/training/corrections/export.jsonl' target='_blank' rel='noopener'>Exportar JSONL</a>" +
      "</div>" +
      "<div data-iad-training-body></div>";

    host.appendChild(panel);

    var btn = panel.querySelector("[data-iad-refresh-training]");
    if (btn) {
      btn.addEventListener("click", function () {
        loadCorrections(panel);
      });
    }

    loadCorrections(panel);
  }

  var oldFetch = window.fetch;
  if (typeof oldFetch === "function" && !oldFetch.__iadTrainingCorrectionsWrappedV2) {
    var wrapped = async function () {
      var args = arguments;
      var res = await oldFetch.apply(this, args);

      try {
        var clone = res.clone();
        var ct = clone.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          clone.json().then(function (data) {
            capturePayload(data);
            setTimeout(ensureTrainingButton, 120);
            setTimeout(ensureTrainingButton, 700);
            setTimeout(mountTrainingPagePanel, 300);
          }).catch(function () {});
        }
      } catch (e) {}

      return res;
    };
    wrapped.__iadTrainingCorrectionsWrappedV2 = true;
    window.fetch = wrapped;
  }

  function tick() {
    ensureTrainingButton();
    mountTrainingPagePanel();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(tick, 300);
      setTimeout(tick, 1200);
    });
  } else {
    setTimeout(tick, 300);
    setTimeout(tick, 1200);
  }

  try {
    var obs = new MutationObserver(function () {
      ensureTrainingButton();
    });
    obs.observe(document.documentElement || document.body, {childList: true, subtree: true});
  } catch (e) {}
})();


// IAD_VALIDATION_SAVE_BUTTON_V3
(function () {
  "use strict";

  if (window.__iadValidationSaveButtonV3) return;
  window.__iadValidationSaveButtonV3 = true;

  function txt(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v.trim();
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v).trim(); }
  }

  function esc(s) {
    s = (s === null || s === undefined) ? "" : String(s);
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function short(s, n) {
    s = (s === null || s === undefined) ? "" : String(s);
    return s.length > n ? s.slice(0, n) + "..." : s;
  }

  function getFinalArea() {
    return document.getElementById("iad-real-final-report")
      || document.getElementById("finalReport")
      || document.querySelector("textarea[name='resultado_revisado']")
      || Array.from(document.querySelectorAll("textarea")).find(function (t) {
        return (t.value || "").includes("Impresión diagnóstica");
      });
  }

  function getSourceText() {
    var el = document.getElementById("sourceText")
      || document.querySelector("textarea[name='input_text_final']");
    return el ? (el.value || "") : "";
  }

  function getTemplateName() {
    var el = document.getElementById("iad-real-template")
      || document.getElementById("iad-native-final-template");

    var v = el ? txt(el.textContent || el.value || "") : "";
    if (v && v !== "—") return v;

    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || window.__iadRealFinalPayloadV3
      || {};

    return txt(
      (payload.plantilla_sugerida && payload.plantilla_sugerida.nombre)
      || payload.plantilla_nombre
      || payload.template_name
      || payload.template
      || ""
    );
  }

  function getOriginalAiReport() {
    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || {};

    return txt(
      window.__iadValidationOriginalReportV3
      || window.__iadTrainingOriginalReportV2
      || payload.informe_final_inteligente
      || payload.informe_final_deterministico
      || payload.informe_final_modelo
      || payload.informe_final_antes_ap_style_rules
      || payload.informe_final_antes_clean_ap_writer
      || payload.informe_final_antes_exam_type_guard
      || payload.informe_final
      || payload.final_report
      || ""
    );
  }

  function getModelName() {
    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || {};

    return txt(
      (payload.intelligence_editor && payload.intelligence_editor.model)
      || payload.modelo_usado
      || payload.model
      || ""
    );
  }

  function capturePayload(data) {
    if (!data || typeof data !== "object") return;

    var report = txt(data.informe_final || data.final_report || data.resultado_revisado || "");
    if (report && !window.__iadValidationOriginalReportV3) {
      window.__iadValidationOriginalReportV3 = report;
    }

    if (
      report
      || data.hallazgos_estructurados
      || data.structured_mapper
      || data.intelligence_editor
      || data.clean_writer
      || data.exam_type_guard
      || data.ap_style_rules
      || data.mapa_aplicacion
    ) {
      window.__iadValidationLastPayloadV3 = data;
    }
  }

  function findActionHost() {
    var area = getFinalArea();
    if (!area) return null;

    var panel = document.getElementById("iad-real-final-panel")
      || area.closest("section")
      || area.parentElement;

    if (!panel) return null;

    var actions = panel.querySelector(".iad-real-actions")
      || panel.querySelector(".iad-native-final-actions")
      || panel.querySelector("[data-iad-actions]");

    if (!actions) {
      actions = document.createElement("div");
      actions.className = "iad-real-actions";
      actions.setAttribute("data-iad-actions", "1");
      actions.style.display = "flex";
      actions.style.gap = "8px";
      actions.style.flexWrap = "wrap";
      actions.style.marginTop = "10px";
      panel.appendChild(actions);
    }

    return actions;
  }

  function hideOldTrainingOnlyButton() {
    var old = document.getElementById("iad-save-training-correction-v2")
      || document.getElementById("iad-save-training-correction");

    if (old) {
      old.style.display = "none";
      old.setAttribute("aria-hidden", "true");
    }
  }

  function ensureValidationButton() {
    var area = getFinalArea();
    if (!area) return;

    hideOldTrainingOnlyButton();

    if (document.getElementById("iad-save-validation-v3")) return;

    var actions = findActionHost();
    if (!actions) return;

    var btn = document.createElement("button");
    btn.type = "button";
    btn.id = "iad-save-validation-v3";
    btn.textContent = "Guardar validación";
    btn.style.border = "0";
    btn.style.borderRadius = "10px";
    btn.style.padding = "8px 12px";
    btn.style.fontWeight = "700";
    btn.style.cursor = "pointer";

    var status = document.createElement("span");
    status.id = "iad-save-validation-status-v3";
    status.style.alignSelf = "center";
    status.style.color = "#9fb0c4";
    status.style.fontSize = ".86rem";

    btn.addEventListener("click", async function () {
      var finalArea = getFinalArea();
      var validated = finalArea ? finalArea.value || "" : "";

      if (!validated.trim()) {
        status.textContent = "No hay informe validado para guardar.";
        return;
      }

      var payload = window.__iadValidationLastPayloadV3
        || window.__iadTrainingLastPayloadV2
        || {};

      var body = {
        template_name: getTemplateName(),
        dictado_original: getSourceText(),
        transcripcion: payload.transcripcion || payload.transcription || "",
        clinical_json: payload.hallazgos_estructurados || payload.structured_findings || {},
        informe_ia: getOriginalAiReport(),
        informe_validado: validated,
        informe_corregido: validated,
        modelo_usado: getModelName(),
        source: "work_v2_guardar_validacion_v3",
        estado: "validado",
        hallazgos_estructurados: payload.hallazgos_estructurados || [],
        mapa_aplicacion: payload.mapa_aplicacion || [],
        advertencias: payload.advertencias || [],
        metadata_json: payload
      };

      btn.disabled = true;
      var oldText = btn.textContent;
      btn.textContent = "Guardando...";
      status.textContent = "";

      try {
        var res = await fetch("/iad/api/validacion/guardar.json", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(body)
        });

        var data = await res.json();

        if (!res.ok || !data.ok) {
          throw new Error(data.error || data.detail || "No se pudo guardar validación");
        }

        btn.textContent = "Validación guardada";
        status.textContent = "Guardado en historial y Training IA.";

        setTimeout(function () {
          btn.textContent = oldText;
          status.textContent = "";
        }, 2200);
      } catch (e) {
        btn.textContent = oldText;
        status.textContent = "Error: " + (e && e.message ? e.message : e);
      } finally {
        btn.disabled = false;
      }
    });

    actions.appendChild(btn);
    actions.appendChild(status);
  }

  function isHistoryPage() {
    var p = (window.location.pathname || "").toLowerCase();
    return p.includes("historial") || p.includes("history");
  }

  async function loadValidationHistory(root) {
    var body = root.querySelector("[data-iad-validation-history-body]");
    if (!body) return;

    body.innerHTML = "Cargando validaciones...";

    try {
      var res = await fetch("/iad/api/validacion/historial.json?limit=50");
      var data = await res.json();

      if (!res.ok || !data.ok) {
        throw new Error(data.error || data.detail || "No se pudo cargar historial");
      }

      if (!data.items || !data.items.length) {
        body.innerHTML = "<p>No hay validaciones guardadas todavía.</p>";
        return;
      }

      var html = "";
      html += "<table style='width:100%;border-collapse:collapse;font-size:.88rem'>";
      html += "<thead><tr>";
      html += "<th style='text-align:left;border-bottom:1px solid rgba(148,163,184,.25);padding:6px'>Fecha</th>";
      html += "<th style='text-align:left;border-bottom:1px solid rgba(148,163,184,.25);padding:6px'>Plantilla</th>";
      html += "<th style='text-align:left;border-bottom:1px solid rgba(148,163,184,.25);padding:6px'>Informe validado</th>";
      html += "</tr></thead><tbody>";

      data.items.forEach(function (item) {
        html += "<tr>";
        html += "<td style='vertical-align:top;border-bottom:1px solid rgba(148,163,184,.14);padding:6px'>" + esc(item.created_at || "") + "</td>";
        html += "<td style='vertical-align:top;border-bottom:1px solid rgba(148,163,184,.14);padding:6px'>" + esc(item.template_name || "") + "</td>";
        html += "<td style='vertical-align:top;border-bottom:1px solid rgba(148,163,184,.14);padding:6px;white-space:pre-wrap;font-family:monospace'>" + esc(short(item.informe_validado || "", 900)) + "</td>";
        html += "</tr>";
      });

      html += "</tbody></table>";
      body.innerHTML = html;
    } catch (e) {
      body.innerHTML = "<p>Error cargando historial: " + esc(e && e.message ? e.message : e) + "</p>";
    }
  }

  function mountValidationHistoryPanel() {
    if (!isHistoryPage()) return;
    if (document.getElementById("iad-validation-history-panel-v3")) return;

    var host = document.querySelector("main")
      || document.querySelector(".content")
      || document.body;

    var panel = document.createElement("section");
    panel.id = "iad-validation-history-panel-v3";
    panel.style.marginTop = "16px";
    panel.style.border = "1px solid rgba(125,211,252,.30)";
    panel.style.borderRadius = "14px";
    panel.style.background = "#101d2d";
    panel.style.padding = "14px";
    panel.style.color = "#e5edf7";

    panel.innerHTML =
      "<h2 style='margin-top:0'>Historial de validaciones IA Dictador</h2>" +
      "<p style='color:#9fb0c4'>Cada validación queda guardada en historial y también como ejemplo para Training IA.</p>" +
      "<div style='display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px'>" +
        "<button type='button' data-iad-refresh-validation-history>Actualizar</button>" +
        "<a href='/iad/api/validacion/historial/export.jsonl' target='_blank' rel='noopener'>Exportar historial JSONL</a>" +
      "</div>" +
      "<div data-iad-validation-history-body></div>";

    host.appendChild(panel);

    var btn = panel.querySelector("[data-iad-refresh-validation-history]");
    if (btn) {
      btn.addEventListener("click", function () {
        loadValidationHistory(panel);
      });
    }

    loadValidationHistory(panel);
  }

  var oldFetch = window.fetch;
  if (typeof oldFetch === "function" && !oldFetch.__iadValidationSaveWrappedV3) {
    var wrapped = async function () {
      var args = arguments;
      var res = await oldFetch.apply(this, args);

      try {
        var clone = res.clone();
        var ct = clone.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          clone.json().then(function (data) {
            capturePayload(data);
            setTimeout(ensureValidationButton, 120);
            setTimeout(ensureValidationButton, 700);
            setTimeout(mountValidationHistoryPanel, 300);
          }).catch(function () {});
        }
      } catch (e) {}

      return res;
    };

    wrapped.__iadValidationSaveWrappedV3 = true;
    window.fetch = wrapped;
  }

  function tick() {
    ensureValidationButton();
    mountValidationHistoryPanel();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(tick, 300);
      setTimeout(tick, 1200);
      setTimeout(tick, 2500);
    });
  } else {
    setTimeout(tick, 300);
    setTimeout(tick, 1200);
    setTimeout(tick, 2500);
  }

  try {
    var obs = new MutationObserver(function () {
      setTimeout(ensureValidationButton, 50);
    });
    obs.observe(document.documentElement || document.body, {childList: true, subtree: true});
  } catch (e) {}
})();


// IAD_VALIDATION_OT_SYNC_AND_LATENCY_V4
(function () {
  "use strict";

  if (window.__iadValidationOtSyncLatencyV4) return;
  window.__iadValidationOtSyncLatencyV4 = true;

  function txt(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v.trim();
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v).trim(); }
  }

  function esc(s) {
    s = (s === null || s === undefined) ? "" : String(s);
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function getOtId() {
    var p = window.location.pathname || "";
    var m = p.match(/\/iad\/ot\/(\d+)/);
    if (m) return parseInt(m[1], 10);

    var body = document.body ? document.body.textContent || "" : "";
    m = body.match(/\bOT\s*#\s*(\d+)/i);
    if (m) return parseInt(m[1], 10);

    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || window.__iadRealFinalPayloadV3
      || {};
    var v = payload.ot_id || payload.work_order_id || payload.orden_id;
    if (v) {
      var n = parseInt(v, 10);
      if (!isNaN(n)) return n;
    }

    return null;
  }

  function getFinalArea() {
    return document.getElementById("iad-real-final-report")
      || document.getElementById("finalReport")
      || document.querySelector("textarea[name='resultado_revisado']")
      || document.querySelector("textarea[name='resultado']")
      || Array.from(document.querySelectorAll("textarea")).find(function (t) {
        return (t.value || "").includes("Impresión diagnóstica");
      });
  }

  function getReviewArea() {
    return document.querySelector("textarea[name='revision']")
      || document.querySelector("textarea[name='revisión']")
      || document.querySelector("textarea[name='revision_text']")
      || Array.from(document.querySelectorAll("textarea")).find(function (t) {
        var label = (t.closest("section") || t.parentElement || document.body).textContent || "";
        return /revisi[oó]n/i.test(label);
      });
  }

  function getSourceText() {
    var el = document.getElementById("sourceText")
      || document.querySelector("textarea[name='input_text_final']");
    return el ? (el.value || "") : "";
  }

  function getTemplateName() {
    var el = document.getElementById("iad-real-template")
      || document.getElementById("iad-native-final-template");

    var v = el ? txt(el.textContent || el.value || "") : "";
    if (v && v !== "—") return v;

    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || window.__iadRealFinalPayloadV3
      || {};

    return txt(
      (payload.plantilla_sugerida && payload.plantilla_sugerida.nombre)
      || payload.plantilla_nombre
      || payload.template_name
      || payload.template
      || ""
    );
  }

  function getOriginalAiReport() {
    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || {};

    return txt(
      window.__iadValidationOriginalReportV3
      || window.__iadTrainingOriginalReportV2
      || payload.informe_final_antes_ap_style_rules
      || payload.informe_final_antes_clean_ap_writer
      || payload.informe_final_antes_exam_type_guard
      || payload.informe_final_inteligente
      || payload.informe_final_deterministico
      || payload.informe_final
      || payload.final_report
      || ""
    );
  }

  function getModelName() {
    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || {};
    return txt(
      (payload.intelligence_editor && payload.intelligence_editor.model)
      || payload.modelo_usado
      || payload.model
      || ""
    );
  }

  function capturePayload(data) {
    if (!data || typeof data !== "object") return;

    var report = txt(data.informe_final || data.final_report || data.resultado_revisado || "");
    if (report && !window.__iadValidationOriginalReportV3) {
      window.__iadValidationOriginalReportV3 = report;
    }

    if (
      report
      || data.hallazgos_estructurados
      || data.clean_writer
      || data.exam_type_guard
      || data.ap_style_rules
      || data.mapa_aplicacion
    ) {
      window.__iadValidationLastPayloadV3 = data;
    }
  }

  async function postValidationV4(statusEl, buttonEl) {
    var finalArea = getFinalArea();
    var validated = finalArea ? finalArea.value || "" : "";

    if (!validated.trim()) {
      if (statusEl) statusEl.textContent = "No hay informe validado para guardar.";
      return false;
    }

    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || {};

    var body = {
      ot_id: getOtId(),
      template_name: getTemplateName(),
      dictado_original: getSourceText(),
      transcripcion: payload.transcripcion || payload.transcription || "",
      clinical_json: payload.hallazgos_estructurados || payload.structured_findings || {},
      informe_ia: getOriginalAiReport(),
      informe_validado: validated,
      informe_corregido: validated,
      modelo_usado: getModelName(),
      source: "work_or_ot_guardar_validacion_v4",
      estado: "validado",
      hallazgos_estructurados: payload.hallazgos_estructurados || [],
      mapa_aplicacion: payload.mapa_aplicacion || [],
      advertencias: payload.advertencias || [],
      metadata_json: payload
    };

    if (buttonEl) buttonEl.disabled = true;
    if (statusEl) statusEl.textContent = "Guardando validación...";

    try {
      var res = await fetch("/iad/api/validacion/guardar-v4.json", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });

      var data = await res.json();

      if (!res.ok || !data.ok) {
        throw new Error(data.error || data.detail || "No se pudo guardar validación");
      }

      if (statusEl) {
        statusEl.textContent =
          "Guardado en historial, Training IA" +
          (data.ot_id ? " y OT #" + data.ot_id : "") +
          ".";
      }

      return true;
    } catch (e) {
      if (statusEl) statusEl.textContent = "Error: " + (e && e.message ? e.message : e);
      return false;
    } finally {
      if (buttonEl) buttonEl.disabled = false;
    }
  }

  function findActionHost() {
    var area = getFinalArea();
    if (!area) return null;

    var panel = document.getElementById("iad-real-final-panel")
      || area.closest("section")
      || area.parentElement;

    if (!panel) return null;

    var actions = panel.querySelector(".iad-real-actions")
      || panel.querySelector(".iad-native-final-actions")
      || panel.querySelector("[data-iad-actions]");

    if (!actions) {
      actions = document.createElement("div");
      actions.className = "iad-real-actions";
      actions.setAttribute("data-iad-actions", "1");
      actions.style.display = "flex";
      actions.style.gap = "8px";
      actions.style.flexWrap = "wrap";
      actions.style.marginTop = "10px";
      panel.appendChild(actions);
    }

    return actions;
  }

  function ensureValidationButtonV4() {
    var area = getFinalArea();
    if (!area) return;

    var oldV3 = document.getElementById("iad-save-validation-v3");
    if (oldV3) {
      oldV3.style.display = "none";
      oldV3.setAttribute("aria-hidden", "true");
    }

    var oldTrain = document.getElementById("iad-save-training-correction-v2")
      || document.getElementById("iad-save-training-correction");
    if (oldTrain) {
      oldTrain.style.display = "none";
      oldTrain.setAttribute("aria-hidden", "true");
    }

    if (document.getElementById("iad-save-validation-v4")) return;

    var actions = findActionHost();
    if (!actions) return;

    var btn = document.createElement("button");
    btn.type = "button";
    btn.id = "iad-save-validation-v4";
    btn.textContent = "Guardar validación";
    btn.style.border = "0";
    btn.style.borderRadius = "10px";
    btn.style.padding = "8px 12px";
    btn.style.fontWeight = "700";
    btn.style.cursor = "pointer";

    var status = document.createElement("span");
    status.id = "iad-save-validation-status-v4";
    status.style.alignSelf = "center";
    status.style.color = "#9fb0c4";
    status.style.fontSize = ".86rem";

    btn.addEventListener("click", async function () {
      var old = btn.textContent;
      btn.textContent = "Guardando...";
      var ok = await postValidationV4(status, btn);
      btn.textContent = ok ? "Validación guardada" : old;
      if (ok) {
        setTimeout(function () {
          btn.textContent = old;
          if (status) status.textContent = "";
        }, 2300);
      }
    });

    actions.appendChild(btn);
    actions.appendChild(status);
  }

  async function fillOtPageFromLatestValidation() {
    var otId = getOtId();
    if (!otId) return;
    if (window.__iadFilledOtLatestValidationV4) return;
    window.__iadFilledOtLatestValidationV4 = true;

    try {
      var res = await fetch("/iad/api/validacion/ot/" + otId + "/latest.json");
      var data = await res.json();

      if (!res.ok || !data.ok || !data.found || !data.item) return;

      var finalArea = getFinalArea();
      var reviewArea = getReviewArea();

      if (finalArea && !(finalArea.value || "").trim()) {
        finalArea.value = data.item.informe_validado || "";
        finalArea.dispatchEvent(new Event("input", { bubbles: true }));
      }

      if (reviewArea && !(reviewArea.value || "").trim()) {
        reviewArea.value = data.item.diferencias_detectadas || "";
        reviewArea.dispatchEvent(new Event("input", { bubbles: true }));
      }

      var box = document.createElement("div");
      box.style.marginTop = "8px";
      box.style.color = "#9fb0c4";
      box.style.fontSize = ".9rem";
      box.textContent = "Informe recuperado desde historial de validaciones para OT #" + otId + ".";

      if (finalArea && finalArea.parentElement && !document.getElementById("iad-ot-sync-note-v4")) {
        box.id = "iad-ot-sync-note-v4";
        finalArea.parentElement.appendChild(box);
      }
    } catch (e) {}
  }

  function hookOldGuardarCopiarButton() {
    document.querySelectorAll("button, input[type='submit'], input[type='button']").forEach(function (btn) {
      var label = (btn.innerText || btn.textContent || btn.value || "").trim().toLowerCase();
      if (!label.includes("guardar") || !label.includes("copiar")) return;
      if (btn.__iadHookedGuardarCopiarV4) return;

      btn.__iadHookedGuardarCopiarV4 = true;

      btn.addEventListener("click", function () {
        var status = document.getElementById("iad-save-validation-status-v4");
        postValidationV4(status, btn);
      }, true);
    });
  }

  function installLatencyMonitor() {
    var oldFetch = window.fetch;
    if (typeof oldFetch !== "function" || oldFetch.__iadLatencyMonitorV4) return;

    var wrapped = async function () {
      var args = arguments;
      var url = "";
      try {
        url = String(args[0] && args[0].url ? args[0].url : args[0]);
      } catch (e) {}

      var t0 = performance.now();

      try {
        var res = await oldFetch.apply(this, args);
        var dt = performance.now() - t0;

        if (url.includes("/iad/api/audio/procesar-dictado-completo.json")) {
          console.log("[IA Dictador latencia] audio-first total navegador:", Math.round(dt), "ms");

          var box = document.getElementById("iad-latency-box-v4");
          if (!box) {
            box = document.createElement("div");
            box.id = "iad-latency-box-v4";
            box.style.margin = "8px 0";
            box.style.color = "#9fb0c4";
            box.style.fontSize = ".9rem";
            var host = document.querySelector("main") || document.body;
            host.prepend(box);
          }
          box.textContent = "Último procesamiento audio-first: " + Math.round(dt / 100) / 10 + " s";
        }

        try {
          var clone = res.clone();
          var ct = clone.headers.get("content-type") || "";
          if (ct.includes("application/json")) {
            clone.json().then(function (data) {
              capturePayload(data);
              setTimeout(ensureValidationButtonV4, 120);
              setTimeout(ensureValidationButtonV4, 700);
            }).catch(function () {});
          }
        } catch (e) {}

        return res;
      } catch (e) {
        var dtErr = performance.now() - t0;
        if (url.includes("/iad/api/audio/procesar-dictado-completo.json")) {
          console.log("[IA Dictador latencia] audio-first error tras:", Math.round(dtErr), "ms", e);
        }
        throw e;
      }
    };

    wrapped.__iadLatencyMonitorV4 = true;
    window.fetch = wrapped;
  }

  function tick() {
    ensureValidationButtonV4();
    fillOtPageFromLatestValidation();
    hookOldGuardarCopiarButton();
  }

  installLatencyMonitor();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(tick, 300);
      setTimeout(tick, 1200);
      setTimeout(tick, 2500);
    });
  } else {
    setTimeout(tick, 300);
    setTimeout(tick, 1200);
    setTimeout(tick, 2500);
  }

  try {
    var obs = new MutationObserver(function () {
      setTimeout(tick, 80);
    });
    obs.observe(document.documentElement || document.body, {childList: true, subtree: true});
  } catch (e) {}
})();


// IAD_VALIDATION_OT_SYNC_V5
(function () {
  "use strict";

  if (window.__iadValidationOtSyncV5) return;
  window.__iadValidationOtSyncV5 = true;

  function txt(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v.trim();
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v).trim(); }
  }

  function getOtId() {
    var p = window.location.pathname || "";
    var m = p.match(/\/iad\/ot\/(\d+)/);
    if (m) return parseInt(m[1], 10);

    var qs = new URLSearchParams(window.location.search || "");
    var q = qs.get("ot_id") || qs.get("work_order_id") || qs.get("orden_id");
    if (q && !isNaN(parseInt(q, 10))) return parseInt(q, 10);

    var body = document.body ? document.body.textContent || "" : "";
    m = body.match(/\bOT\s*#\s*(\d+)/i);
    if (m) return parseInt(m[1], 10);

    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || window.__iadRealFinalPayloadV3
      || {};
    var v = payload.ot_id || payload.work_order_id || payload.orden_id || payload.id_ot;
    if (v && !isNaN(parseInt(v, 10))) return parseInt(v, 10);

    return null;
  }

  function getFinalArea() {
    return document.getElementById("iad-real-final-report")
      || document.getElementById("finalReport")
      || document.querySelector("textarea[name='final_report_accepted']")
      || document.querySelector("textarea[name='resultado_revisado']")
      || document.querySelector("textarea[name='resultado']")
      || Array.from(document.querySelectorAll("textarea")).find(function (t) {
        return (t.value || "").includes("Impresión diagnóstica");
      });
  }

  function getReviewArea() {
    return document.querySelector("textarea[name='review_report']")
      || document.querySelector("textarea[name='revision']")
      || document.querySelector("textarea[name='revisión']")
      || document.querySelector("textarea[name='revision_text']")
      || Array.from(document.querySelectorAll("textarea")).find(function (t) {
        var label = (t.closest("section") || t.parentElement || document.body).textContent || "";
        return /revisi[oó]n/i.test(label);
      });
  }

  function getSourceText() {
    var el = document.getElementById("sourceText")
      || document.querySelector("textarea[name='input_text_final']");
    return el ? (el.value || "") : "";
  }

  function getTemplateName() {
    var el = document.getElementById("iad-real-template")
      || document.getElementById("iad-native-final-template");

    var v = el ? txt(el.textContent || el.value || "") : "";
    if (v && v !== "—") return v;

    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || window.__iadRealFinalPayloadV3
      || {};

    return txt(
      (payload.plantilla_sugerida && payload.plantilla_sugerida.nombre)
      || payload.plantilla_nombre
      || payload.template_name
      || payload.template
      || ""
    );
  }

  function getOriginalAiReport() {
    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || {};

    return txt(
      window.__iadValidationOriginalReportV3
      || window.__iadTrainingOriginalReportV2
      || payload.informe_final_antes_safe_impression_v2
      || payload.informe_final_antes_ap_style_rules
      || payload.informe_final_antes_clean_ap_writer
      || payload.informe_final_antes_exam_type_guard
      || payload.informe_final_inteligente
      || payload.informe_final_deterministico
      || payload.informe_final
      || payload.final_report
      || ""
    );
  }

  function getModelName() {
    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || {};
    return txt(
      (payload.intelligence_editor && payload.intelligence_editor.model)
      || payload.modelo_usado
      || payload.model
      || ""
    );
  }

  async function postValidationV5(statusEl, buttonEl) {
    var finalArea = getFinalArea();
    var validated = finalArea ? finalArea.value || "" : "";

    if (!validated.trim()) {
      if (statusEl) statusEl.textContent = "No hay informe validado para guardar.";
      return false;
    }

    var payload = window.__iadValidationLastPayloadV3
      || window.__iadTrainingLastPayloadV2
      || {};

    var body = {
      ot_id: getOtId(),
      template_name: getTemplateName(),
      dictado_original: getSourceText(),
      transcripcion: payload.transcripcion || payload.transcription || "",
      clinical_json: payload.hallazgos_estructurados || payload.structured_findings || {},
      informe_ia: getOriginalAiReport(),
      informe_validado: validated,
      informe_corregido: validated,
      modelo_usado: getModelName(),
      source: "work_or_ot_guardar_validacion_v5",
      estado: "validado",
      hallazgos_estructurados: payload.hallazgos_estructurados || [],
      mapa_aplicacion: payload.mapa_aplicacion || [],
      advertencias: payload.advertencias || [],
      metadata_json: payload
    };

    if (buttonEl) buttonEl.disabled = true;
    if (statusEl) statusEl.textContent = "Guardando validación...";

    try {
      var res = await fetch("/iad/api/validacion/guardar-v5.json", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });

      var data = await res.json();

      if (!res.ok || !data.ok) {
        throw new Error(data.error || data.detail || "No se pudo guardar validación");
      }

      if (statusEl) {
        statusEl.textContent =
          "Guardado en historial y Training IA" +
          (data.saved_workorder ? " y OT #" + data.ot_id : "") +
          ".";
      }

      return true;
    } catch (e) {
      if (statusEl) statusEl.textContent = "Error: " + (e && e.message ? e.message : e);
      return false;
    } finally {
      if (buttonEl) buttonEl.disabled = false;
    }
  }

  function findActionHost() {
    var area = getFinalArea();
    if (!area) return null;

    var panel = document.getElementById("iad-real-final-panel")
      || area.closest("section")
      || area.parentElement;

    if (!panel) return null;

    var actions = panel.querySelector(".iad-real-actions")
      || panel.querySelector(".iad-native-final-actions")
      || panel.querySelector("[data-iad-actions]");

    if (!actions) {
      actions = document.createElement("div");
      actions.className = "iad-real-actions";
      actions.setAttribute("data-iad-actions", "1");
      actions.style.display = "flex";
      actions.style.gap = "8px";
      actions.style.flexWrap = "wrap";
      actions.style.marginTop = "10px";
      panel.appendChild(actions);
    }

    return actions;
  }

  function ensureButtonV5() {
    var area = getFinalArea();
    if (!area) return;

    ["iad-save-validation-v3", "iad-save-validation-v4", "iad-save-training-correction-v2", "iad-save-training-correction"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) {
        el.style.display = "none";
        el.setAttribute("aria-hidden", "true");
      }
    });

    if (document.getElementById("iad-save-validation-v5")) return;

    var actions = findActionHost();
    if (!actions) return;

    var btn = document.createElement("button");
    btn.type = "button";
    btn.id = "iad-save-validation-v5";
    btn.textContent = "Guardar validación";
    btn.style.border = "0";
    btn.style.borderRadius = "10px";
    btn.style.padding = "8px 12px";
    btn.style.fontWeight = "700";
    btn.style.cursor = "pointer";

    var status = document.createElement("span");
    status.id = "iad-save-validation-status-v5";
    status.style.alignSelf = "center";
    status.style.color = "#9fb0c4";
    status.style.fontSize = ".86rem";

    btn.addEventListener("click", async function () {
      var old = btn.textContent;
      btn.textContent = "Guardando...";
      var ok = await postValidationV5(status, btn);
      btn.textContent = ok ? "Validación guardada" : old;
      if (ok) {
        setTimeout(function () {
          btn.textContent = old;
          if (status) status.textContent = "";
        }, 2300);
      }
    });

    actions.appendChild(btn);
    actions.appendChild(status);
  }

  async function fillOtPageV5() {
    var otId = getOtId();
    if (!otId) return;
    if (window.__iadFilledOtLatestValidationV5) return;
    window.__iadFilledOtLatestValidationV5 = true;

    try {
      var res = await fetch("/iad/api/validacion/ot/" + otId + "/latest-v5.json");
      var data = await res.json();

      if (!res.ok || !data.ok || !data.found || !data.item) return;

      var finalArea = getFinalArea();
      var reviewArea = getReviewArea();

      if (finalArea && !(finalArea.value || "").trim()) {
        finalArea.value = data.item.informe_validado || "";
        finalArea.dispatchEvent(new Event("input", { bubbles: true }));
      }

      if (reviewArea && !(reviewArea.value || "").trim()) {
        reviewArea.value = data.item.diferencias_detectadas || "";
        reviewArea.dispatchEvent(new Event("input", { bubbles: true }));
      }
    } catch (e) {}
  }

  function hookOldGuardarCopiarV5() {
    document.querySelectorAll("button, input[type='submit'], input[type='button']").forEach(function (btn) {
      var label = (btn.innerText || btn.textContent || btn.value || "").trim().toLowerCase();
      if (!label.includes("guardar") || !label.includes("copiar")) return;
      if (btn.__iadHookedGuardarCopiarV5) return;

      btn.__iadHookedGuardarCopiarV5 = true;

      btn.addEventListener("click", function () {
        var status = document.getElementById("iad-save-validation-status-v5");
        postValidationV5(status, btn);
      }, true);
    });
  }

  function capturePayload(data) {
    if (!data || typeof data !== "object") return;

    var report = txt(data.informe_final || data.final_report || data.resultado_revisado || "");
    if (report && !window.__iadValidationOriginalReportV3) {
      window.__iadValidationOriginalReportV3 = report;
    }

    if (
      report
      || data.hallazgos_estructurados
      || data.clean_writer
      || data.exam_type_guard
      || data.ap_style_rules
      || data.ap_safe_impression_v2
      || data.mapa_aplicacion
    ) {
      window.__iadValidationLastPayloadV3 = data;
    }
  }

  var oldFetch = window.fetch;
  if (typeof oldFetch === "function" && !oldFetch.__iadValidationV5Wrapped) {
    var wrapped = async function () {
      var args = arguments;
      var res = await oldFetch.apply(this, args);

      try {
        var clone = res.clone();
        var ct = clone.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          clone.json().then(function (data) {
            capturePayload(data);
            setTimeout(ensureButtonV5, 120);
            setTimeout(ensureButtonV5, 700);
          }).catch(function () {});
        }
      } catch (e) {}

      return res;
    };

    wrapped.__iadValidationV5Wrapped = true;
    window.fetch = wrapped;
  }

  function tick() {
    ensureButtonV5();
    fillOtPageV5();
    hookOldGuardarCopiarV5();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(tick, 300);
      setTimeout(tick, 1200);
      setTimeout(tick, 2500);
    });
  } else {
    setTimeout(tick, 300);
    setTimeout(tick, 1200);
    setTimeout(tick, 2500);
  }

  try {
    var obs = new MutationObserver(function () {
      setTimeout(tick, 80);
    });
    obs.observe(document.documentElement || document.body, {childList: true, subtree: true});
  } catch (e) {}
})();

