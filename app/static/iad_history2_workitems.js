// IAD_HISTORY2_WORKITEMS_FRONTEND_V1
(function () {
  "use strict";

  if (window.__iadHistory2WorkItemsFrontendV1) return;
  window.__iadHistory2WorkItemsFrontendV1 = true;

  const rawFetch = window.fetch.bind(window);

  function txt(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v.trim();
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v).trim(); }
  }

  function finalArea() {
    return document.getElementById("iad-real-final-report")
      || document.getElementById("finalReport")
      || Array.from(document.querySelectorAll("textarea")).find(t => (t.value || "").includes("Impresión diagnóstica"));
  }

  function sourceText() {
    const el = document.getElementById("sourceText")
      || document.querySelector("textarea[name='input_text_final']");
    return el ? (el.value || "") : "";
  }

  function templateName(payload) {
    payload = payload || {};
    return txt(
      (payload.plantilla_sugerida && payload.plantilla_sugerida.nombre)
      || payload.plantilla_nombre
      || payload.template_name
      || payload.template
      || ""
    );
  }

  function modalityFromTemplate(name) {
    const n = (name || "").toLowerCase();
    if (n.includes("tc") || n.includes("tac")) return "TC";
    if (n.includes("rx")) return "RX";
    if (n.includes("us") || n.includes("eco")) return "US";
    if (n.includes("rm")) return "RM";
    return "";
  }

  function extractPayloadForWorkItem(payload, estado) {
    payload = payload || {};
    const tpl = templateName(payload);
    const fa = finalArea();

    return {
      work_item_id: window.__iadHistory2CurrentWorkItemId || null,
      estado: estado || "generada",
      modalidad: modalityFromTemplate(tpl),
      nombre_estudio: tpl || "Trabajo IA",
      template_name: tpl,
      modelo_ia: txt((payload.intelligence_editor && payload.intelligence_editor.model) || payload.modelo_usado || payload.model || ""),
      version_ia: txt(payload.metodo || payload.method || payload.source || ""),
      transcripcion: txt((payload.resumen_extraccion && payload.resumen_extraccion.texto_transcrito_literal) || payload.texto_transcrito_literal || payload.transcripcion || payload.transcription || sourceText()),
      clinical_json: payload.hallazgos_estructurados || payload.structured_findings || payload.clinical_json || {},
      tags_importantes_reconocidos: (payload.resumen_extraccion && payload.resumen_extraccion.tags_especificos) || payload.tags_especificos_ia || payload.hallazgos_estructurados || payload.structured_findings || [],
      propuesta_ia: txt(payload.informe_final || payload.final_report || ""),
      puntos_conflictivos_detectados: (payload.resumen_extraccion && payload.resumen_extraccion.advertencias) || payload.advertencias_visibles || payload.advertencias || payload.warnings || payload.posibles_omisiones || [],
      version_final_usuario: estado === "validada" && fa ? (fa.value || "") : "",
      diff: txt(payload.diferencias_detectadas || payload.diff || ""),
      metadata_json: payload,
      source: estado === "validada" ? "frontend_validation_button" : "frontend_audio_first_generation"
    };
  }

  async function saveWorkItem(payload, estado) {
    const body = extractPayloadForWorkItem(payload, estado);

    if (!body.transcripcion && !body.propuesta_ia && !body.version_final_usuario) {
      return null;
    }

    try {
      const res = await rawFetch("/iad/api/historial2/workitems/save.json", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });

      const data = await res.json();

      if (res.ok && data.ok && data.item && data.item.id) {
        window.__iadHistory2CurrentWorkItemId = data.item.id;
        return data.item;
      }
    } catch (e) {
      console.warn("[Historial2] No se pudo guardar workitem:", e);
    }

    return null;
  }

  function capturePayload(data) {
    if (!data || typeof data !== "object") return;

    const report = txt(data.informe_final || data.final_report || "");
    const trans = txt(data.transcripcion || data.transcription || "");

    if (report || trans) {
      window.__iadHistory2LastPayload = data;
    }
  }

  if (typeof window.fetch === "function" && !window.fetch.__iadHistory2WorkItemsWrappedV1) {
    const previousFetch = window.fetch.bind(window);

    const wrapped = async function () {
      const args = arguments;
      let url = "";
      try {
        url = String(args[0] && args[0].url ? args[0].url : args[0]);
      } catch (e) {}

      const res = await previousFetch.apply(this, args);

      if (url.includes("/iad/api/historial2/workitems/save.json")) {
        return res;
      }

      try {
        const clone = res.clone();
        const ct = clone.headers.get("content-type") || "";

        if (ct.includes("application/json")) {
          clone.json().then(async function (data) {
            capturePayload(data);

            if (url.includes("/iad/api/audio/procesar-dictado-completo.json")) {
              await saveWorkItem(data, "generada");
            }
          }).catch(function () {});
        }
      } catch (e) {}

      return res;
    };

    wrapped.__iadHistory2WorkItemsWrappedV1 = true;
    window.fetch = wrapped;
  }

  document.addEventListener("click", function (ev) {
    const btn = ev.target && ev.target.closest ? ev.target.closest("button, input[type='button'], input[type='submit']") : null;
    if (!btn) return;

    const label = txt(btn.innerText || btn.textContent || btn.value || "").toLowerCase();

    if (!label.includes("guardar validación") && !(label.includes("guardar") && label.includes("copiar"))) {
      return;
    }

    setTimeout(function () {
      const payload = window.__iadHistory2LastPayload || window.__iadValidationLastPayloadV3 || window.__iadTrainingLastPayloadV2 || {};
      saveWorkItem(payload, "validada");
    }, 400);
  }, true);
})();


// IAD_HISTORY2_USE_EXTRACTION_SUMMARY_V1
(function () {
  "use strict";

  if (window.__iadHistory2UseExtractionSummaryV1) return;
  window.__iadHistory2UseExtractionSummaryV1 = true;

  function txt(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v.trim();
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v).trim(); }
  }

  function list(v) {
    if (!v) return [];
    if (Array.isArray(v)) return v.map(txt).filter(Boolean);
    return [txt(v)].filter(Boolean);
  }

  window.iadHistory2BuildTrainingPayloadV1 = function (payload, estado) {
    payload = payload || {};
    const resumen = payload.resumen_extraccion || {};

    const tags =
      list(resumen.tags_especificos).length
        ? list(resumen.tags_especificos)
        : list(payload.tags_especificos_ia).length
          ? list(payload.tags_especificos_ia)
          : list(payload.hallazgos_estructurados || payload.structured_findings);

    const warnings =
      list(resumen.advertencias).length
        ? list(resumen.advertencias)
        : list(payload.advertencias_visibles || payload.advertencias || payload.warnings || payload.posibles_omisiones);

    return {
      tags_importantes_reconocidos: tags,
      puntos_conflictivos_detectados: warnings,
      texto_transcrito_literal: txt(resumen.texto_transcrito_literal || payload.texto_transcrito_literal || payload.transcripcion || payload.transcription),
      estado: estado || "generada"
    };
  };
})();

