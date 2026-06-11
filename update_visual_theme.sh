#!/usr/bin/env bash

echo "===== IADICTADOR - MEJORAR COLORES Y EDITOR FINAL ====="
echo "HOST=$(hostname)"
date
echo

BASE="$HOME/Experimentos/iadictador"

echo "===== 1) VERIFICACION PREVIA ====="
cd "$BASE" || exit 1
pwd
echo

ls -l app/services/template_engine.py app/templates/index.html app/static/style.css .env docker-compose.yml
echo

echo "===== 2) BACKUP ====="
mkdir -p backups
TS="$(date +%Y%m%d_%H%M%S)"
cp app/services/template_engine.py "backups/template_engine_${TS}.py"
cp app/templates/index.html "backups/index_${TS}.html"
cp app/static/style.css "backups/style_${TS}.css"
echo "Backups creados en backups/"
echo

echo "===== 3) ACTUALIZAR TEMPLATE ENGINE CON DIFERENCIAS PALABRA A PALABRA ====="
cat > app/services/template_engine.py <<'PY'
from copy import deepcopy
from pathlib import Path
from typing import Any
import difflib
import html
import re

import yaml


BASE_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = BASE_DIR / "report_templates"


def load_template(template_id: str = "tc_tap_cc") -> dict[str, Any]:
    path = TEMPLATE_DIR / f"{template_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No existe plantilla: {path}")

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _highlight_placeholders_escaped(escaped_text: str) -> str:
    """
    Marca campos tipo [ ] o [texto] como placeholders grises.
    Recibe texto ya escapado para HTML.
    """
    return re.sub(
        r"(\[[^\]]*\])",
        r'<span class="diff-placeholder">\1</span>',
        escaped_text,
    )


def _escape_with_placeholders(text: str) -> str:
    return _highlight_placeholders_escaped(html.escape(text or ""))


def _tokenize_with_spaces(text: str) -> list[str]:
    return re.findall(r"\S+|\s+", text or "", flags=re.UNICODE)


def _word_diff_html(original: str, new: str, mode: str = "modified") -> str:
    """
    Devuelve HTML mostrando el texto final.
    - Partes iguales quedan normales.
    - Partes nuevas/modificadas quedan azules o verdes.
    - Lo eliminado no se muestra en la frase final; queda en detalle 'Original'.
    """
    original_tokens = _tokenize_with_spaces(original or "")
    new_tokens = _tokenize_with_spaces(new or "")

    if not original:
        return f'<span class="diff-added-text">{_escape_with_placeholders(new)}</span>'

    sm = difflib.SequenceMatcher(a=original_tokens, b=new_tokens)
    chunks: list[str] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        new_chunk = "".join(new_tokens[j1:j2])

        if tag == "equal":
            chunks.append(_escape_with_placeholders(new_chunk))
        elif tag in ("replace", "insert"):
            css = "diff-added-text" if mode == "added" else "diff-modified-text"
            chunks.append(f'<span class="{css}">{_escape_with_placeholders(new_chunk)}</span>')
        elif tag == "delete":
            # Lo eliminado no va en el texto final; se muestra aparte como original.
            continue

    return "".join(chunks)


def _line_status_class(tags: list[str], requires_review: bool) -> str:
    if "CONFLICTO" in tags:
        return "conflicto"
    if requires_review:
        return "revisar"
    if "ELIMINADO" in tags:
        return "eliminado"
    if "AGREGADO" in tags:
        return "agregado"
    if "REEMPLAZADO" in tags:
        return "reemplazado"
    if "IA" in tags:
        return "ia"
    return "normal"


def _prepare_line_visuals(line: dict[str, Any]) -> None:
    tags = line.get("tags", [])
    text = line.get("text", "")
    original = line.get("original_text", "")

    if line.get("removed"):
        line["diff_html"] = _escape_with_placeholders(text)
        return

    if "AGREGADO" in tags:
        line["diff_html"] = _word_diff_html("", text, mode="added")
    elif "REEMPLAZADO" in tags and original:
        line["diff_html"] = _word_diff_html(original, text, mode="modified")
    else:
        line["diff_html"] = _escape_with_placeholders(text)


def build_report(template: dict[str, Any], interpretation: dict[str, Any] | None = None) -> dict[str, Any]:
    interpretation = interpretation or {"actions": [], "global_warnings": []}
    sections = deepcopy(template["sections"])

    # Normalizar líneas
    for section in sections:
        for line in section["lines"]:
            line["tags"] = []
            line["status_class"] = "normal"
            line["requires_review"] = False
            line["note"] = ""
            line["review_reasons"] = []
            line["original_text"] = ""
            line["diff_html"] = _escape_with_placeholders(line.get("text", ""))

    actions = interpretation.get("actions", [])

    for action in actions:
        action_type = action.get("type")
        section_key = action.get("section")

        target_section = None
        for section in sections:
            if section["key"] == section_key:
                target_section = section
                break

        if target_section is None:
            continue

        if action_type == "replace":
            for line in target_section["lines"]:
                if line["id"] == action.get("line_id"):
                    line["original_text"] = line["text"]
                    line["text"] = action.get("new_text", line["text"])
                    line["tags"] = action.get("tags", ["REEMPLAZADO"])
                    line["requires_review"] = bool(action.get("requires_review", False))
                    line["note"] = action.get("note", "")
                    line["review_reasons"] = action.get("review_reasons", [])
                    line["status_class"] = _line_status_class(line["tags"], line["requires_review"])
                    _prepare_line_visuals(line)
                    break

        elif action_type == "remove":
            for line in target_section["lines"]:
                if line["id"] == action.get("line_id"):
                    line["tags"] = action.get("tags", ["ELIMINADO"])
                    line["requires_review"] = bool(action.get("requires_review", False))
                    line["note"] = action.get("note", "")
                    line["review_reasons"] = action.get("review_reasons", [])
                    line["status_class"] = _line_status_class(line["tags"], line["requires_review"])
                    line["removed"] = True
                    _prepare_line_visuals(line)
                    break

        elif action_type == "add_after":
            new_line = {
                "id": action.get("new_id", "linea_agregada"),
                "text": action.get("new_text", ""),
                "tags": action.get("tags", ["AGREGADO"]),
                "requires_review": bool(action.get("requires_review", False)),
                "note": action.get("note", ""),
                "review_reasons": action.get("review_reasons", []),
                "original_text": "",
                "status_class": _line_status_class(action.get("tags", ["AGREGADO"]), bool(action.get("requires_review", False))),
                "added": True,
            }
            _prepare_line_visuals(new_line)

            after_id = action.get("after_id")
            insert_idx = len(target_section["lines"])

            for idx, line in enumerate(target_section["lines"]):
                if line["id"] == after_id:
                    insert_idx = idx + 1
                    break

            already_exists = any(line["id"] == new_line["id"] for line in target_section["lines"])
            if not already_exists:
                target_section["lines"].insert(insert_idx, new_line)

    # Preparar visuales para líneas no tocadas
    for section in sections:
        for line in section["lines"]:
            if not line.get("diff_html"):
                _prepare_line_visuals(line)

    clean_text = render_clean_text(template["nombre"], sections)
    stats = collect_stats(sections, interpretation)

    return {
        "template_name": template["nombre"],
        "sections": sections,
        "clean_text": clean_text,
        "stats": stats,
        "global_warnings": interpretation.get("global_warnings", []),
        "dictado_normalizado": interpretation.get("dictado_normalizado", ""),
    }


def render_clean_text(title: str, sections: list[dict[str, Any]]) -> str:
    chunks = [title, ""]

    for section in sections:
        chunks.append(section["title"] + ":")
        visible_lines = []

        for line in section["lines"]:
            if line.get("removed"):
                continue
            text = (line.get("text") or "").strip()
            if text:
                visible_lines.append(text)

        if visible_lines:
            chunks.extend(visible_lines)
        else:
            chunks.append("")

        chunks.append("")

    return "\n".join(chunks).strip() + "\n"


def collect_stats(sections: list[dict[str, Any]], interpretation: dict[str, Any]) -> dict[str, int]:
    stats = {
        "agregado": 0,
        "reemplazado": 0,
        "ia": 0,
        "revisar": 0,
        "conflicto": 0,
        "eliminado": 0,
    }

    for section in sections:
        for line in section["lines"]:
            tags = line.get("tags", [])
            if "AGREGADO" in tags:
                stats["agregado"] += 1
            if "REEMPLAZADO" in tags:
                stats["reemplazado"] += 1
            if "IA" in tags:
                stats["ia"] += 1
            if line.get("requires_review"):
                stats["revisar"] += 1
            if "CONFLICTO" in tags:
                stats["conflicto"] += 1
            if "ELIMINADO" in tags:
                stats["eliminado"] += 1

    return stats
PY

echo "===== 4) ACTUALIZAR HTML ====="
cat > app/templates/index.html <<'HTML'
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Reporte IA Prototype</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header class="topbar">
    <div>
      <h1>Reporte IA Prototype</h1>
      <p>Plantilla activa: <strong>{{ result.template_name }}</strong> · Motor: <strong>{{ provider }}</strong></p>
    </div>
    <div class="stats">
      <span class="pill agregado">Agregados: {{ result.stats.agregado }}</span>
      <span class="pill reemplazado">Reemplazos: {{ result.stats.reemplazado }}</span>
      <span class="pill ia">IA: {{ result.stats.ia }}</span>
      <span class="pill revisar">Revisar: {{ result.stats.revisar }}</span>
      <span class="pill conflicto">Conflictos: {{ result.stats.conflicto }}</span>
    </div>
  </header>

  <main class="layout">
    <section class="panel input-panel">
      <h2>Dictado bruto escrito</h2>
      <form method="post" action="/process">
        <textarea name="dictado_bruto" spellcheck="false" placeholder="Ejemplo: lesión hepática hipodensa de bordes bien definidos con realce arterial periférico">{{ dictado_bruto }}</textarea>
        <div class="buttons">
          <button type="submit">Procesar</button>
          <a class="button-secondary" href="/">Limpiar</a>
        </div>
      </form>

      <div class="legend-block">
        <h3>Código de colores</h3>
        <div class="legend-row"><span class="sample normal-sample">Texto normal</span><span>Conservado o aceptado.</span></div>
        <div class="legend-row"><span class="sample blue-sample">Azul</span><span>Texto reemplazado/modificado.</span></div>
        <div class="legend-row"><span class="sample green-sample">Verde</span><span>Texto agregado desde dictado.</span></div>
        <div class="legend-row"><span class="sample gray-sample">[gris]</span><span>Campo variable o placeholder.</span></div>
        <div class="legend-row"><span class="sample yellow-sample">Revisar</span><span>Requiere decisión del radiólogo.</span></div>
        <div class="legend-row"><span class="sample red-sample">Conflicto</span><span>No debería firmarse sin resolver.</span></div>
      </div>

      <div class="examples">
        <h3>Pruebas rápidas</h3>
        <ul>
          <li><code>vesícula ausente</code></li>
          <li><code>lesión hepática hipodensa de bordes bien definidos con realce arterial periférico</code></li>
          <li><code>hay divertículos no complicados</code></li>
          <li><code>litiasis puntiforme en cáliz inferior izquierdo de tres mm sin dilatación</code></li>
        </ul>
      </div>

      {% if processed %}
      <div class="debug">
        <h3>Dictado normalizado</h3>
        <pre>{{ result.dictado_normalizado }}</pre>
      </div>
      {% endif %}
    </section>

    <section class="panel report-panel">
      <div class="report-header">
        <h2>Informe en modo revisión</h2>
        <div class="legend compact">
          <span class="legend-item agregado">Agregado</span>
          <span class="legend-item reemplazado">Reemplazado</span>
          <span class="legend-item ia">IA</span>
          <span class="legend-item revisar">Revisar</span>
          <span class="legend-item conflicto">Conflicto</span>
          <span class="legend-item eliminado">Eliminado</span>
        </div>
      </div>

      {% if result.global_warnings %}
      <div class="global-warning">
        <strong>Advertencias generales:</strong>
        <ul>
          {% for warning in result.global_warnings %}
          <li>{{ warning }}</li>
          {% endfor %}
        </ul>
      </div>
      {% endif %}

      <article class="report">
        <h1>{{ result.template_name }}</h1>

        {% for section in result.sections %}
          <h3>{{ section.title }}</h3>

          {% for line in section.lines %}
            {% if line.text %}
              <div class="report-line {{ line.status_class }}">
                <div class="line-main">
                  <span class="line-text">{{ line.diff_html | safe }}</span>

                  {% for tag in line.tags %}
                    <span class="badge {{ tag|lower }}">{{ tag }}</span>
                  {% endfor %}

                  {% if line.requires_review %}
                    <span class="badge revisar">REVISAR</span>
                  {% endif %}
                </div>

                {% if line.original_text %}
                  <div class="original-text">
                    <span>Original:</span> {{ line.original_text }}
                  </div>
                {% endif %}

                {% if line.note %}
                  <div class="note">
                    {{ line.note }}
                  </div>
                {% endif %}

                {% if line.review_reasons %}
                  <div class="review-reasons">
                    <strong>Motivos de revisión:</strong>
                    <ul>
                      {% for reason in line.review_reasons %}
                        <li>{{ reason }}</li>
                      {% endfor %}
                    </ul>
                  </div>
                {% endif %}
              </div>
            {% endif %}
          {% endfor %}
        {% endfor %}
      </article>
    </section>

    <section class="panel final-panel">
      <h2>Informe limpio final editable</h2>
      <p class="small">Puedes editar aquí. El botón copia texto plano, sin etiquetas HTML.</p>
      <div class="buttons">
        <button type="button" onclick="copyFinalEditor()">Copiar informe final</button>
        <button type="button" class="button-secondary" onclick="selectFinalEditor()">Seleccionar todo</button>
      </div>

      <article id="finalEditor" class="final-editor" contenteditable="true" spellcheck="true">
        <h1>{{ result.template_name }}</h1>

        {% for section in result.sections %}
          <h3>{{ section.title }}</h3>

          {% for line in section.lines %}
            {% if line.text and not line.removed %}
              <p class="final-line {{ line.status_class }}">{{ line.diff_html | safe }}</p>
            {% endif %}
          {% endfor %}
        {% endfor %}
      </article>

      <textarea id="plainCopyBuffer" class="hidden-buffer">{{ result.clean_text }}</textarea>
    </section>
  </main>

  <script>
    function copyFinalEditor() {
      const editor = document.getElementById("finalEditor");
      const text = editor.innerText.replace(/\n{3,}/g, "\n\n").trim() + "\n";
      navigator.clipboard.writeText(text);
    }

    function selectFinalEditor() {
      const editor = document.getElementById("finalEditor");
      const range = document.createRange();
      range.selectNodeContents(editor);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
  </script>
</body>
</html>
HTML

echo "===== 5) ACTUALIZAR CSS DARK THEME ====="
cat > app/static/style.css <<'CSS'
:root {
  --bg: #0b1120;
  --panel: #111827;
  --panel-soft: #162033;
  --panel-strong: #0f172a;
  --text: #e5e7eb;
  --text-strong: #f9fafb;
  --muted: #9ca3af;
  --border: #334155;

  --blue-bg: rgba(37, 99, 235, 0.18);
  --blue-border: #60a5fa;
  --blue-text: #93c5fd;

  --green-bg: rgba(22, 163, 74, 0.18);
  --green-border: #4ade80;
  --green-text: #86efac;

  --purple-bg: rgba(147, 51, 234, 0.18);
  --purple-border: #c084fc;
  --purple-text: #d8b4fe;

  --yellow-bg: rgba(245, 158, 11, 0.18);
  --yellow-border: #fbbf24;
  --yellow-text: #fde68a;

  --red-bg: rgba(220, 38, 38, 0.18);
  --red-border: #f87171;
  --red-text: #fecaca;

  --gray-bg: rgba(148, 163, 184, 0.14);
  --gray-border: #94a3b8;
  --gray-text: #cbd5e1;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
}

.topbar {
  padding: 16px 20px;
  background: #050816;
  color: var(--text-strong);
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: center;
  border-bottom: 1px solid var(--border);
}

.topbar h1 {
  margin: 0 0 4px 0;
  font-size: 22px;
}

.topbar p {
  margin: 0;
  color: var(--muted);
}

.stats {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.layout {
  display: grid;
  grid-template-columns: 360px minmax(580px, 1fr) 420px;
  gap: 14px;
  padding: 14px;
}

.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px;
  min-width: 0;
  box-shadow: 0 12px 30px rgba(0,0,0,0.25);
}

.panel h2 {
  margin-top: 0;
  font-size: 18px;
  color: var(--text-strong);
}

textarea {
  width: 100%;
  min-height: 220px;
  resize: vertical;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  font-size: 15px;
  line-height: 1.45;
  background: #0b1220;
  color: var(--text-strong);
}

textarea:focus,
.final-editor:focus {
  outline: 2px solid #38bdf8;
  outline-offset: 2px;
}

.buttons {
  margin-top: 10px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

button,
.button-secondary {
  border: 0;
  padding: 10px 14px;
  border-radius: 10px;
  background: #2563eb;
  color: white;
  font-weight: 700;
  cursor: pointer;
  text-decoration: none;
  display: inline-block;
}

.button-secondary {
  background: #475569;
}

.examples,
.legend-block {
  margin-top: 18px;
  color: var(--muted);
}

.examples code {
  color: var(--text-strong);
}

.legend-block h3,
.examples h3,
.debug h3 {
  color: var(--text-strong);
  margin-bottom: 8px;
}

.legend-row {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 8px;
  margin: 5px 0;
  font-size: 13px;
}

.sample {
  padding: 2px 7px;
  border-radius: 7px;
  border: 1px solid var(--border);
  font-weight: 700;
}

.normal-sample {
  color: var(--text-strong);
}

.blue-sample {
  color: var(--blue-text);
  background: var(--blue-bg);
  border-color: var(--blue-border);
}

.green-sample {
  color: var(--green-text);
  background: var(--green-bg);
  border-color: var(--green-border);
}

.gray-sample {
  color: var(--gray-text);
  background: var(--gray-bg);
  border-color: var(--gray-border);
}

.yellow-sample {
  color: var(--yellow-text);
  background: var(--yellow-bg);
  border-color: var(--yellow-border);
}

.red-sample {
  color: var(--red-text);
  background: var(--red-bg);
  border-color: var(--red-border);
}

.report-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.legend {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.legend-item,
.pill,
.badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 800;
  border: 1px solid transparent;
  letter-spacing: 0.02em;
}

.report {
  font-size: 15px;
  line-height: 1.5;
}

.report h1,
.final-editor h1 {
  font-size: 20px;
  margin-bottom: 18px;
  color: var(--text-strong);
}

.report h3,
.final-editor h3 {
  margin-top: 18px;
  margin-bottom: 8px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  color: var(--text-strong);
}

.report-line {
  padding: 9px 10px;
  border-radius: 10px;
  margin: 6px 0;
  border-left: 4px solid transparent;
  background: transparent;
}

.report-line.normal {
  color: var(--text);
}

.report-line.agregado {
  border-left-color: var(--green-border);
  background: rgba(22, 163, 74, 0.08);
}

.report-line.reemplazado {
  border-left-color: var(--blue-border);
  background: rgba(37, 99, 235, 0.08);
}

.report-line.ia {
  border-left-color: var(--purple-border);
  background: rgba(147, 51, 234, 0.08);
}

.report-line.revisar {
  border-left-color: var(--yellow-border);
  background: rgba(245, 158, 11, 0.12);
}

.report-line.conflicto {
  border-left-color: var(--red-border);
  background: rgba(220, 38, 38, 0.14);
}

.report-line.eliminado {
  border-left-color: var(--gray-border);
  background: rgba(148, 163, 184, 0.10);
  text-decoration: line-through;
  opacity: 0.75;
}

.line-main {
  display: flex;
  gap: 6px;
  align-items: baseline;
  flex-wrap: wrap;
}

.line-text {
  flex: 1 1 auto;
}

.diff-modified-text {
  color: var(--blue-text);
  background: var(--blue-bg);
  border-bottom: 1px solid var(--blue-border);
  border-radius: 4px;
  padding: 0 2px;
}

.diff-added-text {
  color: var(--green-text);
  background: var(--green-bg);
  border-bottom: 1px solid var(--green-border);
  border-radius: 4px;
  padding: 0 2px;
}

.diff-placeholder {
  color: var(--gray-text);
  background: var(--gray-bg);
  border: 1px dashed var(--gray-border);
  border-radius: 4px;
  padding: 0 3px;
}

.pill.agregado,
.legend-item.agregado,
.badge.agregado {
  background: var(--green-bg);
  border-color: var(--green-border);
  color: var(--green-text);
}

.pill.reemplazado,
.legend-item.reemplazado,
.badge.reemplazado {
  background: var(--blue-bg);
  border-color: var(--blue-border);
  color: var(--blue-text);
}

.pill.ia,
.legend-item.ia,
.badge.ia {
  background: var(--purple-bg);
  border-color: var(--purple-border);
  color: var(--purple-text);
}

.pill.revisar,
.legend-item.revisar,
.badge.revisar {
  background: var(--yellow-bg);
  border-color: var(--yellow-border);
  color: var(--yellow-text);
}

.pill.conflicto,
.legend-item.conflicto,
.badge.conflicto {
  background: var(--red-bg);
  border-color: var(--red-border);
  color: var(--red-text);
}

.legend-item.eliminado,
.badge.eliminado {
  background: var(--gray-bg);
  border-color: var(--gray-border);
  color: var(--gray-text);
  text-decoration: line-through;
}

.original-text {
  margin-top: 7px;
  color: var(--muted);
  font-size: 13px;
}

.original-text span {
  color: var(--gray-text);
  font-weight: 800;
}

.note {
  margin-top: 4px;
  color: var(--muted);
  font-size: 13px;
}

.review-reasons {
  margin-top: 7px;
  color: var(--yellow-text);
  font-size: 13px;
}

.review-reasons ul {
  margin: 4px 0 0 18px;
  padding: 0;
}

.global-warning {
  background: var(--yellow-bg);
  border: 1px solid var(--yellow-border);
  color: var(--yellow-text);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 12px;
}

pre {
  white-space: pre-wrap;
  word-break: break-word;
  background: #020617;
  color: #e5e7eb;
  padding: 12px;
  border-radius: 10px;
  max-height: 70vh;
  overflow: auto;
  border: 1px solid var(--border);
}

.small {
  color: var(--muted);
  font-size: 13px;
}

.debug pre {
  max-height: 120px;
  font-size: 12px;
}

.final-editor {
  margin-top: 12px;
  background: #020617;
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
  min-height: 520px;
  max-height: 78vh;
  overflow: auto;
  line-height: 1.5;
  font-size: 14px;
  white-space: normal;
}

.final-editor h1 {
  margin-top: 0;
}

.final-line {
  margin: 6px 0;
  padding: 2px 0;
}

.final-line.revisar {
  border-left: 3px solid var(--yellow-border);
  padding-left: 8px;
}

.final-line.conflicto {
  border-left: 3px solid var(--red-border);
  padding-left: 8px;
}

.hidden-buffer {
  display: none;
}

@media (max-width: 1350px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .topbar {
    flex-direction: column;
    align-items: flex-start;
  }

  .stats {
    justify-content: flex-start;
  }
}
CSS

echo "===== 6) RECONSTRUIR Y LEVANTAR ====="

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "ERROR: No se encontró docker compose ni docker-compose."
  exit 1
fi

echo "Usando: $COMPOSE"
$COMPOSE down
$COMPOSE up -d --build --force-recreate
echo

echo "===== 7) ESTADO ====="
$COMPOSE ps
echo

echo "===== 8) HEALTHCHECK ====="
sleep 3
curl -sS http://localhost:8015/health || true
echo

echo
echo "Abre:"
echo "http://localhost:8015"
echo
echo "Prueba:"
echo "lesión hepática hipodensa de bordes bien definidos con realce arterial periférico"
echo
echo "#######################################"
echo "######    FIN INPUT    ###############"
echo "#######################################"
