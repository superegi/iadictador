(function dictadorSidebarFix() {
  const BRAND_HTML = `
    <div class="dictador-sidebar-brand">
      <img src="/static/img/logo.png" alt="dIctAdor">
      <div>
        <div class="dictador-sidebar-brand-title">d<span class="ai">I</span>ct<span class="ai">A</span>dor</div>
        <div class="dictador-sidebar-brand-subtitle">radiología asistida</div>
      </div>
    </div>
  `;

  let activeAiRequests = 0;

  function replaceVisibleText(root) {
    if (!root) return;

    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          const parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          if (["SCRIPT", "STYLE", "TEXTAREA", "INPUT", "PRE", "CODE"].includes(parent.tagName)) {
            return NodeFilter.FILTER_REJECT;
          }

          const value = node.nodeValue || "";
          if (
            value.includes("IA Dictador") ||
            value.includes("IADictador") ||
            value.includes("Trining IA") ||
            value.includes("Historial2")
          ) {
            return NodeFilter.FILTER_ACCEPT;
          }

          return NodeFilter.FILTER_REJECT;
        }
      }
    );

    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    nodes.forEach(node => {
      node.nodeValue = node.nodeValue
        .replaceAll("IA Dictador", "dIctAdor")
        .replaceAll("IADictador", "dIctAdor")
        .replaceAll("Trining IA", "Training IA")
        .replaceAll("Historial2", "Historial");
    });
  }

  function sidebarCandidates() {
    return [
      ...document.querySelectorAll("aside"),
      ...document.querySelectorAll(".sidebar"),
      ...document.querySelectorAll(".side-menu"),
      ...document.querySelectorAll(".iad-sidebar"),
      ...document.querySelectorAll("[class*='sidebar']")
    ].filter(Boolean);
  }

  function bestSidebar() {
    const candidates = sidebarCandidates();

    if (!candidates.length) return null;

    let best = null;
    let bestScore = -1;

    for (const el of candidates) {
      const rect = el.getBoundingClientRect();
      const text = (el.textContent || "").toLowerCase();
      let score = 0;

      if (rect.left < 80) score += 4;
      if (rect.width >= 140 && rect.width <= 340) score += 4;
      if (text.includes("plantillas")) score += 3;
      if (text.includes("historial")) score += 3;
      if (text.includes("training")) score += 3;
      if (text.includes("usuarios")) score += 2;
      if (text.includes("cerrar sesión") || text.includes("cerrar sesion")) score += 2;

      if (score > bestScore) {
        best = el;
        bestScore = score;
      }
    }

    return best;
  }

  function cleanDuplicateLinks(sidebar) {
    if (!sidebar) return;

    const links = [...sidebar.querySelectorAll("a")];
    const seen = new Set();

    for (const a of links) {
      let label = (a.textContent || "").trim()
        .replaceAll("Trining IA", "Training IA")
        .replaceAll("Historial2", "Historial")
        .replaceAll("IA Dictador", "dIctAdor");

      a.textContent = label;

      const href = a.getAttribute("href") || "";
      const key = href + "::" + label.toLowerCase();

      if (seen.has(key)) {
        a.remove();
      } else {
        seen.add(key);
      }
    }

    const reglasLinks = [...sidebar.querySelectorAll("a")]
      .filter(a => (a.textContent || "").trim().toLowerCase() === "reglas ia");

    reglasLinks.slice(1).forEach(a => a.remove());
  }

  function ensureRulesLink(sidebar) {
    if (!sidebar) return;

    const has = [...sidebar.querySelectorAll("a")].some(a => {
      return (a.textContent || "").trim().toLowerCase() === "reglas ia";
    });

    if (has) return;

    const a = document.createElement("a");
    a.href = "/iad/reglas-ia";
    a.textContent = "Reglas IA";
    a.setAttribute("data-dictador-rules-link", "1");

    const logout = [...sidebar.querySelectorAll("a")]
      .find(x => (x.textContent || "").toLowerCase().includes("cerrar"));

    if (logout && logout.parentElement === sidebar) {
      logout.insertAdjacentElement("beforebegin", a);
    } else {
      sidebar.appendChild(a);
    }
  }

  function ensureBrand(sidebar) {
    if (!sidebar) return;

    const existing = sidebar.querySelector(".dictador-sidebar-brand");
    if (existing) return;

    const oldBrand = [...sidebar.children].find(el => {
      const text = (el.textContent || "").trim().toLowerCase();
      return (
        text.includes("ia dictador") ||
        text.includes("dictador") ||
        text.includes("radiología asistida") ||
        text.includes("radiologia asistida")
      );
    });

    if (oldBrand) {
      oldBrand.outerHTML = BRAND_HTML;
    } else {
      sidebar.insertAdjacentHTML("afterbegin", BRAND_HTML);
    }
  }

  function markUserCard(sidebar) {
    if (!sidebar) return;

    [...sidebar.children].forEach(el => {
      const text = (el.textContent || "").toLowerCase();
      if (
        text.includes("rol:") ||
        text.includes("requests sesión") ||
        text.includes("requests sesion") ||
        text.includes("último login") ||
        text.includes("ultimo login")
      ) {
        el.classList.add("dictador-user-card");
      }
    });
  }


  function ensureUsageOpenAiLink(sidebar) {
    if (!sidebar) return;

    const has = [...sidebar.querySelectorAll("a")].some(a => {
      return (a.textContent || "").trim().toLowerCase() === "uso openai";
    });

    if (has) return;

    const a = document.createElement("a");
    a.href = "/iad/uso-openai";
    a.textContent = "Uso OpenAI";
    a.setAttribute("data-dictador-usage-link", "1");

    const rules = [...sidebar.querySelectorAll("a")]
      .find(x => (x.textContent || "").trim().toLowerCase() === "reglas ia");

    if (rules && rules.parentElement === sidebar) {
      rules.insertAdjacentElement("afterend", a);
    } else {
      sidebar.appendChild(a);
    }
  }

  function applyActive(sidebar) {
    if (!sidebar) return;

    const path = window.location.pathname;

    [...sidebar.querySelectorAll("a")].forEach(a => {
      const href = a.getAttribute("href") || "";
      a.classList.toggle("active", !!href && path.startsWith(href));
    });
  }

  function normalizeSidebar() {
    document.title = (document.title || "")
      .replaceAll("IA Dictador", "dIctAdor")
      .replaceAll("IADictador", "dIctAdor")
      .replaceAll("Trining IA", "Training IA")
      .replaceAll("Historial2", "Historial");

    replaceVisibleText(document.body);

    const sidebar = bestSidebar();
    if (!sidebar) return;

    sidebar.classList.add("dictador-sidebar-fixed");

    ensureBrand(sidebar);
    cleanDuplicateLinks(sidebar);
    ensureRulesLink(sidebar);
    ensureUsageOpenAiLink(sidebar);
    markUserCard(sidebar);
    applyActive(sidebar);
  }

  function ensureLoadingPill() {
    if (document.querySelector(".dictador-loading-pill")) return;

    const pill = document.createElement("div");
    pill.className = "dictador-loading-pill";
    pill.innerHTML = '<span class="dictador-loading-dot"></span><span>IA trabajando</span>';
    document.body.appendChild(pill);
  }

  function setWorking(on) {
    if (on) {
      activeAiRequests += 1;
    } else {
      activeAiRequests = Math.max(0, activeAiRequests - 1);
    }

    document.body.classList.toggle("iad-ai-working", activeAiRequests > 0);
    document.body.setAttribute("aria-busy", activeAiRequests > 0 ? "true" : "false");
  }

  function isAiEndpoint(url) {
    return (
      url.includes("/iad/api/audio/procesar-dictado-completo.json") ||
      url.includes("/iad/api/v3/audio/procesar-dictado-completo.json") ||
      url.includes("/iad/api/radiology") ||
      url.includes("/iad/api/ia") ||
      url.includes("/iad/api/ai")
    );
  }

  if (!window.__dictador_sidebar_fetch_wrapped) {
    window.__dictador_sidebar_fetch_wrapped = true;

    const originalFetch = window.fetch;

    window.fetch = async function dictadorSidebarFetchWrapper(input, init) {
      const url = (typeof input === "string") ? input : (input && input.url) || "";
      const track = isAiEndpoint(url);

      if (track) setWorking(true);

      try {
        return await originalFetch.apply(this, arguments);
      } finally {
        if (track) {
          setTimeout(() => setWorking(false), 300);
          setTimeout(normalizeSidebar, 400);
        }
      }
    };
  }

  function init() {
    normalizeSidebar();
    ensureLoadingPill();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  setTimeout(init, 300);
  setTimeout(init, 1200);
  setTimeout(init, 2500);

  window.dictadorNormalizeSidebar = normalizeSidebar;
  window.dictadorSetWorking = setWorking;
})();
