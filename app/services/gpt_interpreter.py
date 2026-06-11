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
- "" o "no hay vesícula" debe reemplazar vesicula_estado por "Vesícula biliar no visualizada."
- "" debe reemplazar la línea higado, manteniendo si corresponde la morfología normal, y agregar impresión descriptiva. No debe decir hemangioma, HCC ni metástasis si el dictante no lo dijo.
- "" debe reemplazar la línea renal normal y agregar impresión de nefrolitiasis no obstructiva izquierda.
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
