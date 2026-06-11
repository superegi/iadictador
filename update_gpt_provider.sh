#!/usr/bin/env bash

echo "===== IADICTADOR - AGREGAR GPT COMO INTERPRETADOR ====="
echo "HOST=$(hostname)"
date
echo

BASE="$HOME/Experimentos/iadictador"

echo "===== 1) VERIFICACION PREVIA ====="
cd "$BASE" || exit 1

echo "Directorio:"
pwd
echo

echo "Archivos esperados:"
ls -l requirements.txt app/main.py app/services/template_engine.py report_templates/tc_tap_cc.yaml .env
echo

echo "===== 2) BACKUP ====="
mkdir -p backups
TS="$(date +%Y%m%d_%H%M%S)"
cp requirements.txt "backups/requirements_${TS}.txt"
cp app/main.py "backups/main_${TS}.py"
echo "Backup creado en backups/"
echo

echo "===== 3) ACTUALIZAR REQUIREMENTS ====="
grep -q '^requests==' requirements.txt || echo 'requests==2.32.3' >> requirements.txt
echo "requirements.txt:"
cat requirements.txt
echo

echo "===== 4) CREAR GPT INTERPRETER ====="
cat > app/services/gpt_interpreter.py <<'PY'
import json
import os
from typing import Any

import requests


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ["1", "true", "yes", "y", "si", "sí"]


def _section_lines_summary(template: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for section in template.get("sections", []):
        for line in section.get("lines", []):
            rows.append({
                "section": section.get("key", ""),
                "section_title": section.get("title", ""),
                "line_id": line.get("id", ""),
                "text": line.get("text", ""),
            })
    return rows


def _schema() -> dict[str, Any]:
    """
    Esquema estricto y simple.
    Todos los campos son obligatorios para evitar respuestas variables.
    En acciones donde un campo no aplica, GPT debe devolver string vacío o lista vacía.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["replace", "add_after", "remove"]
                        },
                        "section": {
                            "type": "string",
                            "enum": ["antecedentes", "hallazgos", "impresion"]
                        },
                        "line_id": {
                            "type": "string",
                            "description": "ID de línea a reemplazar o eliminar. Vacío si no aplica."
                        },
                        "after_id": {
                            "type": "string",
                            "description": "ID de línea después de la cual insertar. Vacío si no aplica."
                        },
                        "new_id": {
                            "type": "string",
                            "description": "ID nuevo para add_after. Vacío si no aplica."
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Texto nuevo radiológico. Vacío para remove."
                        },
                        "tags": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["AGREGADO", "REEMPLAZADO", "IA", "REVISAR", "CONFLICTO", "ELIMINADO"]
                            }
                        },
                        "note": {
                            "type": "string"
                        },
                        "requires_review": {
                            "type": "boolean"
                        },
                        "review_reasons": {
                            "type": "array",
                            "items": {
                                "type": "string"
                            }
                        }
                    },
                    "required": [
                        "type",
                        "section",
                        "line_id",
                        "after_id",
                        "new_id",
                        "new_text",
                        "tags",
                        "note",
                        "requires_review",
                        "review_reasons"
                    ]
                }
            },
            "global_warnings": {
                "type": "array",
                "items": {
                    "type": "string"
                }
            },
            "model_notes": {
                "type": "string"
            }
        },
        "required": ["actions", "global_warnings", "model_notes"]
    }


def _build_prompt(template: dict[str, Any], dictado_bruto: str) -> str:
    lines = _section_lines_summary(template)

    return f"""
Eres un asistente de estructuración de informes radiológicos en español.

Tu tarea NO es diagnosticar libremente.
Tu tarea es convertir un dictado bruto en acciones controladas sobre una plantilla radiológica.

REGLAS CLÍNICAS ESTRICTAS:
1. Mantén todo lo que el dictado no contradiga.
2. Si el dictado contradice una frase normal de la plantilla, reemplaza esa frase.
3. Si el dictado agrega un hallazgo sin frase equivalente, insértalo en la sección anatómica más lógica.
4. No inventes diagnósticos etiológicos.
5. No transformes una descripción en diagnóstico específico salvo que el dictante lo diga explícitamente.
6. Si hay lesión nueva, lateralidad corregida, medición nueva, incertidumbre o localización imprecisa, marca requires_review=true.
7. Si agregas una impresión patológica, elimina la impresión normal "Examen sin hallazgos patológicos significativos." usando una acción remove.
8. Si agregas algo a impresión, debe existir correlato en hallazgos.
9. Si el dictante corrige algo ("no, izquierda", "perdón derecho"), usa la última versión y marca revisión.
10. Usa estilo radiológico sobrio y conciso.
11. No agregues recomendaciones clínicas salvo que el dictante las diga.
12. No elimines hallazgos normales salvo contradicción directa.

TIPOS DE ACCIÓN:
- replace: reemplaza una línea existente. Requiere line_id.
- add_after: inserta una línea nueva después de after_id. Requiere new_id y new_text.
- remove: elimina visualmente una línea existente. Requiere line_id.

TAGS:
- REEMPLAZADO: cuando cambia una línea existente.
- AGREGADO: cuando se agrega una línea nueva.
- IA: siempre que el texto fue estructurado desde dictado por el modelo.
- REVISAR: cuando requiere revisión humana.
- CONFLICTO: cuando hay contradicción peligrosa.
- ELIMINADO: para remove.

PLANTILLA DISPONIBLE, CON IDs:
{json.dumps(lines, ensure_ascii=False, indent=2)}

DICTADO_BRUTO:
{dictado_bruto}

EJEMPLOS DE COMPORTAMIENTO:
- "vesícula ausente" o "no hay vesícula" debe reemplazar vesicula_estado por "Vesícula biliar no visualizada."
- "lesión hepática hipodensa de bordes bien definidos con realce arterial periférico" debe reemplazar la línea higado, manteniendo si corresponde la morfología normal, y agregar impresión descriptiva. No debe decir hemangioma, HCC ni metástasis si el dictante no lo dijo.
- "litiasis puntiforme en cáliz inferior izquierdo de tres mm sin dilatación" debe reemplazar la línea renal normal y agregar impresión de nefrolitiasis no obstructiva izquierda.
- "rodilla derecha... no, izquierda" debe usar izquierda y marcar revisión por corrección de lateralidad.

Devuelve exclusivamente JSON válido según el esquema.
""".strip()


def _extract_output_text(response_json: dict[str, Any]) -> str:
    if "output_text" in response_json and response_json["output_text"]:
        return response_json["output_text"]

    output = response_json.get("output", [])
    parts = []

    for item in output:
        for content in item.get("content", []):
            if content.get("type") in ["output_text", "text"]:
                text = content.get("text")
                if text:
                    parts.append(text)

    if parts:
        return "\n".join(parts)

    raise RuntimeError(f"No se encontró texto JSON en respuesta OpenAI: {json.dumps(response_json, ensure_ascii=False)[:1000]}")


def interpret_gpt(dictado_bruto: str, template: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
    store = _env_bool("OPENAI_STORE", False)

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY no está configurada en .env")

    prompt = _build_prompt(template, dictado_bruto)
    schema = _schema()

    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "store": store,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "radiology_report_actions",
                "schema": schema,
                "strict": True
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    resp = requests.post(
        OPENAI_RESPONSES_URL,
        headers=headers,
        json=payload,
        timeout=60,
    )

    if resp.status_code >= 400:
        raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:2000]}")

    data = resp.json()
    text = _extract_output_text(data)

    parsed = json.loads(text)

    parsed.setdefault("actions", [])
    parsed.setdefault("global_warnings", [])
    parsed.setdefault("model_notes", "")

    parsed["dictado_normalizado"] = dictado_bruto.strip()
    parsed["provider"] = "gpt"
    parsed["model"] = model
    parsed["stored"] = store

    return parsed
PY

echo "gpt_interpreter.py creado."
echo

echo "===== 5) ACTUALIZAR MAIN.PY ====="
cat > app/main.py <<'PY'
import os

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.services.rule_interpreter import interpret_rules
from app.services.template_engine import build_report, load_template


app = FastAPI(title="Reporte IA Prototype")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def interpret_dictation(dictado_bruto: str, template: dict):
    provider = os.getenv("AI_PROVIDER", "rules").strip().lower()

    if not dictado_bruto.strip():
        return {
            "dictado_normalizado": "",
            "actions": [],
            "global_warnings": [],
            "provider": provider,
        }

    if provider in ["gpt", "openai"]:
        try:
            from app.services.gpt_interpreter import interpret_gpt
            return interpret_gpt(dictado_bruto, template)
        except Exception as exc:
            fallback = interpret_rules(dictado_bruto)
            fallback.setdefault("global_warnings", [])
            fallback["global_warnings"].insert(
                0,
                f"GPT falló y se usaron reglas locales como fallback: {exc}"
            )
            fallback["provider"] = "rules_fallback"
            return fallback

    result = interpret_rules(dictado_bruto)
    result["provider"] = "rules"
    return result


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
            "provider": os.getenv("AI_PROVIDER", "rules"),
        },
    )


@app.post("/process", response_class=HTMLResponse)
async def process(request: Request, dictado_bruto: str = Form("")):
    template = load_template("tc_tap_cc")
    interpretation = interpret_dictation(dictado_bruto, template)
    result = build_report(template, interpretation)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "dictado_bruto": dictado_bruto,
            "result": result,
            "actions": interpretation.get("actions", []),
            "processed": True,
            "provider": interpretation.get("provider", os.getenv("AI_PROVIDER", "rules")),
        },
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "ai_provider": os.getenv("AI_PROVIDER", "rules"),
        "openai_model": os.getenv("OPENAI_MODEL", ""),
    }
PY

echo "main.py actualizado."
echo

echo "===== 6) MEJORAR HTML PARA MOSTRAR PROVIDER ====="
python3 - <<'PY'
from pathlib import Path

p = Path("app/templates/index.html")
s = p.read_text(encoding="utf-8")

old = '<p>Plantilla activa: <strong>{{ result.template_name }}</strong></p>'
new = '<p>Plantilla activa: <strong>{{ result.template_name }}</strong> · Motor: <strong>{{ provider }}</strong></p>'

if old in s and new not in s:
    s = s.replace(old, new)

p.write_text(s, encoding="utf-8")
PY

echo "index.html actualizado."
echo

echo "===== 7) VERIFICAR .ENV ====="
echo "Variables relevantes:"
grep -E '^(AI_PROVIDER|OPENAI_MODEL|OPENAI_STORE|APP_PORT)=' .env || true
if ! grep -q '^OPENAI_API_KEY=' .env; then
  echo "ADVERTENCIA: .env no tiene OPENAI_API_KEY"
else
  echo "OPENAI_API_KEY presente en .env"
fi
echo

echo "===== 8) RECONSTRUIR DOCKER ====="

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
$COMPOSE up -d --build
echo

echo "===== 9) ESTADO ====="
$COMPOSE ps
echo

echo "===== 10) HEALTHCHECK ====="
sleep 3
curl -sS http://localhost:8015/health || true
echo
echo

echo "===== 11) LOGS RECIENTES ====="
$COMPOSE logs --tail 80
echo

echo "Prueba en la web:"
echo "http://localhost:8015"
echo
echo "Dictado de prueba 1:"
echo "vesícula ausente"
echo
echo "Dictado de prueba 2:"
echo "lesión hepática hipodensa de bordes bien definidos con realce arterial periférico"
echo
echo "Dictado de prueba 3:"
echo "lesión hepática hipodensa de bordes bien definidos con realce arterial periférico y divertículos en colon sin signos de complicación"
echo

echo "#######################################"
echo "######    FIN INPUT    ###############"
echo "#######################################"
