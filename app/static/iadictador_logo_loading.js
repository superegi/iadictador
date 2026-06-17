(function dictadorLogoLoading() {
  const LOGO_URL = "/static/img/logo.png";
  let activeRequests = 0;

  function ensureLoadingPill() {
    if (document.querySelector(".dictador-loading-pill")) return;

    const pill = document.createElement("div");
    pill.className = "dictador-loading-pill";
    pill.innerHTML = '<img class="dictador-loading-logo" src="/static/img/logo.png" alt="dIctAdor trabajando"><span>IA trabajando</span>';
    document.body.appendChild(pill);
  }

  function setWorking(on) {
    if (on) activeRequests += 1;
    else activeRequests = Math.max(0, activeRequests - 1);

    document.body.classList.toggle("iad-ai-working", activeRequests > 0);
    document.body.setAttribute("aria-busy", activeRequests > 0 ? "true" : "false");
  }

  function isAiEndpoint(url) {
    return (
      url.includes("/iad/api/audio/procesar-dictado-completo.json") ||
      url.includes("/iad/api/v3/audio/procesar-dictado-completo.json") ||
      url.includes("/iad/api/validar") ||
      url.includes("/iad/api/revision") ||
      url.includes("/iad/api/ia") ||
      url.includes("/iad/api/ai") ||
      url.includes("/iad/analizar-radiologia") ||
      url.includes("/iad/generar-informe")
    );
  }

  function replaceOldLogoImages() {
    document.querySelectorAll("img").forEach(img => {
      const src = img.getAttribute("src") || "";
      const alt = (img.getAttribute("alt") || "").toLowerCase();

      if (
        src.includes("dictador_logo.svg") ||
        src.includes("logo.png") ||
        alt.includes("dictador") ||
        img.closest(".dictador-sidebar-brand")
      ) {
        img.src = LOGO_URL;
        img.classList.add("dictador-logo-real");
        img.setAttribute("data-dictador-logo", "1");
        img.alt = "dIctAdor";
      }
    });
  }

  function ensureLogoInSidebar() {
    replaceOldLogoImages();

    const sidebar =
      document.querySelector("aside") ||
      document.querySelector(".sidebar") ||
      document.querySelector(".iad-sidebar") ||
      document.querySelector("[class*='sidebar']");

    if (!sidebar) return;

    let brand =
      sidebar.querySelector(".dictador-sidebar-brand") ||
      sidebar.querySelector(".brand") ||
      sidebar.querySelector("[data-iad-brand]");

    if (!brand) {
      brand = document.createElement("div");
      brand.className = "dictador-sidebar-brand";
      brand.innerHTML = `
        <img src="${LOGO_URL}" class="dictador-logo-real" data-dictador-logo="1" alt="dIctAdor">
        <div>
          <div class="dictador-sidebar-brand-title">d<span class="ai">I</span>ct<span class="ai">A</span>dor</div>
          <div class="dictador-sidebar-brand-subtitle">radiología asistida</div>
        </div>
      `;
      sidebar.insertAdjacentElement("afterbegin", brand);
      return;
    }

    let img = brand.querySelector("img");
    if (!img) {
      img = document.createElement("img");
      img.src = LOGO_URL;
      img.alt = "dIctAdor";
      img.className = "dictador-logo-real";
      img.setAttribute("data-dictador-logo", "1");
      brand.insertAdjacentElement("afterbegin", img);
    } else {
      img.src = LOGO_URL;
      img.classList.add("dictador-logo-real");
      img.setAttribute("data-dictador-logo", "1");
      img.alt = "dIctAdor";
    }
  }

  function init() {
    ensureLogoInSidebar();
    ensureLoadingPill();
  }

  if (!window.__dictador_logo_loading_fetch_wrapped) {
    window.__dictador_logo_loading_fetch_wrapped = true;
    const originalFetch = window.fetch;

    window.fetch = async function dictadorLogoLoadingFetch(input, init) {
      const url = (typeof input === "string") ? input : (input && input.url) || "";
      const track = isAiEndpoint(url);

      if (track) setWorking(true);

      try {
        return await originalFetch.apply(this, arguments);
      } finally {
        if (track) {
          setTimeout(() => setWorking(false), 300);
          setTimeout(init, 450);
        }
      }
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  setTimeout(init, 300);
  setTimeout(init, 1200);

  window.dictadorSetWorking = setWorking;
  window.dictadorEnsureLogo = init;
})();
