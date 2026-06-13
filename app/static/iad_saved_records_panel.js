(function () {
  "use strict";

  const path = window.location.pathname;

  if (!(path.includes("/iad/historial") || path.includes("/iad/training"))) {
    return;
  }

  function esc(value) {
    return String(value || "").replace(/[<>&"]/g, function (c) {
      return {"<":"&lt;", ">":"&gt;", "&":"&amp;", '"':"&quot;"}[c];
    });
  }

  function short(value, n) {
    value = String(value || "");
    if (value.length <= n) return value;
    return value.slice(0, n) + "…";
  }

  function panelStyle() {
    if (document.getElementById("iad-saved-panel-style")) return;

    const style = document.createElement("style");
    style.id = "iad-saved-panel-style";
    style.textContent = `
      .iad-saved-panel {
        margin: 18px 0;
        padding: 16px;
        border: 1px solid #31445f;
        border-radius: 18px;
        background: #152235;
        color: #e5eefc;
      }
      .iad-saved-panel h2 {
        margin: 0 0 10px 0;
        font-size: 20px;
      }
      .iad-saved-table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 10px;
        font-size: 13px;
      }
      .iad-saved-table th,
      .iad-saved-table td {
        border-bottom: 1px solid #31445f;
        padding: 9px 8px;
        vertical-align: top;
        text-align: left;
      }
      .iad-saved-table th {
        color: #9fb0c7;
        font-weight: 800;
      }
      .iad-saved-small {
        color: #9fb0c7;
        font-size: 12px;
      }
      .iad-saved-pre {
        white-space: pre-wrap;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      }
    `;
    document.head.appendChild(style);
  }

  function mountPanel(title) {
    panelStyle();

    let root = document.getElementById("iad-saved-records-panel");
    if (root) return root;

    root = document.createElement("section");
    root.id = "iad-saved-records-panel";
    root.className = "iad-saved-panel";
    root.innerHTML = "<h2>" + esc(title) + "</h2><div class='iad-saved-small'>Cargando...</div>";

    const main = document.querySelector("main") || document.querySelector(".content") || document.body;
    main.appendChild(root);

    return root;
  }

  function renderHistory(root, items) {
    if (!items.length) {
      root.innerHTML = "<h2>Historial de trabajos guardados</h2><div class='iad-saved-small'>Aún no hay trabajos guardados.</div>";
      return;
    }

    root.innerHTML = `
      <h2>Historial de trabajos guardados</h2>
      <div class="iad-saved-small">Últimos ${items.length} informes guardados desde Área de trabajo.</div>
      <table class="iad-saved-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Fecha</th>
            <th>Plantilla</th>
            <th>Usuario</th>
            <th>Informe final</th>
          </tr>
        </thead>
        <tbody>
          ${items.map(item => `
            <tr>
              <td>${esc(item.id)}</td>
              <td>${esc(item.created_at)}</td>
              <td>${esc(item.template_name || "—")}<br><span class="iad-saved-small">${esc(item.confidence || "")}</span></td>
              <td>${esc(item.username || "—")}</td>
              <td class="iad-saved-pre">${esc(short(item.final_report || "", 700))}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  }

  function renderTraining(root, items) {
    if (!items.length) {
      root.innerHTML = "<h2>Training IA - muestras guardadas</h2><div class='iad-saved-small'>Aún no hay muestras guardadas.</div>";
      return;
    }

    root.innerHTML = `
      <h2>Training IA - muestras guardadas</h2>
      <div class="iad-saved-small">Cada revisión guardada genera una muestra input/output para entrenamiento futuro.</div>
      <table class="iad-saved-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Fecha</th>
            <th>Tipo</th>
            <th>Input</th>
            <th>Output final</th>
          </tr>
        </thead>
        <tbody>
          ${items.map(item => `
            <tr>
              <td>${esc(item.id)}</td>
              <td>${esc(item.created_at)}</td>
              <td>${esc(item.sample_type || "—")}</td>
              <td class="iad-saved-pre">${esc(short(item.input_text || "", 350))}</td>
              <td class="iad-saved-pre">${esc(short(item.output_text || "", 550))}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  }

  async function load() {
    if (path.includes("/iad/historial")) {
      const root = mountPanel("Historial de trabajos guardados");
      const response = await fetch("/iad/api/trabajo/historial.json?limit=50", {credentials: "same-origin"});
      const data = await response.json();
      renderHistory(root, data.items || []);
      return;
    }

    if (path.includes("/iad/training")) {
      const root = mountPanel("Training IA - muestras guardadas");
      const response = await fetch("/iad/api/training/samples.json?limit=50", {credentials: "same-origin"});
      const data = await response.json();
      renderTraining(root, data.items || []);
      return;
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    load().catch(function (err) {
      console.error("No se pudo cargar panel de guardados:", err);
    });
  });
})();
