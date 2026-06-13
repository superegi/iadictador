// Copia transferible extraida desde app/static/iadictador_work_v2.js
// Nota: hoy runtime aun usa iadictador_work_v2.js; esta copia sirve para exportar/auditar/refactorizar.

// IAD_TEMPLATE_META_FIX_V4
(function () {
  "use strict";

  if (window.__iadTemplateMetaFixV4) return;
  window.__iadTemplateMetaFixV4 = true;

  function txt(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v.trim();
    return String(v).trim();
  }

  function deep(obj, path) {
    let cur = obj;
    for (const k of path) {
      if (!cur || typeof cur !== "object" || !(k in cur)) return "";
      cur = cur[k];
    }
    return txt(cur);
  }

  function first(obj, paths) {
    for (const p of paths) {
      const v = deep(obj, p);
      if (v) return v;
    }
    return "";
  }

  function improveMeta(raw) {
    raw = raw || {};

    const template = first(raw, [
      ["plantilla_sugerida", "nombre"],
      ["plantilla_sugerida", "name"],
      ["plantilla_nombre"],
      ["template_name"],
      ["template_bridge_force", "template_name"],
      ["template_bridge", "template_name"],
      ["audio_first_original", "plantilla_sugerida", "nombre"]
    ]);

    const confidence = first(raw, [
      ["plantilla_sugerida", "confianza"],
      ["plantilla_sugerida", "confidence"],
      ["confianza"],
      ["confidence"],
      ["audio_first_original", "plantilla_sugerida", "confianza"]
    ]);

    const method = first(raw, [
      ["metodo"],
      ["method"],
      ["template_bridge_force", "source"]
    ]) || "audio_first_template_bridge";

    const t = document.getElementById("iad-real-template");
    const c = document.getElementById("iad-real-confidence");
    const m = document.getElementById("iad-real-method");

    if (t && template) t.textContent = template;
    if (c && confidence) c.textContent = confidence;
    if (m && method) m.textContent = method;
  }

  const oldFetch = window.fetch;
  if (typeof oldFetch === "function" && !oldFetch.__iadMetaFixWrappedV4) {
    const wrapped = async function () {
      const args = arguments;
      const res = await oldFetch.apply(this, args);
      try {
        const clone = res.clone();
        const ct = clone.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          clone.json().then(function (data) {
            setTimeout(function () { improveMeta(data); }, 60);
            setTimeout(function () { improveMeta(data); }, 500);
          }).catch(function () {});
        }
      } catch (e) {}
      return res;
    };
    wrapped.__iadMetaFixWrappedV4 = true;
    window.fetch = wrapped;
  }

  window.IAD_IMPROVE_TEMPLATE_META_V4 = improveMeta;
})();
