// Copia transferible extraida desde app/static/iadictador_work_v2.js
// Nota: hoy runtime aun usa iadictador_work_v2.js; esta copia sirve para exportar/auditar/refactorizar.

// IAD_STRUCTURED_MAPPER_DEBUG_V5
(function () {
  "use strict";

  if (window.__iadStructuredMapperDebugV5) return;
  window.__iadStructuredMapperDebugV5 = true;

  function txt(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v;
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); }
  }

  function esc(s) {
    return txt(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function ensurePanel() {
    let panel = document.getElementById("iad-structured-mapper-debug-v5");
    if (!panel) {
      panel = document.createElement("details");
      panel.id = "iad-structured-mapper-debug-v5";
      panel.style.marginTop = "10px";
      panel.style.border = "1px solid rgba(125,211,252,.22)";
      panel.style.borderRadius = "12px";
      panel.style.padding = "10px";
      panel.style.background = "#071223";
      panel.style.color = "#dbeafe";

      const host = document.getElementById("iad-intelligence-debug-panel")
        || document.getElementById("iad-real-final-panel")
        || document.querySelector("main")
        || document.body;

      if (host && host.parentElement && host.id !== "iad-real-final-panel") {
        host.parentElement.insertBefore(panel, host.nextSibling);
      } else {
        host.appendChild(panel);
      }
    }
    return panel;
  }

  function render(data) {
    if (!data || !data.structured_mapper) return;

    const panel = ensurePanel();
    const sm = data.structured_mapper || {};

    panel.innerHTML = `
      <summary><strong>Structured mapper / aplicación real al informe</strong></summary>
      <p><strong>Aplicó cambios:</strong> ${esc(sm.ok ? "sí" : "no")}</p>
      <p><strong>Hallazgos detectados:</strong> ${esc(sm.findings_count || 0)}</p>
      <h4>Líneas de cuerpo generadas</h4>
      <pre style="white-space:pre-wrap;max-height:280px;overflow:auto;background:rgba(0,0,0,.25);padding:10px;border-radius:10px;">${esc(sm.body_lines || [])}</pre>
      <h4>Líneas insertadas</h4>
      <pre style="white-space:pre-wrap;max-height:280px;overflow:auto;background:rgba(0,0,0,.25);padding:10px;border-radius:10px;">${esc(sm.inserted || [])}</pre>
    `;
  }

  const oldFetch = window.fetch;
  if (typeof oldFetch === "function" && !oldFetch.__iadStructuredMapperDebugWrappedV5) {
    const wrapped = async function () {
      const args = arguments;
      const res = await oldFetch.apply(this, args);

      try {
        const clone = res.clone();
        const ct = clone.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          clone.json().then(function (data) {
            setTimeout(function () { render(data); }, 180);
            setTimeout(function () { render(data); }, 900);
          }).catch(function () {});
        }
      } catch (e) {}

      return res;
    };
    wrapped.__iadStructuredMapperDebugWrappedV5 = true;
    window.fetch = wrapped;
  }

  window.IAD_RENDER_STRUCTURED_MAPPER_DEBUG_V5 = render;
})();
