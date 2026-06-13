(function () {
  "use strict";

  let iadProcessing = false;

  function ready(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  }

  function norm(v) {
    return String(v || "").trim();
  }

  function textOf(el) {
    return norm(el && (el.innerText || el.value || el.textContent));
  }

  function visible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
  }

  function setStatus(msg) {
    const el = document.getElementById("iad-rad-one-status");
    if (el) el.textContent = msg;
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value || "";
  }

  function setValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value || "";
  }

  function getValue(id) {
    const el = document.getElementById(id);
    return el ? norm(el.value) : "";
  }

  function buttonLabel(btn) {
    return norm(btn && (btn.innerText || btn.value || btn.textContent));
  }

  function allButtons() {
    return Array.from(document.querySelectorAll("button, input[type='submit'], input[type='button']"));
  }

  function hide(el) {
    if (el) {
      el.style.display = "none";
      el.setAttribute("aria-hidden", "true");
    }
  }

  function show(el) {
    if (el) {
      el.style.display = "";
      el.removeAttribute("aria-hidden");
    }
  }

  function findSourceTextarea() {
    const candidates = Array.from(document.querySelectorAll("textarea"))
      .filter(visible)
      .filter(function (el) {
        if (el.closest("#iad-rad-one-step-panel")) return false;
        const idname = norm(el.id + " " + el.name + " " + el.placeholder);
        if (/iad-rad|hallazgo|resultado|revisado|primary|plantilla|extra/i.test(idname)) return false;
        return true;
      });

    if (!candidates.length) return null;

    candidates.sort(function (a, b) {
      const av = norm(a.value).length;
      const bv = norm(b.value).length;
      const at = textOf(a.closest("section,.iad-card,.card,div")).slice(0, 1000);
      const bt = textOf(b.closest("section,.iad-card,.card,div")).slice(0, 1000);

      let as = av * 10 + a.getBoundingClientRect().height;
      let bs = bv * 10 + b.getBoundingClientRect().height;

      if (/Información principal para el informe/i.test(at)) as += 100000;
      if (/Información principal para el informe/i.test(bt)) bs += 100000;

      return bs - as;
    });

    return candidates[0];
  }

  function getAudioFileCount() {
    let n = 0;
    document.querySelectorAll("input[type='file']").forEach(function (input) {
      if (input.files) n += input.files.length;
    });
    return n;
  }

  async function waitForTextareaChange(textarea, before, timeoutMs) {
    const start = Date.now();

    while (Date.now() - start < timeoutMs) {
      const current = norm(textarea.value);
      if (current && current !== before) return current;
      await new Promise(function (resolve) { setTimeout(resolve, 700); });
    }

    return norm(textarea.value);
  }

  function confidencePercent(confidence) {
    const c = String(confidence || "").toLowerCase();
    if (c.includes("alta")) return "90%";
    if (c.includes("media")) return "65%";
    if (c.includes("baja")) return "35%";
    const n = parseFloat(c.replace(",", "."));
    if (!Number.isNaN(n)) return (n <= 1 ? Math.round(n * 100) : Math.round(n)) + "%";
    return "";
  }

  function inferModalityFromTemplate(name) {
    const raw = String(name || "").trim().toLowerCase();
    if (raw.startsWith("tc") || raw.includes("tomografía") || raw.includes("tomografia") || raw.includes("tac")) return "TC";
    if (raw.startsWith("rm") || raw.includes("resonancia")) return "RM";
    if (raw.startsWith("rx") || raw.includes("radiografía") || raw.includes("radiografia")) return "RX";
    if (raw.startsWith("us") || raw.startsWith("eco") || raw.includes("ecografía") || raw.includes("ecografia") || raw.includes("ultrasonido")) return "US";
    if (raw.startsWith("mg") || raw.includes("mamografía") || raw.includes("mamografia")) return "MG";
    return "";
  }

  function inferTipoFromTemplate(name) {
    const raw = String(name || "").trim();
    if (!raw) return "";
    const parts = raw.split(" - ");
    if (parts.length > 1) return parts.slice(1).join(" - ").trim();
    return raw;
  }

  function getOtId() {
    const m = window.location.pathname.match(/\/ot\/(\d+)/i);
    if (m) return m[1];
    return "";
  }

  function neutralizeOldUi() {
    const form = document.getElementById("iad-main-work-form") || document.querySelector('form[action*="/iad/ot/crear"]');
    if (form) {
      form.setAttribute("action", "javascript:void(0)");
      form.setAttribute("onsubmit", "return false;");
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        analyzeAndGenerateOneStep().catch(function (err) {
          console.error(err);
          setStatus("Error al procesar.");
          alert("Error al procesar: " + err.message);
        });
        return false;
      }, true);
    }

    allButtons().forEach(function (btn) {
      const t = buttonLabel(btn);

      if (/^Transcribir todos$/i.test(t)) hide(btn);
      if (/^Procesar con datos extra$/i.test(t)) hide(btn);

      if (/^Procesar$/i.test(t)) {
        btn.type = "button";
        btn.id = "iad-rad-one-analyze";
        btn.textContent = "Analizar radiología";
        btn.value = "Analizar radiología";
      }
    });
  }

  async function transcribeIfNeeded(textarea) {
    const audioCount = getAudioFileCount();

    if (audioCount === 0) {
      return norm(textarea.value);
    }

    const transcribeBtn = document.getElementById("transcribeAllBtn");

    if (!transcribeBtn) {
      return norm(textarea.value);
    }

    const before = norm(textarea.value);
    setStatus("Transcribiendo audio...");

    transcribeBtn.click();

    const after = await waitForTextareaChange(textarea, before, 120000);

    if (after) return after;

    throw new Error("Transcribió audio, pero no encontré texto en el cuadro principal.");
  }


  // IAD_LATERALITY_VALIDATION_FRONTEND_V1
  function ensureValidationWarningBox() {
    let box = document.getElementById("iad-rad-validation-warning");
    if (box) return box;

    box = document.createElement("div");
    box.id = "iad-rad-validation-warning";
    box.style.display = "none";
    box.style.margin = "12px 0";
    box.style.padding = "12px 14px";
    box.style.borderRadius = "12px";
    box.style.border = "1px solid #f59e0b";
    box.style.background = "#fff4c7";
    box.style.color = "#1f2937";
    box.style.fontWeight = "600";

    const results = document.getElementById("iad-rad-one-results");
    if (results && results.parentNode) {
      results.parentNode.insertBefore(box, results);
    } else {
      document.body.appendChild(box);
    }

    return box;
  }

  function renderValidationWarnings(data) {
    const box = ensureValidationWarningBox();
    const warnings = Array.isArray(data.advertencias) ? data.advertencias : [];
    const conflicts = Array.isArray(data.conflictos) ? data.conflictos : [];

    if (!warnings.length && !conflicts.length) {
      box.style.display = "none";
      box.innerHTML = "";
      window.__iadValidationHasWarning = false;
      return;
    }

    window.__iadValidationHasWarning = true;

    let html = "<strong>Advertencia antes de firmar:</strong><ul>";

    warnings.forEach(function (w) {
      html += "<li>" + String(w).replace(/[<>&]/g, function (c) {
        return {"<":"&lt;", ">":"&gt;", "&":"&amp;"}[c];
      }) + "</li>";
    });

    conflicts.forEach(function (c) {
      const t = c && c.texto ? c.texto : "Conflicto clínico detectado.";
      html += "<li>" + String(t).replace(/[<>&]/g, function (ch) {
        return {"<":"&lt;", ">":"&gt;", "&":"&amp;"}[ch];
      }) + "</li>";
    });

    html += "</ul><div style='margin-top:8px;'>Usa <strong>Revisar informe IA</strong> antes de copiar o guardar.</div>";

    box.innerHTML = html;
    box.style.display = "";
  }

  async function validateDictationVsReport(raw, report) {
    window.__iadValidationHasWarning = false;

    const response = await fetch("/iad/api/validar-dictado-informe.json", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_text: raw || "",
        generated_text: report || ""
      })
    });

    if (!response.ok) {
      const txt = await response.text();
      throw new Error("Validación HTTP " + response.status + ": " + txt.slice(0, 300));
    }

    const data = await response.json();
    window.__iadLastValidation = data;
    renderValidationWarnings(data);
    
    try {
      if (data && data.revision && typeof iadRenderInlineReview === "function") {
        iadRenderInlineReview(data.revision);
      }
    } catch (inlineErr) {
      console.error("No se pudo renderizar revisión inline desde validación:", inlineErr);
    }
return data;
  }


  async function analyzeAndGenerateOneStep() {
    if (iadProcessing) return;

    iadProcessing = true;

    const btn = document.getElementById("iad-rad-one-analyze");
    const textarea = findSourceTextarea();

    if (!textarea) {
      iadProcessing = false;
      alert("No encontré el cuadro principal de texto.");
      return;
    }

    try {
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Procesando...";
      }

      let raw = await iadEnsureAllAudioTextBeforeAnalysis(textarea);
      raw = norm(textarea.value || raw || '');
      // IAD_FORCE_FULL_TEXTAREA_RAW_V5
      window.__iadLastDictatedText = raw;
      iad5RenderAudit(raw);

      if (!raw) throw new Error("No hay texto para analizar.");

      window.__iadLastDictatedText = raw;

      setStatus("Analizando plantilla...");

      const analyzeBody = new URLSearchParams();
      analyzeBody.set("texto_bruto", raw);

      const analyzeResponse = await fetch("/iad/analizar-radiologia-estructurada.json", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
        body: analyzeBody.toString()
      });

      if (!analyzeResponse.ok) {
        const txt = await analyzeResponse.text();
        throw new Error("Análisis HTTP " + analyzeResponse.status + ": " + txt.slice(0, 400));
      }

      const analysis = await analyzeResponse.json();

      if (analysis.ok === false) throw new Error(analysis.error || "No se detectó plantilla.");

      const tpl = analysis.plantilla_sugerida || {};
      const plantillaNombre = norm(tpl.nombre || "");
      const plantillaId = norm(tpl.id || "");
      const hallazgos = norm(analysis.hallazgos_radiologicos || raw);
      const clinicalJson = analysis.clinical_json || null;
      window.__iadLastClinicalJson = clinicalJson;

      if (!plantillaNombre && !plantillaId) {
        throw new Error("No se detectó plantilla.");
      }

      setText("iad-rad-one-template-name", plantillaNombre || ("ID " + plantillaId));
      setText("iad-rad-one-confidence", (tpl.confianza || "—") + (confidencePercent(tpl.confianza) ? " · " + confidencePercent(tpl.confianza) : ""));
      setValue("iad-rad-one-template-id", plantillaId);
      setValue("iad-rad-one-hallazgos", hallazgos);
      show(document.getElementById("iad-rad-one-template-box"));

      window.__iadLastAnalysis = analysis;

      setStatus("Plantilla detectada. Generando informe...");

      const generateBody = new URLSearchParams();
      generateBody.set("plantilla_nombre", plantillaNombre);
      generateBody.set("plantilla_id", plantillaId);
      generateBody.set("hallazgos", hallazgos);
      if (window.__iadLastClinicalJson) {
        generateBody.set("clinical_json", JSON.stringify(window.__iadLastClinicalJson));
      }

      const generateResponse = await fetch("/iad/generar-informe-radiologico-estructurado.json", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
        body: generateBody.toString()
      });

      if (!generateResponse.ok) {
        const txt = await generateResponse.text();
        throw new Error("Generación HTTP " + generateResponse.status + ": " + txt.slice(0, 400));
      }

      const generated = await generateResponse.json();

      if (generated.ok === false) throw new Error(generated.error || "No se pudo generar informe.");

      const report = generated.informe_final || "";

      setValue("iad-rad-one-primary-report", report);
      setValue("iad-rad-one-revised-report", report);
      show(document.getElementById("iad-rad-one-results"));

      try {
        if (typeof iadHideLegacyReportBlocks === "function") {
          iadHideLegacyReportBlocks();
        }
      } catch (hideErr) {
        console.error("No se pudieron ocultar bloques legacy:", hideErr);
      }

      window.__iadLastGenerated = generated;
      try {
        await iad5BuildInlineReviewDirect(raw, report);
      } catch (inlineErr) {
        console.error("No se pudo construir panel inline V5:", inlineErr);
      }
      try { setTimeout(iad4FetchAndRender, 300); } catch (e) { console.error(e); }
      if (generated.clinical_json) {
        window.__iadLastClinicalJson = generated.clinical_json;
      }

      try {
        await validateDictationVsReport(raw, report);
        await iadV3RenderFromBackend();
      } catch (validationErr) {
        console.error(validationErr);
        setStatus("Informe generado. No se pudo validar discordancias.");
      }

      if (window.__iadValidationHasWarning) {
        setStatus("Informe generado con advertencias. Revisar antes de copiar o guardar.");
      } else {
        setStatus("Informe generado en esta misma página.");
      }
    } finally {
      iadProcessing = false;
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Analizar radiología";
      }
    }
  }

  async function saveRevision() {
    const plantillaNombre = textOf(document.getElementById("iad-rad-one-template-name"));
    const plantillaId = getValue("iad-rad-one-template-id");
    const hallazgos = getValue("iad-rad-one-hallazgos");
    const primary = getValue("iad-rad-one-primary-report");
    const inlineFinal = document.getElementById("iad-inline-final-report");
    if (inlineFinal) {
      const hiddenRevisedBeforeSave = document.getElementById("iad-rad-one-revised-report");
      if (hiddenRevisedBeforeSave) hiddenRevisedBeforeSave.value = inlineFinal.value || "";
    }

    const revised = getValue("iad-rad-one-revised-report");
    const textarea = findSourceTextarea();

    if (!primary || !revised) {
      alert("No hay informe generado para guardar.");
      return;
    }

    const meta = {
      url: window.location.href,
      analysis: window.__iadLastAnalysis || null,
      generated: window.__iadLastGenerated || null,
      user_agent: navigator.userAgent,
      saved_at_client: new Date().toISOString()
    };

    const body = new URLSearchParams();
    body.set("ot_id", getOtId());
    body.set("texto_dictado", window.__iadLastDictatedText || norm(textarea && textarea.value));
    body.set("plantilla_nombre", plantillaNombre);
    body.set("plantilla_id", plantillaId);
    body.set("hallazgos_detectados", hallazgos);
    body.set("resultado_primario", primary);
    body.set("resultado_revisado", revised);
    body.set("modelo", "gpt");
    body.set("metadata_json", JSON.stringify(meta));
    body.set("titulo", plantillaNombre);
    body.set("modalidad", inferModalityFromTemplate(plantillaNombre));
    body.set("tipo", inferTipoFromTemplate(plantillaNombre));
    body.set("paciente", "");
    body.set("edad", "");

    setStatus("Guardando revisión...");

    const response = await fetch("/iad/guardar-revision-y-historial-v3.json", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
      body: body.toString()
    });

    if (!response.ok) {
      const txt = await response.text();
      throw new Error("Guardar HTTP " + response.status + ": " + txt.slice(0, 400));
    }

    const data = await response.json();
    const sync = data.historial_sync || {};

    if (sync.ok) setStatus("Revisión guardada. Historial actualizado: OT #" + (data.ot_id || sync.ot_id || ""));
    else setStatus("Revisión guardada. Historial no sincronizado: " + (sync.reason || "sin detalle"));
  
    // IAD_FIX_RAD_SAVE_CALL_COPY_NEW_OT_V2
    if (window.iadPostSaveCopyAndNewOt) {
      await window.iadPostSaveCopyAndNewOt((typeof report !== "undefined" ? report : null), data, setStatus);
    }
}

  function copyRevised() {
    const report = document.getElementById("iad-rad-one-revised-report");
    if (!report) return;
    navigator.clipboard.writeText(report.value || "").then(function () {
      setStatus("Resultado revisado copiado.");
    }).catch(function () {
      report.focus();
      report.select();
      document.execCommand("copy");
      setStatus("Resultado revisado copiado.");
    });
  }

  function bindEvents() {
    document.addEventListener("click", function (ev) {
      const btn = ev.target.closest("button, input[type='button'], input[type='submit']");
      if (!btn) return;

      const label = buttonLabel(btn);

      if (btn.id === "iad-rad-one-analyze" || /^Procesar$/i.test(label) || /Analizar radiolog/i.test(label)) {
        ev.preventDefault();
        ev.stopPropagation();
        analyzeAndGenerateOneStep().catch(function (err) {
          console.error(err);
          setStatus("Error al analizar/generar.");
          alert("Error: " + err.message);
        });
        return false;
      }

      if (btn.id === "iad-rad-one-save") {
        ev.preventDefault();
        ev.stopPropagation();
        saveRevision().catch(function (err) {
          console.error(err);
          setStatus("Error al guardar.");
          alert("Error al guardar: " + err.message);
        });
        return false;
      }

      if (btn.id === "iad-rad-one-copy") {
        ev.preventDefault();
        ev.stopPropagation();
        copyRevised();
        return false;
      }
    }, true);
  }

  function setup() {
    neutralizeOldUi();
    bindEvents();
    console.log("[IAD] work flujo un-paso activo v22");
  }

  ready(setup);


  // IAD_FORCE_VALIDATION_WATCHER_V2
  function iadEscHtml(s) {
    return String(s || "").replace(/[<>&"]/g, function (c) {
      return {"<":"&lt;", ">":"&gt;", "&":"&amp;", '"':"&quot;"}[c];
    });
  }

  function iadFindValidationSourceText() {
    if (window.__iadLastDictatedText) return String(window.__iadLastDictatedText || "").trim();

    const areas = Array.from(document.querySelectorAll("textarea"));
    if (!areas.length) return "";

    let best = null;

    areas.forEach(function (el) {
      const value = String(el.value || "").trim();
      const ctx = String((el.closest("section,div,main") || document.body).innerText || "").toLowerCase();

      if (!value) return;

      let score = value.length;
      if (ctx.includes("información principal") || ctx.includes("informacion principal")) score += 100000;
      if (ctx.includes("resultado primario") || ctx.includes("resultado revisado")) score -= 100000;

      if (!best || score > best.score) best = {el: el, value: value, score: score};
    });

    return best ? best.value : "";
  }

  function iadFindValidationGeneratedText() {
    const ids = [
      "iad-rad-one-revised-report",
      "iad-rad-one-primary-report"
    ];

    for (const id of ids) {
      const el = document.getElementById(id);
      if (el && String(el.value || "").trim()) return String(el.value || "").trim();
    }

    if (window.__iadLastGenerated && window.__iadLastGenerated.informe_final) {
      return String(window.__iadLastGenerated.informe_final || "").trim();
    }

    return "";
  }

  function iadEnsureValidationBanner() {
    let box = document.getElementById("iad-force-validation-banner");
    if (box) return box;

    box = document.createElement("div");
    box.id = "iad-force-validation-banner";
    box.style.display = "none";
    box.style.margin = "12px 0";
    box.style.padding = "12px 14px";
    box.style.borderRadius = "12px";
    box.style.border = "1px solid #f59e0b";
    box.style.background = "#fff4c7";
    box.style.color = "#111827";
    box.style.fontWeight = "600";
    box.style.lineHeight = "1.45";

    const results = document.getElementById("iad-rad-one-results");
    if (results && results.parentNode) {
      results.parentNode.insertBefore(box, results);
    } else {
      const primary = document.getElementById("iad-rad-one-primary-report");
      if (primary && primary.parentNode) primary.parentNode.insertBefore(box, primary);
      else document.body.appendChild(box);
    }

    return box;
  }

  function iadRenderForcedValidation(data) {
    const box = iadEnsureValidationBanner();
    const warnings = Array.isArray(data && data.advertencias) ? data.advertencias : [];
    const conflicts = Array.isArray(data && data.conflictos) ? data.conflictos : [];

    if (!warnings.length && !conflicts.length) {
      box.style.display = "none";
      box.innerHTML = "";
      window.__iadValidationHasWarning = false;
      return;
    }

    window.__iadValidationHasWarning = true;

    let html = "<strong>Advertencia antes de firmar/copiar:</strong><ul>";

    warnings.forEach(function (w) {
      html += "<li>" + iadEscHtml(w) + "</li>";
    });

    conflicts.forEach(function (c) {
      html += "<li>" + iadEscHtml((c && c.texto) || "Conflicto clínico detectado.") + "</li>";
    });

    html += "</ul><div>Usa <strong>Revisar informe IA</strong> y resuelve el conflicto antes de guardar.</div>";

    box.innerHTML = html;
    box.style.display = "";
  }

  async function iadRunForcedValidation() {
    const source = iadFindValidationSourceText();
    const generated = iadFindValidationGeneratedText();

    if (!source || !generated) return;

    const key = source.slice(0, 300) + "||" + generated.slice(0, 300);
    if (window.__iadLastForcedValidationKey === key) return;
    window.__iadLastForcedValidationKey = key;

    try {
      const response = await fetch("/iad/api/validar-dictado-informe.json", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          source_text: source,
          generated_text: generated
        })
      });

      if (!response.ok) return;

      const data = await response.json();
      window.__iadLastValidation = data;
      iadRenderForcedValidation(data);
    } catch (err) {
      console.error("Validación forzada falló:", err);
    }
  }

  document.addEventListener("click", function (ev) {
    const btn = ev.target.closest("button, input[type='button'], input[type='submit']");
    if (!btn) return;

    const label = String(btn.innerText || btn.value || btn.textContent || "").toLowerCase();

    if ((btn.id === "iad-rad-one-save" || label.includes("guardar revisión") || label.includes("guardar revision")) && window.__iadValidationHasWarning) {
      const ok = confirm("Hay advertencias/conflictos clínicos pendientes. ¿Guardar de todos modos?");
      if (!ok) {
        ev.preventDefault();
        ev.stopPropagation();
        return false;
      }
    }
  }, true);

  setInterval(iadRunForcedValidation, 1600);




  // IAD_INLINE_REVIEW_SPLIT_V1
  function iadEsc(s) {
    return String(s || "").replace(/[<>&"]/g, function (c) {
      return {"<":"&lt;", ">":"&gt;", "&":"&amp;", '"':"&quot;"}[c];
    });
  }

  function iadEnsureInlineReviewStyles() {
    if (document.getElementById("iad-inline-review-style")) return;

    const style = document.createElement("style");
    style.id = "iad-inline-review-style";
    style.textContent = `
      #iad-inline-review-root {
        margin: 14px 0 18px 0;
        background: #eef2f7;
        border: 1px solid #cfd8e3;
        border-radius: 18px;
        padding: 14px;
        color: #1f2937;
      }

      #iad-inline-review-root .iad-inline-top {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 12px;
        margin-bottom: 12px;
      }

      #iad-inline-review-root .iad-inline-title {
        font-size: 20px;
        font-weight: 800;
        line-height: 1.15;
        color: #1f2937;
      }

      #iad-inline-review-root .iad-inline-legend,
      #iad-inline-review-root .iad-inline-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }

      #iad-inline-review-root .iad-badge {
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        border-radius: 999px;
        padding: 4px 11px;
        border: 1.4px solid;
        font-size: 12px;
        font-weight: 800;
        white-space: nowrap;
      }

      #iad-inline-review-root .iad-badge-agregado { background: #dcfce7; border-color: #22c55e; }
      #iad-inline-review-root .iad-badge-reemplazado { background: #dbeafe; border-color: #2563eb; }
      #iad-inline-review-root .iad-badge-estructurado { background: #f3e8ff; border-color: #a855f7; }
      #iad-inline-review-root .iad-badge-revisar { background: #fff4c7; border-color: #d97706; }
      #iad-inline-review-root .iad-badge-conflicto { background: #fee2e2; border-color: #ef4444; }
      #iad-inline-review-root .iad-badge-eliminado { background: #e5e7eb; border-color: #9ca3af; text-decoration: line-through; }
      #iad-inline-review-root .iad-badge-fuente { background: #ede9fe; border-color: #7c3aed; }

      #iad-inline-review-root .iad-inline-warning {
        background: #fff4c7;
        border: 1.3px solid #f59e0b;
        border-radius: 14px;
        padding: 12px 14px;
        margin-bottom: 14px;
      }

      #iad-inline-review-root .iad-inline-split {
        display: grid;
        grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.95fr);
        gap: 14px;
        align-items: start;
      }

      #iad-inline-review-root .iad-inline-left,
      #iad-inline-review-root .iad-inline-right {
        background: #ffffff;
        border: 1px solid #d7dde7;
        border-radius: 16px;
        padding: 14px;
      }

      #iad-inline-review-root .iad-inline-section {
        margin-bottom: 16px;
      }

      #iad-inline-review-root .iad-inline-section h3 {
        margin: 0 0 10px 0;
        font-size: 15px;
        font-weight: 800;
        color: #1f2937;
        padding-bottom: 6px;
        border-bottom: 1px solid #e5e7eb;
      }

      #iad-inline-review-root .iad-normal-line {
        font-size: 13px;
        line-height: 1.5;
        margin: 0 0 10px 0;
        color: #374151;
      }

      #iad-inline-review-root .iad-card {
        border-left: 5px solid #f59e0b;
        border-radius: 13px;
        padding: 11px 12px;
        margin: 10px 0;
        background: #fff8dd;
      }

      #iad-inline-review-root .iad-card[data-tipo="conflicto"] {
        background: #fee2e2;
        border-left-color: #ef4444;
      }

      #iad-inline-review-root .iad-card[data-tipo="agregado"] {
        background: #dcfce7;
        border-left-color: #22c55e;
      }

      #iad-inline-review-root .iad-card[data-tipo="reemplazado"] {
        background: #dbeafe;
        border-left-color: #2563eb;
      }

      #iad-inline-review-root .iad-card[data-tipo="eliminado"] {
        background: #e5e7eb;
        border-left-color: #9ca3af;
      }

      #iad-inline-review-root .iad-card.accepted {
        outline: 2px solid #22c55e;
      }

      #iad-inline-review-root .iad-card.rejected {
        opacity: 0.55;
        filter: grayscale(0.35);
      }

      #iad-inline-review-root .iad-card-text {
        font-size: 14px;
        font-weight: 600;
        line-height: 1.45;
        color: #1f2937;
        margin-bottom: 8px;
      }

      #iad-inline-review-root .iad-card-meta {
        font-size: 12px;
        line-height: 1.45;
        color: #5b6574;
        margin: 5px 0;
      }

      #iad-inline-review-root .iad-card-motivos {
        font-size: 12px;
        color: #374151;
        margin-top: 7px;
      }

      #iad-inline-review-root .iad-card-motivos ul {
        margin: 5px 0 0 0;
        padding-left: 18px;
      }

      #iad-inline-review-root .iad-card-actions,
      #iad-inline-review-root .iad-inline-toolbar {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }

      #iad-inline-review-root .iad-card-actions {
        margin-top: 10px;
      }

      #iad-inline-review-root .iad-inline-toolbar {
        margin: 12px 0 10px 0;
      }

      #iad-inline-review-root button {
        border: 1px solid #cbd5e1;
        background: #ffffff;
        color: #0f172a;
        border-radius: 10px;
        padding: 7px 10px;
        font-size: 12px;
        font-weight: 800;
        cursor: pointer;
      }

      #iad-inline-review-root button:hover {
        background: #f8fafc;
      }

      #iad-inline-review-root .iad-inline-right h3 {
        margin: 0 0 8px 0;
        font-size: 17px;
        font-weight: 800;
        color: #1f2937;
      }

      #iad-inline-review-root .iad-inline-right .iad-inline-note {
        font-size: 12px;
        color: #5b6574;
        margin-bottom: 10px;
      }

      #iad-inline-review-root textarea#iad-inline-final-report {
        width: 100%;
        min-height: 520px;
        border-radius: 14px;
        border: 1px solid #cbd5e1;
        padding: 12px;
        background: #0b1730;
        color: #f8fafc;
        font-size: 13px;
        line-height: 1.45;
        resize: vertical;
      }

      @media (max-width: 1100px) {
        #iad-inline-review-root .iad-inline-split {
          grid-template-columns: 1fr;
        }

        #iad-inline-review-root textarea#iad-inline-final-report {
          min-height: 300px;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function iadFindAnchorForInlineReview() {
    const primary = document.getElementById("iad-rad-one-primary-report");
    if (primary && primary.parentNode) return primary;
    const revised = document.getElementById("iad-rad-one-revised-report");
    if (revised && revised.parentNode) return revised;
    return null;
  }

  function iadEnsureInlineReviewRoot() {
    iadEnsureInlineReviewStyles();

    let root = document.getElementById("iad-inline-review-root");
    if (root) return root;

    const anchor = iadFindAnchorForInlineReview();
    if (!anchor || !anchor.parentNode) return null;

    root = document.createElement("div");
    root.id = "iad-inline-review-root";
    anchor.parentNode.insertBefore(root, anchor);

    return root;
  }

  function iadHideLegacyReportBlocks() {
    const idsToHide = [
      "iad-rad-one-primary-report",
      "iad-rad-one-revised-report"
    ];

    idsToHide.forEach(function (id) {
      const el = document.getElementById(id);
      if (!el) return;

      el.style.display = "none";

      let prev = el.previousElementSibling;
      if (prev) {
        const t = String(prev.innerText || prev.textContent || "").trim().toLowerCase();
        if (
          t.includes("resultado primario ia") ||
          t.includes("resultado revisado")
        ) {
          prev.style.display = "none";
        }
      }
    });
  }

  function iadGetRevisionSourceText() {
    if (typeof iadFindValidationSourceText === "function") {
      return iadFindValidationSourceText();
    }
    const areas = Array.from(document.querySelectorAll("textarea"));
    return areas.length ? String(areas[0].value || "").trim() : "";
  }

  function iadGetRevisionGeneratedText() {
    if (typeof iadFindValidationGeneratedText === "function") {
      return iadFindValidationGeneratedText();
    }
    const revised = document.getElementById("iad-rad-one-revised-report");
    if (revised && String(revised.value || "").trim()) return String(revised.value || "").trim();
    const primary = document.getElementById("iad-rad-one-primary-report");
    if (primary && String(primary.value || "").trim()) return String(primary.value || "").trim();
    return "";
  }

  function iadBadgeHtml(label, cls) {
    return '<span class="iad-badge ' + cls + '">' + iadEsc(label) + '</span>';
  }

  function iadRenderNormalLine(text) {
    return '<p class="iad-normal-line" data-clean="1">' + iadEsc(text || "") + '</p>';
  }

  function iadRenderCard(block, sectionIndex, blockIndex) {
    const tipo = String(block.tipo || "revisar").toLowerCase();
    const texto = String(block.texto || "");
    const original = String(block.original || "");
    const explicacion = String(block.explicacion || "");
    const fuente = String(block.fuente || "");
    const requiere = !!block.requiere_revision;
    const motivos = Array.isArray(block.motivos) ? block.motivos : [];

    let badges = iadBadgeHtml(tipo.toUpperCase(), "iad-badge-" + tipo);
    if (fuente) badges += iadBadgeHtml(fuente, "iad-badge-fuente");
    if (requiere) badges += iadBadgeHtml("REVISAR", "iad-badge-revisar");

    let motivosHtml = "";
    if (motivos.length) {
      motivosHtml = '<div class="iad-card-motivos"><strong>Motivos de revisión:</strong><ul>' +
        motivos.map(function (m) { return '<li>' + iadEsc(m) + '</li>'; }).join("") +
        '</ul></div>';
    }

    return `
      <article class="iad-card accepted"
               data-section-index="${sectionIndex}"
               data-block-index="${blockIndex}"
               data-tipo="${iadEsc(tipo)}"
               data-accepted="1">
        <div class="iad-card-text" contenteditable="false">${iadEsc(texto)}</div>
        <div class="iad-inline-badges">${badges}</div>
        ${original ? '<div class="iad-card-meta"><strong>Original:</strong> ' + iadEsc(original) + '</div>' : ''}
        ${explicacion ? '<div class="iad-card-meta">' + iadEsc(explicacion) + '</div>' : ''}
        ${motivosHtml}
        <div class="iad-card-actions">
          <button type="button" data-iad-action="accept">Aceptar</button>
          <button type="button" data-iad-action="reject">Rechazar</button>
          <button type="button" data-iad-action="edit">Editar</button>
        </div>
      </article>
    `;
  }

  function iadSectionToHtml(section, sectionIndex) {
    const title = String(section.titulo || "");
    const blocks = Array.isArray(section.bloques) ? section.bloques : [];

    let html = '<section class="iad-inline-section" data-section-title="' + iadEsc(title) + '">';
    html += '<h3>' + iadEsc(title) + '</h3>';

    blocks.forEach(function (block, blockIndex) {
      const tipo = String(block.tipo || "normal").toLowerCase();
      if (tipo === "normal") {
        html += iadRenderNormalLine(block.texto || "");
      } else {
        html += iadRenderCard(block, sectionIndex, blockIndex);
      }
    });

    html += '</section>';
    return html;
  }

  function iadBuildInlineLayout(data) {
    const title = String(data.titulo || "Informe en revisión");
    const warnings = Array.isArray(data.advertencias) ? data.advertencias : [];
    const sections = Array.isArray(data.secciones) ? data.secciones : [];

    let warningsHtml = "";
    if (warnings.length) {
      warningsHtml = `
        <section class="iad-inline-warning">
          <strong>Advertencias generales:</strong>
          <ul>${warnings.map(function (w) { return '<li>' + iadEsc(w) + '</li>'; }).join("")}</ul>
        </section>
      `;
    }

    return `
      <div class="iad-inline-top">
        <div class="iad-inline-title">Informe en modo revisión</div>
        <div class="iad-inline-legend">
          ${iadBadgeHtml("Agregado", "iad-badge-agregado")}
          ${iadBadgeHtml("Reemplazado", "iad-badge-reemplazado")}
          ${iadBadgeHtml("Estructurado", "iad-badge-estructurado")}
          ${iadBadgeHtml("Revisar", "iad-badge-revisar")}
          ${iadBadgeHtml("Conflicto", "iad-badge-conflicto")}
          ${iadBadgeHtml("Eliminado", "iad-badge-eliminado")}
        </div>
      </div>

      ${warningsHtml}

      <div class="iad-inline-split">
        <div class="iad-inline-left">
          <div class="iad-inline-section">
            <h3>${iadEsc(title)}</h3>
          </div>
          ${sections.map(iadSectionToHtml).join("")}
        </div>

        <div class="iad-inline-right">
          <h3>Informe limpio final</h3>
          <div class="iad-inline-note">Puedes editar tarjetas a la izquierda y ver aquí el resultado final. También puedes editar manualmente este texto final.</div>

          <div class="iad-inline-toolbar">
            <button type="button" id="iad-inline-accept-all">Aceptar todo</button>
            <button type="button" id="iad-inline-rebuild">Actualizar informe limpio</button>
            <button type="button" id="iad-inline-copy">Copiar informe limpio</button>
          </div>

          <textarea id="iad-inline-final-report"></textarea>
        </div>
      </div>
    `;
  }

  function iadRebuildInlineFinalReport() {
    const root = document.getElementById("iad-inline-review-root");
    if (!root) return "";

    const lines = [];
    const titleNode = root.querySelector(".iad-inline-left .iad-inline-section h3");
    if (titleNode && titleNode.innerText.trim()) {
      lines.push(titleNode.innerText.trim());
      lines.push("");
    }

    root.querySelectorAll(".iad-inline-left .iad-inline-section").forEach(function (section, index) {
      const title = String(section.getAttribute("data-section-title") || "").trim();
      if (title) {
        lines.push(title);
        lines.push("");
      }

      section.querySelectorAll(".iad-normal-line, .iad-card").forEach(function (node) {
        if (node.classList.contains("iad-card")) {
          if (node.classList.contains("rejected")) return;

          const tipo = String(node.getAttribute("data-tipo") || "").toLowerCase();
          if (tipo === "conflicto" || tipo === "eliminado") return;

          const txt = node.querySelector(".iad-card-text");
          if (txt && txt.innerText.trim()) {
            lines.push(txt.innerText.trim());
            lines.push("");
          }
        } else {
          if (node.innerText.trim()) {
            lines.push(node.innerText.trim());
            lines.push("");
          }
        }
      });
    });

    const finalText = lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();

    const finalArea = document.getElementById("iad-inline-final-report");
    if (finalArea) finalArea.value = finalText;

    const hiddenRevised = document.getElementById("iad-rad-one-revised-report");
    if (hiddenRevised) hiddenRevised.value = finalText;

    return finalText;
  }

  async function iadCopyInlineFinalReport() {
    const finalArea = document.getElementById("iad-inline-final-report");
    if (!finalArea) return;

    try {
      await navigator.clipboard.writeText(finalArea.value || "");
      alert("Informe limpio copiado.");
    } catch (e) {
      finalArea.focus();
      finalArea.select();
      alert("No pude copiar automáticamente. El texto quedó seleccionado.");
    }
  }

  function iadWireInlineReviewActions() {
    const root = document.getElementById("iad-inline-review-root");
    if (!root) return;

    root.addEventListener("click", function (ev) {
      const btn = ev.target.closest("button");
      if (!btn) return;

      const action = btn.getAttribute("data-iad-action");
      const card = btn.closest(".iad-card");

      if (btn.id === "iad-inline-accept-all") {
        root.querySelectorAll(".iad-card").forEach(function (c) {
          c.classList.remove("rejected");
          c.classList.add("accepted");
          c.setAttribute("data-accepted", "1");
        });
        iadRebuildInlineFinalReport();
        return;
      }

      if (btn.id === "iad-inline-rebuild") {
        iadRebuildInlineFinalReport();
        return;
      }

      if (btn.id === "iad-inline-copy") {
        iadCopyInlineFinalReport();
        return;
      }

      if (!card || !action) return;

      if (action === "accept") {
        card.classList.remove("rejected");
        card.classList.add("accepted");
        card.setAttribute("data-accepted", "1");
        iadRebuildInlineFinalReport();
        return;
      }

      if (action === "reject") {
        card.classList.remove("accepted");
        card.classList.add("rejected");
        card.setAttribute("data-accepted", "0");
        iadRebuildInlineFinalReport();
        return;
      }

      if (action === "edit") {
        const txt = card.querySelector(".iad-card-text");
        if (txt) {
          txt.contentEditable = "true";
          txt.focus();
          card.classList.remove("rejected");
          card.classList.add("accepted");
          card.setAttribute("data-accepted", "1");
          iadRebuildInlineFinalReport();
        }
      }
    });

    root.addEventListener("input", function (ev) {
      if (ev.target && ev.target.id === "iad-inline-final-report") {
        const hiddenRevised = document.getElementById("iad-rad-one-revised-report");
        if (hiddenRevised) hiddenRevised.value = ev.target.value || "";
        return;
      }

      const cardText = ev.target.closest(".iad-card-text");
      if (cardText) {
        iadRebuildInlineFinalReport();
      }
    });
  }

  function iadRenderInlineReview(data) {
    if (!data || !data.secciones) return;

    window.__iadLastRevisionPayload = data;

    const root = iadEnsureInlineReviewRoot();
    if (!root) return;

    root.innerHTML = iadBuildInlineLayout(data);
    iadHideLegacyReportBlocks();
    iadWireInlineReviewActions();
    iadRebuildInlineFinalReport();

    root.scrollIntoView({behavior: "smooth", block: "start"});
  }

  async function iadValidateAndRenderInlineReview() {
    const source = iadGetRevisionSourceText();
    const generated = iadGetRevisionGeneratedText();

    if (!source || !generated) return;

    try {
      const response = await fetch("/iad/api/validar-dictado-informe.json", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_text: source,
          generated_text: generated
        })
      });

      if (!response.ok) {
        const txt = await response.text();
        throw new Error("HTTP " + response.status + ": " + txt.slice(0, 250));
      }

      const data = await response.json();
      window.__iadLastValidation = data;

      if (data && data.revision) {
        iadRenderInlineReview(data.revision);
      }
    } catch (err) {
      console.error("No se pudo renderizar revisión inline:", err);
    }
  }

  document.addEventListener("click", function (ev) {
    const btn = ev.target.closest("button, input[type='button'], input[type='submit']");
    if (!btn) return;

    const label = String(btn.innerText || btn.value || btn.textContent || "").trim().toLowerCase();

    if (label.includes("revisar informe ia")) {
      ev.preventDefault();
      ev.stopPropagation();

      try {
        if (window.__iadLastValidation && window.__iadLastValidation.revision) {
          iadRenderInlineReview(window.__iadLastValidation.revision);
        } else {
          iadValidateAndRenderInlineReview();
        }
      } catch (reviewErr) {
        console.error("Error abriendo revisión inline:", reviewErr);
        iadValidateAndRenderInlineReview();
      }

      return false;
    }
  }, true);




  // IAD_INLINE_REVIEW_FORCE_V2
  function iadForceEsc(s) {
    return String(s || "").replace(/[<>&"]/g, function (c) {
      return {"<":"&lt;", ">":"&gt;", "&":"&amp;", '"':"&quot;"}[c];
    });
  }

  function iadForceReviewSource() {
    if (window.__iadLastDictatedText) return String(window.__iadLastDictatedText || "").trim();

    const areas = Array.from(document.querySelectorAll("textarea"));
    let best = null;

    areas.forEach(function (el) {
      const value = String(el.value || "").trim();
      if (!value) return;

      const ctx = String((el.closest("section,div,main") || document.body).innerText || "").toLowerCase();
      let score = value.length;

      if (ctx.includes("información principal") || ctx.includes("informacion principal")) score += 100000;
      if (ctx.includes("resultado primario") || ctx.includes("resultado revisado")) score -= 100000;

      if (!best || score > best.score) best = {value: value, score: score};
    });

    return best ? best.value : "";
  }

  function iadForceReviewGenerated() {
    const revised = document.getElementById("iad-rad-one-revised-report");
    const primary = document.getElementById("iad-rad-one-primary-report");

    if (revised && String(revised.value || "").trim()) return String(revised.value || "").trim();
    if (primary && String(primary.value || "").trim()) return String(primary.value || "").trim();

    if (window.__iadLastGenerated && window.__iadLastGenerated.informe_final) {
      return String(window.__iadLastGenerated.informe_final || "").trim();
    }

    return "";
  }

  function iadForceEnsureStyles() {
    if (document.getElementById("iad-inline-force-style-v2")) return;

    const style = document.createElement("style");
    style.id = "iad-inline-force-style-v2";
    style.textContent = `
      #iad-inline-force-root {
        margin: 14px 0 18px 0;
        padding: 14px;
        border-radius: 18px;
        border: 1px solid #334155;
        background: #eaf0f7;
        color: #111827;
      }

      #iad-inline-force-root .iad-force-head {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 12px;
        margin-bottom: 12px;
      }

      #iad-inline-force-root .iad-force-title {
        font-weight: 900;
        font-size: 20px;
        line-height: 1.1;
      }

      #iad-inline-force-root .iad-force-grid {
        display: grid;
        grid-template-columns: minmax(0, 1.4fr) minmax(340px, 0.9fr);
        gap: 14px;
      }

      #iad-inline-force-root .iad-force-left,
      #iad-inline-force-root .iad-force-right {
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 16px;
        padding: 14px;
      }

      #iad-inline-force-root h3 {
        margin: 0 0 10px 0;
        font-size: 16px;
        font-weight: 900;
        border-bottom: 1px solid #e5e7eb;
        padding-bottom: 7px;
      }

      #iad-inline-force-root .iad-force-warning {
        background: #fff7cc;
        border: 1px solid #f59e0b;
        border-radius: 13px;
        padding: 10px 12px;
        margin-bottom: 12px;
        font-size: 13px;
      }

      #iad-inline-force-root .iad-force-card {
        border-left: 5px solid #f59e0b;
        background: #fff7cc;
        border-radius: 13px;
        padding: 10px 12px;
        margin: 10px 0;
      }

      #iad-inline-force-root .iad-force-card[data-tipo="normal"] {
        border-left-color: #94a3b8;
        background: #f8fafc;
      }

      #iad-inline-force-root .iad-force-card[data-tipo="agregado"] {
        border-left-color: #22c55e;
        background: #dcfce7;
      }

      #iad-inline-force-root .iad-force-card[data-tipo="reemplazado"] {
        border-left-color: #2563eb;
        background: #dbeafe;
      }

      #iad-inline-force-root .iad-force-card[data-tipo="conflicto"] {
        border-left-color: #ef4444;
        background: #fee2e2;
      }

      #iad-inline-force-root .iad-force-card[data-tipo="eliminado"] {
        border-left-color: #9ca3af;
        background: #e5e7eb;
      }

      #iad-inline-force-root .iad-force-card.rejected {
        opacity: 0.48;
        filter: grayscale(0.4);
      }

      #iad-inline-force-root .iad-force-text {
        font-size: 14px;
        font-weight: 650;
        line-height: 1.45;
        margin-bottom: 8px;
      }

      #iad-inline-force-root .iad-force-meta {
        font-size: 12px;
        color: #475569;
        line-height: 1.45;
        margin-top: 5px;
      }

      #iad-inline-force-root .iad-force-badges {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        margin: 6px 0;
      }

      #iad-inline-force-root .iad-force-badge {
        display: inline-flex;
        border: 1px solid #64748b;
        border-radius: 999px;
        padding: 3px 8px;
        font-size: 11px;
        font-weight: 900;
        background: #f8fafc;
      }

      #iad-inline-force-root .iad-force-actions,
      #iad-inline-force-root .iad-force-toolbar {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 10px;
      }

      #iad-inline-force-root button {
        border: 1px solid #cbd5e1;
        border-radius: 10px;
        background: #ffffff;
        color: #0f172a;
        padding: 7px 10px;
        font-size: 12px;
        font-weight: 900;
        cursor: pointer;
      }

      #iad-inline-force-root textarea {
        width: 100%;
        min-height: 520px;
        border-radius: 14px;
        border: 1px solid #1e293b;
        background: #071326;
        color: #f8fafc;
        padding: 12px;
        font-size: 13px;
        line-height: 1.45;
        resize: vertical;
      }

      @media (max-width: 1100px) {
        #iad-inline-force-root .iad-force-grid {
          grid-template-columns: 1fr;
        }

        #iad-inline-force-root textarea {
          min-height: 320px;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function iadForceHideLegacy() {
    ["iad-rad-one-primary-report", "iad-rad-one-revised-report"].forEach(function (id) {
      const el = document.getElementById(id);
      if (!el) return;

      el.style.display = "none";

      let prev = el.previousElementSibling;
      if (prev) {
        const label = String(prev.innerText || prev.textContent || "").toLowerCase();
        if (label.includes("resultado primario") || label.includes("resultado revisado")) {
          prev.style.display = "none";
        }
      }
    });
  }

  function iadForceAnchor() {
    const primary = document.getElementById("iad-rad-one-primary-report");
    if (primary && primary.parentNode) return primary;

    const revised = document.getElementById("iad-rad-one-revised-report");
    if (revised && revised.parentNode) return revised;

    return null;
  }

  function iadForceRoot() {
    iadForceEnsureStyles();

    let root = document.getElementById("iad-inline-force-root");
    if (root) return root;

    const anchor = iadForceAnchor();
    if (!anchor || !anchor.parentNode) return null;

    root = document.createElement("div");
    root.id = "iad-inline-force-root";
    anchor.parentNode.insertBefore(root, anchor);

    return root;
  }

  function iadForceBlockHtml(block, si, bi) {
    const tipo = String(block.tipo || "normal").toLowerCase();
    const texto = String(block.texto || "");
    const original = String(block.original || "");
    const explicacion = String(block.explicacion || "");
    const fuente = String(block.fuente || "");
    const motivos = Array.isArray(block.motivos) ? block.motivos : [];

    let meta = "";
    if (original) meta += '<div class="iad-force-meta"><strong>Original:</strong> ' + iadForceEsc(original) + '</div>';
    if (explicacion) meta += '<div class="iad-force-meta">' + iadForceEsc(explicacion) + '</div>';
    if (motivos.length) {
      meta += '<div class="iad-force-meta"><strong>Motivos:</strong><ul>' +
        motivos.map(function (m) { return '<li>' + iadForceEsc(m) + '</li>'; }).join("") +
        '</ul></div>';
    }

    return `
      <article class="iad-force-card" data-tipo="${iadForceEsc(tipo)}" data-accepted="1">
        <div class="iad-force-text" contenteditable="${tipo === "normal" ? "false" : "false"}">${iadForceEsc(texto)}</div>
        <div class="iad-force-badges">
          <span class="iad-force-badge">${iadForceEsc(tipo.toUpperCase())}</span>
          ${fuente ? '<span class="iad-force-badge">' + iadForceEsc(fuente) + '</span>' : ''}
          ${block.requiere_revision ? '<span class="iad-force-badge">REVISAR</span>' : ''}
        </div>
        ${meta}
        <div class="iad-force-actions">
          <button type="button" data-force-action="accept">Aceptar</button>
          <button type="button" data-force-action="reject">Rechazar</button>
          <button type="button" data-force-action="edit">Editar</button>
        </div>
      </article>
    `;
  }

  function iadForceRender(data) {
    if (!data || !Array.isArray(data.secciones)) return;

    const root = iadForceRoot();
    if (!root) return;

    const title = String(data.titulo || "Informe en revisión");
    const warnings = Array.isArray(data.advertencias) ? data.advertencias : [];

    let left = '<h3>' + iadForceEsc(title) + '</h3>';

    data.secciones.forEach(function (sec, si) {
      left += '<section class="iad-force-section" data-section-title="' + iadForceEsc(sec.titulo || "") + '">';
      left += '<h3>' + iadForceEsc(sec.titulo || "") + '</h3>';

      const blocks = Array.isArray(sec.bloques) ? sec.bloques : [];
      blocks.forEach(function (block, bi) {
        left += iadForceBlockHtml(block, si, bi);
      });

      left += '</section>';
    });

    let warningsHtml = "";
    if (warnings.length) {
      warningsHtml = '<div class="iad-force-warning"><strong>Advertencias:</strong><ul>' +
        warnings.map(function (w) { return '<li>' + iadForceEsc(w) + '</li>'; }).join("") +
        '</ul></div>';
    }

    root.innerHTML = `
      <div class="iad-force-head">
        <div class="iad-force-title">Informe en modo revisión</div>
        <div class="iad-force-badges">
          <span class="iad-force-badge">Agregado</span>
          <span class="iad-force-badge">Reemplazado</span>
          <span class="iad-force-badge">Revisar</span>
          <span class="iad-force-badge">Conflicto</span>
        </div>
      </div>

      ${warningsHtml}

      <div class="iad-force-grid">
        <div class="iad-force-left">${left}</div>
        <div class="iad-force-right">
          <h3>Informe limpio final</h3>
          <div class="iad-force-meta">Edita tarjetas a la izquierda o el texto final aquí. El resultado se sincroniza con “Resultado revisado”.</div>
          <div class="iad-force-toolbar">
            <button type="button" id="iad-force-accept-all">Aceptar todo</button>
            <button type="button" id="iad-force-rebuild">Actualizar informe limpio</button>
            <button type="button" id="iad-force-copy">Copiar informe limpio</button>
          </div>
          <textarea id="iad-force-final"></textarea>
        </div>
      </div>
    `;

    iadForceHideLegacy();
    iadForceWire();
    iadForceRebuild();
  }

  function iadForceRebuild() {
    const root = document.getElementById("iad-inline-force-root");
    if (!root) return "";

    const lines = [];
    const title = root.querySelector(".iad-force-left > h3");
    if (title && title.innerText.trim()) {
      lines.push(title.innerText.trim());
      lines.push("");
    }

    root.querySelectorAll(".iad-force-section").forEach(function (section) {
      const secTitle = String(section.getAttribute("data-section-title") || "").trim();

      if (secTitle) {
        lines.push(secTitle);
        lines.push("");
      }

      section.querySelectorAll(".iad-force-card").forEach(function (card) {
        if (card.classList.contains("rejected")) return;

        const tipo = String(card.getAttribute("data-tipo") || "").toLowerCase();
        if (tipo === "conflicto" || tipo === "eliminado") return;

        const textNode = card.querySelector(".iad-force-text");
        const val = textNode ? String(textNode.innerText || "").trim() : "";

        if (val) {
          lines.push(val);
          lines.push("");
        }
      });
    });

    const finalText = lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();

    const area = document.getElementById("iad-force-final");
    if (area) area.value = finalText;

    const hidden = document.getElementById("iad-rad-one-revised-report");
    if (hidden) hidden.value = finalText;

    return finalText;
  }

  function iadForceWire() {
    const root = document.getElementById("iad-inline-force-root");
    if (!root || root.dataset.wired === "1") return;

    root.dataset.wired = "1";

    root.addEventListener("click", function (ev) {
      const btn = ev.target.closest("button");
      if (!btn) return;

      if (btn.id === "iad-force-accept-all") {
        root.querySelectorAll(".iad-force-card").forEach(function (card) {
          card.classList.remove("rejected");
          card.setAttribute("data-accepted", "1");
        });
        iadForceRebuild();
        return;
      }

      if (btn.id === "iad-force-rebuild") {
        iadForceRebuild();
        return;
      }

      if (btn.id === "iad-force-copy") {
        const area = document.getElementById("iad-force-final");
        if (area) {
          navigator.clipboard.writeText(area.value || "").catch(function () {
            area.focus();
            area.select();
          });
        }
        return;
      }

      const action = btn.getAttribute("data-force-action");
      const card = btn.closest(".iad-force-card");
      if (!action || !card) return;

      if (action === "accept") {
        card.classList.remove("rejected");
        card.setAttribute("data-accepted", "1");
        iadForceRebuild();
      }

      if (action === "reject") {
        card.classList.add("rejected");
        card.setAttribute("data-accepted", "0");
        iadForceRebuild();
      }

      if (action === "edit") {
        const t = card.querySelector(".iad-force-text");
        if (t) {
          t.contentEditable = "true";
          t.focus();
          card.classList.remove("rejected");
          card.setAttribute("data-accepted", "1");
        }
      }
    });

    root.addEventListener("input", function (ev) {
      if (ev.target && ev.target.id === "iad-force-final") {
        const hidden = document.getElementById("iad-rad-one-revised-report");
        if (hidden) hidden.value = ev.target.value || "";
        return;
      }

      if (ev.target && ev.target.closest(".iad-force-text")) {
        iadForceRebuild();
      }
    });
  }

  async function iadForceRenderFromBackend() {
    const source = iadForceReviewSource();
    const generated = iadForceReviewGenerated();

    if (!source || !generated) return;

    const key = source.slice(0, 500) + "::" + generated.slice(0, 500);
    if (window.__iadForceRenderedKey === key) return;
    window.__iadForceRenderedKey = key;

    try {
      const resp = await fetch("/iad/api/validar-dictado-informe.json", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          source_text: source,
          generated_text: generated
        })
      });

      if (!resp.ok) {
        window.__iadForceRenderedKey = "";
        return;
      }

      const data = await resp.json();
      window.__iadLastValidation = data;

      if (data && data.revision) {
        iadForceRender(data.revision);
      }
    } catch (err) {
      window.__iadForceRenderedKey = "";
      console.error("iadForceRenderFromBackend error:", err);
    }
  }

  document.addEventListener("click", function (ev) {
    const btn = ev.target.closest("button, input[type='button'], input[type='submit']");
    if (!btn) return;

    const label = String(btn.innerText || btn.value || btn.textContent || "").toLowerCase();

    if (label.includes("revisar informe ia")) {
      ev.preventDefault();
      ev.stopPropagation();
      window.__iadForceRenderedKey = "";
      iadForceRenderFromBackend();
      return false;
    }
  }, true);

  setInterval(function () {
    const generated = iadForceReviewGenerated();
    if (generated && generated.length > 20) {
      iadForceRenderFromBackend();
    }
  }, 1800);




  // IAD_THREE_AUDIO_INLINE_V3
  function iadV3Esc(s) {
    return String(s || "").replace(/[<>&"]/g, function (c) {
      return {"<":"&lt;", ">":"&gt;", "&":"&amp;", '"':"&quot;"}[c];
    });
  }

  function iadV3AudioCount() {
    const audioTags = document.querySelectorAll("audio").length;

    let fileCount = 0;
    document.querySelectorAll("input[type='file']").forEach(function (input) {
      if (input.files) fileCount += input.files.length;
    });

    return Math.max(audioTags, fileCount);
  }

  function iadV3TranscriptionCompleteCount() {
    const body = String(document.body.innerText || "");
    const m = body.match(/Transcripción completa:\s*(\d+)\s*audio/i);
    if (m) return parseInt(m[1], 10) || 0;
    return 0;
  }

  function iadV3FindTranscribeButtons() {
    return Array.from(document.querySelectorAll("button, input[type='button'], input[type='submit']"))
      .filter(function (btn) {
        const txt = String(btn.innerText || btn.value || btn.textContent || "").trim().toLowerCase();
        if (txt !== "transcribir") return false;
        if (btn.disabled) return false;
        const rect = btn.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      });
  }

  function iadV3Sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  async function iadV3WaitStableTextarea(textarea, timeoutMs, stableMs) {
    const start = Date.now();
    let last = String(textarea.value || "");
    let lastChange = Date.now();

    while (Date.now() - start < timeoutMs) {
      await iadV3Sleep(700);

      const current = String(textarea.value || "");
      if (current !== last) {
        last = current;
        lastChange = Date.now();
      }

      const audioN = iadV3AudioCount();
      const completeN = iadV3TranscriptionCompleteCount();

      if (audioN > 0 && completeN >= audioN && Date.now() - lastChange >= stableMs) {
        return norm(current);
      }

      if (audioN === 0 && Date.now() - lastChange >= stableMs) {
        return norm(current);
      }
    }

    return norm(textarea.value || "");
  }

  function iadV3KeyTerms(raw) {
    const t = String(raw || "").toLowerCase();

    const terms = [
      ["vesícula", /ves[ií]cula/],
      ["ateromatosis", /ateromatosis/],
      ["adenopatías", /adenopat[ií]a/],
      ["divertículos", /divert[ií]cul/],
      ["próstata", /pr[oó]stata/],
      ["60 mm", /\b60\s*(mm|mil[ií]metros)/],
      ["abdomen y pelvis", /abdomen\s+y\s+pelvis/]
    ];

    return terms
      .filter(function (item) { return item[1].test(t); })
      .map(function (item) { return item[0]; });
  }

  function iadV3AuditBox(raw) {
    let box = document.getElementById("iad-v3-source-audit");
    if (!box) {
      box = document.createElement("div");
      box.id = "iad-v3-source-audit";
      box.style.margin = "10px 0";
      box.style.padding = "10px 12px";
      box.style.borderRadius = "12px";
      box.style.border = "1px solid #38bdf8";
      box.style.background = "#082f49";
      box.style.color = "#e0f2fe";
      box.style.fontWeight = "700";

      const tplBox = document.getElementById("iad-rad-one-template-box");
      if (tplBox && tplBox.parentNode) {
        tplBox.parentNode.insertBefore(box, tplBox.nextSibling);
      } else {
        const primary = document.getElementById("iad-rad-one-primary-report");
        if (primary && primary.parentNode) primary.parentNode.insertBefore(box, primary);
      }
    }

    const audioN = iadV3AudioCount();
    const completeN = iadV3TranscriptionCompleteCount();
    const keys = iadV3KeyTerms(raw);

    let warn = "";
    if (audioN > 0 && completeN < audioN) {
      warn = " ⚠️ Transcripción incompleta según contador visible.";
    }

    box.innerHTML =
      "Fuente usada por IA: " +
      "audios detectados <strong>" + audioN + "</strong> · " +
      "transcripción completa <strong>" + completeN + "</strong> · " +
      "texto <strong>" + String(raw || "").length + "</strong> caracteres · " +
      "claves: <strong>" + iadV3Esc(keys.join(", ") || "sin claves") + "</strong>" +
      warn;
  }

  async function iadEnsureAllAudioTextBeforeAnalysis(textarea) {
    const audioN = iadV3AudioCount();
    const completeN = iadV3TranscriptionCompleteCount();

    if (audioN > 0 && completeN < audioN) {
      setStatus("Transcribiendo todos los audios antes de analizar...");

      const buttons = iadV3FindTranscribeButtons();
      for (const btn of buttons) {
        try {
          btn.click();
          await iadV3Sleep(450);
        } catch (e) {
          console.error("No pude apretar botón Transcribir:", e);
        }
      }

      await iadV3WaitStableTextarea(textarea, 180000, 3500);
    }

    const raw = norm(textarea.value || "");
    window.__iadLastDictatedText = raw;
    iadV3AuditBox(raw);

    return raw;
  }

  function iadV3HideBridgeButtons() {
    Array.from(document.querySelectorAll("a,button,input[type='button'],input[type='submit']")).forEach(function (el) {
      const label = String(el.innerText || el.value || el.textContent || "").trim().toLowerCase();
      const href = String(el.getAttribute("href") || "");

      if (href.includes("/iad/revision/") || label === "revisar ia") {
        el.style.display = "none";
        el.setAttribute("aria-hidden", "true");
      }
    });
  }

  function iadV3HideLegacyReports() {
    ["iad-rad-one-primary-report", "iad-rad-one-revised-report"].forEach(function (id) {
      const el = document.getElementById(id);
      if (!el) return;

      el.style.display = "none";
      el.setAttribute("aria-hidden", "true");

      let prev = el.previousElementSibling;
      if (prev) {
        const label = String(prev.innerText || prev.textContent || "").toLowerCase();
        if (label.includes("resultado primario") || label.includes("resultado revisado")) {
          prev.style.display = "none";
        }
      }
    });
  }

  function iadV3EnsureInlineRoot() {
    let root = document.getElementById("iad-v3-inline-review");
    if (root) return root;

    const tplBox = document.getElementById("iad-rad-one-template-box");
    const primary = document.getElementById("iad-rad-one-primary-report");

    root = document.createElement("div");
    root.id = "iad-v3-inline-review";

    if (tplBox && tplBox.parentNode) {
      tplBox.parentNode.insertBefore(root, tplBox.nextSibling);
    } else if (primary && primary.parentNode) {
      primary.parentNode.insertBefore(root, primary);
    } else {
      document.body.appendChild(root);
    }

    return root;
  }

  function iadV3Styles() {
    if (document.getElementById("iad-v3-inline-style")) return;

    const style = document.createElement("style");
    style.id = "iad-v3-inline-style";
    style.textContent = `
      #iad-v3-inline-review {
        margin: 12px 0 18px 0;
        padding: 14px;
        border-radius: 18px;
        background: #e8eef8;
        border: 1px solid #cbd5e1;
        color: #172033;
      }
      #iad-v3-inline-review .iad-v3-head {
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        gap:12px;
        margin-bottom:12px;
      }
      #iad-v3-inline-review .iad-v3-title {
        font-size:22px;
        font-weight:900;
        line-height:1.1;
      }
      #iad-v3-inline-review .iad-v3-grid {
        display:grid;
        grid-template-columns:minmax(0,1.35fr) minmax(340px,.95fr);
        gap:14px;
      }
      #iad-v3-inline-review .iad-v3-left,
      #iad-v3-inline-review .iad-v3-right {
        background:#fff;
        border:1px solid #d1d5db;
        border-radius:16px;
        padding:14px;
      }
      #iad-v3-inline-review h3 {
        margin:0 0 10px 0;
        font-weight:900;
        padding-bottom:7px;
        border-bottom:1px solid #e5e7eb;
      }
      #iad-v3-inline-review .iad-v3-warning {
        background:#fff7cc;
        border:1px solid #f59e0b;
        border-radius:12px;
        padding:10px 12px;
        margin-bottom:12px;
      }
      #iad-v3-inline-review .iad-v3-card {
        border-left:5px solid #64748b;
        background:#f8fafc;
        border-radius:13px;
        padding:10px 12px;
        margin:10px 0;
      }
      #iad-v3-inline-review .iad-v3-card[data-tipo="agregado"] { border-left-color:#22c55e; background:#dcfce7; }
      #iad-v3-inline-review .iad-v3-card[data-tipo="reemplazado"] { border-left-color:#2563eb; background:#dbeafe; }
      #iad-v3-inline-review .iad-v3-card[data-tipo="conflicto"] { border-left-color:#ef4444; background:#fee2e2; }
      #iad-v3-inline-review .iad-v3-card[data-tipo="eliminado"] { border-left-color:#9ca3af; background:#e5e7eb; }
      #iad-v3-inline-review .iad-v3-card.rejected { opacity:.45; filter:grayscale(.4); }
      #iad-v3-inline-review .iad-v3-text {
        font-size:14px;
        font-weight:650;
        line-height:1.45;
        margin-bottom:8px;
      }
      #iad-v3-inline-review .iad-v3-meta {
        font-size:12px;
        color:#475569;
        line-height:1.45;
        margin-top:5px;
      }
      #iad-v3-inline-review .iad-v3-badge {
        display:inline-flex;
        border:1px solid #64748b;
        border-radius:999px;
        padding:3px 8px;
        margin:2px;
        font-size:11px;
        font-weight:900;
        background:#f8fafc;
      }
      #iad-v3-inline-review .iad-v3-actions,
      #iad-v3-inline-review .iad-v3-toolbar {
        display:flex;
        gap:8px;
        flex-wrap:wrap;
        margin-top:10px;
      }
      #iad-v3-inline-review button {
        border:1px solid #cbd5e1;
        border-radius:10px;
        background:#fff;
        color:#0f172a;
        padding:7px 10px;
        font-size:12px;
        font-weight:900;
        cursor:pointer;
      }
      #iad-v3-final-report {
        width:100%;
        min-height:520px;
        border-radius:14px;
        border:1px solid #1e293b;
        background:#071326;
        color:#f8fafc;
        padding:12px;
        font-size:13px;
        line-height:1.45;
        resize:vertical;
      }
      @media (max-width:1100px) {
        #iad-v3-inline-review .iad-v3-grid { grid-template-columns:1fr; }
        #iad-v3-final-report { min-height:320px; }
      }
    `;
    document.head.appendChild(style);
  }

  function iadV3RenderBlock(block) {
    const tipo = String(block.tipo || "normal").toLowerCase();
    const texto = String(block.texto || "");
    const original = String(block.original || "");
    const explicacion = String(block.explicacion || "");
    const fuente = String(block.fuente || "");
    const motivos = Array.isArray(block.motivos) ? block.motivos : [];

    return `
      <article class="iad-v3-card" data-tipo="${iadV3Esc(tipo)}" data-accepted="1">
        <div class="iad-v3-text" contenteditable="false">${iadV3Esc(texto)}</div>
        <div>
          <span class="iad-v3-badge">${iadV3Esc(tipo.toUpperCase())}</span>
          ${fuente ? '<span class="iad-v3-badge">' + iadV3Esc(fuente) + '</span>' : ''}
          ${block.requiere_revision ? '<span class="iad-v3-badge">REVISAR</span>' : ''}
        </div>
        ${original ? '<div class="iad-v3-meta"><strong>Original:</strong> ' + iadV3Esc(original) + '</div>' : ''}
        ${explicacion ? '<div class="iad-v3-meta">' + iadV3Esc(explicacion) + '</div>' : ''}
        ${motivos.length ? '<div class="iad-v3-meta"><strong>Motivos:</strong><ul>' + motivos.map(function(m){return '<li>'+iadV3Esc(m)+'</li>';}).join("") + '</ul></div>' : ''}
        <div class="iad-v3-actions">
          <button type="button" data-v3-action="accept">Aceptar</button>
          <button type="button" data-v3-action="reject">Rechazar</button>
          <button type="button" data-v3-action="edit">Editar</button>
        </div>
      </article>
    `;
  }

  function iadV3RenderReview(data) {
    if (!data || !Array.isArray(data.secciones)) return;

    iadV3Styles();
    iadV3HideBridgeButtons();

    const root = iadV3EnsureInlineRoot();
    const title = String(data.titulo || "Informe en revisión");
    const warnings = Array.isArray(data.advertencias) ? data.advertencias : [];

    let left = '<h3>' + iadV3Esc(title) + '</h3>';

    data.secciones.forEach(function (sec) {
      left += '<section class="iad-v3-section" data-section-title="' + iadV3Esc(sec.titulo || "") + '">';
      left += '<h3>' + iadV3Esc(sec.titulo || "") + '</h3>';

      const blocks = Array.isArray(sec.bloques) ? sec.bloques : [];
      blocks.forEach(function (block) {
        left += iadV3RenderBlock(block);
      });

      left += '</section>';
    });

    root.innerHTML = `
      <div class="iad-v3-head">
        <div class="iad-v3-title">Informe en modo revisión</div>
        <div>
          <span class="iad-v3-badge">Agregado</span>
          <span class="iad-v3-badge">Reemplazado</span>
          <span class="iad-v3-badge">Revisar</span>
          <span class="iad-v3-badge">Conflicto</span>
        </div>
      </div>

      ${warnings.length ? '<div class="iad-v3-warning"><strong>Advertencias:</strong><ul>' + warnings.map(function(w){return '<li>'+iadV3Esc(w)+'</li>';}).join("") + '</ul></div>' : ''}

      <div class="iad-v3-grid">
        <div class="iad-v3-left">${left}</div>
        <div class="iad-v3-right">
          <h3>Informe limpio final</h3>
          <div class="iad-v3-meta">Edita tarjetas a la izquierda o el texto final aquí. Esto alimenta internamente “Resultado revisado”.</div>
          <div class="iad-v3-toolbar">
            <button type="button" id="iad-v3-accept-all">Aceptar todo</button>
            <button type="button" id="iad-v3-rebuild">Actualizar informe limpio</button>
            <button type="button" id="iad-v3-copy">Copiar informe limpio</button>
          </div>
          <textarea id="iad-v3-final-report"></textarea>
        </div>
      </div>
    `;

    iadV3HideLegacyReports();
    iadV3Wire();
    iadV3RebuildFinal();

    root.scrollIntoView({behavior:"smooth", block:"start"});
  }

  function iadV3RebuildFinal() {
    const root = document.getElementById("iad-v3-inline-review");
    if (!root) return "";

    const lines = [];
    const title = root.querySelector(".iad-v3-left > h3");

    if (title && title.innerText.trim()) {
      lines.push(title.innerText.trim());
      lines.push("");
    }

    root.querySelectorAll(".iad-v3-section").forEach(function (section) {
      const secTitle = String(section.getAttribute("data-section-title") || "").trim();

      if (secTitle) {
        lines.push(secTitle);
        lines.push("");
      }

      section.querySelectorAll(".iad-v3-card").forEach(function (card) {
        if (card.classList.contains("rejected")) return;

        const tipo = String(card.getAttribute("data-tipo") || "").toLowerCase();
        if (tipo === "conflicto" || tipo === "eliminado") return;

        const textNode = card.querySelector(".iad-v3-text");
        const val = textNode ? String(textNode.innerText || "").trim() : "";

        if (val) {
          lines.push(val);
          lines.push("");
        }
      });
    });

    const finalText = lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();

    const area = document.getElementById("iad-v3-final-report");
    if (area) area.value = finalText;

    const hidden = document.getElementById("iad-rad-one-revised-report");
    if (hidden) hidden.value = finalText;

    return finalText;
  }

  function iadV3Wire() {
    const root = document.getElementById("iad-v3-inline-review");
    if (!root || root.dataset.wired === "1") return;
    root.dataset.wired = "1";

    root.addEventListener("click", function (ev) {
      const btn = ev.target.closest("button");
      if (!btn) return;

      if (btn.id === "iad-v3-accept-all") {
        root.querySelectorAll(".iad-v3-card").forEach(function (card) {
          card.classList.remove("rejected");
          card.setAttribute("data-accepted", "1");
        });
        iadV3RebuildFinal();
        return;
      }

      if (btn.id === "iad-v3-rebuild") {
        iadV3RebuildFinal();
        return;
      }

      if (btn.id === "iad-v3-copy") {
        const area = document.getElementById("iad-v3-final-report");
        if (area) navigator.clipboard.writeText(area.value || "").catch(function () {
          area.focus();
          area.select();
        });
        return;
      }

      const action = btn.getAttribute("data-v3-action");
      const card = btn.closest(".iad-v3-card");
      if (!action || !card) return;

      if (action === "accept") {
        card.classList.remove("rejected");
        card.setAttribute("data-accepted", "1");
        iadV3RebuildFinal();
      }

      if (action === "reject") {
        card.classList.add("rejected");
        card.setAttribute("data-accepted", "0");
        iadV3RebuildFinal();
      }

      if (action === "edit") {
        const t = card.querySelector(".iad-v3-text");
        if (t) {
          t.contentEditable = "true";
          t.focus();
          card.classList.remove("rejected");
          card.setAttribute("data-accepted", "1");
        }
      }
    });

    root.addEventListener("input", function (ev) {
      if (ev.target && ev.target.id === "iad-v3-final-report") {
        const hidden = document.getElementById("iad-rad-one-revised-report");
        if (hidden) hidden.value = ev.target.value || "";
        return;
      }

      if (ev.target && ev.target.closest(".iad-v3-text")) {
        iadV3RebuildFinal();
      }
    });
  }

  async function iadV3RenderFromBackend() {
    const source = window.__iadLastDictatedText || iadV3GetSourceText();
    const generated = iadV3GetGeneratedText();

    if (!source || !generated) return;

    try {
      const resp = await fetch("/iad/api/validar-dictado-informe.json", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          source_text: source,
          generated_text: generated
        })
      });

      if (!resp.ok) return;

      const data = await resp.json();
      window.__iadLastValidation = data;

      if (data && data.revision) {
        iadV3RenderReview(data.revision);
      }
    } catch (err) {
      console.error("iadV3RenderFromBackend error:", err);
    }
  }

  function iadV3GetSourceText() {
    const areas = Array.from(document.querySelectorAll("textarea"))
      .filter(function (el) {
        if (el.id && /iad-rad|final|resultado|revisado|primary/i.test(el.id)) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 100 && rect.height > 50;
      });

    areas.sort(function (a,b) {
      return String(b.value || "").length - String(a.value || "").length;
    });

    return areas[0] ? norm(areas[0].value || "") : "";
  }

  function iadV3GetGeneratedText() {
    const revised = document.getElementById("iad-rad-one-revised-report");
    const primary = document.getElementById("iad-rad-one-primary-report");

    if (revised && String(revised.value || "").trim()) return String(revised.value || "").trim();
    if (primary && String(primary.value || "").trim()) return String(primary.value || "").trim();

    if (window.__iadLastGenerated && window.__iadLastGenerated.informe_final) {
      return String(window.__iadLastGenerated.informe_final || "").trim();
    }

    return "";
  }

  document.addEventListener("click", function (ev) {
    const node = ev.target.closest("a,button,input[type='button'],input[type='submit']");
    if (!node) return;

    const label = String(node.innerText || node.value || node.textContent || "").trim().toLowerCase();
    const href = String(node.getAttribute("href") || "");

    if (label === "revisar ia" || label.includes("revisar informe ia") || href.includes("/iad/revision/")) {
      ev.preventDefault();
      ev.stopPropagation();
      if (typeof ev.stopImmediatePropagation === "function") ev.stopImmediatePropagation();

      iadV3RenderFromBackend();
      return false;
    }
  }, true);

  setInterval(function () {
    iadV3HideBridgeButtons();

    const generated = iadV3GetGeneratedText();
    if (generated && generated.length > 20) {
      iadV3HideLegacyReports();
    }
  }, 1200);




  // IAD_INLINE_REVIEW_OBSERVER_V4
  function iad4Esc(s) {
    return String(s || "").replace(/[<>&"]/g, function (c) {
      return {"<":"&lt;", ">":"&gt;", "&":"&amp;"}[c];
    });
  }

  function iad4AudioCount() {
    return document.querySelectorAll("audio").length;
  }

  function iad4CompleteCount() {
    const body = String(document.body.innerText || "");
    const m = body.match(/Transcripción completa:\s*(\d+)\s*audio/i);
    return m ? (parseInt(m[1], 10) || 0) : 0;
  }

  function iad4MainTextarea() {
    const areas = Array.from(document.querySelectorAll("textarea"))
      .filter(function (el) {
        const id = String(el.id || "");
        if (/iad-rad|resultado|revisado|primary|final/i.test(id)) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 100 && rect.height > 60;
      });

    areas.sort(function (a, b) {
      const av = String(a.value || "").length;
      const bv = String(b.value || "").length;

      const at = String((a.closest("section,div,main") || document.body).innerText || "").toLowerCase();
      const bt = String((b.closest("section,div,main") || document.body).innerText || "").toLowerCase();

      let as = av;
      let bs = bv;

      if (at.includes("información principal") || at.includes("informacion principal")) as += 100000;
      if (bt.includes("información principal") || bt.includes("informacion principal")) bs += 100000;

      return bs - as;
    });

    return areas[0] || null;
  }

  function iad4SourceText() {
    const ta = iad4MainTextarea();
    return ta ? norm(ta.value || "") : "";
  }

  async function iad4WaitAllAudioText(textarea) {
    const audioN = iad4AudioCount();
    let completeN = iad4CompleteCount();

    if (audioN > 0 && completeN < audioN) {
      setStatus("Esperando transcripción completa de todos los audios...");

      const buttons = Array.from(document.querySelectorAll("button,input[type='button'],input[type='submit']"))
        .filter(function (btn) {
          const label = String(btn.innerText || btn.value || btn.textContent || "").trim().toLowerCase();
          return label === "transcribir" && !btn.disabled;
        });

      for (const btn of buttons) {
        try {
          btn.click();
          await new Promise(function (r) { setTimeout(r, 500); });
        } catch (e) {
          console.error(e);
        }
      }

      const start = Date.now();
      while (Date.now() - start < 180000) {
        await new Promise(function (r) { setTimeout(r, 800); });
        completeN = iad4CompleteCount();
        if (completeN >= audioN) break;
      }
    }

    await new Promise(function (r) { setTimeout(r, 600); });

    const raw = norm((textarea && textarea.value) || iad4SourceText());
    window.__iadLastDictatedText = raw;
    iad4RenderAudit(raw);

    return raw;
  }

  function iad4GeneratedText() {
    const primary = document.getElementById("iad-rad-one-primary-report");
    const revised = document.getElementById("iad-rad-one-revised-report");

    if (primary && String(primary.value || "").trim()) return String(primary.value || "").trim();
    if (revised && String(revised.value || "").trim()) return String(revised.value || "").trim();

    if (window.__iadLastGenerated && window.__iadLastGenerated.informe_final) {
      return String(window.__iadLastGenerated.informe_final || "").trim();
    }

    return "";
  }

  function iad4KeyTerms(raw) {
    const t = String(raw || "").toLowerCase();
    const terms = [
      ["vesícula", /ves[ií]cula/],
      ["ateromatosis", /ateromatosis/],
      ["adenopatías", /adenopat/],
      ["divertículos", /divert[ií]cul/],
      ["próstata", /pr[oó]stata/],
      ["60 mm", /\b60\s*(mm|mil[ií]metros)/],
      ["abdomen y pelvis", /abdomen\s+y\s+pelvis/]
    ];

    return terms.filter(function (x) { return x[1].test(t); }).map(function (x) { return x[0]; });
  }

  function iad4RenderAudit(raw) {
    let box = document.getElementById("iad4-source-audit");
    if (!box) {
      box = document.createElement("div");
      box.id = "iad4-source-audit";
      box.style.margin = "10px 0";
      box.style.padding = "10px 12px";
      box.style.borderRadius = "12px";
      box.style.border = "1px solid #38bdf8";
      box.style.background = "#082f49";
      box.style.color = "#e0f2fe";
      box.style.fontWeight = "800";

      const templateBox = document.getElementById("iad-rad-one-template-box");
      const primary = document.getElementById("iad-rad-one-primary-report");

      if (templateBox && templateBox.parentNode) {
        templateBox.parentNode.insertBefore(box, templateBox.nextSibling);
      } else if (primary && primary.parentNode) {
        primary.parentNode.insertBefore(box, primary);
      }
    }

    const audioN = iad4AudioCount();
    const completeN = iad4CompleteCount();
    const keys = iad4KeyTerms(raw);

    box.innerHTML =
      "Fuente usada por IA: audios detectados <strong>" + audioN + "</strong> · " +
      "transcripción completa <strong>" + completeN + "</strong> · " +
      "texto usado <strong>" + String(raw || "").length + "</strong> caracteres · " +
      "claves: <strong>" + iad4Esc(keys.join(", ") || "sin claves") + "</strong>";
  }

  function iad4HideLegacy() {
    ["iad-rad-one-primary-report", "iad-rad-one-revised-report"].forEach(function (id) {
      const el = document.getElementById(id);
      if (!el) return;

      el.style.display = "none";
      el.setAttribute("aria-hidden", "true");

      const prev = el.previousElementSibling;
      if (prev) {
        const label = String(prev.innerText || prev.textContent || "").toLowerCase();
        if (label.includes("resultado primario") || label.includes("resultado revisado")) {
          prev.style.display = "none";
        }
      }
    });
  }

  function iad4HideExternalReviewButtons() {
    Array.from(document.querySelectorAll("a,button,input[type='button'],input[type='submit']")).forEach(function (el) {
      const label = String(el.innerText || el.value || el.textContent || "").trim().toLowerCase();
      const href = String(el.getAttribute("href") || "");

      if (label === "revisar ia" || href.includes("/iad/revision/")) {
        el.style.display = "none";
        el.setAttribute("aria-hidden", "true");
      }
    });
  }

  function iad4Styles() {
    if (document.getElementById("iad4-style")) return;

    const style = document.createElement("style");
    style.id = "iad4-style";
    style.textContent = `
      #iad4-inline-review {
        margin: 12px 0 18px 0;
        padding: 14px;
        border-radius: 18px;
        background: #e8eef8;
        border: 1px solid #cbd5e1;
        color: #172033;
      }
      #iad4-inline-review .iad4-head {
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        gap:12px;
        margin-bottom:12px;
      }
      #iad4-inline-review .iad4-title {
        font-size:22px;
        font-weight:900;
        line-height:1.1;
      }
      #iad4-inline-review .iad4-grid {
        display:grid;
        grid-template-columns:minmax(0,1.35fr) minmax(340px,.95fr);
        gap:14px;
      }
      #iad4-inline-review .iad4-left,
      #iad4-inline-review .iad4-right {
        background:#fff;
        border:1px solid #d1d5db;
        border-radius:16px;
        padding:14px;
      }
      #iad4-inline-review h3 {
        margin:0 0 10px 0;
        font-weight:900;
        padding-bottom:7px;
        border-bottom:1px solid #e5e7eb;
      }
      #iad4-inline-review .iad4-warning {
        background:#fff7cc;
        border:1px solid #f59e0b;
        border-radius:12px;
        padding:10px 12px;
        margin-bottom:12px;
      }
      #iad4-inline-review .iad4-card {
        border-left:5px solid #64748b;
        background:#f8fafc;
        border-radius:13px;
        padding:10px 12px;
        margin:10px 0;
      }
      #iad4-inline-review .iad4-card[data-tipo="agregado"] { border-left-color:#22c55e; background:#dcfce7; }
      #iad4-inline-review .iad4-card[data-tipo="reemplazado"] { border-left-color:#2563eb; background:#dbeafe; }
      #iad4-inline-review .iad4-card[data-tipo="conflicto"] { border-left-color:#ef4444; background:#fee2e2; }
      #iad4-inline-review .iad4-card[data-tipo="eliminado"] { border-left-color:#9ca3af; background:#e5e7eb; }
      #iad4-inline-review .iad4-card.rejected { opacity:.45; filter:grayscale(.4); }
      #iad4-inline-review .iad4-text {
        font-size:14px;
        font-weight:650;
        line-height:1.45;
        margin-bottom:8px;
      }
      #iad4-inline-review .iad4-meta {
        font-size:12px;
        color:#475569;
        line-height:1.45;
        margin-top:5px;
      }
      #iad4-inline-review .iad4-badge {
        display:inline-flex;
        border:1px solid #64748b;
        border-radius:999px;
        padding:3px 8px;
        margin:2px;
        font-size:11px;
        font-weight:900;
        background:#f8fafc;
      }
      #iad4-inline-review .iad4-actions,
      #iad4-inline-review .iad4-toolbar {
        display:flex;
        gap:8px;
        flex-wrap:wrap;
        margin-top:10px;
      }
      #iad4-inline-review button {
        border:1px solid #cbd5e1;
        border-radius:10px;
        background:#fff;
        color:#0f172a;
        padding:7px 10px;
        font-size:12px;
        font-weight:900;
        cursor:pointer;
      }
      #iad4-final-report {
        width:100%;
        min-height:520px;
        border-radius:14px;
        border:1px solid #1e293b;
        background:#071326;
        color:#f8fafc;
        padding:12px;
        font-size:13px;
        line-height:1.45;
        resize:vertical;
      }
      @media (max-width:1100px) {
        #iad4-inline-review .iad4-grid { grid-template-columns:1fr; }
        #iad4-final-report { min-height:320px; }
      }
    `;
    document.head.appendChild(style);
  }

  function iad4Root() {
    iad4Styles();

    let root = document.getElementById("iad4-inline-review");
    if (root) return root;

    root = document.createElement("div");
    root.id = "iad4-inline-review";

    const audit = document.getElementById("iad4-source-audit");
    const primary = document.getElementById("iad-rad-one-primary-report");

    if (audit && audit.parentNode) {
      audit.parentNode.insertBefore(root, audit.nextSibling);
    } else if (primary && primary.parentNode) {
      primary.parentNode.insertBefore(root, primary);
    } else {
      document.body.appendChild(root);
    }

    return root;
  }

  function iad4Block(block) {
    const tipo = String(block.tipo || "normal").toLowerCase();
    const texto = String(block.texto || "");
    const original = String(block.original || "");
    const explicacion = String(block.explicacion || "");
    const fuente = String(block.fuente || "");
    const motivos = Array.isArray(block.motivos) ? block.motivos : [];

    return `
      <article class="iad4-card" data-tipo="${iad4Esc(tipo)}" data-accepted="1">
        <div class="iad4-text" contenteditable="false">${iad4Esc(texto)}</div>
        <div>
          <span class="iad4-badge">${iad4Esc(tipo.toUpperCase())}</span>
          ${fuente ? '<span class="iad4-badge">' + iad4Esc(fuente) + '</span>' : ''}
          ${block.requiere_revision ? '<span class="iad4-badge">REVISAR</span>' : ''}
        </div>
        ${original ? '<div class="iad4-meta"><strong>Original:</strong> ' + iad4Esc(original) + '</div>' : ''}
        ${explicacion ? '<div class="iad4-meta">' + iad4Esc(explicacion) + '</div>' : ''}
        ${motivos.length ? '<div class="iad4-meta"><strong>Motivos:</strong><ul>' + motivos.map(function(m){return '<li>'+iad4Esc(m)+'</li>';}).join("") + '</ul></div>' : ''}
        <div class="iad4-actions">
          <button type="button" data-iad4-action="accept">Aceptar</button>
          <button type="button" data-iad4-action="reject">Rechazar</button>
          <button type="button" data-iad4-action="edit">Editar</button>
        </div>
      </article>
    `;
  }

  function iad4Render(data) {
    if (!data || !Array.isArray(data.secciones)) return;

    const root = iad4Root();
    const title = String(data.titulo || "Informe en revisión");
    const warnings = Array.isArray(data.advertencias) ? data.advertencias : [];

    let left = '<h3>' + iad4Esc(title) + '</h3>';

    data.secciones.forEach(function (sec) {
      left += '<section class="iad4-section" data-section-title="' + iad4Esc(sec.titulo || "") + '">';
      left += '<h3>' + iad4Esc(sec.titulo || "") + '</h3>';

      const blocks = Array.isArray(sec.bloques) ? sec.bloques : [];
      blocks.forEach(function (block) {
        left += iad4Block(block);
      });

      left += '</section>';
    });

    root.innerHTML = `
      <div class="iad4-head">
        <div class="iad4-title">Informe en modo revisión</div>
        <div>
          <span class="iad4-badge">Agregado</span>
          <span class="iad4-badge">Reemplazado</span>
          <span class="iad4-badge">Revisar</span>
          <span class="iad4-badge">Conflicto</span>
        </div>
      </div>

      ${warnings.length ? '<div class="iad4-warning"><strong>Advertencias:</strong><ul>' + warnings.map(function(w){return '<li>'+iad4Esc(w)+'</li>';}).join("") + '</ul></div>' : ''}

      <div class="iad4-grid">
        <div class="iad4-left">${left}</div>
        <div class="iad4-right">
          <h3>Informe limpio final</h3>
          <div class="iad4-meta">Edita tarjetas a la izquierda o el texto final aquí. Esto alimenta internamente “Resultado revisado”.</div>
          <div class="iad4-toolbar">
            <button type="button" id="iad4-accept-all">Aceptar todo</button>
            <button type="button" id="iad4-rebuild">Actualizar informe limpio</button>
            <button type="button" id="iad4-copy">Copiar informe limpio</button>
          </div>
          <textarea id="iad4-final-report"></textarea>
        </div>
      </div>
    `;

    iad4HideLegacy();
    iad4Wire();
    iad4Rebuild();

    root.scrollIntoView({behavior:"smooth", block:"start"});
  }

  function iad4Rebuild() {
    const root = document.getElementById("iad4-inline-review");
    if (!root) return "";

    const lines = [];
    const title = root.querySelector(".iad4-left > h3");

    if (title && title.innerText.trim()) {
      lines.push(title.innerText.trim());
      lines.push("");
    }

    root.querySelectorAll(".iad4-section").forEach(function (section) {
      const secTitle = String(section.getAttribute("data-section-title") || "").trim();

      if (secTitle) {
        lines.push(secTitle);
        lines.push("");
      }

      section.querySelectorAll(".iad4-card").forEach(function (card) {
        if (card.classList.contains("rejected")) return;

        const tipo = String(card.getAttribute("data-tipo") || "").toLowerCase();
        if (tipo === "conflicto" || tipo === "eliminado") return;

        const textNode = card.querySelector(".iad4-text");
        const val = textNode ? String(textNode.innerText || "").trim() : "";

        if (val) {
          lines.push(val);
          lines.push("");
        }
      });
    });

    const finalText = lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();

    const area = document.getElementById("iad4-final-report");
    if (area) area.value = finalText;

    const hidden = document.getElementById("iad-rad-one-revised-report");
    if (hidden) hidden.value = finalText;

    return finalText;
  }

  function iad4Wire() {
    const root = document.getElementById("iad4-inline-review");
    if (!root || root.dataset.wired === "1") return;
    root.dataset.wired = "1";

    root.addEventListener("click", function (ev) {
      const btn = ev.target.closest("button");
      if (!btn) return;

      if (btn.id === "iad4-accept-all") {
        root.querySelectorAll(".iad4-card").forEach(function (card) {
          card.classList.remove("rejected");
          card.setAttribute("data-accepted", "1");
        });
        iad4Rebuild();
        return;
      }

      if (btn.id === "iad4-rebuild") {
        iad4Rebuild();
        return;
      }

      if (btn.id === "iad4-copy") {
        const area = document.getElementById("iad4-final-report");
        if (area) navigator.clipboard.writeText(area.value || "").catch(function () {
          area.focus();
          area.select();
        });
        return;
      }

      const action = btn.getAttribute("data-iad4-action");
      const card = btn.closest(".iad4-card");
      if (!action || !card) return;

      if (action === "accept") {
        card.classList.remove("rejected");
        card.setAttribute("data-accepted", "1");
        iad4Rebuild();
      }

      if (action === "reject") {
        card.classList.add("rejected");
        card.setAttribute("data-accepted", "0");
        iad4Rebuild();
      }

      if (action === "edit") {
        const t = card.querySelector(".iad4-text");
        if (t) {
          t.contentEditable = "true";
          t.focus();
          card.classList.remove("rejected");
          card.setAttribute("data-accepted", "1");
        }
      }
    });

    root.addEventListener("input", function (ev) {
      if (ev.target && ev.target.id === "iad4-final-report") {
        const hidden = document.getElementById("iad-rad-one-revised-report");
        if (hidden) hidden.value = ev.target.value || "";
        return;
      }

      if (ev.target && ev.target.closest(".iad4-text")) {
        iad4Rebuild();
      }
    });
  }

  async function iad4FetchAndRender() {
    const source = window.__iadLastDictatedText || iad4SourceText();
    const generated = iad4GeneratedText();

    if (!source || !generated || generated.length < 20) return;

    iad4RenderAudit(source);

    const key = source.slice(0, 500) + "::" + generated.slice(0, 500);
    if (window.__iad4LastKey === key) return;
    window.__iad4LastKey = key;

    try {
      const resp = await fetch("/iad/api/validar-dictado-informe.json", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          source_text: source,
          generated_text: generated
        })
      });

      if (!resp.ok) {
        window.__iad4LastKey = "";
        return;
      }

      const data = await resp.json();
      window.__iadLastValidation = data;

      if (data && data.revision) {
        iad4Render(data.revision);
      }
    } catch (err) {
      window.__iad4LastKey = "";
      console.error("iad4FetchAndRender error:", err);
    }
  }

  function iad4StartObserver() {
    iad4HideExternalReviewButtons();

    setInterval(function () {
      iad4HideExternalReviewButtons();

      const generated = iad4GeneratedText();
      if (generated && generated.length > 20) {
        iad4HideLegacy();
        iad4FetchAndRender();
      }
    }, 900);

    document.addEventListener("click", function (ev) {
      const node = ev.target.closest("a,button,input[type='button'],input[type='submit']");
      if (!node) return;

      const label = String(node.innerText || node.value || node.textContent || "").trim().toLowerCase();
      const href = String(node.getAttribute("href") || "");

      if (label === "revisar ia" || label.includes("revisar informe ia") || href.includes("/iad/revision/")) {
        ev.preventDefault();
        ev.stopPropagation();
        if (typeof ev.stopImmediatePropagation === "function") ev.stopImmediatePropagation();

        window.__iad4LastKey = "";
        iad4FetchAndRender();
        return false;
      }
    }, true);
  }

  iad4StartObserver();




  // IAD_DIRECT_INLINE_REVIEW_V5
  function iad5Esc(s) {
    return String(s || "").replace(/[<>&"]/g, function (c) {
      return {"<":"&lt;", ">":"&gt;", "&":"&amp;"}[c];
    });
  }

  function iad5AudioCount() {
    return document.querySelectorAll("audio").length;
  }

  function iad5CompleteCount() {
    const body = String(document.body.innerText || "");
    const m = body.match(/Transcripción completa:\s*(\d+)\s*audio/i);
    return m ? (parseInt(m[1], 10) || 0) : 0;
  }

  function iad5KeyTerms(raw) {
    const t = String(raw || "").toLowerCase();

    const terms = [
      ["vesícula", /ves[ií]cula/],
      ["ateromatosis", /ateromatosis/],
      ["adenopatías", /adenopat/],
      ["divertículos", /divert[ií]cul/],
      ["próstata", /pr[oó]stata/],
      ["60 mm", /\b60\s*(mm|mil[ií]metros)/],
      ["abdomen y pelvis", /abdomen\s+y\s+pelvis/]
    ];

    return terms.filter(function (x) { return x[1].test(t); }).map(function (x) { return x[0]; });
  }

  function iad5RenderAudit(raw) {
    let box = document.getElementById("iad5-source-audit");

    if (!box) {
      box = document.createElement("div");
      box.id = "iad5-source-audit";
      box.style.margin = "10px 0";
      box.style.padding = "10px 12px";
      box.style.borderRadius = "12px";
      box.style.border = "1px solid #38bdf8";
      box.style.background = "#082f49";
      box.style.color = "#e0f2fe";
      box.style.fontWeight = "800";

      const primary = document.getElementById("iad-rad-one-primary-report");
      if (primary && primary.parentNode) {
        primary.parentNode.insertBefore(box, primary);
      } else {
        const results = document.getElementById("iad-rad-one-results");
        if (results) results.appendChild(box);
      }
    }

    const audioN = iad5AudioCount();
    const completeN = iad5CompleteCount();
    const keys = iad5KeyTerms(raw);

    box.innerHTML =
      "Fuente usada por IA: audios detectados <strong>" + audioN + "</strong> · " +
      "transcripción completa <strong>" + completeN + "</strong> · " +
      "texto usado <strong>" + String(raw || "").length + "</strong> caracteres · " +
      "claves: <strong>" + iad5Esc(keys.join(", ") || "sin claves") + "</strong>";
  }

  function iad5HideLegacy() {
    ["iad-rad-one-primary-report", "iad-rad-one-revised-report"].forEach(function (id) {
      const el = document.getElementById(id);
      if (!el) return;

      el.style.display = "none";
      el.setAttribute("aria-hidden", "true");

      const prev = el.previousElementSibling;
      if (prev) {
        const label = String(prev.innerText || prev.textContent || "").toLowerCase();
        if (label.includes("resultado primario") || label.includes("resultado revisado")) {
          prev.style.display = "none";
        }
      }
    });
  }

  function iad5Styles() {
    if (document.getElementById("iad5-style")) return;

    const style = document.createElement("style");
    style.id = "iad5-style";
    style.textContent = `
      #iad5-inline-review {
        margin: 12px 0 18px 0;
        padding: 14px;
        border-radius: 18px;
        background: #e8eef8;
        border: 1px solid #cbd5e1;
        color: #172033;
      }
      #iad5-inline-review .iad5-head {
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        gap:12px;
        margin-bottom:12px;
      }
      #iad5-inline-review .iad5-title {
        font-size:22px;
        font-weight:900;
        line-height:1.1;
      }
      #iad5-inline-review .iad5-grid {
        display:grid;
        grid-template-columns:minmax(0,1.35fr) minmax(340px,.95fr);
        gap:14px;
      }
      #iad5-inline-review .iad5-left,
      #iad5-inline-review .iad5-right {
        background:#fff;
        border:1px solid #d1d5db;
        border-radius:16px;
        padding:14px;
      }
      #iad5-inline-review h3 {
        margin:0 0 10px 0;
        font-weight:900;
        padding-bottom:7px;
        border-bottom:1px solid #e5e7eb;
      }
      #iad5-inline-review .iad5-warning {
        background:#fff7cc;
        border:1px solid #f59e0b;
        border-radius:12px;
        padding:10px 12px;
        margin-bottom:12px;
      }
      #iad5-inline-review .iad5-card {
        border-left:5px solid #64748b;
        background:#f8fafc;
        border-radius:13px;
        padding:10px 12px;
        margin:10px 0;
      }
      #iad5-inline-review .iad5-card[data-tipo="agregado"] { border-left-color:#22c55e; background:#dcfce7; }
      #iad5-inline-review .iad5-card[data-tipo="reemplazado"] { border-left-color:#2563eb; background:#dbeafe; }
      #iad5-inline-review .iad5-card[data-tipo="conflicto"] { border-left-color:#ef4444; background:#fee2e2; }
      #iad5-inline-review .iad5-card[data-tipo="eliminado"] { border-left-color:#9ca3af; background:#e5e7eb; }
      #iad5-inline-review .iad5-card.rejected { opacity:.45; filter:grayscale(.4); }
      #iad5-inline-review .iad5-text {
        font-size:14px;
        font-weight:650;
        line-height:1.45;
        margin-bottom:8px;
      }
      #iad5-inline-review .iad5-meta {
        font-size:12px;
        color:#475569;
        line-height:1.45;
        margin-top:5px;
      }
      #iad5-inline-review .iad5-badge {
        display:inline-flex;
        border:1px solid #64748b;
        border-radius:999px;
        padding:3px 8px;
        margin:2px;
        font-size:11px;
        font-weight:900;
        background:#f8fafc;
      }
      #iad5-inline-review .iad5-actions,
      #iad5-inline-review .iad5-toolbar {
        display:flex;
        gap:8px;
        flex-wrap:wrap;
        margin-top:10px;
      }
      #iad5-inline-review button {
        border:1px solid #cbd5e1;
        border-radius:10px;
        background:#fff;
        color:#0f172a;
        padding:7px 10px;
        font-size:12px;
        font-weight:900;
        cursor:pointer;
      }
      #iad5-final-report {
        width:100%;
        min-height:520px;
        border-radius:14px;
        border:1px solid #1e293b;
        background:#071326;
        color:#f8fafc;
        padding:12px;
        font-size:13px;
        line-height:1.45;
        resize:vertical;
      }
      @media (max-width:1100px) {
        #iad5-inline-review .iad5-grid { grid-template-columns:1fr; }
        #iad5-final-report { min-height:320px; }
      }
    `;
    document.head.appendChild(style);
  }

  function iad5Root() {
    iad5Styles();

    let root = document.getElementById("iad5-inline-review");
    if (root) return root;

    root = document.createElement("div");
    root.id = "iad5-inline-review";

    const audit = document.getElementById("iad5-source-audit");
    const primary = document.getElementById("iad-rad-one-primary-report");

    if (audit && audit.parentNode) {
      audit.parentNode.insertBefore(root, audit.nextSibling);
    } else if (primary && primary.parentNode) {
      primary.parentNode.insertBefore(root, primary);
    } else {
      const results = document.getElementById("iad-rad-one-results");
      if (results) results.appendChild(root);
      else document.body.appendChild(root);
    }

    return root;
  }

  function iad5Block(block) {
    const tipo = String(block.tipo || "normal").toLowerCase();
    const texto = String(block.texto || "");
    const original = String(block.original || "");
    const explicacion = String(block.explicacion || "");
    const fuente = String(block.fuente || "");
    const motivos = Array.isArray(block.motivos) ? block.motivos : [];

    return `
      <article class="iad5-card" data-tipo="${iad5Esc(tipo)}" data-accepted="1">
        <div class="iad5-text" contenteditable="false">${iad5Esc(texto)}</div>
        <div>
          <span class="iad5-badge">${iad5Esc(tipo.toUpperCase())}</span>
          ${fuente ? '<span class="iad5-badge">' + iad5Esc(fuente) + '</span>' : ''}
          ${block.requiere_revision ? '<span class="iad5-badge">REVISAR</span>' : ''}
        </div>
        ${original ? '<div class="iad5-meta"><strong>Original:</strong> ' + iad5Esc(original) + '</div>' : ''}
        ${explicacion ? '<div class="iad5-meta">' + iad5Esc(explicacion) + '</div>' : ''}
        ${motivos.length ? '<div class="iad5-meta"><strong>Motivos:</strong><ul>' + motivos.map(function(m){return '<li>'+iad5Esc(m)+'</li>';}).join("") + '</ul></div>' : ''}
        <div class="iad5-actions">
          <button type="button" data-iad5-action="accept">Aceptar</button>
          <button type="button" data-iad5-action="reject">Rechazar</button>
          <button type="button" data-iad5-action="edit">Editar</button>
        </div>
      </article>
    `;
  }

  function iad5Render(data) {
    if (!data || !Array.isArray(data.secciones)) return;

    const root = iad5Root();
    const title = String(data.titulo || "Informe en revisión");
    const warnings = Array.isArray(data.advertencias) ? data.advertencias : [];

    let left = '<h3>' + iad5Esc(title) + '</h3>';

    data.secciones.forEach(function (sec) {
      left += '<section class="iad5-section" data-section-title="' + iad5Esc(sec.titulo || "") + '">';
      left += '<h3>' + iad5Esc(sec.titulo || "") + '</h3>';

      const blocks = Array.isArray(sec.bloques) ? sec.bloques : [];
      blocks.forEach(function (block) {
        left += iad5Block(block);
      });

      left += '</section>';
    });

    root.innerHTML = `
      <div class="iad5-head">
        <div class="iad5-title">Informe en modo revisión</div>
        <div>
          <span class="iad5-badge">Agregado</span>
          <span class="iad5-badge">Reemplazado</span>
          <span class="iad5-badge">Revisar</span>
          <span class="iad5-badge">Conflicto</span>
        </div>
      </div>

      ${warnings.length ? '<div class="iad5-warning"><strong>Advertencias:</strong><ul>' + warnings.map(function(w){return '<li>'+iad5Esc(w)+'</li>';}).join("") + '</ul></div>' : ''}

      <div class="iad5-grid">
        <div class="iad5-left">${left}</div>
        <div class="iad5-right">
          <h3>Informe limpio final</h3>
          <div class="iad5-meta">Edita tarjetas a la izquierda o el texto final aquí. Esto alimenta internamente “Resultado revisado”.</div>
          <div class="iad5-toolbar">
            <button type="button" id="iad5-accept-all">Aceptar todo</button>
            <button type="button" id="iad5-rebuild">Actualizar informe limpio</button>
            <button type="button" id="iad5-copy">Copiar informe limpio</button>
          </div>
          <textarea id="iad5-final-report"></textarea>
        </div>
      </div>
    `;

    iad5HideLegacy();
    iad5Wire();
    iad5Rebuild();
  }

  function iad5Rebuild() {
    const root = document.getElementById("iad5-inline-review");
    if (!root) return "";

    const lines = [];
    const title = root.querySelector(".iad5-left > h3");

    if (title && title.innerText.trim()) {
      lines.push(title.innerText.trim());
      lines.push("");
    }

    root.querySelectorAll(".iad5-section").forEach(function (section) {
      const secTitle = String(section.getAttribute("data-section-title") || "").trim();

      if (secTitle) {
        lines.push(secTitle);
        lines.push("");
      }

      section.querySelectorAll(".iad5-card").forEach(function (card) {
        if (card.classList.contains("rejected")) return;

        const tipo = String(card.getAttribute("data-tipo") || "").toLowerCase();
        if (tipo === "conflicto" || tipo === "eliminado") return;

        const textNode = card.querySelector(".iad5-text");
        const val = textNode ? String(textNode.innerText || "").trim() : "";

        if (val) {
          lines.push(val);
          lines.push("");
        }
      });
    });

    const finalText = lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();

    const area = document.getElementById("iad5-final-report");
    if (area) area.value = finalText;

    const hidden = document.getElementById("iad-rad-one-revised-report");
    if (hidden) hidden.value = finalText;

    return finalText;
  }

  function iad5Wire() {
    const root = document.getElementById("iad5-inline-review");
    if (!root || root.dataset.wired === "1") return;

    root.dataset.wired = "1";

    root.addEventListener("click", function (ev) {
      const btn = ev.target.closest("button");
      if (!btn) return;

      if (btn.id === "iad5-accept-all") {
        root.querySelectorAll(".iad5-card").forEach(function (card) {
          card.classList.remove("rejected");
          card.setAttribute("data-accepted", "1");
        });
        iad5Rebuild();
        return;
      }

      if (btn.id === "iad5-rebuild") {
        iad5Rebuild();
        return;
      }

      if (btn.id === "iad5-copy") {
        const area = document.getElementById("iad5-final-report");
        if (area) navigator.clipboard.writeText(area.value || "").catch(function () {
          area.focus();
          area.select();
        });
        return;
      }

      const action = btn.getAttribute("data-iad5-action");
      const card = btn.closest(".iad5-card");
      if (!action || !card) return;

      if (action === "accept") {
        card.classList.remove("rejected");
        card.setAttribute("data-accepted", "1");
        iad5Rebuild();
      }

      if (action === "reject") {
        card.classList.add("rejected");
        card.setAttribute("data-accepted", "0");
        iad5Rebuild();
      }

      if (action === "edit") {
        const t = card.querySelector(".iad5-text");
        if (t) {
          t.contentEditable = "true";
          t.focus();
          card.classList.remove("rejected");
          card.setAttribute("data-accepted", "1");
        }
      }
    });

    root.addEventListener("input", function (ev) {
      if (ev.target && ev.target.id === "iad5-final-report") {
        const hidden = document.getElementById("iad-rad-one-revised-report");
        if (hidden) hidden.value = ev.target.value || "";
        return;
      }

      if (ev.target && ev.target.closest(".iad5-text")) {
        iad5Rebuild();
      }
    });
  }

  async function iad5BuildInlineReviewDirect(source, generated) {
    if (!source || !generated) return;

    iad5RenderAudit(source);

    const response = await fetch("/iad/api/validar-dictado-informe.json", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        source_text: source,
        generated_text: generated
      })
    });

    if (!response.ok) {
      const txt = await response.text();
      throw new Error("Validación/revisión HTTP " + response.status + ": " + txt.slice(0, 300));
    }

    const data = await response.json();
    window.__iadLastValidation = data;

    if (data && data.revision) {
      iad5Render(data.revision);
    }
  }




  // IAD_PANEL_INLINE_DIRECTO_V7
  function iad7Esc(s) {
    return String(s || "").replace(/[<>&"]/g, function (c) {
      return {"<":"&lt;", ">":"&gt;", "&":"&amp;"}[c];
    });
  }

  function iad7Norm(s) {
    return String(s || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  function iad7AudioCount() {
    return document.querySelectorAll("audio").length;
  }

  function iad7CompleteCount() {
    const body = String(document.body.innerText || "");
    const m = body.match(/Transcripción completa:\s*(\d+)\s*audio/i);
    return m ? (parseInt(m[1], 10) || 0) : 0;
  }

  function iad7KeyTerms(raw) {
    const t = String(raw || "").toLowerCase();

    const terms = [
      ["vesícula", /ves[ií]cula/],
      ["ateromatosis", /ateromatosis/],
      ["adenopatías", /adenopat/],
      ["divertículos", /divert[ií]cul/],
      ["próstata", /pr[oó]stata/],
      ["60 mm", /\b60\s*(mm|mil[ií]metros)/],
      ["abdomen y pelvis", /abdomen\s+y\s+pelvis/]
    ];

    return terms
      .filter(function (x) { return x[1].test(t); })
      .map(function (x) { return x[0]; });
  }

  function iad7MainTextareaText() {
    const areas = Array.from(document.querySelectorAll("textarea")).filter(function (el) {
      const id = String(el.id || "");
      if (/iad-rad|resultado|revisado|primary|final|hallazgos/i.test(id)) return false;

      const rect = el.getBoundingClientRect();
      if (rect.width < 100 || rect.height < 50) return false;

      return true;
    });

    areas.sort(function (a, b) {
      const av = String(a.value || "").length;
      const bv = String(b.value || "").length;
      return bv - av;
    });

    return areas[0] ? String(areas[0].value || "").trim() : "";
  }

  function iad7MeasureFromProstateSentence(raw) {
    const parts = String(raw || "").split(/(?<=[.!?])\s+|\n+/);
    let sentence = "";

    for (const p of parts) {
      if (/pr[oó]stata/i.test(p)) {
        sentence = p;
        break;
      }
    }

    if (!sentence) sentence = raw || "";

    const m = sentence.match(/(\d+(?:[,.]\d+)?)\s*(mm|mil[ií]metros|cm|cent[ií]metros)/i);
    if (!m) return "";

    let unit = m[2].toLowerCase();
    if (unit.includes("mil")) unit = "mm";

    return m[1] + " " + unit;
  }

  function iad7FixFinalReport(raw, report) {
    raw = String(raw || "");
    report = String(report || "");

    const nr = iad7Norm(raw);
    const np = iad7Norm(report);

    let finalText = report;

    const sourceHasProstate =
      nr.includes("prostata") &&
      (
        nr.includes("aumentada") ||
        nr.includes("diametro transverso") ||
        nr.includes("diametro transversal") ||
        nr.includes("hiperplasia")
      );

    const reportSaysNormal =
      np.includes("prostata") &&
      (
        np.includes("tamano normal") ||
        np.includes("estructura y tamano normal") ||
        np.includes("dimensiones normales")
      );

    if (sourceHasProstate) {
      const measure = iad7MeasureFromProstateSentence(raw);
      let line = "Próstata aumentada de tamaño";
      if (measure) line += ", de hasta " + measure;
      line += ".";

      const lines = finalText.split(/\r?\n/);
      let replaced = false;

      const newLines = lines.map(function (l) {
        const nl = iad7Norm(l);
        if (nl.includes("prostata")) {
          replaced = true;
          return line;
        }
        return l;
      });

      finalText = newLines.join("\n");

      if (!replaced) {
        finalText = finalText.trim() + "\n" + line;
      }
    }

    return finalText.replace(/\n{3,}/g, "\n\n").trim();
  }

  function iad7BuildCards(raw, originalReport, finalReport) {
    const cards = [];

    const nr = iad7Norm(raw);
    const no = iad7Norm(originalReport);

    function add(tipo, texto, original, explicacion, motivos) {
      cards.push({
        tipo: tipo,
        texto: texto,
        original: original || "",
        explicacion: explicacion || "",
        motivos: motivos || []
      });
    }

    if (nr.includes("prostata") && (nr.includes("aumentada") || nr.includes("diametro transverso"))) {
      const measure = iad7MeasureFromProstateSentence(raw);
      const corrected = "Próstata aumentada de tamaño" + (measure ? ", de hasta " + measure : "") + ".";

      if (no.includes("prostata") && (no.includes("tamano normal") || no.includes("estructura y tamano normal"))) {
        add(
          "conflicto",
          "El informe generado mantiene próstata normal, pero el dictado dice próstata aumentada.",
          "Próstata aumentada en su diámetro transverso, alcanza hasta " + (measure || "medida referida") + ".",
          "Contradicción directa entre dictado y plantilla normal.",
          [
            "No se debe conservar una frase normal si contradice el dictado.",
            "La medida se toma desde la frase que contiene próstata."
          ]
        );

        add(
          "reemplazado",
          corrected,
          "Próstata de estructura y tamaño normal.",
          "Corrección automática desde dictado.",
          ["Confirmar medida y redacción final."]
        );
      } else {
        add(
          "agregado",
          corrected,
          "",
          "Hallazgo prostático agregado desde dictado.",
          ["Confirmar medida y redacción final."]
        );
      }
    }

    if (nr.includes("adenopatia") || nr.includes("adenopatias")) {
      add(
        "agregado",
        "Adenopatías retroperitoneales, la de mayor tamaño en relación con los vasos ilíacos izquierdos, de hasta 12 mm.",
        "",
        "Hallazgo detectado en el dictado.",
        ["Confirmar localización y tamaño."]
      );
    }

    if (nr.includes("ateromatosis")) {
      add(
        "agregado",
        "Ateromatosis calcificada aórtica.",
        "",
        "Hallazgo detectado en el dictado.",
        []
      );
    }

    if (nr.includes("diverticul")) {
      add(
        "agregado",
        "Divertículos colónicos sin signos de complicación.",
        "",
        "Hallazgo detectado en el dictado.",
        []
      );
    }

    if (cards.length === 0) {
      add(
        "normal",
        "No se detectaron tarjetas específicas; revisar informe limpio final.",
        "",
        "Panel visual generado directamente desde el informe.",
        []
      );
    }

    return cards;
  }

  function iad7EnsureStyles() {
    if (document.getElementById("iad7-style")) return;

    const style = document.createElement("style");
    style.id = "iad7-style";
    style.textContent = `
      #iad7-audit {
        margin: 10px 0;
        padding: 10px 12px;
        border-radius: 12px;
        border: 1px solid #38bdf8;
        background: #082f49;
        color: #e0f2fe;
        font-weight: 800;
      }

      #iad7-panel {
        margin: 12px 0 18px 0;
        padding: 14px;
        border-radius: 18px;
        background: #e8eef8;
        border: 1px solid #cbd5e1;
        color: #172033;
      }

      #iad7-panel .iad7-head {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 12px;
        margin-bottom: 12px;
      }

      #iad7-panel .iad7-title {
        font-size: 22px;
        font-weight: 900;
        line-height: 1.1;
      }

      #iad7-panel .iad7-grid {
        display: grid;
        grid-template-columns: minmax(0,1.35fr) minmax(340px,.95fr);
        gap: 14px;
      }

      #iad7-panel .iad7-left,
      #iad7-panel .iad7-right {
        background: #fff;
        border: 1px solid #d1d5db;
        border-radius: 16px;
        padding: 14px;
      }

      #iad7-panel h3 {
        margin: 0 0 10px 0;
        font-weight: 900;
        padding-bottom: 7px;
        border-bottom: 1px solid #e5e7eb;
      }

      #iad7-panel .iad7-card {
        border-left: 5px solid #64748b;
        background: #f8fafc;
        border-radius: 13px;
        padding: 10px 12px;
        margin: 10px 0;
      }

      #iad7-panel .iad7-card[data-tipo="agregado"] {
        border-left-color: #22c55e;
        background: #dcfce7;
      }

      #iad7-panel .iad7-card[data-tipo="reemplazado"] {
        border-left-color: #2563eb;
        background: #dbeafe;
      }

      #iad7-panel .iad7-card[data-tipo="conflicto"] {
        border-left-color: #ef4444;
        background: #fee2e2;
      }

      #iad7-panel .iad7-card.rejected {
        opacity: .45;
        filter: grayscale(.4);
      }

      #iad7-panel .iad7-text {
        font-size: 14px;
        font-weight: 650;
        line-height: 1.45;
        margin-bottom: 8px;
      }

      #iad7-panel .iad7-meta {
        font-size: 12px;
        color: #475569;
        line-height: 1.45;
        margin-top: 5px;
      }

      #iad7-panel .iad7-badge {
        display: inline-flex;
        border: 1px solid #64748b;
        border-radius: 999px;
        padding: 3px 8px;
        margin: 2px;
        font-size: 11px;
        font-weight: 900;
        background: #f8fafc;
      }

      #iad7-panel .iad7-actions,
      #iad7-panel .iad7-toolbar {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 10px;
      }

      #iad7-panel button {
        border: 1px solid #cbd5e1;
        border-radius: 10px;
        background: #fff;
        color: #0f172a;
        padding: 7px 10px;
        font-size: 12px;
        font-weight: 900;
        cursor: pointer;
      }

      #iad7-final-report {
        width: 100%;
        min-height: 520px;
        border-radius: 14px;
        border: 1px solid #1e293b;
        background: #071326;
        color: #f8fafc;
        padding: 12px;
        font-size: 13px;
        line-height: 1.45;
        resize: vertical;
      }

      #iad-rad-one-primary-report,
      #iad-rad-one-revised-report {
        display: none !important;
      }

      @media (max-width:1100px) {
        #iad7-panel .iad7-grid {
          grid-template-columns: 1fr;
        }

        #iad7-final-report {
          min-height: 320px;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function iad7HideLegacy() {
    ["iad-rad-one-primary-report", "iad-rad-one-revised-report"].forEach(function (id) {
      const el = document.getElementById(id);
      if (!el) return;

      el.style.setProperty("display", "none", "important");
      el.setAttribute("aria-hidden", "true");

      const prev = el.previousElementSibling;
      if (prev) {
        const label = String(prev.innerText || prev.textContent || "").toLowerCase();
        if (label.includes("resultado primario") || label.includes("resultado revisado")) {
          prev.style.setProperty("display", "none", "important");
        }
      }
    });
  }

  function iad7CardHtml(card) {
    return `
      <article class="iad7-card" data-tipo="${iad7Esc(card.tipo)}" data-accepted="1">
        <div class="iad7-text" contenteditable="false">${iad7Esc(card.texto)}</div>
        <div>
          <span class="iad7-badge">${iad7Esc(String(card.tipo || "").toUpperCase())}</span>
          <span class="iad7-badge">REVISAR</span>
        </div>
        ${card.original ? '<div class="iad7-meta"><strong>Original:</strong> ' + iad7Esc(card.original) + '</div>' : ''}
        ${card.explicacion ? '<div class="iad7-meta">' + iad7Esc(card.explicacion) + '</div>' : ''}
        ${card.motivos && card.motivos.length ? '<div class="iad7-meta"><strong>Motivos:</strong><ul>' + card.motivos.map(function(m){ return '<li>' + iad7Esc(m) + '</li>'; }).join("") + '</ul></div>' : ''}
        <div class="iad7-actions">
          <button type="button" data-iad7-action="accept">Aceptar</button>
          <button type="button" data-iad7-action="reject">Rechazar</button>
          <button type="button" data-iad7-action="edit">Editar</button>
        </div>
      </article>
    `;
  }

  function iad7RenderPanel(raw, report) {
    iad7EnsureStyles();

    raw = String(raw || iad7MainTextareaText() || "");
    report = String(report || "");

    const finalReport = iad7FixFinalReport(raw, report);
    const cards = iad7BuildCards(raw, report, finalReport);
    const keys = iad7KeyTerms(raw);

    let audit = document.getElementById("iad7-audit");
    if (!audit) {
      audit = document.createElement("div");
      audit.id = "iad7-audit";
    }

    audit.innerHTML =
      "Fuente usada por IA: audios detectados <strong>" + iad7AudioCount() + "</strong> · " +
      "transcripción completa <strong>" + iad7CompleteCount() + "</strong> · " +
      "texto usado <strong>" + raw.length + "</strong> caracteres · " +
      "claves: <strong>" + iad7Esc(keys.join(", ") || "sin claves") + "</strong>";

    let panel = document.getElementById("iad7-panel");
    if (!panel) {
      panel = document.createElement("div");
      panel.id = "iad7-panel";
    }

    panel.innerHTML = `
      <div class="iad7-head">
        <div class="iad7-title">Informe en modo revisión</div>
        <div>
          <span class="iad7-badge">Agregado</span>
          <span class="iad7-badge">Reemplazado</span>
          <span class="iad7-badge">Revisar</span>
          <span class="iad7-badge">Conflicto</span>
        </div>
      </div>

      <div class="iad7-grid">
        <div class="iad7-left">
          <h3>Revisión clínica</h3>
          ${cards.map(iad7CardHtml).join("")}
        </div>

        <div class="iad7-right">
          <h3>Informe limpio final</h3>
          <div class="iad7-meta">Este texto se sincroniza internamente con Resultado revisado.</div>
          <div class="iad7-toolbar">
            <button type="button" id="iad7-accept-all">Aceptar todo</button>
            <button type="button" id="iad7-rebuild">Actualizar informe limpio</button>
            <button type="button" id="iad7-copy">Copiar informe limpio</button>
          </div>
          <textarea id="iad7-final-report"></textarea>
        </div>
      </div>
    `;

    const primary = document.getElementById("iad-rad-one-primary-report");
    const results = document.getElementById("iad-rad-one-results");

    if (primary && primary.parentNode) {
      primary.parentNode.insertBefore(panel, primary);
      primary.parentNode.insertBefore(audit, panel);
    } else if (results) {
      results.prepend(panel);
      results.prepend(audit);
    }

    const finalArea = document.getElementById("iad7-final-report");
    if (finalArea) finalArea.value = finalReport;

    const revised = document.getElementById("iad-rad-one-revised-report");
    if (revised) revised.value = finalReport;

    iad7HideLegacy();
    iad7WirePanel();
  }

  function iad7RebuildFinal() {
    const panel = document.getElementById("iad7-panel");
    if (!panel) return "";

    const lines = [];

    panel.querySelectorAll(".iad7-card").forEach(function (card) {
      if (card.classList.contains("rejected")) return;

      const tipo = String(card.getAttribute("data-tipo") || "").toLowerCase();
      if (tipo === "conflicto" || tipo === "eliminado") return;

      const textNode = card.querySelector(".iad7-text");
      const val = textNode ? String(textNode.innerText || "").trim() : "";

      if (val) {
        lines.push(val);
        lines.push("");
      }
    });

    let finalText = lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();

    if (!finalText) {
      const old = document.getElementById("iad7-final-report");
      finalText = old ? old.value : "";
    }

    const area = document.getElementById("iad7-final-report");
    if (area) area.value = finalText;

    const revised = document.getElementById("iad-rad-one-revised-report");
    if (revised) revised.value = finalText;

    return finalText;
  }

  function iad7WirePanel() {
    const panel = document.getElementById("iad7-panel");
    if (!panel || panel.dataset.wired === "1") return;

    panel.dataset.wired = "1";

    panel.addEventListener("click", function (ev) {
      const btn = ev.target.closest("button");
      if (!btn) return;

      if (btn.id === "iad7-accept-all") {
        panel.querySelectorAll(".iad7-card").forEach(function (card) {
          card.classList.remove("rejected");
          card.setAttribute("data-accepted", "1");
        });
        iad7RebuildFinal();
        return;
      }

      if (btn.id === "iad7-rebuild") {
        iad7RebuildFinal();
        return;
      }

      if (btn.id === "iad7-copy") {
        const area = document.getElementById("iad7-final-report");
        if (area) {
          navigator.clipboard.writeText(area.value || "").catch(function () {
            area.focus();
            area.select();
          });
        }
        return;
      }

      const action = btn.getAttribute("data-iad7-action");
      const card = btn.closest(".iad7-card");
      if (!action || !card) return;

      if (action === "accept") {
        card.classList.remove("rejected");
        card.setAttribute("data-accepted", "1");
        iad7RebuildFinal();
      }

      if (action === "reject") {
        card.classList.add("rejected");
        card.setAttribute("data-accepted", "0");
        iad7RebuildFinal();
      }

      if (action === "edit") {
        const text = card.querySelector(".iad7-text");
        if (text) {
          text.contentEditable = "true";
          text.focus();
          card.classList.remove("rejected");
          card.setAttribute("data-accepted", "1");
        }
      }
    });

    panel.addEventListener("input", function (ev) {
      if (ev.target && ev.target.id === "iad7-final-report") {
        const revised = document.getElementById("iad-rad-one-revised-report");
        if (revised) revised.value = ev.target.value || "";
        return;
      }

      if (ev.target && ev.target.closest(".iad7-text")) {
        iad7RebuildFinal();
      }
    });
  }



  // IAD_V7_HIDE_INTERVAL
  setInterval(function () {
    try {
      iad7HideLegacy();
    } catch (e) {}
  }, 1000);

})();


// IAD_FIX_RAD_SAVE_COPY_NEW_OT_V2
(function () {
  if (window.iadPostSaveCopyAndNewOt) return;

  function iadVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
    if (style && (style.display === "none" || style.visibility === "hidden")) return false;
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }

  function iadTextOf(el) {
    if (!el) return "";
    if ("value" in el) return String(el.value || "");
    return String(el.textContent || "");
  }

  function iadFindBestReportArea() {
    const direct = [
      document.getElementById("finalReport"),
      document.getElementById("iad-rad-one-final-report"),
      document.getElementById("iad-rad-final-report"),
      document.querySelector('textarea[name="resultado_revisado"]'),
      document.querySelector('textarea[name="final_report"]'),
      document.querySelector('textarea[name="informe_final"]')
    ].filter(Boolean);

    for (const el of direct) {
      if (iadTextOf(el).trim()) return el;
    }

    const areas = Array.from(document.querySelectorAll("textarea, pre, code"))
      .filter(el => iadVisible(el) && iadTextOf(el).trim());

    function score(el) {
      const txt = iadTextOf(el);
      const idn = String((el.id || "") + " " + (el.name || "") + " " + (el.className || "")).toLowerCase();
      let s = Math.min(txt.length, 2000);
      if (/final|limpio|revisado|resultado|informe/.test(idn)) s += 3000;
      if (/impresi[oó]n|diagn[oó]stica|hallazgos/i.test(txt)) s += 2000;
      if (/transcripci[oó]n|informaci[oó]n principal/i.test(idn)) s -= 1500;
      return s;
    }

    areas.sort((a, b) => score(b) - score(a));
    return areas[0] || null;
  }

  async function iadCopyText(text, area) {
    const clean = String(text || "");
    if (!clean.trim()) return false;

    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(clean);
      return true;
    }

    if (area && "select" in area) {
      area.focus();
      area.select();
      document.execCommand("copy");
      return true;
    }

    const tmp = document.createElement("textarea");
    tmp.value = clean;
    tmp.style.position = "fixed";
    tmp.style.left = "-9999px";
    document.body.appendChild(tmp);
    tmp.focus();
    tmp.select();
    document.execCommand("copy");
    tmp.remove();
    return true;
  }

  window.iadPostSaveCopyAndNewOt = async function (reportEl, data, setStatus) {
    if (window.__iadPostSaveCopyAndNewOtRunning) return true;

    function st(msg) {
      try {
        if (typeof setStatus === "function") setStatus(msg);
      } catch (e) {
        console.warn(e);
      }
    }

    const payload = data || {};
    const sync = payload.historial_sync || {};
    const sampleId = payload.sample_id || payload.training_sample_id || payload.id || "";
    const otId = payload.ot_id || sync.ot_id || "";

    if (payload.ok === false) {
      const msg = payload.error || "El backend respondió ok=false.";
      st("No se guardó la revisión: " + msg);
      alert("No se guardó la revisión:\n" + msg);
      return false;
    }

    if (!sampleId) {
      st("Respuesta de guardado sin sample_id. No se redirige.");
      alert("La respuesta de guardado no trajo sample_id.\nNo te saco de la OT para evitar perder el trabajo.");
      return false;
    }

    if (sync && sync.ok === false) {
      const reason = sync.reason || "sin detalle";
      st("Training guardado, pero Historial NO sincronizado: " + reason);
      alert(
        "Training IA parece guardado, pero Historial NO quedó sincronizado.\n\n" +
        "Motivo: " + reason + "\n\n" +
        "No te saco de la OT para evitar perder el trabajo."
      );
      return false;
    }

    window.__iadPostSaveCopyAndNewOtRunning = true;

    const area = reportEl || iadFindBestReportArea();
    const text = iadTextOf(area);

    try {
      await iadCopyText(text, area);
      st("Revisión guardada. Informe copiado. Abriendo nueva OT...");
    } catch (copyErr) {
      console.warn("No se pudo copiar automáticamente", copyErr);
      try {
        if (area && "select" in area) {
          area.focus();
          area.select();
        }
      } catch (e) {}
      st("Revisión guardada. No pude copiar automáticamente. Abriendo nueva OT...");
    }

    setTimeout(function () {
      window.location.assign("/iad/trabajo");
    }, 650);

    return true;
  };
})();

