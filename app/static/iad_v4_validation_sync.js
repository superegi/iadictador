(function dictadorV4ValidationSync() {
  const STORAGE_KEY = "dictador_v4_last_job";
  const AUDIO_ENDPOINT = "/iad/api/audio/procesar-dictado-completo.json";
  const V4_VALIDATE_ENDPOINT = "/iad/api/validacion/core-v4/update-existing.json";

  function saveLastJob(data) {
    if (!data || typeof data !== "object") return;

    const jobId =
      data?.auto_persist?.source_ref ||
      data?.audio_composition?.job_id ||
      data?.v4_debug?.job_id ||
      "";

    if (!jobId) return;

    const ids = data?.auto_persist?.ids || {};

    const payload = {
      job_id: jobId,
      source_ref: jobId,
      history2_work_item_id: ids.history2_work_item_id || null,
      training_correction_id: ids.training_correction_id || null,
      validation_history_id: ids.validation_history_id || null,
      informe_ia: data.informe_final || "",
      template_name: data?.plantilla_sugerida?.nombre || "",
      metodo: data.metodo || "",
      created_at_ms: Date.now()
    };

    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      window.__dictador_v4_last_job = payload;
    } catch (e) {
      window.__dictador_v4_last_job = payload;
    }
  }

  function loadLastJob() {
    if (window.__dictador_v4_last_job) return window.__dictador_v4_last_job;

    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const obj = JSON.parse(raw);
      if (obj && obj.job_id) return obj;
    } catch (e) {}

    return null;
  }

  function labelTextFor(el) {
    if (!el) return "";
    const id = el.id || "";
    let txt = [
      id,
      el.name || "",
      el.placeholder || "",
      el.getAttribute("aria-label") || "",
      el.getAttribute("data-label") || ""
    ].join(" ").toLowerCase();

    if (id && window.CSS && CSS.escape) {
      const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (lab) txt += " " + (lab.textContent || "").toLowerCase();
    }

    const parent = el.closest("section, div, article, fieldset");
    if (parent) txt += " " + (parent.textContent || "").slice(0, 700).toLowerCase();

    return txt;
  }

  function findFinalReportText() {
    const candidates = Array.from(document.querySelectorAll("textarea, [contenteditable='true']"));

    const scored = candidates.map(el => {
      const t = labelTextFor(el);
      const value = el.isContentEditable ? (el.innerText || "") : (el.value || "");
      let score = 0;

      if (!value || !value.trim()) score -= 1000;
      if (t.includes("informe final")) score += 120;
      if (t.includes("editable")) score += 80;
      if (t.includes("versión final")) score += 80;
      if (t.includes("version final")) score += 80;
      if (t.includes("propuesta ia")) score += 20;
      if (value.includes("Hallazgos")) score += 30;
      if (value.includes("Impresión diagnóstica") || value.includes("Impresion diagnostica")) score += 30;
      if (t.includes("texto complementario") || t.includes("información principal") || t.includes("informacion principal")) score -= 200;
      if (t.includes("extracción ia") || t.includes("extraccion ia") || t.includes("debug")) score -= 200;

      score += Math.min(60, Math.floor(value.length / 80));

      return { el, value: value.trim(), score };
    }).filter(x => x.value);

    scored.sort((a, b) => b.score - a.score);

    return scored[0]?.value || "";
  }

  function isValidationEndpoint(url) {
    return (
      url.includes("/iad/api/validacion/guardar-v5.json") ||
      url.includes("/iad/api/validacion/guardar-v4.json") ||
      url.includes("/iad/api/validacion/guardar.json")
    );
  }

  function parseBody(body) {
    if (!body) return null;

    if (typeof body === "string") {
      try {
        return JSON.parse(body);
      } catch (e) {
        return null;
      }
    }

    if (body instanceof FormData) {
      const obj = {};
      body.forEach((v, k) => {
        obj[k] = v;
      });
      return obj;
    }

    return null;
  }

  if (window.__dictador_v4_validation_sync_wrapped) return;
  window.__dictador_v4_validation_sync_wrapped = true;

  const originalFetch = window.fetch;

  window.fetch = async function dictadorV4ValidationFetchWrapper(input, init) {
    const url = (typeof input === "string") ? input : (input && input.url) || "";

    if (url.includes(AUDIO_ENDPOINT)) {
      const response = await originalFetch.apply(this, arguments);

      try {
        response.clone().json().then(saveLastJob).catch(() => {});
      } catch (e) {}

      return response;
    }

    if (isValidationEndpoint(url)) {
      const last = loadLastJob();

      if (last && last.job_id && init && init.body) {
        const payload = parseBody(init.body);

        if (payload) {
          const finalReport = findFinalReportText();

          payload.core_v4_job_id = last.job_id;
          payload.job_id = last.job_id;
          payload.source_ref = last.job_id;
          payload.history2_work_item_id = last.history2_work_item_id;
          payload.training_correction_id = last.training_correction_id;
          payload.validation_history_id = last.validation_history_id;
          payload.source = "core_v4_validated";
          payload.original_validation_endpoint = url;

          if (!payload.informe_ia && last.informe_ia) {
            payload.informe_ia = last.informe_ia;
          }

          if (!payload.informe_validado && finalReport) {
            payload.informe_validado = finalReport;
          }

          if (!payload.informe_corregido && finalReport) {
            payload.informe_corregido = finalReport;
          }

          if (!payload.version_final_usuario && finalReport) {
            payload.version_final_usuario = finalReport;
          }

          const nextInit = Object.assign({}, init, {
            body: JSON.stringify(payload),
            headers: Object.assign(
              {},
              init.headers || {},
              {"Content-Type": "application/json"}
            )
          });

          return originalFetch.call(this, V4_VALIDATE_ENDPOINT, nextInit);
        }
      }
    }

    return originalFetch.apply(this, arguments);
  };
})();
