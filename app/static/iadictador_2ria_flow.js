(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  function norm(txt) {
    return String(txt || "").trim();
  }

  function buttonText(btn) {
    return norm(btn.innerText || btn.value || btn.textContent);
  }

  function findButtonByText(regex) {
    const buttons = Array.from(document.querySelectorAll("button, input[type='submit'], input[type='button']"));
    return buttons.find((btn) => regex.test(buttonText(btn)));
  }

  function findMainTextarea() {
    const areas = Array.from(document.querySelectorAll("textarea")).filter((el) => {
      const rect = el.getBoundingClientRect();
      return rect.width > 100 && rect.height > 50;
    });

    if (!areas.length) return null;

    areas.sort((a, b) => {
      const av = (a.rows || 0) * 1000 + a.getBoundingClientRect().height + norm(a.value).length;
      const bv = (b.rows || 0) * 1000 + b.getBoundingClientRect().height + norm(b.value).length;
      return bv - av;
    });

    return areas[0];
  }

  function findForm(el) {
    if (!el) return document.querySelector("form");
    return el.closest("form") || document.querySelector("form");
  }

  function createPanelAfter(target) {
    if (document.getElementById("iad-2ria-panel")) return;

    const panel = document.createElement("section");
    panel.id = "iad-2ria-panel";
    panel.className = "iad-2ria-panel";

    panel.innerHTML = `
      <h2>2) Información extra</h2>
      <p class="iad-muted">
        Información detectada desde el texto o audio transcrito. Revisa y corrige antes del procesamiento final.
      </p>

      <div id="iad-2ria-status" class="iad-2ria-status">
        Sin extracción todavía.
      </div>

      <div class="iad-2ria-grid">
        <div class="iad-2ria-box">
          <h3>Plantilla sugerida</h3>
          <label>Plantilla</label>
          <input id="iad-2ria-plantilla" type="text" placeholder="Plantilla sugerida por IA">
          <label>Confianza</label>
          <input id="iad-2ria-confianza" type="text" placeholder="alta / media / baja">
          <label>Motivo</label>
          <textarea id="iad-2ria-motivo-plantilla" rows="2"></textarea>
        </div>

        <div class="iad-2ria-box">
          <h3>Datos secundarios</h3>
          <label>Paciente</label>
          <input id="iad-2ria-paciente" type="text">
          <label>Edad</label>
          <input id="iad-2ria-edad" type="text">
          <label>Sexo</label>
          <input id="iad-2ria-sexo" type="text">
          <label>Ocupación / lugar de trabajo</label>
          <input id="iad-2ria-ocupacion" type="text">
          <label>Institución / lugar</label>
          <input id="iad-2ria-institucion" type="text">
          <label>Motivo del examen</label>
          <textarea id="iad-2ria-motivo" rows="2"></textarea>
          <label>Antecedentes</label>
          <textarea id="iad-2ria-antecedentes" rows="2"></textarea>
        </div>

        <div class="iad-2ria-box iad-2ria-wide">
          <h3>Hallazgos radiológicos detectados</h3>
          <textarea id="iad-2ria-hallazgos" rows="8"></textarea>
        </div>

        <div class="iad-2ria-box iad-2ria-wide">
          <h3>Advertencias</h3>
          <ul id="iad-2ria-advertencias">
            <li>Sin advertencias.</li>
          </ul>
        </div>
      </div>

      <h2>3) Confluencia</h2>
      <p class="iad-muted">
        Después de revisar la información principal y la información extra, usa este botón para generar el resultado final.
      </p>
      <button type="button" id="iad-2ria-procesar-confirmado" class="iad-btn iad-btn-primary">
        Procesar hallazgos e información 2ria
      </button>
    `;

    const anchor = target.closest("section, .card, .iad-card, div") || target;
    anchor.insertAdjacentElement("afterend", panel);
  }

  function setVal(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value || "";
  }

  function getVal(id) {
    const el = document.getElementById(id);
    return el ? norm(el.value) : "";
  }

  function setStatus(text) {
    const el = document.getElementById("iad-2ria-status");
    if (el) el.textContent = text;
  }

  function fillExtraction(extraction) {
    const plantilla = extraction.plantilla_sugerida || {};
    const info = extraction.informacion_secundaria || {};

    setVal("iad-2ria-plantilla", plantilla.nombre || "");
    setVal("iad-2ria-confianza", plantilla.confianza || "");
    setVal("iad-2ria-motivo-plantilla", plantilla.motivo || "");

    setVal("iad-2ria-paciente", info.paciente_nombre_completo || "");
    setVal("iad-2ria-edad", info.edad || "");
    setVal("iad-2ria-sexo", info.sexo || "");
    setVal("iad-2ria-ocupacion", info.ocupacion_lugar_trabajo || "");
    setVal("iad-2ria-institucion", info.institucion_lugar || "");
    setVal("iad-2ria-motivo", info.motivo_examen || "");
    setVal("iad-2ria-antecedentes", info.antecedentes || "");
    setVal("iad-2ria-hallazgos", extraction.hallazgos_radiologicos || "");

    const ul = document.getElementById("iad-2ria-advertencias");
    if (ul) {
      ul.innerHTML = "";
      const warnings = Array.isArray(extraction.advertencias) ? extraction.advertencias : [];
      if (!warnings.length) {
        const li = document.createElement("li");
        li.textContent = "Sin advertencias.";
        ul.appendChild(li);
      } else {
        warnings.forEach((warning) => {
          const li = document.createElement("li");
          li.textContent = String(warning);
          ul.appendChild(li);
        });
      }
    }
  }

  function getAudioFileCount() {
    let n = 0;
    document.querySelectorAll("input[type='file']").forEach((input) => {
      if (input.files) n += input.files.length;
    });
    return n;
  }

  async function waitForTextareaChange(textarea, before, timeoutMs) {
    const start = Date.now();

    while (Date.now() - start < timeoutMs) {
      const current = norm(textarea.value);
      if (current && current !== before) return current;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    return norm(textarea.value);
  }

  async function transcribeIfPossible(textarea) {
    const transcribeBtn = findButtonByText(/transcribir\s+todos/i);
    const audioCount = getAudioFileCount();

    if (!transcribeBtn || audioCount === 0) {
      return norm(textarea.value);
    }

    const before = norm(textarea.value);
    setStatus("Transcribiendo audio(s)...");

    transcribeBtn.click();

    const after = await waitForTextareaChange(textarea, before, 90000);

    if (after && after !== before) {
      setStatus("Audio transcrito. Extrayendo información 2ria...");
      return after;
    }

    setStatus("No se detectó cambio en la transcripción. Se usará el texto visible actual.");
    return norm(textarea.value);
  }

  async function extractSecondary(options) {
    const textarea = findMainTextarea();
    if (!textarea) {
      alert("No encontré el cuadro de texto principal.");
      return null;
    }

    options = options || {};
    const shouldTranscribe = options.transcribe !== false;

    let raw = "";
    if (shouldTranscribe) {
      raw = await transcribeIfPossible(textarea);
    } else {
      raw = norm(textarea.value);
    }

    raw = norm(raw || textarea.value);

    if (!raw) {
      alert("No hay texto para extraer información. Graba, sube audio o escribe información primero.");
      return null;
    }

    setStatus("Extrayendo información secundaria y plantilla sugerida...");

    const body = new URLSearchParams();
    body.set("texto_bruto", raw);

    const response = await fetch("/iad/extraer-informacion-2ria-v2.json", {
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
      throw new Error(data.error || "Extracción fallida.");
    }

    fillExtraction(data.extraction || {});
    setStatus("Información 2ria extraída. Revisa y corrige antes de procesar.");
    return data.extraction || {};
  }

  function buildStructuredText(originalText) {
    const lines = [];

    lines.push("[PLANTILLA CONFIRMADA]");
    lines.push(getVal("iad-2ria-plantilla") || "No especificada");
    lines.push("");

    lines.push("[INFORMACION SECUNDARIA CONFIRMADA]");
    lines.push("Paciente: " + getVal("iad-2ria-paciente"));
    lines.push("Edad: " + getVal("iad-2ria-edad"));
    lines.push("Sexo: " + getVal("iad-2ria-sexo"));
    lines.push("Ocupación/lugar de trabajo: " + getVal("iad-2ria-ocupacion"));
    lines.push("Institución/lugar: " + getVal("iad-2ria-institucion"));
    lines.push("Motivo del examen: " + getVal("iad-2ria-motivo"));
    lines.push("Antecedentes: " + getVal("iad-2ria-antecedentes"));
    lines.push("");

    lines.push("[HALLAZGOS RADIOLOGICOS CONFIRMADOS]");
    lines.push(getVal("iad-2ria-hallazgos") || originalText || "");
    lines.push("");

    lines.push("[TEXTO BRUTO ORIGINAL]");
    lines.push(originalText || "");

    return lines.join("\n").trim();
  }

  function submitOriginalProcess(originalProcessBtn) {
    const textarea = findMainTextarea();
    if (!textarea) {
      alert("No encontré el cuadro de texto principal.");
      return;
    }

    const originalText = norm(textarea.value);
    const structured = buildStructuredText(originalText);

    textarea.dataset.iadTextoOriginal = originalText;
    textarea.value = structured;

    window.__iadAllowOriginalProcess = true;
    originalProcessBtn.click();

    setTimeout(() => {
      window.__iadAllowOriginalProcess = false;
    }, 3000);
  }

  function setupButtons() {
    const textarea = findMainTextarea();
    if (!textarea) return;

    createPanelAfter(textarea);

    const originalProcessBtn = findButtonByText(/^procesar$/i) || findButtonByText(/procesar/i);
    if (!originalProcessBtn) {
      setStatus("No encontré botón Procesar original.");
      return;
    }

    originalProcessBtn.dataset.iadOriginalProcess = "1";
    if (originalProcessBtn.tagName === "INPUT") {
      originalProcessBtn.value = "Procesar todo rápido";
    } else {
      originalProcessBtn.textContent = "Procesar todo rápido";
    }

    const extraBtn = document.createElement("button");
    extraBtn.type = "button";
    extraBtn.id = "iad-2ria-extraer-btn";
    extraBtn.className = "iad-btn iad-btn-secondary";
    extraBtn.textContent = "Extraer información 2ria";

    originalProcessBtn.insertAdjacentElement("afterend", extraBtn);

    extraBtn.addEventListener("click", async () => {
      try {
        await extractSecondary({ transcribe: true });
      } catch (err) {
        console.error(err);
        setStatus("Error extrayendo información 2ria.");
        alert("Error extrayendo información 2ria: " + err.message);
      }
    });

    const confirmedBtn = document.getElementById("iad-2ria-procesar-confirmado");
    if (confirmedBtn) {
      confirmedBtn.addEventListener("click", () => {
        submitOriginalProcess(originalProcessBtn);
      });
    }

    originalProcessBtn.addEventListener("click", async (ev) => {
      if (window.__iadAllowOriginalProcess) return;

      ev.preventDefault();
      ev.stopPropagation();

      try {
        setStatus("Procesamiento rápido: transcribir, extraer y procesar...");
        await extractSecondary({ transcribe: true });
        submitOriginalProcess(originalProcessBtn);
      } catch (err) {
        console.error(err);
        setStatus("Error en procesamiento rápido.");
        alert("Error en procesamiento rápido: " + err.message);
      }
    }, true);
  }

  ready(setupButtons);
})();
