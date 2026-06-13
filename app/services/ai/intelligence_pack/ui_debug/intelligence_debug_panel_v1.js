// Copia transferible extraida desde app/static/iadictador_work_v2.js
// Nota: hoy runtime aun usa iadictador_work_v2.js; esta copia sirve para exportar/auditar/refactorizar.

// IAD_INTELLIGENCE_DEBUG_PANEL_V1
(function () {
  "use strict";

  if (window.__iadIntelligenceDebugPanelV1) return;
  window.__iadIntelligenceDebugPanelV1 = true;

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

  function installCss() {
    if (document.getElementById("iad-intelligence-debug-style-v1")) return;

    const st = document.createElement("style");
    st.id = "iad-intelligence-debug-style-v1";
    st.textContent = `
      #iad-intelligence-debug-panel {
        margin-top: 10px;
        border: 1px solid rgba(148,163,184,.20);
        border-radius: 12px;
        background: #071223;
        color: #dbeafe;
        padding: 10px;
      }

      #iad-intelligence-debug-panel summary {
        cursor: pointer;
        font-weight: 700;
        color: #bfdbfe;
      }

      #iad-intelligence-debug-panel pre {
        white-space: pre-wrap;
        overflow: auto;
        max-height: 420px;
        border-radius: 10px;
        padding: 10px;
        background: rgba(0,0,0,.20);
        border: 1px solid rgba(148,163,184,.16);
        font-size: .82rem;
      }

      #iad-intelligence-debug-panel .iad-debug-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        margin: 10px 0;
      }

      #iad-intelligence-debug-panel .iad-debug-card {
        border: 1px solid rgba(148,163,184,.16);
        border-radius: 10px;
        padding: 8px;
        background: rgba(15,23,42,.70);
      }

      #iad-intelligence-debug-panel .iad-debug-card strong {
        display: block;
        color: #93c5fd;
        margin-bottom: 4px;
      }

      @media(max-width:800px) {
        #iad-intelligence-debug-panel .iad-debug-grid {
          grid-template-columns: 1fr;
        }
      }
    `;
    document.head.appendChild(st);
  }

  function findFinalPanel() {
    return document.getElementById("iad-real-final-panel")
      || document.getElementById("iad-native-final-panel")
      || document.querySelector("main")
      || document.body;
  }

  function renderDebug(data) {
    installCss();

    const editor = data && data.intelligence_editor ? data.intelligence_editor : {};
    const map = data && data.mapa_aplicacion ? data.mapa_aplicacion : [];
    const structured = data && data.hallazgos_estructurados ? data.hallazgos_estructurados : [];
    const warnings = data && data.advertencias ? data.advertencias : [];

    let panel = document.getElementById("iad-intelligence-debug-panel");
    if (!panel) {
      panel = document.createElement("details");
      panel.id = "iad-intelligence-debug-panel";
      panel.open = false;
      const host = findFinalPanel();
      if (host && host.parentElement && host.id === "iad-real-final-panel") {
        host.parentElement.insertBefore(panel, host.nextSibling);
      } else {
        host.appendChild(panel);
      }
    }

    const ok = editor && editor.ok ? "sí" : "no";
    const model = editor.model || "—";
    const method = data.metodo || data.method || "—";
    const confidence = (data.plantilla_sugerida && data.plantilla_sugerida.confianza) || editor.confianza || data.confianza || "—";

    panel.innerHTML = `
      <summary>Depuración IA / inteligencia transferible</summary>

      <div class="iad-debug-grid">
        <div class="iad-debug-card"><strong>Editor inteligente activo</strong>${esc(ok)}</div>
        <div class="iad-debug-card"><strong>Modelo</strong>${esc(model)}</div>
        <div class="iad-debug-card"><strong>Método final</strong>${esc(method)}</div>
        <div class="iad-debug-card"><strong>Confianza</strong>${esc(confidence)}</div>
        <div class="iad-debug-card"><strong>Score antes</strong>${esc(editor.before_score || "—")}</div>
        <div class="iad-debug-card"><strong>Score después</strong>${esc(editor.after_score || "—")}</div>
      </div>

      <h4>Mapa de aplicación</h4>
      <pre>${esc(map)}</pre>

      <h4>Hallazgos estructurados</h4>
      <pre>${esc(structured)}</pre>

      <h4>Advertencias</h4>
      <pre>${esc(warnings)}</pre>

      <h4>Informe IA original previo</h4>
      <pre>${esc(data.informe_final_modelo || "")}</pre>

      <h4>Informe determinístico fallback</h4>
      <pre>${esc(data.informe_final_deterministico || "")}</pre>
    `;
  }

  const oldFetch = window.fetch;
  if (typeof oldFetch === "function" && !oldFetch.__iadDebugWrappedV1) {
    const wrapped = async function () {
      const args = arguments;
      const res = await oldFetch.apply(this, args);

      try {
        const clone = res.clone();
        const ct = clone.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          clone.json().then(function (data) {
            setTimeout(function () { renderDebug(data); }, 150);
            setTimeout(function () { renderDebug(data); }, 800);
          }).catch(function () {});
        }
      } catch (e) {}

      return res;
    };
    wrapped.__iadDebugWrappedV1 = true;
    window.fetch = wrapped;
  }

  window.IAD_RENDER_INTELLIGENCE_DEBUG = renderDebug;
})();
