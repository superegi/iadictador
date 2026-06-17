(function dictadorV4TracePanel() {
  function currentTarget() {
    const path = window.location.pathname;

    let m = path.match(/\/iad\/historial2\/w\/(\d+)/);
    if (m) {
      return {
        kind: "history2",
        id: m[1],
        url: `/iad/api/v4/trace/history2/${m[1]}.json`
      };
    }

    m = path.match(/\/iad\/training(?:_ia)?\/(?:detail\/)?(\d+)/);
    if (m) {
      return {
        kind: "training",
        id: m[1],
        url: `/iad/api/v4/trace/training/${m[1]}.json`
      };
    }

    m = path.match(/\/iad\/training\/(\d+)/);
    if (m) {
      return {
        kind: "training",
        id: m[1],
        url: `/iad/api/v4/trace/training/${m[1]}.json`
      };
    }

    return null;
  }

  function fmtMs(ms) {
    if (!ms && ms !== 0) return "—";
    if (ms < 1000) return `${ms} ms`;
    return `${(ms / 1000).toFixed(1)} s`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function pill(text, cls) {
    return `<span class="v4-pill ${cls || ""}">${escapeHtml(text)}</span>`;
  }

  function render(data) {
    if (document.getElementById("dictador-v4-trace-panel")) return;

    const usage = data.usage_summary || {};
    const calls = usage.calls || [];
    const rules = data.rules_manifest || {};
    const audio = data.audio_merge || {};
    const meta = data.metadata_clinica || {};

    const callsHtml = calls.length
      ? calls.map(c => {
          return `
            <tr>
              <td>${escapeHtml(c.stage)}</td>
              <td>${escapeHtml(c.model)}</td>
              <td>${fmtMs(c.duration_ms)}</td>
              <td>${escapeHtml(c.tokens ?? "—")}</td>
            </tr>
          `;
        }).join("")
      : `<tr><td colspan="4">Sin llamadas registradas.</td></tr>`;

    const sources = (rules.sources || []).map(s => {
      return `<li><strong>${escapeHtml(s.scope)}</strong>: ${escapeHtml(s.lines)} líneas · ${escapeHtml(s.chars)} caracteres · ${escapeHtml((s.sha256 || "").slice(0, 12))}</li>`;
    }).join("");

    const statusClass = (data.estado || "").includes("no_validado") ? "warn" : "ok";

    const html = `
      <section id="dictador-v4-trace-panel" class="v4-panel">
        <h2>Trazabilidad V4</h2>

        <div class="v4-row">
          ${pill(data.estado || "sin estado", statusClass)}
          ${pill(data.source || "sin source")}
          ${pill(data.job_id || "sin job")}
          ${pill(data.modelo || "sin modelo")}
        </div>

        <div class="v4-grid">
          <div>
            <h3>Uso OpenAI</h3>
            <div class="v4-metric">
              <div><span>Llamadas</span><strong>${escapeHtml(usage.total_calls ?? "—")}</strong></div>
              <div><span>Tokens</span><strong>${escapeHtml(usage.total_tokens ?? "—")}</strong></div>
              <div><span>Tiempo</span><strong>${fmtMs(usage.duration_ms)}</strong></div>
            </div>
            <table class="v4-table">
              <thead>
                <tr><th>Etapa</th><th>Modelo</th><th>Tiempo</th><th>Tokens</th></tr>
              </thead>
              <tbody>${callsHtml}</tbody>
            </table>
          </div>

          <div>
            <h3>Metadata clínica</h3>
            <pre>${escapeHtml(JSON.stringify(meta, null, 2))}</pre>
          </div>
        </div>

        <div class="v4-grid">
          <div>
            <h3>Reglas usadas</h3>
            <div class="v4-small">
              Prioridad: ${escapeHtml(rules.rule_conflict_policy || "app > general > user")}<br>
              Compiladas: ${escapeHtml(rules.compiled?.lines ?? "—")} líneas · ${escapeHtml(rules.compiled?.chars ?? "—")} caracteres
            </div>
            <ul class="v4-small">${sources || "<li>Sin manifest de reglas.</li>"}</ul>
          </div>

          <div>
            <h3>Audio / texto</h3>
            <div class="v4-small">
              Fusión audio: <strong>${audio.used ? "sí" : "no"}</strong><br>
              Audios entrada: ${escapeHtml(audio.input_count ?? "—")}<br>
              Estrategia: ${escapeHtml(audio.strategy || audio.reason || "—")}
            </div>
            <h3>Texto complementario</h3>
            <pre>${escapeHtml(data.extra_context_normalized || "")}</pre>
          </div>
        </div>
      </section>
    `;

    const main = document.querySelector("main") || document.querySelector(".content") || document.body;
    main.insertAdjacentHTML("afterbegin", html);
  }

  function injectStyle() {
    if (document.getElementById("dictador-v4-trace-style")) return;

    const style = document.createElement("style");
    style.id = "dictador-v4-trace-style";
    style.textContent = `
      .v4-panel {
        background: #111827;
        border: 1px solid #334155;
        border-radius: 16px;
        padding: 16px;
        margin: 0 0 18px 0;
        color: #e5e7eb;
      }
      .v4-panel h2 {
        margin: 0 0 12px 0;
        font-size: 24px;
      }
      .v4-panel h3 {
        margin: 12px 0 8px 0;
        font-size: 16px;
      }
      .v4-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 12px;
      }
      .v4-pill {
        display: inline-block;
        padding: 5px 9px;
        border-radius: 999px;
        border: 1px solid #475569;
        background: #020617;
        color: #cbd5e1;
        font-size: 12px;
        font-weight: 700;
      }
      .v4-pill.warn {
        border-color: #fbbf24;
        color: #fbbf24;
      }
      .v4-pill.ok {
        border-color: #34d399;
        color: #34d399;
      }
      .v4-grid {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: 14px;
      }
      .v4-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }
      .v4-table th,
      .v4-table td {
        border-bottom: 1px solid #334155;
        padding: 6px;
        text-align: left;
      }
      .v4-metric {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 8px;
        margin-bottom: 10px;
      }
      .v4-metric div {
        background: #020617;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 8px;
      }
      .v4-metric span {
        display: block;
        color: #94a3b8;
        font-size: 12px;
      }
      .v4-metric strong {
        font-size: 18px;
      }
      .v4-panel pre {
        background: #020617;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 10px;
        max-height: 260px;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-word;
      }
      .v4-small {
        color: #cbd5e1;
        font-size: 13px;
        line-height: 1.45;
      }
      @media (max-width: 950px) {
        .v4-grid {
          grid-template-columns: 1fr;
        }
      }
    `;
    document.head.appendChild(style);
  }

  async function load() {
    const target = currentTarget();
    if (!target) return;

    injectStyle();

    try {
      const res = await fetch(target.url, { credentials: "same-origin" });
      if (!res.ok) return;
      const data = await res.json();
      if (!data || !data.ok) return;
      render(data);
    } catch (err) {
      console.warn("No se pudo cargar trazabilidad V4", err);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
