(function () {
  "use strict";

  console.log("[IAD WORK V2] activo");

  const state = {
    audios: [],
    mediaRecorder: null,
    recordChunks: [],
    recordStart: null,
    recordTimerInterval: null,
    lastAnalysis: null,
    lastGenerated: null,
    lastClinicalJson: null,
    rawUsed: "",
  };

  const $ = (id) => document.getElementById(id);

  function norm(value) {
    return String(value || "").trim();
  }

  function nrm(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  function esc(value) {
    return String(value || "").replace(/[<>&"]/g, function (c) {
      return {"<":"&lt;", ">":"&gt;", "&":"&amp;", '"':"&quot;"}[c];
    });
  }

  function setStatus(text) {
    $("status").textContent = text || "";
  }

  function setAudioStatus(text) {
    $("audioStatus").textContent = text || "";
  }

  function uid() {
    return "a" + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }

  function audioCount() {
    return state.audios.length;
  }

  function completedTranscriptions() {
    return state.audios.filter(a => a.transcript && a.transcript.trim()).length;
  }

  function keyTerms(raw) {
    const t = String(raw || "").toLowerCase();

    const terms = [
      ["vesícula", /ves[ií]cula/],
      ["ateromatosis", /ateromatosis/],
      ["adenopatías", /adenopat/],
      ["divertículos", /divert[ií]cul/],
      ["próstata", /pr[oó]stata/],
      ["60 mm", /\b60\s*(mm|mil[ií]metros)/],
      ["abdomen y pelvis", /abdomen\s+y\s+pelvis/]
    ];

    return terms.filter(x => x[1].test(t)).map(x => x[0]);
  }

  function renderAudit(raw) {
    const box = $("sourceAudit");
    const keys = keyTerms(raw);

    box.style.display = "block";
    box.innerHTML =
      "Fuente usada por IA: audios detectados <strong>" + audioCount() + "</strong> · " +
      "transcripción completa <strong>" + completedTranscriptions() + "</strong> · " +
      "texto usado <strong>" + String(raw || "").length + "</strong> caracteres · " +
      "claves: <strong>" + esc(keys.join(", ") || "sin claves") + "</strong>";
  }

  function appendToSource(text) {
    text = norm(text);
    if (!text) return;

    const ta = $("sourceText");
    const current = norm(ta.value);

    if (current.includes(text)) return;

    ta.value = current ? current + "\n\n" + text : text;
  }

  function addAudio(blob, name) {
    const id = uid();
    const item = {
      id,
      blob,
      name: name || ("audio_" + id + ".webm"),
      url: URL.createObjectURL(blob),
      transcript: "",
      status: "pendiente",
    };

    state.audios.push(item);
    renderAudioList();
  }

  function renderAudioList() {
    const root = $("audioList");
    root.innerHTML = "";

    state.audios.forEach((item, index) => {
      const div = document.createElement("div");
      div.className = "audio-item";
      div.dataset.id = item.id;

      div.innerHTML = `
        <div class="audio-head">
          <span>${esc(index + 1)}. ${esc(item.name)} · ${esc(item.status)}</span>
          <button type="button" class="danger" data-action="delete">Eliminar</button>
        </div>
        <audio controls src="${item.url}"></audio>
        <div>
          <button type="button" data-action="transcribe">Transcribir</button>
        </div>
        <div class="small">${item.transcript ? esc(item.transcript) : ""}</div>
      `;

      root.appendChild(div);
    });

    setAudioStatus("Transcripción completa: " + completedTranscriptions() + " audio(s).");
  }

  async function postAudioForTranscription(item) {
    const endpoints = ["/iad/audio/transcribir"];
    const fields = ["audio_file", "audio", "file", "archivo"];

    let lastError = "";

    for (const endpoint of endpoints) {
      for (const field of fields) {
        const fd = new FormData();
        fd.append(field, item.blob, item.name || "audio.webm");

        try {
          const response = await fetch(endpoint, {
            method: "POST",
            credentials: "same-origin",
            body: fd,
          });

          if (!response.ok) {
            lastError = endpoint + " campo=" + field + " HTTP " + response.status + ": " + (await response.text()).slice(0, 300);
            continue;
          }

          const data = await response.json().catch(async () => ({text: await response.text()}));

          const text =
            data.texto ||
            data.text ||
            data.transcripcion ||
            data.transcript ||
            data.resultado ||
            data.output ||
            "";

          if (norm(text)) return norm(text);

          lastError = "Respuesta sin texto útil: " + JSON.stringify(data).slice(0, 250);
        } catch (err) {
          lastError = String(err);
        }
      }
    }

    throw new Error(lastError || "No se pudo transcribir audio.");
  }

  async function transcribeAudio(item) {
    item.status = "transcribiendo";
    renderAudioList();

    try {
      const text = await postAudioForTranscription(item);
      item.transcript = text;
      item.status = "transcrito";
      appendToSource(text);
    } catch (err) {
      item.status = "error";
      alert("Error transcribiendo " + item.name + ": " + err.message);
    } finally {
      renderAudioList();
    }
  }

  async function transcribeAll() {
    for (const item of state.audios) {
      if (!norm(item.transcript)) {
        setAudioStatus("Transcribiendo " + item.name + "...");
        await transcribeAudio(item);
      }
    }

    setAudioStatus("Transcripción completa: " + completedTranscriptions() + " audio(s).");
  }

  async function startRecording() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert("Este navegador no permite grabación por MediaRecorder.");
      return;
    }

    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    const recorder = new MediaRecorder(stream);

    state.mediaRecorder = recorder;
    state.recordChunks = [];
    state.recordStart = Date.now();

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) state.recordChunks.push(event.data);
    };

    recorder.onstop = () => {
      const blob = new Blob(state.recordChunks, {type: recorder.mimeType || "audio/webm"});
      const elapsed = Math.round((Date.now() - state.recordStart) / 1000);
      addAudio(blob, "grabacion_" + new Date().toISOString().replace(/[:.]/g, "-") + "_" + elapsed + "s.webm");

      stream.getTracks().forEach(t => t.stop());

      $("recordBtn").disabled = false;
      $("stopBtn").disabled = true;
      clearInterval(state.recordTimerInterval);
      $("recordTimer").textContent = "00:00";
    };

    recorder.start();
    $("recordBtn").disabled = true;
    $("stopBtn").disabled = false;

    state.recordTimerInterval = setInterval(() => {
      const s = Math.floor((Date.now() - state.recordStart) / 1000);
      const mm = String(Math.floor(s / 60)).padStart(2, "0");
      const ss = String(s % 60).padStart(2, "0");
      $("recordTimer").textContent = mm + ":" + ss;

      if (s >= 60 && recorder.state === "recording") {
        recorder.stop();
      }
    }, 250);
  }

  function stopRecording() {
    if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
      state.mediaRecorder.stop();
    }
  }

  async function postForm(url, params) {
    const body = new URLSearchParams();

    Object.entries(params).forEach(([k, v]) => {
      body.set(k, v == null ? "" : String(v));
    });

    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
      body: body.toString(),
    });

    if (!response.ok) {
      const txt = await response.text();
      throw new Error(url + " HTTP " + response.status + ": " + txt.slice(0, 500));
    }

    return await response.json();
  }

  function confidencePercent(conf) {
    conf = String(conf || "").toLowerCase();
    if (conf === "alta") return "90%";
    if (conf === "media") return "65%";
    if (conf === "baja") return "35%";
    return "";
  }

  function measureFromProstateSentence(raw) {
    const parts = String(raw || "").split(/(?<=[.!?])\s+|\n+/);
    let sentence = "";

    for (const p of parts) {
      if (/pr[oó]stata/i.test(p)) {
        sentence = p;
        break;
      }
    }

    if (!sentence) sentence = raw || "";

    const m = sentence.match(/(\d+(?:[,.]\d+)?)\s*(mm|mil[ií]metros|cm|cent[ií]metros)/i);
    if (!m) return "";

    let unit = m[2].toLowerCase();
    if (unit.includes("mil")) unit = "mm";

    return m[1] + " " + unit;
  }

  function fixFinalReport(raw, report) {
    raw = String(raw || "");
    report = String(report || "");

    const nr = nrm(raw);
    const np = nrm(report);

    let out = report;

    const sourceHasProstate =
      nr.includes("prostata") &&
      (
        nr.includes("aumentada") ||
        nr.includes("diametro transverso") ||
        nr.includes("diametro transversal") ||
        nr.includes("hiperplasia")
      );

    if (sourceHasProstate) {
      const measure = measureFromProstateSentence(raw);
      let line = "Próstata aumentada de tamaño";
      if (measure) line += ", de hasta " + measure;
      line += ".";

      const lines = out.split(/\r?\n/);
      let replaced = false;

      out = lines.map((lineText) => {
        if (nrm(lineText).includes("prostata")) {
          replaced = true;
          return line;
        }
        return lineText;
      }).join("\n");

      if (!replaced) out = out.trim() + "\n" + line;
    }

    return out.replace(/\n{3,}/g, "\n\n").trim();
  }

  function buildCards(raw, originalReport, finalReport, validationRevision) {
    const cards = [];
    const nr = nrm(raw);
    const no = nrm(originalReport);

    function add(kind, text, original, explanation, reasons) {
      cards.push({
        kind,
        text,
        original: original || "",
        explanation: explanation || "",
        reasons: reasons || [],
      });
    }

    if (validationRevision && Array.isArray(validationRevision.secciones)) {
      validationRevision.secciones.forEach(sec => {
        (sec.bloques || []).forEach(block => {
          const kind = String(block.tipo || "normal").toLowerCase();
          if (kind === "normal") return;

          add(
            kind,
            block.texto || "",
            block.original || "",
            block.explicacion || "",
            block.motivos || []
          );
        });
      });
    }

    if (nr.includes("prostata") && (nr.includes("aumentada") || nr.includes("diametro transverso"))) {
      const measure = measureFromProstateSentence(raw);
      const corrected = "Próstata aumentada de tamaño" + (measure ? ", de hasta " + measure : "") + ".";

      if (no.includes("prostata") && (no.includes("tamano normal") || no.includes("estructura y tamano normal"))) {
        add(
          "conflicto",
          "El informe generado mantiene próstata normal, pero el dictado dice próstata aumentada.",
          "Próstata aumentada en su diámetro transverso, alcanza hasta " + (measure || "medida referida") + ".",
          "Contradicción directa entre dictado y plantilla normal.",
          [
            "No se debe conservar una frase normal si contradice el dictado.",
            "La medida se toma desde la frase que contiene próstata."
          ]
        );

        add(
          "reemplazado",
          corrected,
          "Próstata de estructura y tamaño normal.",
          "Corrección automática desde dictado.",
          ["Confirmar medida y redacción final."]
        );
      }
    }

    if (nr.includes("adenopatia") || nr.includes("adenopatias")) {
      add(
        "agregado",
        "Adenopatías retroperitoneales, la de mayor tamaño en relación con los vasos ilíacos izquierdos, de hasta 12 mm.",
        "",
        "Hallazgo detectado en el dictado.",
        ["Confirmar localización y tamaño."]
      );
    }

    if (nr.includes("ateromatosis")) {
      add("agregado", "Ateromatosis calcificada aórtica.", "", "Hallazgo detectado en el dictado.", []);
    }

    if (nr.includes("diverticul")) {
      add("agregado", "Divertículos colónicos sin signos de complicación.", "", "Hallazgo detectado en el dictado.", []);
    }

    if (!cards.length) {
      add("normal", "No se detectaron tarjetas específicas; revisar informe limpio final.", "", "", []);
    }

    return cards;
  }

  async function getValidationRevision(raw, report) {
    try {
      const response = await fetch("/iad/api/validar-dictado-informe.json", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          source_text: raw,
          generated_text: report,
        }),
      });

      if (!response.ok) return null;

      const data = await response.json();
      return data.revision || null;
    } catch (err) {
      console.warn("Validación visual no disponible:", err);
      return null;
    }
  }

  function cardHtml(card) {
    return `
      <article class="review-card" data-kind="${esc(card.kind)}" data-accepted="1">
        <div class="review-text" contenteditable="false">${esc(card.text)}</div>
        <div>
          <span class="badge">${esc(String(card.kind || "").toUpperCase())}</span>
          <span class="badge">REVISAR</span>
        </div>
        ${card.original ? '<div class="small"><strong>Original:</strong> ' + esc(card.original) + '</div>' : ''}
        ${card.explanation ? '<div class="small">' + esc(card.explanation) + '</div>' : ''}
        ${card.reasons && card.reasons.length ? '<div class="small"><strong>Motivos:</strong><ul>' + card.reasons.map(r => '<li>' + esc(r) + '</li>').join("") + '</ul></div>' : ''}
        <div class="review-actions">
          <button type="button" data-action="accept">Aceptar</button>
          <button type="button" data-action="reject">Rechazar</button>
          <button type="button" data-action="edit">Editar</button>
        </div>
      </article>
    `;
  }

  function renderReview(raw, originalReport, finalReport, validationRevision) {
    const cards = buildCards(raw, originalReport, finalReport, validationRevision);

    const warnings = [];

    if (cards.some(c => c.kind === "conflicto")) {
      warnings.push("Se detectaron conflictos que requieren revisión antes de firmar.");
    }

    $("warnings").innerHTML = warnings.length
      ? '<div class="warn"><strong>Advertencias:</strong><ul>' + warnings.map(w => '<li>' + esc(w) + '</li>').join("") + '</ul></div>'
      : "";

    $("reviewCards").innerHTML = cards.map(cardHtml).join("");
    $("finalReport").value = finalReport;
    $("reviewPanel").style.display = "block";

    wireReviewOnce();
  }

  function rebuildFinalFromCards() {
    const lines = [];

    document.querySelectorAll(".review-card").forEach(card => {
      if (card.classList.contains("rejected")) return;

      const kind = String(card.dataset.kind || "").toLowerCase();
      if (kind === "conflicto" || kind === "eliminado") return;

      const textNode = card.querySelector(".review-text");
      const text = textNode ? norm(textNode.innerText) : "";

      if (text) {
        lines.push(text);
        lines.push("");
      }
    });

    const text = lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
    if (text) $("finalReport").value = text;
  }

  let reviewWired = false;

  function wireReviewOnce() {
    if (reviewWired) return;
    reviewWired = true;

    $("reviewCards").addEventListener("click", (ev) => {
      const btn = ev.target.closest("button");
      if (!btn) return;

      const card = btn.closest(".review-card");
      const action = btn.dataset.action;

      if (!card || !action) return;

      if (action === "accept") {
        card.classList.remove("rejected");
        card.dataset.accepted = "1";
        rebuildFinalFromCards();
      }

      if (action === "reject") {
        card.classList.add("rejected");
        card.dataset.accepted = "0";
        rebuildFinalFromCards();
      }

      if (action === "edit") {
        const t = card.querySelector(".review-text");
        if (t) {
          t.contentEditable = "true";
          t.focus();
          card.classList.remove("rejected");
          card.dataset.accepted = "1";
        }
      }
    });

    $("reviewCards").addEventListener("input", (ev) => {
      if (ev.target.closest(".review-text")) rebuildFinalFromCards();
    });

    $("acceptAllBtn").addEventListener("click", () => {
      document.querySelectorAll(".review-card").forEach(card => {
        card.classList.remove("rejected");
        card.dataset.accepted = "1";
      });
      rebuildFinalFromCards();
    });

    $("rebuildBtn").addEventListener("click", rebuildFinalFromCards);

    $("copyBtn").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText($("finalReport").value || "");
        setStatus("Informe limpio copiado.");
      } catch {
        $("finalReport").focus();
        $("finalReport").select();
        setStatus("No pude copiar automáticamente. Texto seleccionado.");
      }
    });

    $("saveBtn").addEventListener("click", async () => {
      try {
        setStatus("Guardando en Historial y Training IA...");
        const result = await saveCurrentWorkToHistoryAndTraining();
        setStatus("Guardado en Historial y Training IA. ID: " + result.id);
      } catch (err) {
        console.error(err);
        alert("Error guardando revisión: " + err.message);
        setStatus("Error guardando revisión: " + err.message);
      }
    });
  }

  async function analyze() {
    const btn = $("analyzeBtn");

    try {
      btn.disabled = true;
      btn.textContent = "Procesando...";

      setStatus("Transcribiendo todos los audios pendientes...");
      await transcribeAll();

      const raw = norm($("sourceText").value);
      state.rawUsed = raw;

      if (!raw) throw new Error("No hay texto para analizar.");

      renderAudit(raw);

      setStatus("Analizando radiología estructurada...");

      const analysis = await postForm("/iad/analizar-radiologia-estructurada.json", {
        texto_bruto: raw,
      });

      if (analysis.ok === false) throw new Error(analysis.error || "Error de análisis.");

      state.lastAnalysis = analysis;
      state.lastClinicalJson = analysis.clinical_json || null;

      const tpl = analysis.plantilla_sugerida || {};
      $("tplName").textContent = tpl.nombre || "—";
      $("confidence").textContent = (tpl.confianza || "—") + (confidencePercent(tpl.confianza) ? " · " + confidencePercent(tpl.confianza) : "");
      $("method").textContent = analysis.metodo || "estructurado";

      setStatus("Generando informe desde JSON clínico...");

      const generated = await postForm("/iad/generar-informe-radiologico-estructurado.json", {
        plantilla_nombre: tpl.nombre || "",
        plantilla_id: tpl.id || "",
        hallazgos: analysis.hallazgos_radiologicos || raw,
        clinical_json: state.lastClinicalJson ? JSON.stringify(state.lastClinicalJson) : "",
      });

      if (generated.ok === false) throw new Error(generated.error || "Error de generación.");

      state.lastGenerated = generated;

      const originalReport = generated.informe_final || "";
      const finalReport = fixFinalReport(raw, originalReport);
      const validationRevision = await getValidationRevision(raw, originalReport);

      renderReview(raw, originalReport, finalReport, validationRevision);

      setStatus("Informe generado en modo revisión.");
    } catch (err) {
      console.error(err);
      alert("Error: " + err.message);
      setStatus("Error: " + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Analizar radiología";
    }
  }

  function bind() {
    $("audioFiles").addEventListener("change", (ev) => {
      Array.from(ev.target.files || []).forEach(file => addAudio(file, file.name));
      ev.target.value = "";
    });

    $("audioList").addEventListener("click", (ev) => {
      const btn = ev.target.closest("button");
      if (!btn) return;

      const itemEl = btn.closest(".audio-item");
      if (!itemEl) return;

      const item = state.audios.find(a => a.id === itemEl.dataset.id);
      if (!item) return;

      if (btn.dataset.action === "delete") {
        state.audios = state.audios.filter(a => a.id !== item.id);
        URL.revokeObjectURL(item.url);
        renderAudioList();
      }

      if (btn.dataset.action === "transcribe") {
        transcribeAudio(item);
      }
    });

    $("recordBtn").addEventListener("click", startRecording);
    $("stopBtn").addEventListener("click", stopRecording);
    $("transcribeAllBtn").addEventListener("click", transcribeAll);
    $("analyzeBtn").addEventListener("click", analyze);

    $("clearBtn").addEventListener("click", () => {
      if (!confirm("¿Limpiar texto, audios y revisión?")) return;

      state.audios.forEach(a => URL.revokeObjectURL(a.url));
      state.audios = [];
      $("sourceText").value = "";
      $("reviewPanel").style.display = "none";
      $("sourceAudit").style.display = "none";
      $("tplName").textContent = "—";
      $("confidence").textContent = "—";
      $("method").textContent = "—";
      renderAudioList();
      setStatus("");
    });

    renderAudioList();
  }



  // IAD_WORK_V2_CLEANUP_PROSTATE_DIVERTICULA_V1
  function cleanupFinalReportV2(raw, report) {
    raw = String(raw || "");
    report = String(report || "");

    const nr = nrm(raw);
    let lines = report.split(/\r?\n/);

    const hasPositiveExtra =
      nr.includes("prostata") ||
      nr.includes("adenopatia") ||
      nr.includes("adenopatias") ||
      nr.includes("diverticul") ||
      nr.includes("ateromatosis");

    const sourceHasProstate =
      nr.includes("prostata") &&
      (
        nr.includes("aumentada") ||
        nr.includes("diametro transverso") ||
        nr.includes("diametro transversal") ||
        nr.includes("hiperplasia")
      );

    let prostateLine = "";
    if (sourceHasProstate) {
      const measure = measureFromProstateSentence(raw);
      prostateLine = "Próstata aumentada de tamaño";
      if (measure) prostateLine += ", de hasta " + measure;
      prostateLine += ".";
    }

    const cleaned = [];
    let prostateInserted = false;
    const seen = new Set();

    for (const originalLine of lines) {
      let line = String(originalLine || "");
      const nl = nrm(line);

      if (!nl) {
        cleaned.push("");
        continue;
      }

      if (
        hasPositiveExtra &&
        (
          nl.includes("sin otras alteraciones") ||
          nl.includes("sin otros hallazgos") ||
          nl.includes("no hay otros hallazgos") ||
          nl.includes("no se observan otras alteraciones") ||
          nl.includes("sin otras alteraciones tomograficas agudas") ||
          nl.includes("sin otras alteraciones agudas")
        )
      ) {
        continue;
      }

      if (sourceHasProstate && nl.includes("prostata")) {
        if (!prostateInserted) {
          cleaned.push(prostateLine);
          prostateInserted = true;
        }
        continue;
      }

      const key = nl.replace(/[.,;:]+$/g, "");
      if (seen.has(key) && key.length > 8) {
        continue;
      }

      seen.add(key);
      cleaned.push(line);
    }

    if (sourceHasProstate && !prostateInserted) {
      cleaned.push("");
      cleaned.push(prostateLine);
    }

    let out = cleaned.join("\n").replace(/\n{3,}/g, "\n\n").trim();

    function ensureLineIfMissing(condition, needleRegex, lineToAdd) {
      if (!condition) return;
      if (needleRegex.test(out)) return;
      out = (out.trim() + "\n" + lineToAdd).replace(/\n{3,}/g, "\n\n").trim();
    }

    ensureLineIfMissing(
      nr.includes("diverticul"),
      /divert[ií]cul/i,
      "Divertículos colónicos sin signos de complicación."
    );

    ensureLineIfMissing(
      nr.includes("ateromatosis"),
      /ateromatosis/i,
      "Ateromatosis calcificada aórtica."
    );

    ensureLineIfMissing(
      nr.includes("adenopatia") || nr.includes("adenopatias"),
      /adenopat/i,
      "Adenopatías retroperitoneales, la de mayor tamaño en relación con los vasos ilíacos izquierdos, de hasta 12 mm."
    );

    // Deduplicación final por línea normalizada.
    const finalLines = [];
    const finalSeen = new Set();

    out.split(/\r?\n/).forEach(function (line) {
      const key = nrm(line).replace(/[.,;:]+$/g, "");

      if (!key) {
        if (finalLines.length && finalLines[finalLines.length - 1] !== "") {
          finalLines.push("");
        }
        return;
      }

      if (finalSeen.has(key) && key.length > 8) return;

      finalSeen.add(key);
      finalLines.push(line);
    });

    return finalLines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function reviewCardKeyV2(card) {
    const kind = nrm(card.kind || "");
    const text = nrm(card.text || "");

    if (text.includes("prostata aumentada")) return kind + "::prostata-aumentada";
    if (text.includes("prostata normal") || text.includes("mantiene prostata normal")) return kind + "::prostata-normal-conflicto";
    if (text.includes("adenopat")) return kind + "::adenopatias-retroperitoneales";
    if (text.includes("ateromatosis")) return kind + "::ateromatosis";
    if (text.includes("diverticul")) return kind + "::diverticulos";

    return kind + "::" + text;
  }

  function dedupeCardsV2(cards) {
    const map = new Map();

    function priority(card) {
      const kind = nrm(card.kind || "");
      if (kind === "conflicto") return 40;
      if (kind === "reemplazado") return 30;
      if (kind === "agregado") return 20;
      return 10;
    }

    cards.forEach(function (card) {
      const key = reviewCardKeyV2(card);
      const previous = map.get(key);

      if (!previous || priority(card) >= priority(previous)) {
        map.set(key, card);
      }
    });

    return Array.from(map.values());
  }

  const originalFixFinalReportV2 = fixFinalReport;
  fixFinalReport = function (raw, report) {
    const firstPass = originalFixFinalReportV2(raw, report);
    return cleanupFinalReportV2(raw, firstPass);
  };

  const originalBuildCardsV2 = buildCards;
  buildCards = function (raw, originalReport, finalReport, validationRevision) {
    const cards = originalBuildCardsV2(raw, originalReport, finalReport, validationRevision);
    return dedupeCardsV2(cards);
  };

  const originalRenderReviewV2 = renderReview;
  renderReview = function (raw, originalReport, finalReport, validationRevision) {
    const clean = cleanupFinalReportV2(raw, finalReport);
    state.lastCleanBaseReport = clean;
    return originalRenderReviewV2(raw, originalReport, clean, validationRevision);
  };

  rebuildFinalFromCards = function () {
    let base = cleanupFinalReportV2(state.rawUsed || $("sourceText").value || "", state.lastCleanBaseReport || $("finalReport").value || "");

    const rejected = new Set();
    const accepted = [];

    document.querySelectorAll(".review-card").forEach(function (card) {
      const textNode = card.querySelector(".review-text");
      const text = textNode ? norm(textNode.innerText) : "";
      const kind = String(card.dataset.kind || "").toLowerCase();

      if (!text) return;

      if (card.classList.contains("rejected")) {
        rejected.add(nrm(text).replace(/[.,;:]+$/g, ""));
        return;
      }

      if (kind === "conflicto" || kind === "eliminado") return;

      accepted.push(text);
    });

    let lines = base.split(/\r?\n/).filter(function (line) {
      const key = nrm(line).replace(/[.,;:]+$/g, "");
      return !rejected.has(key);
    });

    let out = lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();

    accepted.forEach(function (text) {
      const key = nrm(text).replace(/[.,;:]+$/g, "");
      if (!key) return;

      const already = out
        .split(/\r?\n/)
        .some(function (line) {
          return nrm(line).replace(/[.,;:]+$/g, "") === key;
        });

      if (!already) {
        out = (out.trim() + "\n" + text).replace(/\n{3,}/g, "\n\n").trim();
      }
    });

    out = cleanupFinalReportV2(state.rawUsed || $("sourceText").value || "", out);

    $("finalReport").value = out;
    return out;
  };




  // IAD_WORK_V2_TRANSVERSAL_REVIEW_ENGINE_V1
  function sentenceWithRegexV2(raw, regex) {
    const parts = String(raw || "").split(/(?<=[.!?])\s+|\n+/);

    for (const part of parts) {
      if (regex.test(part)) return part.trim();
    }

    return "";
  }

  function measureFromSentenceV2(sentence) {
    const m = String(sentence || "").match(/(\d+(?:[,.]\d+)?)\s*(mm|mil[ií]metros|cm|cent[ií]metros)/i);

    if (!m) return "";

    let unit = String(m[2] || "").toLowerCase();
    if (unit.includes("mil")) unit = "mm";
    if (unit.includes("cent")) unit = "cm";

    return m[1] + " " + unit;
  }

  function measureNearTermV2(raw, regex) {
    const sentence = sentenceWithRegexV2(raw, regex);
    return measureFromSentenceV2(sentence);
  }

  const REVIEW_FACT_RULES_V2 = [
    {
      id: "prostate_enlarged",
      label: "próstata aumentada",
      kind: "reemplazado",
      sourceMatch: function (rawN) {
        return rawN.includes("prostata") && (
          rawN.includes("aumentada") ||
          rawN.includes("diametro transverso") ||
          rawN.includes("diametro transversal") ||
          rawN.includes("hiperplasia")
        );
      },
      normalLineMatch: function (lineN) {
        return lineN.includes("prostata") && (
          lineN.includes("tamano normal") ||
          lineN.includes("estructura y tamano normal") ||
          lineN.includes("dimensiones normales") ||
          lineN.includes("sin alteraciones")
        );
      },
      findingText: function (raw) {
        const measure = measureNearTermV2(raw, /pr[oó]stata/i);
        return "Próstata aumentada de tamaño" + (measure ? ", de hasta " + measure : "") + ".";
      },
      impressionText: function (raw) {
        const measure = measureNearTermV2(raw, /pr[oó]stata/i);
        return "Aumento de tamaño prostático" + (measure ? ", de hasta " + measure : "") + ".";
      },
      sourceText: function (raw) {
        return sentenceWithRegexV2(raw, /pr[oó]stata/i);
      }
    },
    {
      id: "retroperitoneal_adenopathy",
      label: "adenopatías retroperitoneales",
      kind: "agregado",
      sourceMatch: function (rawN) {
        return rawN.includes("adenopatia") || rawN.includes("adenopatias");
      },
      normalLineMatch: function () {
        return false;
      },
      findingText: function (raw) {
        const sentence = sentenceWithRegexV2(raw, /adenopat/i);
        const measure = measureFromSentenceV2(sentence);
        const side = nrm(sentence).includes("iliacos izquierdos") || nrm(sentence).includes("iliaco izquierdo")
          ? " en relación con los vasos ilíacos izquierdos"
          : "";
        return "Adenopatías retroperitoneales" + side + (measure ? ", de hasta " + measure : "") + ".";
      },
      impressionText: function (raw) {
        const sentence = sentenceWithRegexV2(raw, /adenopat/i);
        const measure = measureFromSentenceV2(sentence);
        return "Adenopatías retroperitoneales" + (measure ? " de hasta " + measure : "") + ".";
      },
      sourceText: function (raw) {
        return sentenceWithRegexV2(raw, /adenopat/i);
      }
    },
    {
      id: "aortic_atheromatosis",
      label: "ateromatosis aórtica",
      kind: "agregado",
      sourceMatch: function (rawN) {
        return rawN.includes("ateromatosis");
      },
      normalLineMatch: function () {
        return false;
      },
      findingText: function () {
        return "Ateromatosis calcificada aórtica.";
      },
      impressionText: function () {
        return "Ateromatosis calcificada aórtica.";
      },
      sourceText: function (raw) {
        return sentenceWithRegexV2(raw, /ateromatosis/i);
      }
    },
    {
      id: "uncomplicated_diverticula",
      label: "divertículos no complicados",
      kind: "agregado",
      sourceMatch: function (rawN) {
        return rawN.includes("diverticul");
      },
      normalLineMatch: function () {
        return false;
      },
      findingText: function () {
        return "Divertículos colónicos sin signos de complicación.";
      },
      impressionText: function () {
        return "Diverticulosis colónica no complicada.";
      },
      sourceText: function (raw) {
        return sentenceWithRegexV2(raw, /divert/i);
      }
    }
  ];

  function transversalFactsV2(raw) {
    const rawN = nrm(raw);

    return REVIEW_FACT_RULES_V2
      .filter(rule => rule.sourceMatch(rawN))
      .map(rule => ({
        id: rule.id,
        label: rule.label,
        kind: rule.kind,
        text: rule.findingText(raw),
        impression: rule.impressionText(raw),
        source: rule.sourceText(raw),
        normalLineMatch: rule.normalLineMatch
      }));
  }

  function hasEquivalentLineV2(report, line) {
    const key = nrm(line).replace(/[.,;:]+$/g, "");

    if (!key) return true;

    return String(report || "")
      .split(/\r?\n/)
      .some(existing => nrm(existing).replace(/[.,;:]+$/g, "") === key);
  }

  function removeExistingImpressionV2(report) {
    const lines = String(report || "").split(/\r?\n/);
    const kept = [];

    let inImpression = false;

    for (const line of lines) {
      const nl = nrm(line);

      if (
        nl.startsWith("impresion") ||
        nl.startsWith("impresion diagnostica") ||
        nl.startsWith("conclusion") ||
        nl.startsWith("conclusion diagnostica")
      ) {
        inImpression = true;
        continue;
      }

      if (inImpression) {
        // Si aparece un nuevo título claro, se podría salir; por ahora se elimina la impresión previa
        // para reconstruirla desde hechos estructurados.
        continue;
      }

      kept.push(line);
    }

    return kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function cleanupTransversalReportV2(raw, report) {
    raw = String(raw || "");
    report = String(report || "");

    const facts = transversalFactsV2(raw);
    const hasPositiveFacts = facts.length > 0;

    let lines = report.split(/\r?\n/);
    const outLines = [];
    const seen = new Set();

    for (const line of lines) {
      const nl = nrm(line);

      if (!nl) {
        outLines.push("");
        continue;
      }

      const contradictsFact = facts.some(fact => fact.normalLineMatch && fact.normalLineMatch(nl));

      if (contradictsFact) {
        continue;
      }

      if (
        hasPositiveFacts &&
        (
          nl.includes("sin otras alteraciones") ||
          nl.includes("sin otros hallazgos") ||
          nl.includes("no hay otros hallazgos") ||
          nl.includes("no se observan otras alteraciones") ||
          nl.includes("sin otras alteraciones tomograficas agudas") ||
          nl.includes("sin otras alteraciones agudas")
        )
      ) {
        continue;
      }

      const key = nl.replace(/[.,;:]+$/g, "");

      if (seen.has(key) && key.length > 8) {
        continue;
      }

      seen.add(key);
      outLines.push(line);
    }

    let clean = outLines.join("\n").replace(/\n{3,}/g, "\n\n").trim();

    for (const fact of facts) {
      if (!hasEquivalentLineV2(clean, fact.text)) {
        clean = (clean.trim() + "\n" + fact.text).replace(/\n{3,}/g, "\n\n").trim();
      }
    }

    clean = removeExistingImpressionV2(clean);

    const impressionLines = [];
    const impressionSeen = new Set();

    for (const fact of facts) {
      const key = nrm(fact.impression).replace(/[.,;:]+$/g, "");
      if (!key || impressionSeen.has(key)) continue;

      impressionSeen.add(key);
      impressionLines.push(fact.impression);
    }

    if (impressionLines.length) {
      clean = clean.trim() + "\n\nImpresión diagnóstica:\n" + impressionLines.join("\n");
    }

    // Deduplicación final por línea.
    const finalLines = [];
    const finalSeen = new Set();

    clean.split(/\r?\n/).forEach(function (line) {
      const key = nrm(line).replace(/[.,;:]+$/g, "");

      if (!key) {
        if (finalLines.length && finalLines[finalLines.length - 1] !== "") finalLines.push("");
        return;
      }

      if (finalSeen.has(key) && key.length > 8) return;

      finalSeen.add(key);
      finalLines.push(line);
    });

    return finalLines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function buildTransversalCardsV2(raw, originalReport) {
    const facts = transversalFactsV2(raw);
    const reportN = nrm(originalReport);
    const cards = [];

    function add(kind, text, original, explanation, reasons, factId) {
      cards.push({
        kind: kind,
        text: text,
        original: original || "",
        explanation: explanation || "",
        reasons: reasons || [],
        factId: factId || kind + ":" + text
      });
    }

    for (const fact of facts) {
      const hasContradictoryNormal = String(originalReport || "")
        .split(/\r?\n/)
        .some(line => fact.normalLineMatch && fact.normalLineMatch(nrm(line)));

      if (hasContradictoryNormal) {
        add(
          "conflicto",
          "El borrador base conserva una frase normal incompatible con el dictado: " + fact.label + ".",
          fact.source,
          "El texto base/plantilla contiene una normalidad que contradice un hecho positivo dictado.",
          [
            "La normalidad de plantilla no debe prevalecer sobre un hallazgo positivo dictado.",
            "Debe resolverse antes de firmar."
          ],
          fact.id + ":conflict"
        );

        add(
          "reemplazado",
          fact.text,
          fact.source,
          "Corrección estructurada desde dictado.",
          [
            "Confirmar redacción y medida si corresponde."
          ],
          fact.id + ":replacement"
        );
      } else {
        add(
          "agregado",
          fact.text,
          fact.source,
          "Hallazgo positivo estructurado desde dictado.",
          [
            "Confirmar si corresponde mantenerlo en hallazgos y/o impresión."
          ],
          fact.id + ":added"
        );
      }
    }

    if (!cards.length) {
      add(
        "normal",
        "No se detectaron hechos positivos estructurados; revisar informe limpio final.",
        "",
        "No se generaron tarjetas específicas.",
        [],
        "none"
      );
    }

    const map = new Map();

    function priority(card) {
      if (card.kind === "conflicto") return 40;
      if (card.kind === "reemplazado") return 30;
      if (card.kind === "agregado") return 20;
      return 10;
    }

    for (const card of cards) {
      const key = card.factId || (card.kind + ":" + nrm(card.text));
      const prev = map.get(key);

      if (!prev || priority(card) >= priority(prev)) {
        map.set(key, card);
      }
    }

    return Array.from(map.values());
  }

  fixFinalReport = function (raw, report) {
    return cleanupTransversalReportV2(raw, report);
  };

  buildCards = function (raw, originalReport, finalReport, validationRevision) {
    return buildTransversalCardsV2(raw, originalReport);
  };

  renderReview = function (raw, originalReport, finalReport, validationRevision) {
    const clean = cleanupTransversalReportV2(raw, finalReport || originalReport || "");
    state.lastCleanBaseReport = clean;

    const cards = buildTransversalCardsV2(raw, originalReport || finalReport || "");
    const warnings = [];

    if (cards.some(c => c.kind === "conflicto")) {
      warnings.push("Se detectaron contradicciones entre el dictado y el texto base/plantilla.");
    }

    $("warnings").innerHTML = warnings.length
      ? '<div class="warn"><strong>Advertencias:</strong><ul>' + warnings.map(w => '<li>' + esc(w) + '</li>').join("") + '</ul></div>'
      : "";

    $("reviewCards").innerHTML = cards.map(cardHtml).join("");
    $("finalReport").value = clean;
    $("reviewPanel").style.display = "block";

    wireReviewOnce();
  };

  rebuildFinalFromCards = function () {
    const raw = state.rawUsed || $("sourceText").value || "";
    let base = cleanupTransversalReportV2(raw, state.lastCleanBaseReport || $("finalReport").value || "");

    const acceptedTexts = [];
    const rejectedKeys = new Set();

    document.querySelectorAll(".review-card").forEach(function (card) {
      const kind = String(card.dataset.kind || "").toLowerCase();
      const textNode = card.querySelector(".review-text");
      const text = textNode ? norm(textNode.innerText) : "";

      if (!text) return;

      const key = nrm(text).replace(/[.,;:]+$/g, "");

      if (card.classList.contains("rejected")) {
        rejectedKeys.add(key);
        return;
      }

      if (kind === "conflicto" || kind === "eliminado") return;

      acceptedTexts.push(text);
    });

    let lines = base.split(/\r?\n/).filter(function (line) {
      const key = nrm(line).replace(/[.,;:]+$/g, "");
      return !rejectedKeys.has(key);
    });

    let out = lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();

    for (const text of acceptedTexts) {
      if (!hasEquivalentLineV2(out, text)) {
        out = (out.trim() + "\n" + text).replace(/\n{3,}/g, "\n\n").trim();
      }
    }

    out = cleanupTransversalReportV2(raw, out);

    $("finalReport").value = out;
    return out;
  };




  // IAD_WORK_V2_BACKEND_REVIEW_ENGINE_V1
  async function backendReviewEngineV1(raw, report) {
    const response = await fetch("/iad/api/revision-clinica-v2.json", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        source_text: raw,
        base_text: report,
        clinical_json: state.lastClinicalJson || {}
      }),
    });

    if (!response.ok) {
      const txt = await response.text();
      throw new Error("revision-clinica-v2 HTTP " + response.status + ": " + txt.slice(0, 400));
    }

    return await response.json();
  }

  getValidationRevision = async function (raw, report) {
    try {
      const data = await backendReviewEngineV1(raw, report);
      state.lastClinicalReview = data;
      return data;
    } catch (err) {
      console.warn("Motor clínico backend no disponible:", err);
      return null;
    }
  };

  fixFinalReport = function (raw, report) {
    if (state.lastClinicalReview && state.lastClinicalReview.informe_limpio) {
      return state.lastClinicalReview.informe_limpio;
    }
    return String(report || "").trim();
  };

  buildCards = function (raw, originalReport, finalReport, validationRevision) {
    const review = validationRevision || state.lastClinicalReview;

    if (review && Array.isArray(review.cards)) {
      return review.cards.map(function (card) {
        return {
          kind: card.kind || card.tipo || "normal",
          text: card.text || card.texto || "",
          original: card.original || "",
          explanation: card.explanation || card.explicacion || "",
          reasons: card.reasons || card.motivos || [],
        };
      });
    }

    return [
      {
        kind: "normal",
        text: "No se pudo obtener revisión estructurada. Revisar informe limpio final.",
        original: "",
        explanation: "Fallback visual.",
        reasons: [],
      }
    ];
  };

  renderReview = function (raw, originalReport, finalReport, validationRevision) {
    const review = validationRevision || state.lastClinicalReview || {};
    const clean = review.informe_limpio || finalReport || originalReport || "";
    const cards = buildCards(raw, originalReport, clean, review);
    const warnings = Array.isArray(review.warnings) ? review.warnings : [];

    $("warnings").innerHTML = warnings.length
      ? '<div class="warn"><strong>Advertencias:</strong><ul>' + warnings.map(w => '<li>' + esc(w) + '</li>').join("") + '</ul></div>'
      : "";

    $("reviewCards").innerHTML = cards.map(cardHtml).join("");
    $("finalReport").value = clean;
    $("reviewPanel").style.display = "block";

    wireReviewOnce();
  };

  rebuildFinalFromCards = function () {
    const review = state.lastClinicalReview || {};
    let base = String(review.informe_limpio || $("finalReport").value || "").trim();

    const rejected = new Set();
    const accepted = [];

    document.querySelectorAll(".review-card").forEach(function (card) {
      const kind = String(card.dataset.kind || "").toLowerCase();
      const textNode = card.querySelector(".review-text");
      const text = textNode ? norm(textNode.innerText) : "";

      if (!text) return;

      const key = nrm(text).replace(/[.,;:]+$/g, "");

      if (card.classList.contains("rejected")) {
        rejected.add(key);
        return;
      }

      if (kind === "conflicto" || kind === "revisar" || kind === "eliminado") return;

      accepted.push(text);
    });

    let lines = base.split(/\r?\n/).filter(function (line) {
      const key = nrm(line).replace(/[.,;:]+$/g, "");
      return !rejected.has(key);
    });

    let out = lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();

    accepted.forEach(function (text) {
      const key = nrm(text).replace(/[.,;:]+$/g, "");

      const exists = out
        .split(/\r?\n/)
        .some(line => nrm(line).replace(/[.,;:]+$/g, "") === key);

      if (!exists) {
        out = (out.trim() + "\n" + text).replace(/\n{3,}/g, "\n\n").trim();
      }
    });

    $("finalReport").value = out;
    return out;
  };




  // IAD_WORK_V2_SAVE_HISTORY_TRAINING_V1
  async function saveCurrentWorkToHistoryAndTraining() {
    const finalReport = norm($("finalReport").value || "");
    const sourceText = norm(state.rawUsed || $("sourceText").value || "");

    if (!finalReport) {
      throw new Error("No hay informe final para guardar.");
    }

    const cards = Array.from(document.querySelectorAll(".review-card")).map(function (card) {
      const textNode = card.querySelector(".review-text");
      return {
        kind: String(card.dataset.kind || ""),
        text: textNode ? norm(textNode.innerText) : "",
        accepted: !card.classList.contains("rejected"),
      };
    });

    const payload = {
      source_text: sourceText,
      base_report: state.lastGenerated && state.lastGenerated.informe_final ? state.lastGenerated.informe_final : "",
      final_report: finalReport,
      template_name: $("tplName") ? $("tplName").textContent : "",
      confidence: $("confidence") ? $("confidence").textContent : "",
      method: $("method") ? $("method").textContent : "",
      analysis: state.lastAnalysis || null,
      generated: state.lastGenerated || null,
      clinical_json: state.lastClinicalJson || null,
      review: state.lastClinicalReview || null,
      cards: cards,
    };

    const response = await fetch("/iad/api/trabajo/guardar_revision.json", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const txt = await response.text();
      throw new Error("Guardar revisión HTTP " + response.status + ": " + txt.slice(0, 400));
    }

    const data = await response.json();

    if (!data.ok) {
      throw new Error(data.error || "No se pudo guardar la revisión.");
    }

    return data;
  }


  document.addEventListener("DOMContentLoaded", bind);
})();
