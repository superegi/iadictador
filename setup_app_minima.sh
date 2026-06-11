bash <<'BASH'
echo "===== REPORTE IA PROTOTYPE - APP MINIMA FUNCIONAL ====="

BASE="$HOME/Experimentos/reporte-ia-prototype"

echo
echo "===== 1) VERIFICACION PREVIA ====="
if [ ! -d "$BASE" ]; then
  echo "ERROR: No existe $BASE"
  echo "Primero ejecuta el bloque de creación de estructura."
  echo
  echo "#######################################"
  echo "######    FIN INPUT    ###############"
  echo "#######################################"
  exit 1
fi

cd "$BASE" || exit 1

echo "Directorio actual:"
pwd

echo
echo "Archivos/carpetas actuales:"
find . -maxdepth 2 -type d | sort

echo
echo "===== 2) CREAR ARCHIVOS PYTHON BASE ====="

touch app/__init__.py
touch app/services/__init__.py

cat > report_templates/tc_tap_cc.yaml <<'EOF'
id: tc_tap_cc
nombre: "TC tórax, abdomen y pelvis CC"

sections:
  - key: antecedentes
    title: "Antecedentes"
    lines:
      - id: antecedentes_vacio
        text: ""

  - key: hallazgos
    title: "Hallazgos"
    lines:
      - id: pulmon_volumen
        text: "Volumen y arquitectura pulmonar conservada."
      - id: via_aerea
        text: "Tráquea y bronquios principales permeables."
      - id: derrame_pleural
        text: "No hay derrame pleural."
      - id: neumotorax
        text: "No hay neumotórax."
      - id: nodulos_condensacion
        text: "No hay focos de condensación neumónico. No se observan nódulos pulmonares morfológicamente patológicos."
      - id: corazon
        text: "Corazón de tamaño normal. No hay derrame pericárdico."
      - id: vasos_torax
        text: "Aorta y resto de los grandes vasos del tórax de calibre conservado."
      - id: higado
        text: "Hígado de morfología normal, sin lesiones focales."
      - id: vesicula_estado
        text: "Vesícula biliar en repleción parcial, de paredes delgadas."
      - id: via_biliar
        text: "No hay dilatación de la vía biliar intrahepática. El colédoco fino."
      - id: organos_solidos
        text: "Bazo, páncreas y glándulas suprarrenales sin alteraciones tomográficas."
      - id: rinones_litiasis
        text: "Riñones de tamaño normal. No se observa hidronefrosis. No son evidentes litiasis."
      - id: vasos_abdomen
        text: "Cava inferior, porta y sus ramas principales de calibre normal."
      - id: asas
        text: "Asas de calibre conservado."
      - id: vejiga
        text: "Vejiga en repleción parcial, sin imágenes patológicas endoluminales."
      - id: organo_sexual
        text: "Próstata de estructura y tamaño normal. Vesículas seminales simétricas."
      - id: liquido_libre
        text: "No hay líquido libre significativo."
      - id: fosas_isquiorrectales
        text: "Fosas isquiorrectales libres."

  - key: impresion
    title: "Impresión diagnóstica"
    lines:
      - id: impresion_normal
        text: "Examen sin hallazgos patológicos significativos."
EOF

cat > app/services/rule_interpreter.py <<'PY'
import re
import unicodedata
from typing import Any


NUM_WORDS = {
    "uno": 1, "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
}


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text


def extract_mm(text_norm: str) -> int | None:
    # 3 mm / 3 milimetros / tres mm / tres milimetros
    m = re.search(
        r"\b(\d{1,3}|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince)\s*(mm|milimetros|milimetro)\b",
        text_norm,
    )
    if not m:
        return None

    raw = m.group(1)
    if raw.isdigit():
        return int(raw)
    return NUM_WORDS.get(raw)


def extract_laterality(text_norm: str) -> tuple[str | None, list[str]]:
    matches = []
    for m in re.finditer(r"\b(derecha|derecho|izquierda|izquierdo|bilateral|bilaterales)\b", text_norm):
        val = m.group(1)
        if val in ["derecha", "derecho"]:
            matches.append("derecha")
        elif val in ["izquierda", "izquierdo"]:
            matches.append("izquierda")
        else:
            matches.append("bilateral")

    if not matches:
        return None, []

    return matches[-1], matches


def interpret_rules(dictado_bruto: str) -> dict[str, Any]:
    """
    Interpretador local inicial.
    No usa IA. Solo reglas para validar flujo visual y motor de plantilla.
    """
    text_norm = normalize(dictado_bruto)
    actions: list[dict[str, Any]] = []
    global_warnings: list[str] = []

    abnormal_impressions = []

    # Vesícula ausente / no visualizada
    if any(phrase in text_norm for phrase in [
        "no hay vesicula",
        "vesicula no visualizada",
        "no se visualiza vesicula",
        "colecistectomia",
        "colecistectomizado",
        "colecistectomizada",
    ]):
        actions.append({
            "type": "replace",
            "section": "hallazgos",
            "line_id": "vesicula_estado",
            "new_text": "Vesícula biliar no visualizada.",
            "tags": ["REEMPLAZADO"],
            "note": "El dictado indica ausencia/no visualización de la vesícula biliar.",
            "requires_review": False,
        })

    # Divertículos no complicados
    if "diverticul" in text_norm:
        if any(phrase in text_norm for phrase in [
            "sin signos de complicacion",
            "no complicados",
            "no complicado",
            "sin complicacion",
        ]):
            divert_text = "Divertículos en el colon sin signos de complicación."
        else:
            divert_text = "Divertículos en el colon."
            global_warnings.append("Divertículos mencionados sin aclarar si hay signos de complicación.")

        actions.append({
            "type": "add_after",
            "section": "hallazgos",
            "after_id": "asas",
            "new_id": "diverticulos_agregado",
            "new_text": divert_text,
            "tags": ["AGREGADO"],
            "note": "Hallazgo agregado desde dictado. No reemplaza una frase específica de la plantilla.",
            "requires_review": "sin signos de complicacion" not in text_norm and "no complicado" not in text_norm and "no complicados" not in text_norm,
        })
        abnormal_impressions.append({
            "new_id": "impresion_diverticulos",
            "text": divert_text,
            "tags": ["AGREGADO"],
            "requires_review": "sin signos de complicacion" not in text_norm and "no complicado" not in text_norm and "no complicados" not in text_norm,
        })

    # Litiasis / nefrolitiasis
    if any(word in text_norm for word in ["nefrolitiasis", "litiasis renal", "litiasis", "caliz", "calicial"]):
        mm = extract_mm(text_norm)
        laterality, lateralities_seen = extract_laterality(text_norm)

        if laterality is None:
            laterality = "no especificada"

        location = None
        if "caliz inferior" in text_norm or "calicial inferior" in text_norm or "grupo calicial inferior" in text_norm:
            location = "en cáliz inferior"
        elif "caliz superior" in text_norm or "calicial superior" in text_norm or "grupo calicial superior" in text_norm:
            location = "en cáliz superior"
        elif "caliz medio" in text_norm or "calicial medio" in text_norm or "grupo calicial medio" in text_norm:
            location = "en cáliz medio"

        obstructive = None
        if any(phrase in text_norm for phrase in ["sin dilatacion", "no hay dilatacion", "no obstructiva", "no obstructivo", "sin hidronefrosis"]):
            obstructive = False
        elif any(phrase in text_norm for phrase in ["obstructiva", "obstructivo", "hidronefrosis", "dilatacion pielocalicial"]):
            obstructive = True

        size_text = f" de {mm} mm" if mm is not None else ""
        loc_text = f" {location}" if location else ""
        lat_text = "" if laterality == "no especificada" else f" {laterality}"

        if obstructive is False:
            hallazgo = f"Litiasis no obstructiva{lat_text}{loc_text}{size_text}, sin dilatación pielocalicial."
            impresion = f"Nefrolitiasis no obstructiva{lat_text}."
        elif obstructive is True:
            hallazgo = f"Litiasis{lat_text}{loc_text}{size_text}, asociada a dilatación pielocalicial."
            impresion = f"Nefrolitiasis obstructiva{lat_text}."
        else:
            hallazgo = f"Litiasis renal{lat_text}{loc_text}{size_text}."
            impresion = f"Nefrolitiasis{lat_text}."

        review_reasons = []
        if mm is None:
            review_reasons.append("No se detectó medición en mm.")
        if laterality == "no especificada":
            review_reasons.append("No se detectó lateralidad.")
        if len(set(lateralities_seen)) > 1:
            review_reasons.append(f"Lateralidad corregida o contradictoria durante el dictado: {', '.join(lateralities_seen)}. Se usó la última: {laterality}.")
        if obstructive is None:
            review_reasons.append("No queda claro si la litiasis es obstructiva o no obstructiva.")

        actions.append({
            "type": "replace",
            "section": "hallazgos",
            "line_id": "rinones_litiasis",
            "new_text": f"Riñones de tamaño normal. No se observa hidronefrosis. {hallazgo}",
            "tags": ["REEMPLAZADO", "IA"],
            "note": "La frase normal renal fue reemplazada por hallazgo de litiasis interpretado desde el dictado.",
            "requires_review": bool(review_reasons),
            "review_reasons": review_reasons,
        })

        abnormal_impressions.append({
            "new_id": "impresion_nefrolitiasis",
            "text": impresion,
            "tags": ["AGREGADO", "IA"],
            "requires_review": bool(review_reasons),
            "review_reasons": review_reasons,
        })

    # Si hay impresión patológica, eliminar impresión normal
    if abnormal_impressions:
        actions.append({
            "type": "remove",
            "section": "impresion",
            "line_id": "impresion_normal",
            "tags": ["ELIMINADO"],
            "note": "Se elimina la impresión normal porque se agregaron hallazgos patológicos.",
            "requires_review": False,
        })

        for item in abnormal_impressions:
            actions.append({
                "type": "add_after",
                "section": "impresion",
                "after_id": "impresion_normal",
                "new_id": item["new_id"],
                "new_text": item["text"],
                "tags": item["tags"],
                "note": "Impresión agregada desde hallazgo detectado en el dictado.",
                "requires_review": item.get("requires_review", False),
                "review_reasons": item.get("review_reasons", []),
            })

    return {
        "dictado_normalizado": text_norm,
        "actions": actions,
        "global_warnings": global_warnings,
    }
PY

cat > app/services/template_engine.py <<'PY'
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


BASE_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = BASE_DIR / "report_templates"


def load_template(template_id: str = "tc_tap_cc") -> dict[str, Any]:
    path = TEMPLATE_DIR / f"{template_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No existe plantilla: {path}")

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _line_status_class(tags: list[str], requires_review: bool) -> str:
    if "CONFLICTO" in tags:
        return "conflicto"
    if requires_review:
        return "revisar"
    if "ELIMINADO" in tags:
        return "eliminado"
    if "REEMPLAZADO" in tags:
        return "reemplazado"
    if "AGREGADO" in tags:
        return "agregado"
    if "IA" in tags:
        return "ia"
    return "normal"


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

            after_id = action.get("after_id")
            insert_idx = len(target_section["lines"])

            for idx, line in enumerate(target_section["lines"]):
                if line["id"] == after_id:
                    insert_idx = idx + 1
                    break

            # Evitar duplicados por id si se procesa varias veces
            already_exists = any(line["id"] == new_line["id"] for line in target_section["lines"])
            if not already_exists:
                target_section["lines"].insert(insert_idx, new_line)

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

cat > app/main.py <<'PY'
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.services.rule_interpreter import interpret_rules
from app.services.template_engine import build_report, load_template


app = FastAPI(title="Reporte IA Prototype")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    template = load_template("tc_tap_cc")
    result = build_report(template)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "dictado_bruto": "",
            "result": result,
            "actions": [],
            "processed": False,
        },
    )


@app.post("/process", response_class=HTMLResponse)
async def process(request: Request, dictado_bruto: str = Form("")):
    template = load_template("tc_tap_cc")
    interpretation = interpret_rules(dictado_bruto)
    result = build_report(template, interpretation)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "dictado_bruto": dictado_bruto,
            "result": result,
            "actions": interpretation.get("actions", []),
            "processed": True,
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
PY

echo
echo "===== 3) CREAR HTML Y CSS ====="

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
      <p>Plantilla activa: <strong>{{ result.template_name }}</strong></p>
    </div>
    <div class="stats">
      <span class="pill agregado">Agregados: {{ result.stats.agregado }}</span>
      <span class="pill reemplazado">Reemplazos: {{ result.stats.reemplazado }}</span>
      <span class="pill ia">IA/reglas: {{ result.stats.ia }}</span>
      <span class="pill revisar">Revisar: {{ result.stats.revisar }}</span>
      <span class="pill conflicto">Conflictos: {{ result.stats.conflicto }}</span>
    </div>
  </header>

  <main class="layout">
    <section class="panel input-panel">
      <h2>Dictado bruto escrito</h2>
      <form method="post" action="/process">
        <textarea name="dictado_bruto" spellcheck="false" placeholder="Ejemplo: no hay vesícula, hay divertículos no complicados, litiasis puntiforme en cáliz inferior izquierdo de tres mm sin dilatación">{{ dictado_bruto }}</textarea>
        <div class="buttons">
          <button type="submit">Procesar</button>
          <a class="button-secondary" href="/">Limpiar</a>
        </div>
      </form>

      <div class="examples">
        <h3>Pruebas rápidas</h3>
        <ul>
          <li><code>no hay vesícula</code></li>
          <li><code>hay divertículos no complicados</code></li>
          <li><code>litiasis puntiforme en cáliz inferior izquierdo de tres mm sin dilatación</code></li>
          <li><code>riñón derecho con litiasis de cuatro mm no perdón izquierdo sin dilatación</code></li>
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
        <div class="legend">
          <span class="legend-item agregado">Agregado</span>
          <span class="legend-item reemplazado">Reemplazado</span>
          <span class="legend-item ia">Estructurado</span>
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
                  <span class="line-text">{{ line.text }}</span>

                  {% for tag in line.tags %}
                    <span class="badge {{ tag|lower }}">{{ tag }}</span>
                  {% endfor %}

                  {% if line.requires_review %}
                    <span class="badge revisar">REVISAR</span>
                  {% endif %}
                </div>

                {% if line.original_text %}
                  <div class="original-text">
                    Original: {{ line.original_text }}
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

    <section class="panel clean-panel">
      <h2>Informe limpio final</h2>
      <p class="small">Esta versión elimina marcas visuales y frases eliminadas.</p>
      <button onclick="copyClean()">Copiar informe limpio</button>
      <pre id="cleanText">{{ result.clean_text }}</pre>
    </section>
  </main>

  <script>
    function copyClean() {
      const text = document.getElementById("cleanText").innerText;
      navigator.clipboard.writeText(text);
    }
  </script>
</body>
</html>
HTML

cat > app/static/style.css <<'CSS'
:root {
  --bg: #f5f7fb;
  --panel: #ffffff;
  --text: #172033;
  --muted: #667085;
  --border: #d0d5dd;

  --green-bg: #dcfce7;
  --green-border: #16a34a;

  --blue-bg: #dbeafe;
  --blue-border: #2563eb;

  --purple-bg: #f3e8ff;
  --purple-border: #9333ea;

  --yellow-bg: #fef3c7;
  --yellow-border: #f59e0b;

  --red-bg: #fee2e2;
  --red-border: #dc2626;

  --gray-bg: #f2f4f7;
  --gray-border: #98a2b3;
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
  padding: 18px 24px;
  background: #0f172a;
  color: white;
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: center;
}

.topbar h1 {
  margin: 0 0 4px 0;
  font-size: 22px;
}

.topbar p {
  margin: 0;
  color: #cbd5e1;
}

.stats {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.layout {
  display: grid;
  grid-template-columns: 360px minmax(500px, 1fr) 420px;
  gap: 16px;
  padding: 16px;
}

.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px;
  min-width: 0;
}

.panel h2 {
  margin-top: 0;
  font-size: 18px;
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
}

.buttons {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}

button,
.button-secondary {
  border: 0;
  padding: 10px 14px;
  border-radius: 10px;
  background: #0f172a;
  color: white;
  font-weight: 700;
  cursor: pointer;
  text-decoration: none;
  display: inline-block;
}

.button-secondary {
  background: #475467;
}

.examples {
  margin-top: 18px;
  color: var(--muted);
}

.examples code {
  color: #111827;
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
  font-size: 12px;
  font-weight: 700;
  border: 1px solid transparent;
}

.report {
  font-size: 15px;
  line-height: 1.45;
}

.report h1 {
  font-size: 20px;
  margin-bottom: 18px;
}

.report h3 {
  margin-top: 18px;
  margin-bottom: 8px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
}

.report-line {
  padding: 8px 10px;
  border-radius: 10px;
  margin: 5px 0;
  border-left: 5px solid transparent;
}

.report-line.normal {
  background: white;
}

.report-line.agregado,
.pill.agregado,
.legend-item.agregado,
.badge.agregado {
  background: var(--green-bg);
  border-color: var(--green-border);
}

.report-line.reemplazado,
.pill.reemplazado,
.legend-item.reemplazado,
.badge.reemplazado {
  background: var(--blue-bg);
  border-color: var(--blue-border);
}

.report-line.ia,
.pill.ia,
.legend-item.ia,
.badge.ia {
  background: var(--purple-bg);
  border-color: var(--purple-border);
}

.report-line.revisar,
.pill.revisar,
.legend-item.revisar,
.badge.revisar {
  background: var(--yellow-bg);
  border-color: var(--yellow-border);
}

.report-line.conflicto,
.pill.conflicto,
.legend-item.conflicto,
.badge.conflicto {
  background: var(--red-bg);
  border-color: var(--red-border);
}

.report-line.eliminado,
.legend-item.eliminado,
.badge.eliminado {
  background: var(--gray-bg);
  border-color: var(--gray-border);
  text-decoration: line-through;
  opacity: 0.8;
}

.report-line.agregado {
  border-left-color: var(--green-border);
}

.report-line.reemplazado {
  border-left-color: var(--blue-border);
}

.report-line.ia {
  border-left-color: var(--purple-border);
}

.report-line.revisar {
  border-left-color: var(--yellow-border);
}

.report-line.conflicto {
  border-left-color: var(--red-border);
}

.report-line.eliminado {
  border-left-color: var(--gray-border);
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

.original-text {
  margin-top: 6px;
  color: #344054;
  font-size: 13px;
}

.note {
  margin-top: 4px;
  color: #475467;
  font-size: 13px;
}

.review-reasons {
  margin-top: 6px;
  font-size: 13px;
}

.review-reasons ul {
  margin: 4px 0 0 18px;
  padding: 0;
}

.global-warning {
  background: var(--yellow-bg);
  border: 1px solid var(--yellow-border);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 12px;
}

pre {
  white-space: pre-wrap;
  word-break: break-word;
  background: #101828;
  color: #f9fafb;
  padding: 12px;
  border-radius: 10px;
  max-height: 70vh;
  overflow: auto;
}

.small {
  color: var(--muted);
  font-size: 13px;
}

.debug pre {
  max-height: 120px;
  font-size: 12px;
}

@media (max-width: 1300px) {
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

echo
echo "===== 4) VERIFICAR DOCKER COMPOSE ====="
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker no está disponible en PATH."
  echo
  echo "#######################################"
  echo "######    FIN INPUT    ###############"
  echo "#######################################"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: docker compose no responde."
  echo
  echo "#######################################"
  echo "######    FIN INPUT    ###############"
  echo "#######################################"
  exit 1
fi

echo "Docker OK:"
docker --version
docker compose version

echo
echo "===== 5) LEVANTAR PROTOTIPO ====="
docker compose up -d --build

echo
echo "===== 6) ESTADO ====="
docker compose ps

echo
echo "===== 7) HEALTHCHECK ====="
sleep 2
curl -sS http://localhost:8015/health || true

echo
echo
echo "Abre en el navegador:"
echo "http://localhost:8015"
echo
echo "Prueba con este dictado:"
echo "no hay vesícula, hay divertículos no complicados, litiasis puntiforme en cáliz inferior izquierdo de tres mm sin dilatación"
echo
echo "#######################################"
echo "######    FIN INPUT    ###############"
echo "#######################################"
BASH
