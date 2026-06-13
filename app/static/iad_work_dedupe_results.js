// IAD_WORK_DEDUPE_RESULTS_V1
(function () {
  "use strict";

  if (window.__iadWorkDedupeResultsV1) return;
  window.__iadWorkDedupeResultsV1 = true;

  if (!/\/iad\/trabajo/.test(window.location.pathname || "")) return;

  function norm(s) {
    return (s === null || s === undefined ? "" : String(s))
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  function visible(el) {
    if (!el) return false;
    const cs = window.getComputedStyle(el);
    return cs.display !== "none" && cs.visibility !== "hidden" && el.offsetParent !== null;
  }

  function directTitle(el) {
    if (!el) return "";
    const h = el.querySelector(":scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > header h1, :scope > header h2, :scope > header h3");
    return norm(h ? h.textContent : "");
  }

  function containsFinalTextarea(el) {
    if (!el) return false;
    return !!(
      el.querySelector("#iad-real-final-report") ||
      el.querySelector("#finalReport") ||
      Array.from(el.querySelectorAll("textarea")).some(t => norm(t.value || t.textContent).includes("impresion diagnostica"))
    );
  }

  function isFinalPanel(el) {
    if (!el) return false;

    if (el.id === "iad-real-final-panel") return true;
    if (containsFinalTextarea(el) && norm(el.textContent).includes("informe final editable")) return true;

    const title = directTitle(el);
    if (title.includes("informe final editable") && el.querySelector("textarea")) return true;

    return false;
  }

  function isResultSummaryPanel(el) {
    if (!el) return false;

    const title = directTitle(el);
    const txt = norm(el.textContent);

    if (title.includes("resultado audio-first")) return true;

    if (
      txt.startsWith("audio-first completo") &&
      txt.includes("plantilla") &&
      txt.includes("informe final")
    ) {
      return true;
    }

    if (
      txt.includes("resultado audio-first") &&
      txt.includes("transcripcion devuelta") &&
      txt.includes("impresion diagnostica")
    ) {
      return true;
    }

    return false;
  }

  function isDangerousRoot(el) {
    if (!el) return true;
    if (el === document.body || el === document.documentElement) return true;
    if (el.tagName === "MAIN") return true;

    const txt = norm(el.textContent);
    if (txt.includes("audio principal") && txt.includes("informacion principal para el informe") && txt.includes("informe final editable")) {
      return true;
    }

    return false;
  }

  function candidateBlocks() {
    const nodes = Array.from(document.querySelectorAll("section, article, form, div"));
    return nodes.filter(el => {
      if (isDangerousRoot(el)) return false;
      if (!visible(el)) return false;
      return isFinalPanel(el) || isResultSummaryPanel(el);
    });
  }

  function scoreFinalPanel(el) {
    let s = 0;

    if (el.id === "iad-real-final-panel") s += 200;
    if (el.querySelector("#iad-real-final-report")) s += 150;
    if (containsFinalTextarea(el)) s += 80;
    if (norm(el.textContent).includes("guardar validacion")) s += 40;
    if (norm(el.textContent).includes("copiar informe final")) s += 30;

    const t = norm(el.textContent);
    if (t.includes("[contenido]")) s -= 80;
    if (t.includes("xxxxxxxx")) s -= 80;
    if (t.includes("hallazgos positivos estructurados aplicados al informe")) s -= 50;

    return s;
  }

  function domIndex(el) {
    return Array.prototype.indexOf.call(document.querySelectorAll("section, article, form, div"), el);
  }

  function hideBlock(el, reason) {
    if (!el || isDangerousRoot(el)) return;
    if (el.dataset.iadDedupeKeep === "1") return;

    el.dataset.iadDedupeHidden = reason || "duplicate";
    el.style.display = "none";
    el.setAttribute("aria-hidden", "true");
  }

  function showBlock(el) {
    if (!el) return;
    if (el.dataset.iadDedupeHidden) {
      delete el.dataset.iadDedupeHidden;
      el.style.display = "";
      el.removeAttribute("aria-hidden");
    }
    el.dataset.iadDedupeKeep = "1";
  }

  function cleanup() {
    const blocks = candidateBlocks();

    const finalPanels = blocks.filter(isFinalPanel);
    const summaries = blocks.filter(isResultSummaryPanel);

    let keepFinal = null;

    if (finalPanels.length) {
      keepFinal = finalPanels
        .slice()
        .sort((a, b) => {
          const ds = scoreFinalPanel(a) - scoreFinalPanel(b);
          if (ds !== 0) return ds;
          return domIndex(a) - domIndex(b);
        })
        .pop();

      showBlock(keepFinal);

      finalPanels.forEach(el => {
        if (el !== keepFinal) {
          hideBlock(el, "duplicate-final-panel");
        }
      });
    }

    /*
      La pantalla final actual ya muestra plantilla/confianza/método.
      Los paneles "Resultado audio-first" antiguos duplican la misma información
      y a veces quedan arriba/abajo del resultado real.
    */
    if (keepFinal) {
      summaries.forEach(el => {
        if (!el.contains(keepFinal) && el !== keepFinal) {
          hideBlock(el, "obsolete-audio-first-summary");
        }
      });
    } else if (summaries.length > 1) {
      const keepSummary = summaries[summaries.length - 1];
      showBlock(keepSummary);
      summaries.forEach(el => {
        if (el !== keepSummary) hideBlock(el, "duplicate-audio-first-summary");
      });
    }

    // Si quedaron textareas finales duplicadas fuera del panel elegido, ocultar su bloque contenedor.
    if (keepFinal) {
      const finalTextareas = Array.from(document.querySelectorAll("textarea")).filter(t => {
        const v = norm(t.value || t.textContent || "");
        return v.includes("impresion diagnostica") || t.id === "finalReport" || t.id === "iad-real-final-report";
      });

      finalTextareas.forEach(t => {
        if (keepFinal.contains(t)) return;

        const block = t.closest("section, article, form, div");
        if (block && !keepFinal.contains(block) && !isDangerousRoot(block)) {
          hideBlock(block, "duplicate-final-textarea");
        }
      });
    }

    return {
      finalPanels: finalPanels.length,
      summaries: summaries.length,
      keptFinal: !!keepFinal
    };
  }

  let timer = null;

  function schedule() {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(function () {
      timer = null;
      cleanup();
    }, 120);
  }

  window.iadWorkDedupeResultsV1 = cleanup;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(cleanup, 300);
      setTimeout(cleanup, 1000);
      setTimeout(cleanup, 2500);
    });
  } else {
    setTimeout(cleanup, 300);
    setTimeout(cleanup, 1000);
    setTimeout(cleanup, 2500);
  }

  try {
    const obs = new MutationObserver(schedule);
    obs.observe(document.documentElement || document.body, {
      childList: true,
      subtree: true
    });
  } catch (e) {}

  const oldFetch = window.fetch;
  if (typeof oldFetch === "function" && !oldFetch.__iadWorkDedupeResultsWrappedV1) {
    const wrapped = async function () {
      const res = await oldFetch.apply(this, arguments);
      setTimeout(cleanup, 150);
      setTimeout(cleanup, 800);
      setTimeout(cleanup, 1800);
      return res;
    };
    wrapped.__iadWorkDedupeResultsWrappedV1 = true;
    window.fetch = wrapped;
  }
})();
