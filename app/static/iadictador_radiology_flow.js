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

      let raw = await transcribeIfNeeded(textarea);
      raw = norm(raw || textarea.value);

      if (!raw) throw new Error("No hay texto para analizar.");

      window.__iadLastDictatedText = raw;

      setStatus("Analizando plantilla...");

      const analyzeBody = new URLSearchParams();
      analyzeBody.set("texto_bruto", raw);

      const analyzeResponse = await fetch("/iad/analizar-radiologia.json", {
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

      const generateResponse = await fetch("/iad/generar-informe-radiologico.json", {
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

      window.__iadLastGenerated = generated;

      setStatus("Informe generado en esta misma página.");
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
})();
