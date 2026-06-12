from __future__ import annotations

import json
import os
import re
from typing import Any


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = _clean_text(text)
    if not raw:
        return {}

    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        fragment = raw[start : end + 1]
        try:
            data = json.loads(fragment)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    return {}


def _template_score(text: str, template: dict[str, Any]) -> int:
    haystack = text.lower()
    name = _clean_text(
        template.get("nombre")
        or template.get("name")
        or template.get("title")
        or template.get("titulo")
    ).lower()

    score = 0
    if name and name in haystack:
        score += 100

    tokens = [
        t
        for t in re.split(r"[^a-záéíóúñ0-9]+", name)
        if len(t) >= 3
    ]
    for t in tokens:
        if t in haystack:
            score += 8

    aliases = {
        "tórax": ["torax", "tórax", "pulmon", "pulmonar", "mediastino"],
        "tap": ["tap", "torax abdomen pelvis", "tórax abdomen pelvis"],
        "abdomen": ["abdomen", "hepático", "higado", "hígado", "vesícula", "pancreas", "páncreas"],
        "rodilla": ["rodilla", "menisco", "ligamento cruzado", "lca", "lcp"],
        "cerebro": ["cerebro", "encefalo", "encéfalo", "cráneo", "craneo"],
        "angio": ["angio", "aneurisma", "estenosis", "oclusión", "oclusion"],
    }

    for key, words in aliases.items():
        if key in name:
            for w in words:
                if w in haystack:
                    score += 12

    return score


def _suggest_template(text: str, templates: list[dict[str, Any]]) -> dict[str, Any]:
    if not templates:
        return {
            "id": None,
            "nombre": "",
            "confianza": "baja",
            "motivo": "No hay plantillas disponibles para comparar.",
        }

    scored = []
    for template in templates:
        score = _template_score(text, template)
        scored.append((score, template))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]

    name = _clean_text(
        best.get("nombre")
        or best.get("name")
        or best.get("title")
        or best.get("titulo")
    )

    if best_score >= 80:
        confidence = "alta"
    elif best_score >= 20:
        confidence = "media"
    else:
        confidence = "baja"

    return {
        "id": best.get("id"),
        "nombre": name,
        "confianza": confidence,
        "motivo": f"Coincidencia heurística con puntaje {best_score}.",
    }


def _heuristic_extract(text: str, templates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    templates = templates or []
    raw = _clean_text(text)
    normalized = " ".join(raw.split())

    edad = ""
    m_age = re.search(r"\b(\d{1,3})\s*(?:años|a[ñn]os|a)\b", normalized, flags=re.I)
    if m_age:
        edad = m_age.group(1)

    paciente = ""
    patient_patterns = [
        r"\bpaciente\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+){1,3})",
        r"\b(?:se llama|nombre)\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+){1,3})",
    ]
    for pat in patient_patterns:
        m = re.search(pat, normalized, flags=re.I)
        if m:
            paciente = m.group(1).strip(" ,.;:")
            break

    sexo = ""
    if re.search(r"\b(masculino|hombre|var[oó]n)\b", normalized, flags=re.I):
        sexo = "masculino"
    elif re.search(r"\b(femenino|mujer)\b", normalized, flags=re.I):
        sexo = "femenino"

    ocupacion = ""
    m_occ = re.search(
        r"\b(?:trabaja como|trabajador(?:a)?|ocupaci[oó]n|profesi[oó]n)\s+([^,.;&]{3,80})",
        normalized,
        flags=re.I,
    )
    if m_occ:
        ocupacion = m_occ.group(1).strip(" ,.;:")

    institucion = ""
    m_inst = re.search(
        r"\b(?:en|instituci[oó]n|cl[ií]nica|hospital|sanatorio)\s+([A-ZÁÉÍÓÚÑ][^,.;&]{3,80})",
        normalized,
    )
    if m_inst:
        institucion = m_inst.group(1).strip(" ,.;:")

    motivo = ""
    m_motivo = re.search(
        r"\b(?:por|motivo|indicaci[oó]n|sospecha de|control de)\s+([^.;]{4,140})",
        normalized,
        flags=re.I,
    )
    if m_motivo:
        motivo = m_motivo.group(1).strip(" ,.;:")

    antecedentes = ""
    m_ant = re.search(
        r"\b(?:antecedente(?:s)? de|antecedente)\s+([^.;]{4,180})",
        normalized,
        flags=re.I,
    )
    if m_ant:
        antecedentes = m_ant.group(1).strip(" ,.;:")

    # Separación simple: por ahora no interpreta clínicamente, solo conserva el bloque de hallazgos.
    hallazgos = normalized
    for phrase in [
        paciente,
        edad + " años" if edad else "",
        ocupacion,
        institucion,
        motivo,
        antecedentes,
    ]:
        if phrase:
            hallazgos = hallazgos.replace(phrase, " ")
    hallazgos = re.sub(r"\s+", " ", hallazgos).strip()

    return {
        "plantilla_sugerida": _suggest_template(normalized, templates),
        "informacion_secundaria": {
            "paciente_nombre_completo": paciente,
            "edad": edad,
            "sexo": sexo,
            "ocupacion_lugar_trabajo": ocupacion,
            "institucion_lugar": institucion,
            "motivo_examen": motivo,
            "antecedentes": antecedentes,
        },
        "hallazgos_radiologicos": hallazgos,
        "advertencias": [
            "Extracción heurística: revisar antes de usar para informe final."
        ],
        "necesita_revision": True,
        "metodo": "heuristico",
    }


def _normalize_extraction(data: dict[str, Any], text: str, templates: list[dict[str, Any]]) -> dict[str, Any]:
    secondary = data.get("informacion_secundaria") or {}
    if not isinstance(secondary, dict):
        secondary = {}

    plantilla = data.get("plantilla_sugerida") or {}
    if not isinstance(plantilla, dict):
        plantilla = {}

    if not plantilla.get("nombre"):
        plantilla = _suggest_template(text, templates)

    warnings = data.get("advertencias") or []
    if isinstance(warnings, str):
        warnings = [warnings]
    if not isinstance(warnings, list):
        warnings = []

    return {
        "plantilla_sugerida": {
            "id": plantilla.get("id"),
            "nombre": _clean_text(plantilla.get("nombre") or plantilla.get("name") or plantilla.get("titulo")),
            "confianza": _clean_text(plantilla.get("confianza") or plantilla.get("confidence") or "baja"),
            "motivo": _clean_text(plantilla.get("motivo") or plantilla.get("reason") or ""),
        },
        "informacion_secundaria": {
            "paciente_nombre_completo": _clean_text(secondary.get("paciente_nombre_completo") or secondary.get("paciente") or secondary.get("nombre_paciente")),
            "edad": _clean_text(secondary.get("edad")),
            "sexo": _clean_text(secondary.get("sexo")),
            "ocupacion_lugar_trabajo": _clean_text(secondary.get("ocupacion_lugar_trabajo") or secondary.get("ocupacion") or secondary.get("lugar_trabajo")),
            "institucion_lugar": _clean_text(secondary.get("institucion_lugar") or secondary.get("institucion") or secondary.get("lugar")),
            "motivo_examen": _clean_text(secondary.get("motivo_examen") or secondary.get("motivo")),
            "antecedentes": _clean_text(secondary.get("antecedentes")),
        },
        "hallazgos_radiologicos": _clean_text(data.get("hallazgos_radiologicos") or data.get("hallazgos") or text),
        "advertencias": warnings,
        "necesita_revision": bool(data.get("necesita_revision", True)),
        "metodo": _clean_text(data.get("metodo") or "ia"),
    }


def extract_information_from_text(
    text: str,
    templates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Extrae:
    - plantilla sugerida
    - información secundaria
    - hallazgos radiológicos separados

    Regla: esta función NO genera informe final.
    """
    templates = templates or []
    raw = _clean_text(text)

    if not raw:
        return {
            "plantilla_sugerida": {"id": None, "nombre": "", "confianza": "baja", "motivo": "Texto vacío."},
            "informacion_secundaria": {},
            "hallazgos_radiologicos": "",
            "advertencias": ["No hay texto para analizar."],
            "necesita_revision": True,
            "metodo": "vacio",
        }

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _heuristic_extract(raw, templates)

    template_brief = []
    for tpl in templates[:80]:
        template_brief.append(
            {
                "id": tpl.get("id"),
                "nombre": tpl.get("nombre") or tpl.get("name") or tpl.get("title") or tpl.get("titulo"),
            }
        )

    prompt = f"""
Eres un extractor estructurado para dictado radiológico.

TAREA:
Separar información desde el texto bruto, sin generar informe final.

Debes devolver SOLO JSON válido con esta estructura:
{{
  "plantilla_sugerida": {{
    "id": null,
    "nombre": "",
    "confianza": "alta|media|baja",
    "motivo": ""
  }},
  "informacion_secundaria": {{
    "paciente_nombre_completo": "",
    "edad": "",
    "sexo": "",
    "ocupacion_lugar_trabajo": "",
    "institucion_lugar": "",
    "motivo_examen": "",
    "antecedentes": ""
  }},
  "hallazgos_radiologicos": "",
  "advertencias": [],
  "necesita_revision": true,
  "metodo": "ia"
}}

REGLAS:
- No inventes datos.
- Si no sabes un campo, déjalo vacío.
- La plantilla sugerida debe elegirse desde la lista si hay coincidencia.
- La plantilla es importante: intenta inferirla desde palabras como TC, RM, ecografía, tórax, TAP, rodilla, etc.
- No generes informe final.
- No mezcles información secundaria como si fuera hallazgo radiológico.
- Los hallazgos radiológicos deben contener solo lo descrito sobre el examen.

PLANTILLAS DISPONIBLES:
{json.dumps(template_brief, ensure_ascii=False)}

TEXTO BRUTO:
{raw}
""".strip()

    try:
        from openai import OpenAI

        model = os.getenv("OPENAI_MODEL") or os.getenv("IAD_AI_MODEL_TEMPLATE_IMPORT") or "gpt-4o-mini"
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Devuelve exclusivamente JSON válido. No agregues markdown."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content or ""
        data = _extract_json_object(content)
        if not data:
            fallback = _heuristic_extract(raw, templates)
            fallback["advertencias"].append("La IA no devolvió JSON válido; se usó extracción heurística.")
            return fallback
        return _normalize_extraction(data, raw, templates)
    except Exception as exc:
        fallback = _heuristic_extract(raw, templates)
        fallback["advertencias"].append(f"Falló extracción IA; se usó heurística. Error: {exc}")
        return fallback
