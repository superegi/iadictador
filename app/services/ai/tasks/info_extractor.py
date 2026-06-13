from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def _s(value: Any) -> str:
    return str(value or "").strip()


def _json_from_text(text: str) -> dict[str, Any]:
    raw = _s(text)
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    return {}


def collect_template_candidates() -> list[dict[str, Any]]:
    """
    Recolecta plantillas desde archivos locales.
    Es deliberadamente tolerante: solo necesita nombre para sugerir plantilla.
    """
    roots = [
        Path("report_templates"),
        Path("app/report_templates"),
        Path("data/report_templates"),
        Path("/data/report_templates"),
    ]

    out: list[dict[str, Any]] = []
    seen = set()

    for root in roots:
        if not root.exists():
            continue

        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".txt", ".md", ".json", ".html"}:
                continue

            name = path.stem.replace("_", " ").replace("-", " ").strip()
            if not name:
                continue

            key = name.lower()
            if key in seen:
                continue
            seen.add(key)

            content = ""
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")[:1000]
            except Exception:
                content = ""

            out.append(
                {
                    "id": None,
                    "nombre": name,
                    "path": str(path),
                    "contenido_preview": content,
                }
            )

    return out


def _score_template(text: str, template: dict[str, Any]) -> int:
    hay = text.lower()
    name = _s(template.get("nombre")).lower()
    preview = _s(template.get("contenido_preview")).lower()

    score = 0

    if name and name in hay:
        score += 120

    for token in re.split(r"[^a-záéíóúñ0-9]+", name):
        if len(token) >= 3 and token in hay:
            score += 12

    synonyms = {
        "tc torax": ["tc de torax", "tc tórax", "tac torax", "tac tórax", "pulmon", "pulmonar", "mediastino"],
        "torax": ["torax", "tórax", "pulmon", "pulmonar", "mediastino"],
        "tap": ["tap", "torax abdomen pelvis", "tórax abdomen pelvis", "tc tap", "tac tap"],
        "abdomen": ["abdomen", "higado", "hígado", "vesicula", "vesícula", "pancreas", "páncreas", "renal"],
        "pelvis": ["pelvis", "pelvico", "pélvico", "uterino", "ovario", "vesical"],
        "rodilla": ["rodilla", "menisco", "ligamento", "cruzado", "lca", "lcp"],
        "columna": ["columna", "lumbar", "cervical", "dorsal", "hernia", "disco"],
        "cerebro": ["cerebro", "encéfalo", "encefalo", "cráneo", "craneo", "parénquima cerebral"],
        "angio": ["angio", "aneurisma", "estenosis", "oclusion", "oclusión", "diseccion", "disección"],
        "ecografia": ["ecografia", "ecografía", "ultrasonido", "eco"],
        "mamografia": ["mamografia", "mamografía", "mama", "birads", "bi-rads"],
    }

    combined = f"{name} {preview}"

    for key, words in synonyms.items():
        if key in combined:
            for word in words:
                if word in hay:
                    score += 18

    return score


def suggest_template(text: str, templates: list[dict[str, Any]]) -> dict[str, Any]:
    if not templates:
        return {
            "id": None,
            "nombre": "",
            "confianza": "baja",
            "motivo": "No se encontraron plantillas locales para comparar.",
        }

    scored = sorted(
        ((_score_template(text, tpl), tpl) for tpl in templates),
        key=lambda item: item[0],
        reverse=True,
    )

    score, tpl = scored[0]
    if score >= 80:
        confianza = "alta"
    elif score >= 25:
        confianza = "media"
    else:
        confianza = "baja"

    return {
        "id": tpl.get("id"),
        "nombre": _s(tpl.get("nombre")),
        "confianza": confianza,
        "motivo": f"Sugerencia por coincidencia con texto dictado. Puntaje: {score}.",
    }


def heuristic_extract(text: str, templates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    templates = templates or []
    raw = _s(text)
    norm = " ".join(raw.split())

    edad = ""
    m = re.search(r"\b(\d{1,3})\s*(?:años|a[ñn]os|a)\b", norm, re.I)
    if m:
        edad = m.group(1)

    paciente = ""
    patterns = [
        r"\bpaciente\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+){1,4})",
        r"\b(?:nombre|se llama)\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+){1,4})",
    ]
    for pat in patterns:
        m = re.search(pat, norm, re.I)
        if m:
            paciente = m.group(1).strip(" ,.;:")
            break

    sexo = ""
    if re.search(r"\b(masculino|hombre|var[oó]n)\b", norm, re.I):
        sexo = "masculino"
    elif re.search(r"\b(femenino|mujer)\b", norm, re.I):
        sexo = "femenino"

    ocupacion = ""
    m = re.search(r"\b(?:trabaja como|trabajador(?:a)?|ocupaci[oó]n|profesi[oó]n)\s+([^,.;&]{3,90})", norm, re.I)
    if m:
        ocupacion = m.group(1).strip(" ,.;:")

    institucion = ""
    m = re.search(r"\b(?:hospital|cl[ií]nica|sanatorio|instituci[oó]n)\s+([A-ZÁÉÍÓÚÑ][^,.;&]{3,90})", norm)
    if m:
        institucion = m.group(0).strip(" ,.;:")

    motivo = ""
    m = re.search(r"\b(?:motivo|indicaci[oó]n|por|sospecha de|control de)\s+([^.;]{4,160})", norm, re.I)
    if m:
        motivo = m.group(1).strip(" ,.;:")

    antecedentes = ""
    m = re.search(r"\b(?:antecedente(?:s)? de|antecedente)\s+([^.;]{4,180})", norm, re.I)
    if m:
        antecedentes = m.group(1).strip(" ,.;:")

    plantilla = suggest_template(norm, templates)

    return {
        "plantilla_sugerida": plantilla,
        "informacion_secundaria": {
            "paciente_nombre_completo": paciente,
            "edad": edad,
            "sexo": sexo,
            "ocupacion_lugar_trabajo": ocupacion,
            "institucion_lugar": institucion,
            "motivo_examen": motivo,
            "antecedentes": antecedentes,
        },
        "hallazgos_radiologicos": norm,
        "advertencias": ["Extracción preliminar. Revisar antes de procesar informe final."],
        "necesita_revision": True,
        "metodo": "heuristico",
    }


def normalize_extraction(data: dict[str, Any], text: str, templates: list[dict[str, Any]]) -> dict[str, Any]:
    plantilla = data.get("plantilla_sugerida") or {}
    if not isinstance(plantilla, dict):
        plantilla = {}

    info = data.get("informacion_secundaria") or {}
    if not isinstance(info, dict):
        info = {}

    if not _s(plantilla.get("nombre")):
        plantilla = suggest_template(text, templates)

    warnings = data.get("advertencias") or []
    if isinstance(warnings, str):
        warnings = [warnings]
    if not isinstance(warnings, list):
        warnings = []

    return {
        "plantilla_sugerida": {
            "id": plantilla.get("id"),
            "nombre": _s(plantilla.get("nombre") or plantilla.get("titulo") or plantilla.get("name")),
            "confianza": _s(plantilla.get("confianza") or plantilla.get("confidence") or "baja"),
            "motivo": _s(plantilla.get("motivo") or plantilla.get("reason")),
        },
        "informacion_secundaria": {
            "paciente_nombre_completo": _s(info.get("paciente_nombre_completo") or info.get("paciente") or info.get("nombre_paciente")),
            "edad": _s(info.get("edad")),
            "sexo": _s(info.get("sexo")),
            "ocupacion_lugar_trabajo": _s(info.get("ocupacion_lugar_trabajo") or info.get("ocupacion") or info.get("lugar_trabajo")),
            "institucion_lugar": _s(info.get("institucion_lugar") or info.get("institucion") or info.get("lugar")),
            "motivo_examen": _s(info.get("motivo_examen") or info.get("motivo")),
            "antecedentes": _s(info.get("antecedentes")),
        },
        "hallazgos_radiologicos": _s(data.get("hallazgos_radiologicos") or data.get("hallazgos") or text),
        "advertencias": warnings,
        "necesita_revision": bool(data.get("necesita_revision", True)),
        "metodo": _s(data.get("metodo") or "ia"),
    }


def extract_information_from_text(text: str, templates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    raw = _s(text)
    templates = templates or collect_template_candidates()

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
        return heuristic_extract(raw, templates)

    template_brief = [
        {"id": t.get("id"), "nombre": t.get("nombre")}
        for t in templates[:120]
    ]

    prompt = f"""
Eres un extractor estructurado para dictado radiológico.

No debes generar informe final.

Devuelve SOLO JSON válido con esta estructura:
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

Reglas:
- No inventes datos.
- Si un dato no está mencionado, déjalo vacío.
- La plantilla sugerida debe inferirse desde el texto y desde la lista de plantillas.
- Los datos del paciente, edad, ocupación, institución, motivo y antecedentes van en información secundaria.
- Los hallazgos radiológicos van separados.
- No mezcles información secundaria como hallazgo.
- No redactes informe final.

Plantillas disponibles:
{json.dumps(template_brief, ensure_ascii=False)}

Texto bruto:
{raw}
""".strip()

    try:
        from openai import OpenAI

        model = os.getenv("OPENAI_MODEL") or os.getenv("IAD_AI_MODEL_TEMPLATE_IMPORT") or "gpt-4o-mini"
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Devuelve exclusivamente JSON válido, sin markdown."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        content = resp.choices[0].message.content or ""
        parsed = _json_from_text(content)

        if not parsed:
            out = heuristic_extract(raw, templates)
            out["advertencias"].append("La IA no devolvió JSON válido. Se usó extracción heurística.")
            return out

        return normalize_extraction(parsed, raw, templates)

    except Exception as exc:
        out = heuristic_extract(raw, templates)
        out["advertencias"].append(f"Falló extracción IA. Se usó heurística. Error: {exc}")
        return out
