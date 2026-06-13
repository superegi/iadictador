(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
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

  function allButtons() {
    return Array.from(document.querySelectorAll("button, input[type='submit'], input[type='button']"));
  }

  function findButton(regex) {
    return allButtons().find(function (btn) {
      return regex.test(textOf(btn));
    });
  }

  function hideElement(el) {
    if (el) {
      el.style.display = "none";
      el.setAttribute("aria-hidden", "true");
    }
  }

  function showElement(el) {
    if (el) {
      el.style.display = "";
      el.removeAttribute("aria-hidden");
    }
  }

  function closestBlock(el) {
    if (!el) return null;
    return el.closest("section, .iad-card, .card, .panel, .box, form, div");
  }

  function getOtId() {
    const m = window.location.pathname.match(/\/ot\/(\d+)/i);
    if (m) return m[1];

    const txt = document.body ? document.body.innerText : "";
    const m2 = txt.match(/OT\s*#\s*(\d+)/i);
    if (m2) return m2[1];

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

  function confidencePercent(confidence) {
    const c = String(confidence || "").toLowerCase();

    if (c.includes("alta")) return "90%";
    if (c.includes("media")) return "65%";
    if (c.includes("baja")) return "35%";

    const n = parseFloat(c.replace(",", "."));
    if (!Number.isNaN(n)) {
      if (n <= 1) return Math.round(n * 100) + "%";
      return Math.round(n) + "%";
    }

    return "";
  }

  function hideOldSections() {
    allButtons().forEach(function (btn) {
      const t = textOf(btn);

      if (/^Procesar$/i.test(t)) hideElement(btn);
      if (/Transcribir\s+todos/i.test(t)) hideElement(btn);
      if (/Procesar\s+todo\s+r[aá]pido/i.test(t)) hideElement(btn);
      if (/Procesar\s+con\s+datos\s+extra/i.test(t)) hideElement(btn);
      if (/Generar\s+informe\s+con\s+plantilla/i.test(t)) hideElement(btn);
      if (/Extraer\s+informaci[oó]n/i.test(t)) hideElement(btn);
    });

    hideElement(document.getElementById("iad-extraction-card"));
    hideElement(document.getElementById("iad-2ria-panel"));

    Array.from(document.querySelectorAll("h1, h2, h3, summary, strong, legend")).forEach(function (h) {
      const t = textOf(h);

      if (/^2\)\s*Informaci[oó]n extra/i.test(t)) hideElement(closestBlock(h));
      if (/^3\)\s*Confluencia/i.test(t)) hideElement(closestBlock(h));
      if (/Plantilla de trabajo/i.test(t)) hideElement(closestBlock(h));
      if (/Lugar\s*\/\s*instituci[oó]n/i.test(t)) hideElement(closestBlock(h));
      if (/Datos del paciente/i.test(t)) hideElement(closestBlock(h));

      // Ocultar paneles anteriores de radiología, pero no el panel nuevo.
      if (/Plantilla detectada/i.test(t) || /^2\)\s*An[aá]lisis radiol[oó]gico IA/i.test(t)) {
        const block = closestBlock(h);
        if (block && block.id !== "iad-rad-one-step-panel") hideElement(block);
      }
    });

    Array.from(document.querySelectorAll("section, .iad-card, .card")).forEach(function (el) {
      if (el.id === "iad-rad-one-step-panel") return;

      const t = textOf(el).slice(0, 1200);

      if (/Opcional\. Se guarda junto a la OT/i.test(t)) hideElement(el);
      if (/Plantilla de trabajo/i.test(t) && /Recargar plantilla/i.test(t)) hideElement(el);
      if (/Paso intermedio: detectar plantilla sugerida/i.test(t)) hideElement(el);
      if (/Plantilla sugerida/i.test(t) && /Hallazgos radiol[oó]gicos detectados/i.test(t)) hideElement(el);
    });
  }

  function isInsideOurPanel(el) {
    return !!(el && el.closest("#iad-rad-one-step-panel"));
  }

  function findSourceTextarea() {
    const candidates = Array.from(document.querySelectorAll("textarea"))
      .filter(visible)
      .filter(function (el) {
        if (isInsideOurPanel(el)) return false;

        const idname = norm(el.id + " " + el.name + " " + el.placeholder);
        if (/iad-rad|iad-2ria|extraccion|extraction|plantilla|hallazgo|resultado|informe final|primary|revisado/i.test(idname)) {
          return false;
        }

        return true;
      });

    if (!candidates.length) return null;

    candidates.sort(function (a, b) {
      const av = norm(a.value).length;
      const bv = norm(b.value).length;

      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();

      let as = av * 10 + ar.width + ar.height;
      let bs = bv * 10 + br.width + br.height;

      const at = textOf(a.closest("section, .iad-card, .card, div")).slice(0, 900);
      const bt = textOf(b.closest("section, .iad-card, .card, div")).slice(0, 900);

      if (/Informaci[oó]n principal para el informe/i.test(at)) as += 100000;
      if (/Informaci[oó]n principal para el informe/i.test(bt)) bs += 100000;

      if (/Ingreso/i.test(at)) as += 50000;
      if (/Ingreso/i.test(bt)) bs += 50000;

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
      await new Promise(function (resolve) { setTimeout(resolve, 1000); });
    }

    return norm(textarea.value);
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

  function createAnalyzeButtonAtEndOfInput(textarea) {
    let btn = document.getElementById("iad-rad-one-analyze");
    if (btn) return btn;

    const oldAnalyze = findButton(/Analizar\s+radiolog[ií]a/i);
    if (oldAnalyze) hideElement(oldAnalyze);

    btn = document.createElement("button");
    btn.type = "button";
    btn.id = "iad-rad-one-analyze";
    btn.className = "iad-btn iad-btn-primary iad-rad-one-main-btn";
    btn.textContent = "Analizar radiología";

    const inputBlock = textarea.closest("section, .iad-card, .card, form, div") || textarea.parentElement;

    let actions = document.getElementById("iad-rad-one-input-actions");
    if (!actions) {
      actions = document.createElement("div");
      actions.id = "iad-rad-one-input-actions";
      actions.className = "iad-rad-one-input-actions";
      textarea.insertAdjacentElement("afterend", actions);
    }

    actions.appendChild(btn);

    return btn;
  }

  function createOneStepPanel(textarea) {
    let panel = document.getElementById("iad-rad-one-step-panel");
    if (panel) return panel;

    panel = document.createElement("section");
    panel.id = "iad-rad-one-step-panel";
    panel.className = "iad-rad-one-step-panel";

    panel.innerHTML = `
      <div class="iad-rad-one-card">
        <div id="iad-rad-one-status" class="iad-rad-one-status">
          Pendiente. Escribe o graba y aprieta “Analizar radiología”.
        </div>

        <div id="iad-rad-one-template-box" class="iad-rad-one-template-box" style="display:none;">
          <div>
            <span class="iad-rad-one-label">Plantilla a usar</span>
            <strong id="iad-rad-one-template-name">—</strong>
          </div>
          <div>
            <span class="iad-rad-one-label">Confianza</span>
            <strong id="iad-rad-one-confidence">—</strong>
          </div>
        </div>

        <input id="iad-rad-one-template-id" type="hidden">
        <textarea id="iad-rad-one-hallazgos" style="display:none;"></textarea>

        <div id="iad-rad-one-results" style="display:none;">
          <div class="iad-rad-one-editors">
            <div>
              <label>Resultado primario IA</label>
              <textarea id="iad-rad-one-primary-report" rows="18" readonly></textarea>
            </div>

            <div>
              <label>Resultado revisado</label>
              <textarea id="iad-rad-one-revised-report" rows="18"></textarea>
            </div>
          </div>

          <div class="iad-rad-one-actions">
            <button type="button" id="iad-rad-one-save" class="iad-btn iad-btn-primary">
              Guardar revisión
            </button>
            <button type="button" id="iad-rad-one-copy" class="iad-btn iad-btn-secondary">
              Copiar resultado revisado
            </button>
          </div>
        </div>
      </div>
    `;

    const inputBlock = textarea.closest("section, .iad-card, .card, form, div") || textarea;
    inputBlock.insertAdjacentElement("afterend", panel);

    return panel;
  }

  async function transcribeIfNeeded(textarea) {
    const transcribeBtn = findButton(/Transcribir\s+todos/i);
    const audioCount = getAudioFileCount();

    if (!transcribeBtn || audioCount === 0) {
      return norm(textarea.value);
    }

    const before = norm(textarea.value);
    setStatus("Transcribiendo audio y luego generando informe...");

    transcribeBtn.click();

    const after = await waitForTextareaChange(textarea, before, 120000);

    if (after && after !== before) {
      return after;
    }

    return norm(textarea.value);
  }

  async function analyzeAndGenerateOneStep() {
    const textarea = findSourceTextarea();

    if (!textarea) {
      alert("No encontré el cuadro principal de texto/transcripción.");
      return;
    }

    const btn = document.getElementById("iad-rad-one-analyze");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Procesando...";
    }

    try {
      let raw = await transcribeIfNeeded(textarea);
      raw = norm(raw || textarea.value);

      if (!raw) {
        alert("No hay texto/audio para analizar.");
        return;
      }

      window.__iadLastDictatedText = raw;

      setStatus("Analizando plantilla y generando informe...");

      const analyzeBody = new URLSearchParams();
      analyzeBody.set("texto_bruto", raw);

      const analyzeResponse = await fetch("/iad/analizar-radiologia.json", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
        },
        body: analyzeBody.toString()
      });

      if (!analyzeResponse.ok) {
        const txt = await analyzeResponse.text();
        throw new Error("Análisis HTTP " + analyzeResponse.status + ": " + txt.slice(0, 300));
      }

      const analysis = await analyzeResponse.json();

      if (analysis.ok === false) {
        throw new Error(analysis.error || "No se pudo analizar radiología.");
      }

      const tpl = analysis.plantilla_sugerida || {};
      const plantillaNombre = norm(tpl.nombre || "");
      const plantillaId = norm(tpl.id || "");
      const hallazgos = norm(analysis.hallazgos_radiologicos || "");

      if (!plantillaNombre && !plantillaId) {
        throw new Error("No se detectó plantilla.");
      }

      if (!hallazgos) {
        throw new Error("No se detectaron hallazgos radiológicos.");
      }

      setText("iad-rad-one-template-name", plantillaNombre || ("ID " + plantillaId));
      setText("iad-rad-one-confidence", (tpl.confianza || "—") + (confidencePercent(tpl.confianza) ? " · " + confidencePercent(tpl.confianza) : ""));
      setValue("iad-rad-one-template-id", plantillaId);
      setValue("iad-rad-one-hallazgos", hallazgos);
      showElement(document.getElementById("iad-rad-one-template-box"));

      window.__iadLastAnalysis = analysis;

      const generateBody = new URLSearchParams();
      generateBody.set("plantilla_nombre", plantillaNombre);
      generateBody.set("plantilla_id", plantillaId);
      generateBody.set("hallazgos", hallazgos);

      const generateResponse = await fetch("/iad/generar-informe-radiologico.json", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
        },
        body: generateBody.toString()
      });

      if (!generateResponse.ok) {
        const txt = await generateResponse.text();
        throw new Error("Generación HTTP " + generateResponse.status + ": " + txt.slice(0, 300));
      }

      const generated = await generateResponse.json();

      if (generated.ok === false) {
        throw new Error(generated.error || "No se pudo generar informe.");
      }

      const report = generated.informe_final || "";

      setValue("iad-rad-one-primary-report", report);
      setValue("iad-rad-one-revised-report", report);
      showElement(document.getElementById("iad-rad-one-results"));

      window.__iadLastGenerated = generated;

      setStatus("Informe generado. Revisa y edita el resultado revisado.");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Analizar radiología";
      }
    }
  }

  async function saveRevision() {
    const textoDictado =
      window.__iadLastDictatedText ||
      norm((findSourceTextarea() || {}).value);

    const plantillaNombre = textOf(document.getElementById("iad-rad-one-template-name"));
    const plantillaId = getValue("iad-rad-one-template-id");
    const hallazgos = getValue("iad-rad-one-hallazgos");
    const primary = getValue("iad-rad-one-primary-report");
    const revised = getValue("iad-rad-one-revised-report");

    if (!primary) {
      alert("No hay resultado primario IA para guardar.");
      return;
    }

    if (!revised) {
      alert("No hay resultado revisado para guardar.");
      return;
    }

    setStatus("Guardando revisión...");

    const meta = {
      url: window.location.href,
      analysis: window.__iadLastAnalysis || null,
      generated: window.__iadLastGenerated || null,
      user_agent: navigator.userAgent,
      saved_at_client: new Date().toISOString()
    };

    const body = new URLSearchParams();
    body.set("ot_id", getOtId());
    body.set("texto_dictado", textoDictado);
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

    const response = await fetch("/iad/guardar-revision-y-historial-v3.json", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
      },
      body: body.toString()
    });

    if (!response.ok) {
      const txt = await response.text();
      throw new Error("HTTP " + response.status + ": " + txt.slice(0, 300));
    }

    const data = await response.json();

    if (!data.ok) {
      throw new Error(data.error || "No se pudo guardar.");
    }

    const sync = data.historial_sync || {};

    if (sync.ok) {
      setStatus("Revisión guardada. Training ID: " + data.sample_id + ". Historial actualizado: OT #" + (data.ot_id || sync.ot_id || ""));
    } else {
      setStatus("Revisión guardada. Training ID: " + data.sample_id + ". Historial no sincronizado: " + (sync.reason || "sin detalle"));
    }
  }

  function copyRevised() {
    const report = document.getElementById("iad-rad-one-revised-report");
    if (!report) return;

    report.focus();
    report.select();

    navigator.clipboard.writeText(report.value || "").then(function () {
      setStatus("Resultado revisado copiado.");
    }).catch(function () {
      document.execCommand("copy");
      setStatus("Resultado revisado copiado.");
    });
  }

  function setupEvents() {
    document.addEventListener("click", async function (ev) {
      const btn = ev.target.closest("button, input[type='button'], input[type='submit']");
      if (!btn) return;

      if (btn.id === "iad-rad-one-analyze") {
        ev.preventDefault();
        ev.stopPropagation();

        try {
          await analyzeAndGenerateOneStep();
        } catch (err) {
          console.error(err);
          setStatus("Error al analizar/generar.");
          alert("Error al analizar radiología: " + err.message);
        }
      }

      if (btn.id === "iad-rad-one-save") {
        ev.preventDefault();
        ev.stopPropagation();

        try {
          await saveRevision();
        } catch (err) {
          console.error(err);
          setStatus("Error al guardar revisión.");
          alert("Error al guardar revisión: " + err.message);
        }
      }

      if (btn.id === "iad-rad-one-copy") {
        ev.preventDefault();
        ev.stopPropagation();
        copyRevised();
      }
    }, true);
  }

  function setup() {
    hideOldSections();

    const textarea = findSourceTextarea();
    if (!textarea) {
      console.warn("[IAD] No encontré textarea fuente.");
      return;
    }

    createAnalyzeButtonAtEndOfInput(textarea);
    createOneStepPanel(textarea);
    setupEvents();

    console.log("[IAD] UI radiología un paso cargada.");
  }

  ready(setup);
})();
