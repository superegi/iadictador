(function () {
  "use strict";

  console.log("[IAD WORK V2] activo");

  const state = window.__iadWorkV2State = {
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
          <button type="button" data-action="transcribe" hidden style="display:none">Transcribir</button>
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

  
  // IAD_FIX_CONTINUOUS_RECORDING_2MIN_V1
  // Graba en segmentos consecutivos de 120 segundos.
  // Al cerrarse un segmento, se agrega a la lista de audios e inicia el siguiente sin detener la sesión.
  async function startRecording() {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      alert("Este navegador no permite grabación por MediaRecorder.");
      return;
    }

    if (state.__iadContinuousRecording) {
      setAudioStatus("Ya hay una grabación en curso.");
      return;
    }

    try {
      state.__iadContinuousRecording = true;
      state.__iadRecordingSessionStart = Date.now();
      state.__iadRecordingSegmentIndex = 0;
      state.__iadRecordingStream = await navigator.mediaDevices.getUserMedia({audio: true});

      $("recordBtn").disabled = true;
      $("stopBtn").disabled = false;
      $("recordTimer").textContent = "00:00";
      setAudioStatus("Grabando. Se crearán archivos automáticos de 2 minutos.");

      clearInterval(state.recordTimerInterval);
      state.recordTimerInterval = setInterval(() => {
        const total = Math.floor((Date.now() - state.__iadRecordingSessionStart) / 1000);
        const mm = String(Math.floor(total / 60)).padStart(2, "0");
        const ss = String(total % 60).padStart(2, "0");
        $("recordTimer").textContent = mm + ":" + ss;
      }, 500);

      startRecordingSegment();
    } catch (err) {
      state.__iadContinuousRecording = false;
      cleanupRecordingSession();
      alert("No se pudo iniciar la grabación: " + (err && err.message ? err.message : err));
    }
  }

  function startRecordingSegment() {
    if (!state.__iadContinuousRecording || !state.__iadRecordingStream) return;

    const stream = state.__iadRecordingStream;
    state.recordChunks = [];
    state.recordStart = Date.now();
    state.__iadRecordingSegmentIndex = (state.__iadRecordingSegmentIndex || 0) + 1;

    let recorder;
    try {
      const preferredMime = MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "";
      recorder = preferredMime ? new MediaRecorder(stream, {mimeType: preferredMime}) : new MediaRecorder(stream);
    } catch (err) {
      state.__iadContinuousRecording = false;
      cleanupRecordingSession();
      alert("No se pudo crear el grabador de audio: " + (err && err.message ? err.message : err));
      return;
    }

    state.mediaRecorder = recorder;

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) state.recordChunks.push(event.data);
    };

    recorder.onstop = () => {
      clearTimeout(state.__iadRecordingSegmentTimer);

      const elapsed = Math.max(1, Math.round((Date.now() - state.recordStart) / 1000));
      const mimeType = recorder.mimeType || "audio/webm";
      const blob = new Blob(state.recordChunks || [], {type: mimeType});

      if (blob && blob.size > 0) {
        const stamp = new Date().toISOString().replace(/[:.]/g, "-");
        const idx = state.__iadRecordingSegmentIndex || 1;
        addAudio(blob, "grabacion_segmento_" + idx + "_" + stamp + "_" + elapsed + "s.webm");
      }

      state.recordChunks = [];

      if (state.__iadContinuousRecording) {
        setAudioStatus("Segmento guardado. Iniciando siguiente segmento...");
        setTimeout(startRecordingSegment, 0);
      } else {
        cleanupRecordingSession();
        setAudioStatus("Grabación detenida. Audios listos para transcribir.");
      }
    };

    recorder.onerror = (event) => {
      console.error("MediaRecorder error", event);
      state.__iadContinuousRecording = false;
      try {
        if (recorder && recorder.state === "recording") recorder.stop();
      } catch (e) {
        cleanupRecordingSession();
      }
    };

    recorder.start();

    clearTimeout(state.__iadRecordingSegmentTimer);
    state.__iadRecordingSegmentTimer = setTimeout(() => {
      if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
        state.mediaRecorder.stop();
      }
    }, 120000);
  }

  function cleanupRecordingSession() {
    clearTimeout(state.__iadRecordingSegmentTimer);
    clearInterval(state.recordTimerInterval);

    if (state.__iadRecordingStream) {
      try {
        state.__iadRecordingStream.getTracks().forEach(t => t.stop());
      } catch (e) {
        console.error(e);
      }
    }

    state.__iadRecordingStream = null;
    state.mediaRecorder = null;
    state.recordChunks = [];
    state.__iadRecordingSegmentTimer = null;

    if ($("recordBtn")) $("recordBtn").disabled = false;
    if ($("stopBtn")) $("stopBtn").disabled = true;
    if ($("recordTimer")) $("recordTimer").textContent = "00:00";
  }

  
  // IAD_FIX_STOP_CONTINUOUS_RECORDING_2MIN_V1
  function stopRecording() {
    state.__iadContinuousRecording = false;
    clearTimeout(state.__iadRecordingSegmentTimer);

    if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
      state.mediaRecorder.stop();
      return;
    }

    cleanupRecordingSession();
    setAudioStatus("Grabación detenida.");
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
        
        // IAD_FIX_SAVE_COPY_NEW_OT_V1
        setStatus("Guardado en Historial y Training IA. Copiando informe y abriendo nueva OT...");
        try {
          const finalText = ($("finalReport") && $("finalReport").value) ? $("finalReport").value : "";
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(finalText);
          } else if ($("finalReport")) {
            $("finalReport").focus();
            $("finalReport").select();
            document.execCommand("copy");
          }
        } catch (copyErr) {
          console.warn("No se pudo copiar automáticamente", copyErr);
          if ($("finalReport")) {
            $("finalReport").focus();
            $("finalReport").select();
          }
        }
        setTimeout(() => {
          window.location.href = "/iad/trabajo";
        }, 450);
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



// IAD_AUDIO_FIRST_FRONTEND_V1
(function () {
  if (window.__iadAudioFirstFrontendInstalled) return;
  window.__iadAudioFirstFrontendInstalled = true;

  function $(id) {
    return document.getElementById(id);
  }

  function textOf(el) {
    if (!el) return "";
    if ("value" in el) return String(el.value || "");
    return String(el.textContent || "");
  }

  function setText(el, value) {
    if (!el) return;
    if ("value" in el) el.value = value || "";
    else el.textContent = value || "";
    try {
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (e) {}
  }

  function findButtonByText(rx) {
    return Array.from(document.querySelectorAll("button, input[type='button'], input[type='submit']"))
      .find(function (btn) {
        const t = (btn.innerText || btn.value || btn.textContent || "").trim();
        return rx.test(t);
      }) || null;
  }

  function setStatus(msg) {
    const targets = [
      $("status"),
      $("audioStatus"),
      $("audio_transcription_status"),
      document.querySelector(".iad-status"),
      document.querySelector("[data-status]")
    ].filter(Boolean);

    for (const el of targets) {
      try { el.textContent = msg || ""; } catch (e) {}
    }
    console.log("[IAD audio-first]", msg);
  }

  function activeAudios() {
    const st = window.__iadWorkV2State;
    if (!st || !Array.isArray(st.audios)) return [];
    return st.audios.filter(function (a) {
      return a && a.blob && a.blob.size > 0 && !a.deleted;
    });
  }

  function buildSegmentsMetadata(audios) {
    let cursor = 0;
    return {
      source: "iadictador_work_v2_state",
      generated_at_client: new Date().toISOString(),
      segment_count: audios.length,
      segments: audios.map(function (a, idx) {
        const dur = Number(a.duration_seconds || a.duration || a.durationSec || 0) || 0;
        const item = {
          orden: idx + 1,
          id: a.id || "",
          nombre: a.name || ("audio_" + (idx + 1) + ".webm"),
          size_bytes: a.blob ? a.blob.size : null,
          mime_type: a.blob ? a.blob.type : "",
          duracion_segundos_cliente: dur || null,
          inicio_aproximado_segundos_cliente: cursor || null,
          fin_aproximado_segundos_cliente: dur ? cursor + dur : null,
          transcript_status: a.transcript ? "transcripcion_existente_no_enviada_como_fuente" : "sin_transcripcion_previa"
        };
        if (dur) cursor += dur;
        return item;
      }),
      regla: "Solo los audios presentes en state.audios al momento de procesar se envían a IA. Las transcripciones previas no son fuente principal."
    };
  }

  function buildExtraContext() {
    const ctx = {
      url: window.location.href,
      title: document.title,
      selected_template: "",
      patient_visible: "",
      note: "Flujo audio-first: la IA debe escuchar el audio compuesto. La transcripción debe volver como producto del proceso."
    };

    const maybeTemplate = [
      $("templateSelect"),
      $("template_id"),
      document.querySelector("[name='template_id']"),
      document.querySelector("[name='plantilla_id']"),
      document.querySelector("[name='template_name']"),
      document.querySelector("[name='plantilla_nombre']")
    ].filter(Boolean)[0];

    if (maybeTemplate) {
      ctx.selected_template = textOf(maybeTemplate) || maybeTemplate.value || "";
    }

    return JSON.stringify(ctx);
  }

  function findMainTextArea() {
    return $("sourceText")
      || $("inputText")
      || $("dictationText")
      || document.querySelector("textarea[name='input_text_final']")
      || document.querySelector("textarea[name='input_text']")
      || document.querySelector("textarea");
  }

  function findFinalReportArea() {
    return $("finalReport")
      || $("final_report")
      || document.querySelector("textarea[name='resultado_revisado']")
      || document.querySelector("textarea[name='final_report']")
      || document.querySelector("textarea[name='informe_final']");
  }

  
  // IAD_AUDIO_FIRST_RENDER_COMPLETE_UI_V1
  function renderAudioFirstResult(data) {
    data = data || {};

    const st = window.__iadWorkV2State || {};
    st.lastAudioFirstResult = data;
    window.__iadLastAudioFirstResult = data;

    const transcription = String(data.transcripcion || data.transcription || data.raw_audio_first_text || "").trim();
    const findings = String(data.hallazgos_radiologicos || data.findings || "").trim();
    const report = String(data.informe_final || data.resultado_revisado || data.final_report || data.report || "").trim();
    const impression = String(data.impresion_diagnostica || "").trim();
    const warnings = Array.isArray(data.advertencias) ? data.advertencias : [];
    const omissions = Array.isArray(data.posibles_omisiones) ? data.posibles_omisiones : [];
    const tpl = data.plantilla_sugerida || {};
    const method = data.metodo || "audio_first";

    const main = findMainTextArea();
    if (main && transcription) setText(main, transcription);

    let finalArea = findFinalReportArea();

    if (!finalArea) {
      const host = document.createElement("div");
      host.id = "iad-audio-first-final-host";
      host.style.margin = "1rem 0";
      host.innerHTML = `
        <h3>Informe final IA</h3>
        <textarea id="finalReport" name="resultado_revisado" style="width:100%;min-height:260px;border-radius:12px;padding:12px;background:#071223;color:#e5edf7;border:1px solid rgba(125,211,252,.35);font-family:monospace;"></textarea>
      `;

      const anchor = main || document.querySelector("main") || document.body;
      if (anchor && anchor.parentNode) {
        anchor.parentNode.insertBefore(host, anchor.nextSibling);
      } else {
        document.body.appendChild(host);
      }

      finalArea = document.getElementById("finalReport");
    }

    if (finalArea && report) {
      setText(finalArea, report);
    }

    // Campos globales útiles para guardado/training.
    window.__iadAudioFirstFinalPayload = {
      analysis: {
        ok: true,
        plantilla_sugerida: tpl,
        hallazgos_radiologicos: findings,
        hallazgos_estructurados: data.hallazgos_estructurados || [],
        advertencias: warnings,
        posibles_omisiones: omissions,
        metodo: method
      },
      generated: {
        ok: true,
        informe_final: report,
        impresion_diagnostica: impression,
        advertencias: warnings,
        metodo: method,
        plantilla_usada: tpl
      },
      transcription: transcription,
      audio_composition: data.audio_composition || {}
    };

    let panel = document.getElementById("iad-audio-first-result-panel");
    if (!panel) {
      panel = document.createElement("div");
      panel.id = "iad-audio-first-result-panel";
      panel.style.margin = "1rem 0";
      panel.style.padding = "1rem";
      panel.style.border = "1px solid rgba(125,211,252,.45)";
      panel.style.borderRadius = "14px";
      panel.style.background = "rgba(14,165,233,.10)";
      panel.style.color = "#e5edf7";

      const anchor = finalArea || main || document.querySelector("main") || document.body;
      if (anchor && anchor.parentNode) {
        anchor.parentNode.insertBefore(panel, anchor.nextSibling);
      } else {
        document.body.appendChild(panel);
      }
    }

    function esc(x) {
      return String(x || "").replace(/[<>&]/g, function (s) {
        return {"<":"&lt;", ">":"&gt;", "&":"&amp;"}[s];
      });
    }

    const segCount = data.audio_composition && data.audio_composition.metadata
      ? data.audio_composition.metadata.segment_count
      : "";

    const dur = data.audio_composition && data.audio_composition.metadata
      ? data.audio_composition.metadata.duration_seconds
      : "";

    panel.innerHTML = `
      <h3 style="margin-top:0;">Audio-first IA</h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.75rem;margin-bottom:1rem;">
        <div style="padding:.7rem;border:1px solid rgba(255,255,255,.12);border-radius:12px;">
          <strong>Plantilla</strong><br>${esc(tpl.nombre || "—")}
        </div>
        <div style="padding:.7rem;border:1px solid rgba(255,255,255,.12);border-radius:12px;">
          <strong>Confianza</strong><br>${esc(tpl.confianza || "—")}
        </div>
        <div style="padding:.7rem;border:1px solid rgba(255,255,255,.12);border-radius:12px;">
          <strong>Método</strong><br>${esc(method)}
        </div>
        <div style="padding:.7rem;border:1px solid rgba(255,255,255,.12);border-radius:12px;">
          <strong>Audio</strong><br>${esc(segCount)} segmento(s) ${dur ? "· " + esc(Number(dur).toFixed ? Number(dur).toFixed(1) : dur) + " s" : ""}
        </div>
      </div>

      <details open>
        <summary><strong>Transcripción devuelta por IA</strong></summary>
        <pre style="white-space:pre-wrap;background:#071223;color:#e5edf7;border-radius:12px;padding:1rem;max-height:260px;overflow:auto;">${esc(transcription || "—")}</pre>
      </details>

      <details open>
        <summary><strong>Hallazgos detectados</strong></summary>
        <pre style="white-space:pre-wrap;background:#071223;color:#e5edf7;border-radius:12px;padding:1rem;max-height:220px;overflow:auto;">${esc(findings || "—")}</pre>
      </details>

      <details open>
        <summary><strong>Informe final</strong></summary>
        <pre style="white-space:pre-wrap;background:#071223;color:#e5edf7;border-radius:12px;padding:1rem;max-height:360px;overflow:auto;">${esc(report || "—")}</pre>
      </details>

      ${warnings.length ? `
      <details open>
        <summary><strong>Advertencias</strong></summary>
        <pre style="white-space:pre-wrap;background:#2a1f06;color:#fde68a;border-radius:12px;padding:1rem;">${esc(warnings.map(String).join("\\n"))}</pre>
      </details>` : ""}

      ${omissions.length ? `
      <details open>
        <summary><strong>Posibles omisiones</strong></summary>
        <pre style="white-space:pre-wrap;background:#3b1111;color:#fecaca;border-radius:12px;padding:1rem;">${esc(omissions.map(String).join("\\n"))}</pre>
      </details>` : ""}
    `;

    let msg = "Audio-first completo.";
    if (tpl && tpl.nombre) msg += " Plantilla: " + tpl.nombre + ".";
    if (report) msg += " Informe final generado.";
    else msg += " Sin informe final completo.";
    if (warnings.length) msg += " Advertencias: " + warnings.length + ".";

    setStatus(msg);
  }

  async function runAudioFirstFlow() {
    const audios = activeAudios();
    if (!audios.length) {
      setStatus("No hay audios activos para audio-first.");
      return false;
    }

    setStatus("Preparando audio compuesto para IA...");

    const fd = new FormData();
    const metadata = buildSegmentsMetadata(audios);

    audios.forEach(function (item, idx) {
      const name = item.name || ("audio_" + (idx + 1) + ".webm");
      fd.append("audio_files", item.blob, name);
    });

    fd.append("segments_metadata_json", JSON.stringify(metadata));
    fd.append("extra_context", buildExtraContext());

    const response = await fetch("/iad/api/audio/procesar-dictado-completo.json", {
      method: "POST",
      body: fd,
      credentials: "same-origin"
    });

    let data = null;
    try {
      data = await response.json();
    } catch (e) {
      const text = await response.text();
      throw new Error("Respuesta no JSON: " + text.slice(0, 500));
    }

    if (!response.ok || !data.ok) {
      throw new Error((data && data.error) ? data.error : ("HTTP " + response.status));
    }

    renderAudioFirstResult(data);
    return true;
  }

  document.addEventListener("click", function (ev) {
    const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
    if (!btn) return;

    const label = (btn.innerText || btn.textContent || btn.value || "").trim();
    if (!/analizar\s+radiolog/i.test(label)) return;

    const audios = activeAudios();
    if (!audios.length) return;

    ev.preventDefault();
    ev.stopPropagation();
    if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();

    runAudioFirstFlow().catch(function (err) {
      console.error(err);
      setStatus("Error en audio-first: " + (err && err.message ? err.message : err));
      alert("Error en audio-first:\n" + (err && err.message ? err.message : err));
    });
  }, true);

  window.iadRunAudioFirstFlow = runAudioFirstFlow;
})();



// IAD_AUDIO_FIRST_VISIBLE_PANEL_V1
(function () {
  if (window.__iadAudioFirstVisiblePanelInstalled) return;
  window.__iadAudioFirstVisiblePanelInstalled = true;

  function esc(x) {
    return String(x == null ? "" : x).replace(/[<>&]/g, function (s) {
      return {"<":"&lt;", ">":"&gt;", "&":"&amp;"}[s];
    });
  }

  function getText(v) {
    if (v == null) return "";
    if (typeof v === "string") return v;
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); }
  }

  function normalizeAudioFirstData(raw) {
    raw = raw || {};

    if (raw.generated || raw.analysis || raw.transcription) {
      const analysis = raw.analysis || {};
      const generated = raw.generated || {};
      return {
        plantilla_sugerida: analysis.plantilla_sugerida || generated.plantilla_usada || {},
        transcripcion: raw.transcription || raw.transcripcion || "",
        hallazgos_radiologicos: analysis.hallazgos_radiologicos || "",
        hallazgos_estructurados: analysis.hallazgos_estructurados || [],
        informe_final: generated.informe_final || generated.final_report || raw.informe_final || "",
        impresion_diagnostica: generated.impresion_diagnostica || "",
        advertencias: analysis.advertencias || generated.advertencias || [],
        posibles_omisiones: analysis.posibles_omisiones || [],
        metodo: analysis.metodo || generated.metodo || "audio_first",
        audio_composition: raw.audio_composition || {}
      };
    }

    return {
      plantilla_sugerida: raw.plantilla_sugerida || {},
      transcripcion: raw.transcripcion || raw.transcription || raw.raw_audio_first_text || "",
      hallazgos_radiologicos: raw.hallazgos_radiologicos || raw.findings || "",
      hallazgos_estructurados: raw.hallazgos_estructurados || [],
      informe_final: raw.informe_final || raw.resultado_revisado || raw.final_report || raw.report || "",
      impresion_diagnostica: raw.impresion_diagnostica || "",
      advertencias: Array.isArray(raw.advertencias) ? raw.advertencias : [],
      posibles_omisiones: Array.isArray(raw.posibles_omisiones) ? raw.posibles_omisiones : [],
      metodo: raw.metodo || "audio_first",
      audio_composition: raw.audio_composition || {}
    };
  }

  function findAnalyzeButton() {
    return Array.from(document.querySelectorAll("button")).find(function (b) {
      return /analizar\s+radiolog/i.test((b.innerText || b.textContent || "").trim());
    }) || null;
  }

  function findStableAnchor() {
    const btn = findAnalyzeButton();
    if (btn) {
      const row = btn.parentElement;
      if (row) return row;
    }

    const textarea = document.querySelector("textarea[name='input_text_final'], textarea");
    if (textarea && textarea.parentElement) return textarea.parentElement;

    return document.querySelector("main") || document.body;
  }

  function setValue(el, value) {
    if (!el) return;
    if ("value" in el) el.value = value || "";
    else el.textContent = value || "";
    try {
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (e) {}
  }

  function ensurePanel() {
    let panel = document.getElementById("iad-audio-first-visible-panel");
    if (panel) return panel;

    panel = document.createElement("section");
    panel.id = "iad-audio-first-visible-panel";
    panel.style.margin = "1rem 0";
    panel.style.padding = "1rem";
    panel.style.border = "2px solid rgba(56,189,248,.65)";
    panel.style.borderRadius = "16px";
    panel.style.background = "rgba(8,47,73,.55)";
    panel.style.color = "#e5edf7";
    panel.style.boxShadow = "0 10px 24px rgba(0,0,0,.25)";

    const anchor = findStableAnchor();
    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(panel, anchor.nextSibling);
    } else {
      document.body.appendChild(panel);
    }

    return panel;
  }

  function ensureFinalReportTextarea(panel, report) {
    let finalArea = document.getElementById("finalReport");

    if (!finalArea) {
      finalArea = document.createElement("textarea");
      finalArea.id = "finalReport";
      finalArea.name = "resultado_revisado";
      finalArea.setAttribute("data-audio-first-created", "1");
      panel.appendChild(finalArea);
    } else if (finalArea.parentElement !== panel && finalArea.getAttribute("data-audio-first-visible-mounted") !== "1") {
      panel.appendChild(finalArea);
    }

    finalArea.setAttribute("data-audio-first-visible-mounted", "1");
    finalArea.style.width = "100%";
    finalArea.style.minHeight = "320px";
    finalArea.style.marginTop = ".75rem";
    finalArea.style.padding = "12px";
    finalArea.style.borderRadius = "12px";
    finalArea.style.background = "#071223";
    finalArea.style.color = "#e5edf7";
    finalArea.style.border = "1px solid rgba(125,211,252,.45)";
    finalArea.style.fontFamily = "monospace";
    finalArea.style.whiteSpace = "pre-wrap";

    if (report) setValue(finalArea, report);

    return finalArea;
  }

  function renderVisibleAudioFirstPanel(raw) {
    const data = normalizeAudioFirstData(raw);
    const tpl = data.plantilla_sugerida || {};
    const transcription = getText(data.transcripcion).trim();
    const findings = getText(data.hallazgos_radiologicos).trim();
    const structured = Array.isArray(data.hallazgos_estructurados) ? data.hallazgos_estructurados : [];
    const report = getText(data.informe_final).trim();
    const impression = getText(data.impresion_diagnostica).trim();
    const warnings = Array.isArray(data.advertencias) ? data.advertencias : [];
    const omissions = Array.isArray(data.posibles_omisiones) ? data.posibles_omisiones : [];
    const audioMeta = data.audio_composition && data.audio_composition.metadata ? data.audio_composition.metadata : {};
    const panel = ensurePanel();

    panel.innerHTML = `
      <h3 style="margin:0 0 .75rem 0;">Resultado audio-first</h3>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.65rem;margin-bottom:1rem;">
        <div style="padding:.65rem;border:1px solid rgba(255,255,255,.16);border-radius:12px;background:rgba(15,23,42,.45);">
          <strong>Plantilla</strong><br>${esc(tpl.nombre || tpl.name || "—")}
        </div>
        <div style="padding:.65rem;border:1px solid rgba(255,255,255,.16);border-radius:12px;background:rgba(15,23,42,.45);">
          <strong>Confianza</strong><br>${esc(tpl.confianza || "—")}
        </div>
        <div style="padding:.65rem;border:1px solid rgba(255,255,255,.16);border-radius:12px;background:rgba(15,23,42,.45);">
          <strong>Método</strong><br>${esc(data.metodo || "audio_first")}
        </div>
        <div style="padding:.65rem;border:1px solid rgba(255,255,255,.16);border-radius:12px;background:rgba(15,23,42,.45);">
          <strong>Audio</strong><br>${esc(audioMeta.segment_count || "")} segmento(s) ${audioMeta.duration_seconds ? "· " + esc(Number(audioMeta.duration_seconds).toFixed(1)) + " s" : ""}
        </div>
      </div>

      <details open>
        <summary><strong>Transcripción devuelta por IA</strong></summary>
        <pre style="white-space:pre-wrap;background:#071223;color:#e5edf7;border-radius:12px;padding:1rem;max-height:220px;overflow:auto;">${esc(transcription || "—")}</pre>
      </details>

      <details open>
        <summary><strong>Hallazgos radiológicos</strong></summary>
        <pre style="white-space:pre-wrap;background:#071223;color:#e5edf7;border-radius:12px;padding:1rem;max-height:220px;overflow:auto;">${esc(findings || "—")}</pre>
      </details>

      ${structured.length ? `
      <details>
        <summary><strong>Hallazgos estructurados</strong></summary>
        <pre style="white-space:pre-wrap;background:#071223;color:#e5edf7;border-radius:12px;padding:1rem;max-height:220px;overflow:auto;">${esc(JSON.stringify(structured, null, 2))}</pre>
      </details>` : ""}

      ${impression ? `
      <details open>
        <summary><strong>Impresión diagnóstica</strong></summary>
        <pre style="white-space:pre-wrap;background:#071223;color:#e5edf7;border-radius:12px;padding:1rem;max-height:180px;overflow:auto;">${esc(impression)}</pre>
      </details>` : ""}

      ${warnings.length ? `
      <details open>
        <summary><strong>Advertencias</strong></summary>
        <pre style="white-space:pre-wrap;background:#3a2a05;color:#fde68a;border-radius:12px;padding:1rem;max-height:180px;overflow:auto;">${esc(warnings.map(String).join("\\n"))}</pre>
      </details>` : ""}

      ${omissions.length ? `
      <details open>
        <summary><strong>Posibles omisiones</strong></summary>
        <pre style="white-space:pre-wrap;background:#3b1111;color:#fecaca;border-radius:12px;padding:1rem;max-height:180px;overflow:auto;">${esc(omissions.map(String).join("\\n"))}</pre>
      </details>` : ""}

      <h4 style="margin:1rem 0 .25rem 0;">Informe final editable</h4>
    `;

    ensureFinalReportTextarea(panel, report);

    window.__iadAudioFirstVisibleRenderedAt = Date.now();
    window.__iadAudioFirstFinalText = report;
    window.__iadAudioFirstTranscriptionText = transcription;

    // Actualizar texto principal si existe y viene transcripción.
    const mainText = document.querySelector("textarea[name='input_text_final'], textarea[name='input_text'], textarea");
    if (mainText && transcription && !String(mainText.value || "").trim()) {
      setValue(mainText, transcription);
    }

    return true;
  }

  let lastKey = "";

  function tick() {
    const raw = window.__iadLastAudioFirstResult || window.__iadAudioFirstFinalPayload || null;
    if (!raw) return;

    let key = "";
    try {
      const d = normalizeAudioFirstData(raw);
      key = [
        d.transcripcion || "",
        d.hallazgos_radiologicos || "",
        d.informe_final || "",
        d.metodo || ""
      ].join("|").slice(0, 600);
    } catch (e) {
      key = String(Date.now());
    }

    if (!key || key === lastKey) return;
    lastKey = key;

    try {
      renderVisibleAudioFirstPanel(raw);
    } catch (err) {
      console.error("Error renderizando panel audio-first visible", err);
    }
  }

  setInterval(tick, 600);
  document.addEventListener("DOMContentLoaded", function () {
    setTimeout(tick, 300);
    setTimeout(tick, 1000);
  });

  window.iadRenderVisibleAudioFirstPanel = renderVisibleAudioFirstPanel;
})();



// IAD_UI_ONLY_ANALYZE_RADIOLOGY_V1
(function () {
  if (window.__iadUiOnlyAnalyzeRadiologyInstalled) return;
  window.__iadUiOnlyAnalyzeRadiologyInstalled = true;

  function shouldHideButton(btn) {
    const label = String(btn.innerText || btn.textContent || btn.value || "").trim().toLowerCase();
    return label === "transcribir todo" || label === "limpiar";
  }

  function hideSecondaryButtons() {
    const buttons = Array.from(document.querySelectorAll("button, input[type='button'], input[type='submit']"));
    for (const btn of buttons) {
      if (!shouldHideButton(btn)) continue;

      btn.dataset.iadHiddenBecause = "flujo_audio_first_unico";
      btn.style.display = "none";
      btn.setAttribute("aria-hidden", "true");
      btn.tabIndex = -1;
    }
  }

  document.addEventListener("DOMContentLoaded", hideSecondaryButtons);
  setInterval(hideSecondaryButtons, 700);

  console.info("[IAD] UI simplificada: solo Analizar radiología queda visible. Transcribir todo/Limpiar ocultos, no eliminados.");
})();



// IAD_UI_AUDIO_FIRST_FORCE_VISIBLE_V2
(function () {
  if (window.__iadUiAudioFirstForceVisibleV2) return;
  window.__iadUiAudioFirstForceVisibleV2 = true;

  function esc(x) {
    return String(x == null ? "" : x).replace(/[<>&]/g, function (s) {
      return {"<":"&lt;", ">":"&gt;", "&":"&amp;"}[s];
    });
  }

  function asText(v) {
    if (v == null) return "";
    if (typeof v === "string") return v;
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); }
  }

  function norm(raw) {
    raw = raw || {};

    if (raw.analysis || raw.generated || raw.transcription) {
      const a = raw.analysis || {};
      const g = raw.generated || {};
      return {
        plantilla_sugerida: a.plantilla_sugerida || g.plantilla_usada || {},
        transcripcion: raw.transcription || raw.transcripcion || "",
        hallazgos_radiologicos: a.hallazgos_radiologicos || "",
        hallazgos_estructurados: a.hallazgos_estructurados || [],
        impresion_diagnostica: g.impresion_diagnostica || "",
        informe_final: g.informe_final || g.final_report || raw.informe_final || "",
        advertencias: a.advertencias || g.advertencias || [],
        posibles_omisiones: a.posibles_omisiones || [],
        metodo: a.metodo || g.metodo || "audio_first",
        audio_composition: raw.audio_composition || {}
      };
    }

    return {
      plantilla_sugerida: raw.plantilla_sugerida || {},
      transcripcion: raw.transcripcion || raw.transcription || raw.raw_audio_first_text || "",
      hallazgos_radiologicos: raw.hallazgos_radiologicos || raw.findings || "",
      hallazgos_estructurados: raw.hallazgos_estructurados || [],
      impresion_diagnostica: raw.impresion_diagnostica || "",
      informe_final: raw.informe_final || raw.resultado_revisado || raw.final_report || raw.report || "",
      advertencias: Array.isArray(raw.advertencias) ? raw.advertencias : [],
      posibles_omisiones: Array.isArray(raw.posibles_omisiones) ? raw.posibles_omisiones : [],
      metodo: raw.metodo || "audio_first",
      audio_composition: raw.audio_composition || {}
    };
  }

  function hideSecondaryButtons() {
    const buttons = Array.from(document.querySelectorAll("button, input[type='button'], input[type='submit']"));
    buttons.forEach(function (btn) {
      const label = String(btn.innerText || btn.textContent || btn.value || "").trim().toLowerCase();
      if (label === "transcribir todo" || label === "limpiar") {
        btn.dataset.iadHiddenBy = "IAD_HIDE_SECONDARY_AUDIO_BUTTONS_V2";
        btn.style.display = "none";
        btn.setAttribute("aria-hidden", "true");
        btn.tabIndex = -1;
      }
    });
  }

  function findAnalyzeButton() {
    return Array.from(document.querySelectorAll("button")).find(function (b) {
      return /analizar\s+radiolog/i.test(String(b.innerText || b.textContent || ""));
    }) || null;
  }

  function anchor() {
    const b = findAnalyzeButton();
    if (b && b.parentElement) return b.parentElement;
    const ta = document.querySelector("textarea");
    if (ta && ta.parentElement) return ta.parentElement;
    return document.querySelector("main") || document.body;
  }

  function setValue(el, v) {
    if (!el) return;
    if ("value" in el) el.value = v || "";
    else el.textContent = v || "";
    try {
      el.dispatchEvent(new Event("input", {bubbles:true}));
      el.dispatchEvent(new Event("change", {bubbles:true}));
    } catch(e) {}
  }

  function ensurePanel() {
    let p = document.getElementById("iad-audio-first-force-panel");
    if (p) return p;

    p = document.createElement("section");
    p.id = "iad-audio-first-force-panel";
    p.style.margin = "1rem 0";
    p.style.padding = "1rem";
    p.style.border = "2px solid rgba(56,189,248,.75)";
    p.style.borderRadius = "16px";
    p.style.background = "rgba(8,47,73,.60)";
    p.style.color = "#e5edf7";

    const a = anchor();
    if (a && a.parentNode) a.parentNode.insertBefore(p, a.nextSibling);
    else document.body.appendChild(p);

    return p;
  }

  function ensureFinal(panel, report) {
    let ta = document.getElementById("finalReport");
    if (!ta) {
      ta = document.createElement("textarea");
      ta.id = "finalReport";
      ta.name = "resultado_revisado";
    }

    ta.style.width = "100%";
    ta.style.minHeight = "320px";
    ta.style.padding = "12px";
    ta.style.borderRadius = "12px";
    ta.style.background = "#071223";
    ta.style.color = "#e5edf7";
    ta.style.border = "1px solid rgba(125,211,252,.45)";
    ta.style.fontFamily = "monospace";

    if (report) setValue(ta, report);
    panel.appendChild(ta);
    return ta;
  }

  function render(raw) {
    const d = norm(raw);
    const tpl = d.plantilla_sugerida || {};
    const meta = d.audio_composition && d.audio_composition.metadata ? d.audio_composition.metadata : {};
    const warnings = Array.isArray(d.advertencias) ? d.advertencias : [];
    const omissions = Array.isArray(d.posibles_omisiones) ? d.posibles_omisiones : [];
    const structured = Array.isArray(d.hallazgos_estructurados) ? d.hallazgos_estructurados : [];
    const report = asText(d.informe_final).trim();

    const p = ensurePanel();

    p.innerHTML = `
      <h3 style="margin-top:0;">Resultado audio-first</h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.65rem;margin-bottom:1rem;">
        <div style="padding:.65rem;border:1px solid rgba(255,255,255,.16);border-radius:12px;background:rgba(15,23,42,.45);"><strong>Plantilla</strong><br>${esc(tpl.nombre || tpl.name || "—")}</div>
        <div style="padding:.65rem;border:1px solid rgba(255,255,255,.16);border-radius:12px;background:rgba(15,23,42,.45);"><strong>Confianza</strong><br>${esc(tpl.confianza || "—")}</div>
        <div style="padding:.65rem;border:1px solid rgba(255,255,255,.16);border-radius:12px;background:rgba(15,23,42,.45);"><strong>Método</strong><br>${esc(d.metodo || "audio_first")}</div>
        <div style="padding:.65rem;border:1px solid rgba(255,255,255,.16);border-radius:12px;background:rgba(15,23,42,.45);"><strong>Audio</strong><br>${esc(meta.segment_count || "")} segmento(s)</div>
      </div>

      <details>
        <summary><strong>Transcripción devuelta por IA</strong></summary>
        <pre style="white-space:pre-wrap;background:#071223;color:#e5edf7;border-radius:12px;padding:1rem;max-height:220px;overflow:auto;">${esc(asText(d.transcripcion) || "—")}</pre>
      </details>

      <details>
        <summary><strong>Hallazgos radiológicos</strong></summary>
        <pre style="white-space:pre-wrap;background:#071223;color:#e5edf7;border-radius:12px;padding:1rem;max-height:220px;overflow:auto;">${esc(asText(d.hallazgos_radiologicos) || "—")}</pre>
      </details>

      ${structured.length ? `<details><summary><strong>Hallazgos estructurados</strong></summary><pre style="white-space:pre-wrap;background:#071223;color:#e5edf7;border-radius:12px;padding:1rem;max-height:220px;overflow:auto;">${esc(JSON.stringify(structured, null, 2))}</pre></details>` : ""}

      <details open>
        <summary><strong>Impresión diagnóstica</strong></summary>
        <pre style="white-space:pre-wrap;background:#071223;color:#e5edf7;border-radius:12px;padding:1rem;max-height:180px;overflow:auto;">${esc(asText(d.impresion_diagnostica) || "—")}</pre>
      </details>

      ${warnings.length ? `<details open><summary><strong>Advertencias</strong></summary><pre style="white-space:pre-wrap;background:#3a2a05;color:#fde68a;border-radius:12px;padding:1rem;max-height:180px;overflow:auto;">${esc(warnings.map(String).join("\\n"))}</pre></details>` : ""}

      ${omissions.length ? `<details open><summary><strong>Posibles omisiones</strong></summary><pre style="white-space:pre-wrap;background:#3b1111;color:#fecaca;border-radius:12px;padding:1rem;max-height:180px;overflow:auto;">${esc(omissions.map(String).join("\\n"))}</pre></details>` : ""}

      <h4>Informe final editable</h4>
    `;

    ensureFinal(p, report);

    window.__iadForcePanelRenderedAt = Date.now();
    return true;
  }

  let last = "";
  function tick() {
    hideSecondaryButtons();

    const raw = window.__iadLastAudioFirstResult || window.__iadAudioFirstFinalPayload || null;
    if (!raw) return;

    let key = "";
    try {
      const d = norm(raw);
      key = [d.metodo, d.informe_final, d.transcripcion, d.hallazgos_radiologicos].join("|").slice(0, 700);
    } catch(e) {
      key = String(Date.now());
    }

    if (!key || key === last) return;
    last = key;

    try { render(raw); } catch(e) { console.error("[IAD force panel]", e); }
  }

  setInterval(tick, 500);
  document.addEventListener("DOMContentLoaded", function () {
    hideSecondaryButtons();
    setTimeout(tick, 300);
    setTimeout(tick, 1000);
    setTimeout(tick, 2000);
  });

  window.iadRenderAudioFirstForcePanel = render;
})();

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


// IAD_INTELLIGENCE_DEBUG_PANEL_V1
(function () {
  "use strict";

  if (window.__iadIntelligenceDebugPanelV1) return;
  window.__iadIntelligenceDebugPanelV1 = true;

  function txt(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v;
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); }
  }

  function esc(s) {
    return txt(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function installCss() {
    if (document.getElementById("iad-intelligence-debug-style-v1")) return;

    const st = document.createElement("style");
    st.id = "iad-intelligence-debug-style-v1";
    st.textContent = `
      #iad-intelligence-debug-panel {
        margin-top: 10px;
        border: 1px solid rgba(148,163,184,.20);
        border-radius: 12px;
        background: #071223;
        color: #dbeafe;
        padding: 10px;
      }

      #iad-intelligence-debug-panel summary {
        cursor: pointer;
        font-weight: 700;
        color: #bfdbfe;
      }

      #iad-intelligence-debug-panel pre {
        white-space: pre-wrap;
        overflow: auto;
        max-height: 420px;
        border-radius: 10px;
        padding: 10px;
        background: rgba(0,0,0,.20);
        border: 1px solid rgba(148,163,184,.16);
        font-size: .82rem;
      }

      #iad-intelligence-debug-panel .iad-debug-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        margin: 10px 0;
      }

      #iad-intelligence-debug-panel .iad-debug-card {
        border: 1px solid rgba(148,163,184,.16);
        border-radius: 10px;
        padding: 8px;
        background: rgba(15,23,42,.70);
      }

      #iad-intelligence-debug-panel .iad-debug-card strong {
        display: block;
        color: #93c5fd;
        margin-bottom: 4px;
      }

      @media(max-width:800px) {
        #iad-intelligence-debug-panel .iad-debug-grid {
          grid-template-columns: 1fr;
        }
      }
    `;
    document.head.appendChild(st);
  }

  function findFinalPanel() {
    return document.getElementById("iad-real-final-panel")
      || document.getElementById("iad-native-final-panel")
      || document.querySelector("main")
      || document.body;
  }

  function renderDebug(data) {
    installCss();

    const editor = data && data.intelligence_editor ? data.intelligence_editor : {};
    const map = data && data.mapa_aplicacion ? data.mapa_aplicacion : [];
    const structured = data && data.hallazgos_estructurados ? data.hallazgos_estructurados : [];
    const warnings = data && data.advertencias ? data.advertencias : [];

    let panel = document.getElementById("iad-intelligence-debug-panel");
    if (!panel) {
      panel = document.createElement("details");
      panel.id = "iad-intelligence-debug-panel";
      panel.open = false;
      const host = findFinalPanel();
      if (host && host.parentElement && host.id === "iad-real-final-panel") {
        host.parentElement.insertBefore(panel, host.nextSibling);
      } else {
        host.appendChild(panel);
      }
    }

    const ok = editor && editor.ok ? "sí" : "no";
    const model = editor.model || "—";
    const method = data.metodo || data.method || "—";
    const confidence = (data.plantilla_sugerida && data.plantilla_sugerida.confianza) || editor.confianza || data.confianza || "—";

    panel.innerHTML = `
      <summary>Depuración IA / inteligencia transferible</summary>

      <div class="iad-debug-grid">
        <div class="iad-debug-card"><strong>Editor inteligente activo</strong>${esc(ok)}</div>
        <div class="iad-debug-card"><strong>Modelo</strong>${esc(model)}</div>
        <div class="iad-debug-card"><strong>Método final</strong>${esc(method)}</div>
        <div class="iad-debug-card"><strong>Confianza</strong>${esc(confidence)}</div>
        <div class="iad-debug-card"><strong>Score antes</strong>${esc(editor.before_score || "—")}</div>
        <div class="iad-debug-card"><strong>Score después</strong>${esc(editor.after_score || "—")}</div>
      </div>

      <h4>Mapa de aplicación</h4>
      <pre>${esc(map)}</pre>

      <h4>Hallazgos estructurados</h4>
      <pre>${esc(structured)}</pre>

      <h4>Advertencias</h4>
      <pre>${esc(warnings)}</pre>

      <h4>Informe IA original previo</h4>
      <pre>${esc(data.informe_final_modelo || "")}</pre>

      <h4>Informe determinístico fallback</h4>
      <pre>${esc(data.informe_final_deterministico || "")}</pre>
    `;
  }

  const oldFetch = window.fetch;
  if (typeof oldFetch === "function" && !oldFetch.__iadDebugWrappedV1) {
    const wrapped = async function () {
      const args = arguments;
      const res = await oldFetch.apply(this, args);

      try {
        const clone = res.clone();
        const ct = clone.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          clone.json().then(function (data) {
            setTimeout(function () { renderDebug(data); }, 150);
            setTimeout(function () { renderDebug(data); }, 800);
          }).catch(function () {});
        }
      } catch (e) {}

      return res;
    };
    wrapped.__iadDebugWrappedV1 = true;
    window.fetch = wrapped;
  }

  window.IAD_RENDER_INTELLIGENCE_DEBUG = renderDebug;
})();


// IAD_STRUCTURED_MAPPER_DEBUG_V5
(function () {
  "use strict";

  if (window.__iadStructuredMapperDebugV5) return;
  window.__iadStructuredMapperDebugV5 = true;

  function txt(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v;
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); }
  }

  function esc(s) {
    return txt(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function ensurePanel() {
    let panel = document.getElementById("iad-structured-mapper-debug-v5");
    if (!panel) {
      panel = document.createElement("details");
      panel.id = "iad-structured-mapper-debug-v5";
      panel.style.marginTop = "10px";
      panel.style.border = "1px solid rgba(125,211,252,.22)";
      panel.style.borderRadius = "12px";
      panel.style.padding = "10px";
      panel.style.background = "#071223";
      panel.style.color = "#dbeafe";

      const host = document.getElementById("iad-intelligence-debug-panel")
        || document.getElementById("iad-real-final-panel")
        || document.querySelector("main")
        || document.body;

      if (host && host.parentElement && host.id !== "iad-real-final-panel") {
        host.parentElement.insertBefore(panel, host.nextSibling);
      } else {
        host.appendChild(panel);
      }
    }
    return panel;
  }

  function render(data) {
    if (!data || !data.structured_mapper) return;

    const panel = ensurePanel();
    const sm = data.structured_mapper || {};

    panel.innerHTML = `
      <summary><strong>Structured mapper / aplicación real al informe</strong></summary>
      <p><strong>Aplicó cambios:</strong> ${esc(sm.ok ? "sí" : "no")}</p>
      <p><strong>Hallazgos detectados:</strong> ${esc(sm.findings_count || 0)}</p>
      <h4>Líneas de cuerpo generadas</h4>
      <pre style="white-space:pre-wrap;max-height:280px;overflow:auto;background:rgba(0,0,0,.25);padding:10px;border-radius:10px;">${esc(sm.body_lines || [])}</pre>
      <h4>Líneas insertadas</h4>
      <pre style="white-space:pre-wrap;max-height:280px;overflow:auto;background:rgba(0,0,0,.25);padding:10px;border-radius:10px;">${esc(sm.inserted || [])}</pre>
    `;
  }

  const oldFetch = window.fetch;
  if (typeof oldFetch === "function" && !oldFetch.__iadStructuredMapperDebugWrappedV5) {
    const wrapped = async function () {
      const args = arguments;
      const res = await oldFetch.apply(this, args);

      try {
        const clone = res.clone();
        const ct = clone.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          clone.json().then(function (data) {
            setTimeout(function () { render(data); }, 180);
            setTimeout(function () { render(data); }, 900);
          }).catch(function () {});
        }
      } catch (e) {}

      return res;
    };
    wrapped.__iadStructuredMapperDebugWrappedV5 = true;
    window.fetch = wrapped;
  }

  window.IAD_RENDER_STRUCTURED_MAPPER_DEBUG_V5 = render;
})();


// IAD_UI_CLEAN_JSON_TRANSCRIPTION_V2
(function () {
  "use strict";

  if (window.__iadUiCleanJsonTranscriptionV2) return;
  window.__iadUiCleanJsonTranscriptionV2 = true;

  function tryJson(value) {
    if (typeof value !== "string") return null;
    var t = value.trim();
    if (!t) return null;
    if (!((t[0] === "{" && t[t.length - 1] === "}") || (t[0] === "[" && t[t.length - 1] === "]"))) return null;
    try { return JSON.parse(t); } catch (e) { return null; }
  }

  function cleanText(value, depth) {
    depth = depth || 0;
    if (depth > 4) return value == null ? "" : String(value);

    if (value && typeof value === "object" && !Array.isArray(value)) {
      var keys = [
        "transcripcion",
        "transcription",
        "raw_audio_first_text",
        "dictado_original",
        "source_text",
        "texto",
        "text"
      ];
      for (var i = 0; i < keys.length; i++) {
        var v = value[keys[i]];
        if (typeof v === "string" && v.trim()) {
          return cleanText(v, depth + 1);
        }
      }
      if (value.analysis) {
        var a = cleanText(value.analysis, depth + 1);
        if (a.trim()) return a;
      }
      return "";
    }

    if (typeof value === "string") {
      var parsed = tryJson(value);
      if (parsed !== null) return cleanText(parsed, depth + 1);
      return value.trim();
    }

    return value == null ? "" : String(value).trim();
  }

  function cleanPayload(data) {
    if (!data || typeof data !== "object") return data;

    var clean = cleanText(data.transcripcion || data.transcription || data.raw_audio_first_text || "");
    if (clean) {
      data.transcripcion = clean;
      data.transcription = clean;
      data.raw_audio_first_text = clean;
    }

    return data;
  }

  function setTextareaClean(id) {
    var el = document.getElementById(id);
    if (!el || !("value" in el)) return;

    var parsed = tryJson(el.value || "");
    if (!parsed) return;

    var clean = cleanText(parsed);
    if (clean && clean !== el.value) {
      el.value = clean;
      try {
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } catch (e) {}
    }
  }

  function cleanVisibleBlocks() {
    setTextareaClean("sourceText");

    document.querySelectorAll("pre, code, textarea, .mono, .result-box").forEach(function (el) {
      var val = "value" in el ? el.value : el.textContent;
      var parsed = tryJson(val || "");
      if (!parsed) return;

      var clean = cleanText(parsed);
      if (!clean) return;

      if ("value" in el) {
        if (el.value !== clean) el.value = clean;
      } else {
        if ((el.textContent || "").trim() !== clean) el.textContent = clean;
      }
    });
  }

  var oldFetch = window.fetch;
  if (typeof oldFetch === "function" && !oldFetch.__iadCleanJsonTranscriptionWrappedV2) {
    var wrapped = async function () {
      var res = await oldFetch.apply(this, arguments);

      try {
        var clone = res.clone();
        var ct = clone.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          clone.json().then(function (data) {
            cleanPayload(data);
            setTimeout(cleanVisibleBlocks, 50);
            setTimeout(cleanVisibleBlocks, 300);
            setTimeout(cleanVisibleBlocks, 1000);
          }).catch(function () {});
        }
      } catch (e) {}

      return res;
    };

    wrapped.__iadCleanJsonTranscriptionWrappedV2 = true;
    window.fetch = wrapped;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(cleanVisibleBlocks, 300);
      setTimeout(cleanVisibleBlocks, 1200);
    });
  } else {
    setTimeout(cleanVisibleBlocks, 300);
    setTimeout(cleanVisibleBlocks, 1200);
  }

  try {
    var obs = new MutationObserver(function () {
      setTimeout(cleanVisibleBlocks, 30);
    });
    obs.observe(document.documentElement || document.body, {childList: true, subtree: true, characterData: true});
  } catch (e) {}

  window.iadCleanJsonTranscriptionV2 = cleanVisibleBlocks;
})();

