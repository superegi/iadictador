// Copia transferible extraida desde app/static/iadictador_work_v2.js
// Nota: hoy runtime aun usa iadictador_work_v2.js; esta copia sirve para exportar/auditar/refactorizar.

// IAD_FINAL_PANEL_REAL_TEXTAREA_V3
(function () {
  "use strict";

  const PATCH = "IAD_FINAL_PANEL_REAL_TEXTAREA_V3";
  if (window.__iadFinalPanelRealTextareaV3) return;
  window.__iadFinalPanelRealTextareaV3 = true;

  function byId(id) {
    return document.getElementById(id);
  }

  function text(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v.trim();
    if (typeof v === "number" || typeof v === "boolean") return String(v).trim();
    return "";
  }

  function getPath(obj, path) {
    let cur = obj;
    for (const key of path) {
      if (!cur || typeof cur !== "object" || !(key in cur)) return "";
      cur = cur[key];
    }
    return cur;
  }

  function firstText(obj, paths) {
    for (const p of paths) {
      const s = text(getPath(obj, p));
      if (s) return s;
    }
    return "";
  }

  function normalize(raw) {
    raw = raw || {};

    const report = firstText(raw, [
      ["informe_final"],
      ["final_report"],
      ["report"],
      ["resultado_revisado"],
      ["informe_limpio"],
      ["generated", "informe_final"],
      ["generated", "final_report"],
      ["analysis", "informe_final"],
      ["analysis", "final_report"],
      ["revision", "informe_limpio"],
      ["revision", "informe_final"],
      ["revision", "final_report"],
      ["data", "informe_final"],
      ["data", "final_report"],
      ["payload", "informe_final"],
      ["payload", "final_report"],
      ["output", "informe_final"],
      ["output", "final_report"]
    ]);

    const template = firstText(raw, [
      ["plantilla_nombre"],
      ["template_name"],
      ["plantilla"],
      ["template"],
      ["analysis", "plantilla_nombre"],
      ["analysis", "template_name"],
      ["generated", "plantilla_nombre"],
      ["generated", "template_name"],
      ["data", "plantilla_nombre"]
    ]);

    const confidence = firstText(raw, [
      ["confianza"],
      ["confidence"],
      ["analysis", "confianza"],
      ["analysis", "confidence"],
      ["generated", "confianza"],
      ["generated", "confidence"],
      ["data", "confianza"]
    ]);

    const method = firstText(raw, [
      ["metodo"],
      ["method"],
      ["analysis", "metodo"],
      ["analysis", "method"],
      ["generated", "metodo"],
      ["generated", "method"],
      ["data", "metodo"]
    ]);

    return { report, template, confidence, method };
  }

  function installCss() {
    if (byId("iad-final-panel-real-textarea-style-v3")) return;

    const style = document.createElement("style");
    style.id = "iad-final-panel-real-textarea-style-v3";
    style.textContent = `
      #iad-native-final-panel,
      #iad-audio-first-final-host,
      #iad-inline-review-root,
      #iad-force-review-root,
      #iad-v3-review-root,
      #iad4-review-root,
      #iad5-review-root {
        display: none !important;
      }

      #iad-real-final-panel {
        margin-top: 14px;
        border: 1px solid rgba(125,211,252,.34);
        border-radius: 14px;
        background: #101d2d;
        padding: 14px;
        box-shadow: 0 10px 28px rgba(0,0,0,.18);
      }

      #iad-real-final-panel h3 {
        margin: 0 0 4px 0;
        color: #e5edf7;
        font-size: 1.05rem;
      }

      #iad-real-final-panel .iad-real-note {
        color: #9fb0c4;
        font-size: .86rem;
        margin-bottom: 10px;
      }

      #iad-real-final-panel .iad-real-meta {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        margin: 10px 0;
      }

      #iad-real-final-panel .iad-real-card {
        border: 1px solid rgba(148,163,184,.18);
        border-radius: 10px;
        background: #071223;
        padding: 9px;
        color: #e5edf7;
        font-size: .86rem;
      }

      #iad-real-final-panel .iad-real-card strong {
        display: block;
        color: #9fb0c4;
        font-size: .78rem;
        margin-bottom: 3px;
      }

      #iad-real-final-report {
        display: block !important;
        visibility: visible !important;
        opacity: 1 !important;
        width: 100% !important;
        min-height: 360px !important;
        box-sizing: border-box !important;
        border-radius: 12px !important;
        padding: 12px !important;
        margin-top: 10px !important;
        background: #071223 !important;
        color: #e5edf7 !important;
        border: 1px solid rgba(125,211,252,.48) !important;
        font-family: ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace !important;
        white-space: pre-wrap !important;
        line-height: 1.45 !important;
        resize: vertical !important;
      }

      #iad-real-final-panel .iad-real-actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 10px;
      }

      #iad-real-final-panel .iad-real-actions button {
        border: 0;
        border-radius: 10px;
        padding: 8px 12px;
        font-weight: 700;
        cursor: pointer;
      }

      @media(max-width:800px) {
        #iad-real-final-panel .iad-real-meta {
          grid-template-columns: 1fr;
        }

        #iad-real-final-report {
          min-height: 300px !important;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function mainScope() {
    return document.querySelector("main")
      || document.querySelector("[role='main']")
      || document.querySelector(".main")
      || document.querySelector(".content")
      || document.body;
  }

  function findInfoSection() {
    const btns = Array.from(document.querySelectorAll("button"));
    const analyze = btns.find(function (b) {
      return (b.textContent || "").replace(/\s+/g, " ").trim().toLowerCase() === "analizar radiología";
    });

    if (!analyze) return null;

    let cur = analyze;
    for (let i = 0; i < 8 && cur && cur !== document.body; i++) {
      const t = (cur.textContent || "").toLowerCase();
      if (t.includes("información principal para el informe")) return cur;
      cur = cur.parentElement;
    }

    return analyze.parentElement;
  }

  function ensurePanel() {
    installCss();

    let panel = byId("iad-real-final-panel");
    if (!panel) {
      panel = document.createElement("section");
      panel.id = "iad-real-final-panel";
      panel.innerHTML = `
        <h3>Informe final editable</h3>
        <div class="iad-real-note">
          Texto final generado desde el audio/texto. Edita aquí antes de copiar o guardar.
        </div>

        <div class="iad-real-meta">
          <div class="iad-real-card"><strong>Plantilla</strong><span id="iad-real-template">—</span></div>
          <div class="iad-real-card"><strong>Confianza</strong><span id="iad-real-confidence">—</span></div>
          <div class="iad-real-card"><strong>Método</strong><span id="iad-real-method">—</span></div>
        </div>

        <textarea id="iad-real-final-report" autocomplete="off" spellcheck="true"></textarea>

        <div class="iad-real-actions">
          <button type="button" id="iad-real-copy-final">Copiar informe final</button>
          <button type="button" id="iad-real-select-final">Seleccionar texto</button>
        </div>
      `;

      const info = findInfoSection();
      if (info && info.parentElement) {
        info.parentElement.insertBefore(panel, info.nextSibling);
      } else {
        mainScope().appendChild(panel);
      }
    }

    const area = byId("iad-real-final-report");

    const copy = byId("iad-real-copy-final");
    if (copy && !copy.dataset.boundV3) {
      copy.dataset.boundV3 = "1";
      copy.addEventListener("click", async function () {
        const v = area ? area.value || "" : "";
        try {
          await navigator.clipboard.writeText(v);
          copy.textContent = "Copiado";
          setTimeout(function () { copy.textContent = "Copiar informe final"; }, 1100);
        } catch (e) {
          if (area) {
            area.focus();
            area.select();
          }
        }
      });
    }

    const select = byId("iad-real-select-final");
    if (select && !select.dataset.boundV3) {
      select.dataset.boundV3 = "1";
      select.addEventListener("click", function () {
        if (area) {
          area.focus();
          area.select();
        }
      });
    }

    if (area && !area.dataset.boundSyncV3) {
      area.dataset.boundSyncV3 = "1";
      area.addEventListener("input", function () {
        syncMirrors(area.value || "");
      });
    }

    return { panel, area };
  }

  function ensureHiddenMirror() {
    let mirror = byId("finalReport");
    if (!mirror) {
      mirror = document.createElement("textarea");
      mirror.id = "finalReport";
      mirror.name = "resultado_revisado";
      mirror.setAttribute("data-iad-hidden-mirror-v3", "1");
      mirror.style.display = "none";
      const panel = byId("iad-real-final-panel") || document.body;
      panel.appendChild(mirror);
    }
    return mirror;
  }

  function syncMirrors(report) {
    const mirror = ensureHiddenMirror();
    mirror.value = report;

    const selectors = [
      "textarea[name='resultado_revisado']",
      "input[name='resultado_revisado']",
      "textarea[name='final_report']",
      "input[name='final_report']",
      "textarea[name='informe_final']",
      "input[name='informe_final']"
    ];

    document.querySelectorAll(selectors.join(",")).forEach(function (el) {
      if (el.id === "iad-real-final-report") return;
      try { el.value = report; } catch (e) {}
    });
  }

  function setMeta(payload) {
    const t = byId("iad-real-template");
    const c = byId("iad-real-confidence");
    const m = byId("iad-real-method");

    if (t) t.textContent = payload.template || readExistingMeta("plantilla") || "—";
    if (c) c.textContent = payload.confidence || readExistingMeta("confianza") || "—";
    if (m) m.textContent = payload.method || readExistingMeta("método") || "audio_first";
  }

  function readExistingMeta(label) {
    label = label.toLowerCase();

    const cards = Array.from(document.querySelectorAll("div, section, article"));
    for (const card of cards) {
      if (card.closest("#iad-real-final-panel")) continue;
      const raw = (card.textContent || "").replace(/\s+/g, " ").trim();
      const low = raw.toLowerCase();

      if (low.startsWith(label + " ") && raw.length < 120) {
        return raw.replace(new RegExp("^" + label, "i"), "").trim();
      }
    }

    return "";
  }

  function render(raw, source) {
    const payload = normalize(raw);
    if (!payload.report) return false;

    const ui = ensurePanel();
    if (!ui.area) return false;

    ui.area.value = payload.report;
    syncMirrors(payload.report);
    setMeta(payload);

    window.__iadRealFinalPayloadV3 = payload;
    window.__iadRealFinalSourceV3 = source || "unknown";

    const status = byId("audioStatus") || byId("status") || document.querySelector("[data-status]");
    if (status) {
      status.textContent = "Informe final visible cargado. Revisa, corrige y copia/guarda.";
    }

    cleanupUi();
    return true;
  }

  function scanWindowState() {
    const candidates = [
      window.__iadAudioFirstFinalPayload,
      window.__iadNativeFinalPayload,
      window.__iadRealFinalPayloadV3,
      window.__iadLastGenerated,
      window.__iadLastValidation,
      window.__iadLastAnalysis
    ].filter(Boolean);

    for (const c of candidates) {
      if (render(c, "window_state")) return true;
    }

    const possibleTextareas = Array.from(document.querySelectorAll("textarea"))
      .filter(function (ta) {
        if (ta.id === "iad-real-final-report") return false;
        if (ta.id === "sourceText") return false;
        if (ta.name === "input_text_final") return false;
        const v = text(ta.value);
        return v.length > 80 && /hallazgos|impresi[oó]n|conclusi[oó]n|informe/i.test(v);
      });

    if (possibleTextareas.length) {
      return render({ informe_final: possibleTextareas[0].value }, "dom_textarea");
    }

    ensurePanel();
    return false;
  }

  function patchFetch() {
    if (window.__iadFetchPatchedRealFinalV3) return;
    window.__iadFetchPatchedRealFinalV3 = true;

    const original = window.fetch;
    if (typeof original !== "function") return;

    window.fetch = async function () {
      const args = arguments;
      const response = await original.apply(this, args);

      try {
        const url = String(args[0] && (args[0].url || args[0]) || "");
        const clone = response.clone();
        const ct = clone.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          clone.json().then(function (data) {
            setTimeout(function () {
              render(data, url || "fetch_json");
            }, 0);
          }).catch(function () {});
        }
      } catch (e) {}

      return response;
    };
  }

  function hideDuplicateNuevaOT() {
    const scope = mainScope();
    const els = Array.from(scope.querySelectorAll("*")).filter(function (el) {
      const t = (el.textContent || "").replace(/\s+/g, " ").trim();
      return t === "Nueva OT";
    });

    if (els.length < 2) return;

    const first = els[0];
    let box = first;

    for (let i = 0; i < 5 && box.parentElement && box.parentElement !== scope; i++) {
      const parentText = (box.parentElement.textContent || "").replace(/\s+/g, " ").trim();
      if (parentText === "Nueva OT") box = box.parentElement;
      else break;
    }

    box.style.display = "none";
    box.setAttribute("data-iad-hidden-duplicate-title", "1");
  }

  function hideOldButtons() {
    document.querySelectorAll("button, a").forEach(function (el) {
      if (el.closest("#iad-real-final-panel")) return;

      const t = (el.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
      const action = (el.getAttribute("data-action") || "").toLowerCase();
      const id = (el.id || "").toLowerCase();

      const old =
        t === "transcribir" ||
        t === "transcribir todos" ||
        t === "limpiar" ||
        action === "transcribe" ||
        action === "clear" ||
        id === "clearbtn" ||
        id === "transcribebtn";

      if (old) {
        el.hidden = true;
        el.disabled = true;
        el.style.display = "none";
        el.setAttribute("aria-hidden", "true");
      }
    });
  }

  function hideOldFinalDetails() {
    document.querySelectorAll("details").forEach(function (d) {
      if (d.closest("#iad-real-final-panel")) return;
      const s = (d.querySelector("summary") && d.querySelector("summary").textContent || "")
        .replace(/\s+/g, " ")
        .trim()
        .toLowerCase();

      if (
        s === "informe final" ||
        s === "hallazgos detectados" ||
        s === "hallazgos radiológicos" ||
        s === "hallazgos estructurados"
      ) {
        d.style.display = "none";
        d.setAttribute("aria-hidden", "true");
      }
    });
  }

  function hidePreviousV2Panel() {
    const old = byId("iad-native-final-panel");
    if (old) {
      old.style.display = "none";
      old.setAttribute("aria-hidden", "true");
    }
  }

  function cleanupUi() {
    hideDuplicateNuevaOT();
    hideOldButtons();
    hideOldFinalDetails();
    hidePreviousV2Panel();
  }

  function tick() {
    cleanupUi();
    scanWindowState();
  }

  patchFetch();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      tick();
      setTimeout(tick, 300);
      setTimeout(tick, 1000);
      setTimeout(tick, 2500);
    });
  } else {
    tick();
    setTimeout(tick, 300);
    setTimeout(tick, 1000);
    setTimeout(tick, 2500);
  }

  const observer = new MutationObserver(function () {
    cleanupUi();
  });

  try {
    observer.observe(document.documentElement || document.body, {
      childList: true,
      subtree: true
    });
  } catch (e) {}

  window.IAD_RENDER_FINAL_REPORT_V3 = render;
  window.IAD_FORCE_RENDER_FINAL_REPORT = render;

  console.info(PATCH + " activo");
})();
