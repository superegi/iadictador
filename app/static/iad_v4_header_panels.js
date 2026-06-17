(function iadV4HeaderPanels() {

  function iadV4PanelsAllowedPage() {
    const path = window.location.pathname || "";
    return path === "/iad/trabajo" || path === "/iad/work" || path.endsWith("/iad/trabajo");
  }

  function iadV4RemovePanelsIfWrongPage() {
    if (iadV4PanelsAllowedPage()) return false;

    [
      "iad-v4-header-panels",
      "iad-v4-admin-panel",
      "iad-v4-warning-panel",
      "iad-v4-warnings-panel",
      "iad-v4-metadata-panel"
    ].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.remove();
    });

    return true;
  }

  if (iadV4RemovePanelsIfWrongPage()) {
    return;
  }

  const AUDIO_ENDPOINT = "/iad/api/audio/procesar-dictado-completo.json";
  const STORAGE_KEY = "iad_v4_last_result_header_panels";

  function saveResult(data) {
    if (!data || typeof data !== "object") return;

    window.__iad_v4_last_result_header_panels = data;

    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch (e) {}

    scheduleRender();
  }

  function loadResult() {
    if (window.__iad_v4_last_result_header_panels) {
      return window.__iad_v4_last_result_header_panels;
    }

    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function norm(value) {
    return String(value || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
  }

  function getText(el) {
    if (!el) return "";
    return el.isContentEditable ? (el.innerText || "") : (el.value || "");
  }

  function setText(el, value) {
    if (!el) return;

    if (el.isContentEditable) {
      el.innerText = value;
    } else {
      el.value = value;
    }

    try {
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (e) {}
  }

  function findFinalReportBox() {
    const candidates = Array.from(document.querySelectorAll("textarea, [contenteditable='true']"));

    const scored = candidates.map(el => {
      const value = getText(el);
      const nvalue = norm(value);

      const idText = norm([
        el.id || "",
        el.name || "",
        el.placeholder || "",
        el.getAttribute("aria-label") || ""
      ].join(" "));

      const container = el.closest("section, article, fieldset, div") || el.parentElement || el;
      const containerText = norm((container.textContent || "").slice(0, 1600));

      let score = 0;

      if (!value.trim()) score -= 600;

      if (nvalue.includes("hallazgos")) score += 120;
      if (nvalue.includes("impresion diagnostica") || nvalue.includes("impresion dianostica")) score += 120;
      if (nvalue.includes("antecedentes")) score += 50;
      if (nvalue.includes("centro al que")) score += 140;
      if (nvalue.includes("paciente:")) score += 80;
      if (nvalue.includes("edad:")) score += 80;

      if (idText.includes("final")) score += 120;
      if (idText.includes("informe") || idText.includes("report")) score += 80;
      if (containerText.includes("informe final")) score += 120;
      if (containerText.includes("editable")) score += 60;

      if (containerText.includes("datos administrativos fuera del informe")) score -= 350;
      if (containerText.includes("advertencias / inconsistencias")) score -= 350;
      if (containerText.includes("texto complementario")) score -= 350;
      if (containerText.includes("informacion principal")) score -= 350;
      if (containerText.includes("texto transcrito")) score -= 200;
      if (containerText.includes("reglas")) score -= 200;
      if (containerText.includes("json")) score -= 200;

      score += Math.min(80, Math.floor(value.length / 120));

      return { el, score, value };
    }).filter(x => x.value.trim());

    scored.sort((a, b) => b.score - a.score);

    return scored[0]?.score > 0 ? scored[0].el : null;
  }

  function captureBlock(text, labelRegex, nextRegex) {
    const re = new RegExp(
      labelRegex + "\\s*\\n?([\\s\\S]*?)(?=\\n\\s*(?:" + nextRegex + ")\\s*:?\\s*(?:\\n|$)|$)",
      "i"
    );

    const m = String(text || "").match(re);
    return m ? String(m[1] || "").trim() : "";
  }

  function extractAdminFromReport(report) {
    const text = String(report || "").replace(/\r\n/g, "\n");

    return {
      centro: captureBlock(
        text,
        "Centro\\s+al\\s+que\\s+(?:corresponde\\s+el\\s+estudio|se\\s+est[áa]?\\s+dictando)\\s*:",
        "Paciente|Edad|Estudio|Antecedentes|Hallazgos|Impresi[oó]n"
      ),
      paciente: captureBlock(
        text,
        "Paciente\\s*:",
        "Edad|Estudio|Antecedentes|Hallazgos|Impresi[oó]n"
      ),
      edad: captureBlock(
        text,
        "Edad\\s*:",
        "Estudio|Antecedentes|Hallazgos|Impresi[oó]n"
      )
    };
  }

  function removeLeadingBlock(text, labelRegex, nextRegex) {
    const re = new RegExp(
      "^\\s*" + labelRegex + "\\s*\\n?[\\s\\S]*?(?=\\n\\s*(?:" + nextRegex + ")\\s*:?\\s*(?:\\n|$)|$)",
      "i"
    );

    return String(text || "").replace(re, "");
  }

  function cleanReport(report) {
    let text = String(report || "").replace(/\r\n/g, "\n").trimStart();

    const next = "Centro\\s+al\\s+que\\s+(?:corresponde\\s+el\\s+estudio|se\\s+est[áa]?\\s+dictando)|Paciente|Edad|Estudio|Antecedentes|Hallazgos|Impresi[oó]n\\s+diagn[oó]stica|Impresi[oó]n\\s+dian[oó]stica";

    let previous = "";
    let guard = 0;

    while (text !== previous && guard < 10) {
      previous = text;

      text = removeLeadingBlock(
        text,
        "Centro\\s+al\\s+que\\s+(?:corresponde\\s+el\\s+estudio|se\\s+est[áa]?\\s+dictando)\\s*:",
        next
      ).trimStart();

      text = removeLeadingBlock(
        text,
        "Paciente\\s*:",
        next
      ).trimStart();

      text = removeLeadingBlock(
        text,
        "Edad\\s*:",
        next
      ).trimStart();

      guard += 1;
    }

    // Sacar solo la etiqueta Estudio:, conservando el título del estudio.
    text = text.replace(/^\s*Estudio\s*:\s*\n?/i, "");

    // Sacar advertencias VERIFICAR del cuerpo si el modelo las dejó al final.
    const lines = text.split("\n");
    const kept = [];
    const warnings = [];

    for (const line of lines) {
      const clean = line.trim();
      if (/^(?:[-•]\s*)?VERIFICAR\s*\{.*?\}\s*:/i.test(clean)) {
        warnings.push(clean.replace(/^[-•]\s*/, ""));
      } else {
        kept.push(line);
      }
    }

    text = kept.join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .trimStart()
      .trimEnd();

    // Mantener separación visual entre antecedentes y hallazgos.
    text = text.replace(
      /(Antecedentes:\s*\n[^\n]+)\n(Hallazgos:)/i,
      "$1\n\n$2"
    );

    return {
      report: text,
      warnings
    };
  }

  function adminText(data, currentReport) {
    const m = data?.metadata_clinica || {};
    const parsed = extractAdminFromReport(currentReport);

    const centro = parsed.centro || m.centro || "";
    const paciente = parsed.paciente || m.nombre_paciente || m.paciente || "";
    const edad = parsed.edad || m.edad || "";

    return [
      `Centro: ${centro}`,
      `Paciente: ${paciente}`,
      `Edad: ${edad}`
    ].join("\n");
  }

  function warningText(data, extractedWarnings) {
    const arr = [];

    if (Array.isArray(extractedWarnings)) arr.push(...extractedWarnings);

    if (Array.isArray(data?.advertencias)) arr.push(...data.advertencias);
    if (Array.isArray(data?.posibles_omisiones)) arr.push(...data.posibles_omisiones);
    if (Array.isArray(data?.puntos_conflictivos)) arr.push(...data.puntos_conflictivos);
    if (Array.isArray(data?.puntos_conflictivos_detectados)) arr.push(...data.puntos_conflictivos_detectados);

    const clinicalCandidates = [
      data?.clinical_json,
      data?.extraccion_ia,
      data?.json_clinico
    ];

    clinicalCandidates.forEach(obj => {
      if (!obj || typeof obj !== "object") return;
      if (Array.isArray(obj.advertencias)) arr.push(...obj.advertencias);
      if (Array.isArray(obj.posibles_omisiones)) arr.push(...obj.posibles_omisiones);
      if (Array.isArray(obj.puntos_conflictivos)) arr.push(...obj.puntos_conflictivos);
    });

    const clean = [...new Set(
      arr
        .map(x => typeof x === "string" ? x : JSON.stringify(x))
        .map(x => x.trim())
        .filter(Boolean)
    )];

    if (!clean.length) return "Sin advertencias";

    return clean.map(x => "• " + x).join("\n");
  }

  function adminPanelHtml(data, currentReport) {
    return `
      <section id="iad-v4-admin-panel" class="iad-v4-admin-panel">
        <h3>Datos administrativos fuera del informe</h3>
        <textarea id="iad-v4-admin-copy-edit" class="iad-v4-admin-textarea" rows="3" spellcheck="false">${esc(adminText(data || {}, currentReport))}</textarea>
      </section>
    `;
  }

  function warningPanelHtml(data, warnings) {
    return `
      <section id="iad-v4-warning-panel" class="iad-v4-warning-panel" contenteditable="false">
        <h3>Advertencias / inconsistencias / omisiones</h3>
        <pre id="iad-v4-warning-copy-text" class="iad-v4-warning-text">${esc(warningText(data || {}, warnings))}</pre>
      </section>
    `;
  }

  function removeOldPanels() {
    [
      "iad-v4-header-panels",
      "iad-v4-admin-panel",
      "iad-v4-warning-panel",
      "iad-v4-warnings-panel",
      "iad-v4-metadata-panel"
    ].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.remove();
    });
  }

  function autosizeReportBox(el) {
    if (!el || el.isContentEditable) return;

    el.classList.add("iad-v4-final-report-autosize");

    function resize() {
      el.style.height = "auto";
      el.style.height = Math.max(260, el.scrollHeight + 10) + "px";
    }

    resize();

    if (!el.__iadV4AutosizeBound) {
      el.__iadV4AutosizeBound = true;
      el.addEventListener("input", resize);
      el.addEventListener("change", resize);
    }
  }

  function render(data) {
    if (!iadV4PanelsAllowedPage()) return false;
    const reportBox = findFinalReportBox();
    if (!reportBox) return false;

    const originalReport = getText(reportBox);
    const cleaned = cleanReport(originalReport);

    removeOldPanels();

    if (cleaned.report && cleaned.report !== originalReport) {
      setText(reportBox, cleaned.report);
    }

    reportBox.insertAdjacentHTML("beforebegin", adminPanelHtml(data || {}, originalReport));
    reportBox.insertAdjacentHTML("afterend", warningPanelHtml(data || {}, cleaned.warnings));

    autosizeReportBox(reportBox);

    return true;
  }

  function renderCurrent() {
    const data = loadResult() || {};
    return render(data);
  }

  function scheduleRender() {
    if (!iadV4PanelsAllowedPage()) return;
    [100, 300, 700, 1200, 2000].forEach(ms => {
      setTimeout(renderCurrent, ms);
    });
  }

  if (!window.__iad_v4_header_panels_fetch_wrapped) {
    window.__iad_v4_header_panels_fetch_wrapped = true;
    const originalFetch = window.fetch;

    window.fetch = async function iadV4HeaderPanelsFetch(input, init) {
      const url = (typeof input === "string") ? input : (input && input.url) || "";
      const response = await originalFetch.apply(this, arguments);

      if (url.includes(AUDIO_ENDPOINT)) {
        try {
          response.clone().json().then(saveResult).catch(() => scheduleRender());
        } catch (e) {
          scheduleRender();
        }
      }

      return response;
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scheduleRender);
  } else {
    scheduleRender();
  }

  // Refuerzo para casos donde otro JS llena el textarea después.
  let ticks = 0;
  const interval = setInterval(() => {
    ticks += 1;
    renderCurrent();
    if (ticks >= 30) clearInterval(interval);
  }, 1000);

  window.iadV4RenderHeaderPanels = renderCurrent;
})();
