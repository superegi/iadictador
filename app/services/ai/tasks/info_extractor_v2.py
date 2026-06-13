from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any


def s(value: Any) -> str:
    return str(value or "").strip()


def noacc(text: str) -> str:
    text = s(text).lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def json_from_text(text: str) -> dict[str, Any]:
    raw = s(text)
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
        try:
            data = json.loads(raw[start : end + 1])
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    return {}


def collect_templates_from_files() -> list[dict[str, Any]]:
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
            key = noacc(name)
            if not key or key in seen:
                continue
            seen.add(key)

            preview = ""
            try:
                preview = path.read_text(encoding="utf-8", errors="ignore")[:1200]
            except Exception:
                pass

            out.append(
                {
                    "id": None,
                    "nombre": name,
                    "origen": "archivo",
                    "path": str(path),
                    "contenido_preview": preview,
                }
            )

    return out


def collect_templates_from_db(db) -> list[dict[str, Any]]:
    if db is None:
        return []

    try:
        from sqlalchemy import text as sa_text
    except Exception:
        return []

    out: list[dict[str, Any]] = []

    try:
        tables = db.execute(
            sa_text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ).fetchall()
    except Exception:
        return []

    for row in tables:
        table = row[0]
        table_l = table.lower()

        if not any(k in table_l for k in ("template", "plantilla", "macro")):
            continue

        try:
            cols = db.execute(sa_text(f'PRAGMA table_info("{table}")')).fetchall()
        except Exception:
            continue

        colnames = [c[1] for c in cols]

        id_col = "id" if "id" in colnames else None

        name_col = None
        for candidate in (
            "nombre",
            "name",
            "titulo",
            "title",
            "template_name",
            "descripcion",
            "description",
        ):
            if candidate in colnames:
                name_col = candidate
                break

        body_col = None
        for candidate in (
            "contenido",
            "content",
            "texto",
            "body",
            "template",
            "plantilla",
            "report_text",
            "informe",
        ):
            if candidate in colnames:
                body_col = candidate
                break

        modality_col = None
        for candidate in ("modalidad", "modality", "tipo", "category", "categoria"):
            if candidate in colnames:
                modality_col = candidate
                break

        if not name_col:
            continue

        select_cols = []
        if id_col:
            select_cols.append(f'"{id_col}"')
        else:
            select_cols.append("NULL")

        select_cols.append(f'"{name_col}"')

        if body_col:
            select_cols.append(f'"{body_col}"')
        else:
            select_cols.append("NULL")

        if modality_col:
            select_cols.append(f'"{modality_col}"')
        else:
            select_cols.append("NULL")

        try:
            sql = f'''
                SELECT {", ".join(select_cols)}
                FROM "{table}"
                ORDER BY "{name_col}"
                LIMIT 500
            '''
            rows = db.execute(sa_text(sql)).fetchall()
        except Exception:
            continue

        for r in rows:
            name = s(r[1])
            if not name:
                continue
            out.append(
                {
                    "id": r[0],
                    "nombre": name,
                    "contenido_preview": s(r[2])[:1600],
                    "modalidad": s(r[3]),
                    "origen": f"db:{table}",
                }
            )

    # dedupe por nombre normalizado
    seen = set()
    clean = []
    for item in out:
        key = noacc(item.get("nombre"))
        if key and key not in seen:
            seen.add(key)
            clean.append(item)

    return clean


def collect_templates(db=None) -> list[dict[str, Any]]:
    db_templates = collect_templates_from_db(db)
    file_templates = collect_templates_from_files()

    all_items = db_templates + file_templates
    seen = set()
    clean = []

    for item in all_items:
        key = noacc(item.get("nombre"))
        if key and key not in seen:
            seen.add(key)
            clean.append(item)

    return clean


def template_score(raw_text: str, template: dict[str, Any]) -> int:
    text = noacc(raw_text)
    name = noacc(template.get("nombre"))
    modality = noacc(template.get("modalidad"))
    preview = noacc(template.get("contenido_preview"))

    combined = f"{name} {modality} {preview}"

    score = 0

    if name and name in text:
        score += 180

    for token in name.split():
        if len(token) >= 3 and token in text:
            score += 14

    # Normalizar sinónimos frecuentes del dictado médico.
    text_flags = {
        "ct": any(x in text for x in ["tc", "tac", "tomografia", "tomografia computada", "tomografica"]),
        "torax": any(x in text for x in ["torax", "toracico", "toracica", "pulmon", "pulmonar"]),
        "abdomen": "abdomen" in text or "abdominal" in text,
        "pelvis": "pelvis" in text or "pelvico" in text or "pelvica" in text,
        "contraste": any(x in text for x in ["cc", "contraste", "contrastado", "con contraste"]),
    }

    tpl_flags = {
        "ct": any(x in combined for x in ["tc", "tac", "tomografia", "tomografia computada"]),
        "torax": any(x in combined for x in ["torax", "toracico", "pulmon"]),
        "abdomen": "abdomen" in combined or "abdominal" in combined,
        "pelvis": "pelvis" in combined or "pelvico" in combined,
        "contraste": any(x in combined for x in ["cc", "contraste", "contrastado", "con contraste"]),
        "tap": any(x in combined for x in ["tap", "torax abdomen pelvis", "torax abdomen y pelvis"]),
    }

    # Caso clave: “tomografía computada de tórax, abdomen y pelvis”
    if text_flags["ct"] and text_flags["torax"] and text_flags["abdomen"] and text_flags["pelvis"]:
        if tpl_flags["tap"] or (tpl_flags["ct"] and tpl_flags["torax"] and tpl_flags["abdomen"] and tpl_flags["pelvis"]):
            score += 250

    if text_flags["ct"] and tpl_flags["ct"]:
        score += 40
    if text_flags["torax"] and tpl_flags["torax"]:
        score += 50
    if text_flags["abdomen"] and tpl_flags["abdomen"]:
        score += 50
    if text_flags["pelvis"] and tpl_flags["pelvis"]:
        score += 50
    if text_flags["contraste"] and tpl_flags["contraste"]:
        score += 20

    # Penalizar plantillas parciales si el texto pide TAP completo.
    if text_flags["torax"] and text_flags["abdomen"] and text_flags["pelvis"]:
        if tpl_flags["torax"] and not tpl_flags["abdomen"] and not tpl_flags["pelvis"]:
            score -= 60
        if tpl_flags["abdomen"] and not tpl_flags["torax"] and not tpl_flags["pelvis"]:
            score -= 60

    return score


def suggest_template(text: str, templates: list[dict[str, Any]]) -> dict[str, Any]:
    if not templates:
        return {
            "id": None,
            "nombre": "",
            "confianza": "baja",
            "motivo": "No se encontraron plantillas en base de datos ni archivos.",
        }

    ranked = sorted(
        ((template_score(text, tpl), tpl) for tpl in templates),
        key=lambda x: x[0],
        reverse=True,
    )

    score, tpl = ranked[0]

    if score >= 180:
        confianza = "alta"
    elif score >= 60:
        confianza = "media"
    else:
        confianza = "baja"

    return {
        "id": tpl.get("id"),
        "nombre": s(tpl.get("nombre")),
        "confianza": confianza,
        "motivo": f"Coincidencia con plantilla {tpl.get('origen', '')}. Puntaje: {score}.",
    }


def extract_patient_name(text: str) -> str:
    raw = " ".join(s(text).split())

    # Caso: "paciente Juan Pérez, tiene..."
    patterns = [
        r"\bpaciente\s+(.+?)(?=\s*(?:,|\.|;|\btiene\b|\bde\s+\d{1,3}\s*años\b|\bcon\b|\bpresenta\b|$))",
        r"\b(?:nombre|se llama)\s+(.+?)(?=\s*(?:,|\.|;|\btiene\b|\bde\s+\d{1,3}\s*años\b|\bcon\b|\bpresenta\b|$))",
    ]

    for pat in patterns:
        m = re.search(pat, raw, flags=re.I)
        if not m:
            continue

        candidate = m.group(1).strip(" ,.;:")

        # Limpiar introducciones residuales.
        candidate = re.sub(r"^(el|la|del|de la)\s+", "", candidate, flags=re.I).strip()

        words = candidate.split()
        if len(words) < 2:
            continue

        # Limitar a 2-4 palabras para no comerse frases largas.
        words = words[:4]
        cleaned = " ".join(words).strip(" ,.;:")

        # Evitar falsos positivos obvios.
        bad = {"tiene", "tomografia", "tomografía", "computada", "examen", "estudio"}
        if any(noacc(w) in bad for w in cleaned.split()):
            continue

        return cleaned

    return ""


def heuristic_extract(text: str, templates: list[dict[str, Any]]) -> dict[str, Any]:
    raw = s(text)
    norm = " ".join(raw.split())

    paciente = extract_patient_name(norm)

    edad = ""
    m = re.search(r"\b(\d{1,3})\s*(?:años|a[ñn]os)\b", norm, flags=re.I)
    if m:
        edad = m.group(1)

    sexo = ""
    if re.search(r"\b(masculino|hombre|var[oó]n)\b", norm, flags=re.I):
        sexo = "masculino"
    elif re.search(r"\b(femenino|mujer)\b", norm, flags=re.I):
        sexo = "femenino"

    ocupacion = ""
    m = re.search(
        r"\b(?:trabaja como|trabajador(?:a)?|ocupaci[oó]n|profesi[oó]n)\s+([^,.;&]{3,90})",
        norm,
        flags=re.I,
    )
    if m:
        ocupacion = m.group(1).strip(" ,.;:")

    institucion = ""
    m = re.search(
        r"\b(?:hospital|cl[ií]nica|sanatorio|instituci[oó]n)\s+([A-ZÁÉÍÓÚÑ][^,.;&]{3,90})",
        norm,
    )
    if m:
        institucion = m.group(0).strip(" ,.;:")

    motivo = ""
    m = re.search(
        r"\b(?:motivo|indicaci[oó]n|por|sospecha de|control de)\s+([^.;]{4,160})",
        norm,
        flags=re.I,
    )
    if m:
        motivo = m.group(1).strip(" ,.;:")

    antecedentes = ""
    m = re.search(
        r"\b(?:antecedente(?:s)? de|antecedente)\s+([^.;]{4,180})",
        norm,
        flags=re.I,
    )
    if m:
        antecedentes = m.group(1).strip(" ,.;:")

    return {
        "plantilla_sugerida": suggest_template(norm, templates),
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
        "metodo": "heuristico_v2",
    }


def normalize_ai(data: dict[str, Any], text: str, templates: list[dict[str, Any]]) -> dict[str, Any]:
    plantilla = data.get("plantilla_sugerida") or {}
    if not isinstance(plantilla, dict):
        plantilla = {}

    info = data.get("informacion_secundaria") or {}
    if not isinstance(info, dict):
        info = {}

    suggested = suggest_template(text, templates)

    # Si la IA no sugiere nada útil, usar heurística de plantilla.
    if not s(plantilla.get("nombre")):
        plantilla = suggested

    # Si la IA sugiere baja confianza pero heurística ve alta, usar heurística.
    if s(plantilla.get("confianza")).lower() == "baja" and suggested.get("confianza") in {"alta", "media"}:
        plantilla = suggested

    # Si la IA no detecta paciente, aplicar regex.
    paciente = s(info.get("paciente_nombre_completo") or info.get("paciente") or info.get("nombre_paciente"))
    if not paciente:
        paciente = extract_patient_name(text)

    warnings = data.get("advertencias") or []
    if isinstance(warnings, str):
        warnings = [warnings]
    if not isinstance(warnings, list):
        warnings = []

    return {
        "plantilla_sugerida": {
            "id": plantilla.get("id"),
            "nombre": s(plantilla.get("nombre") or plantilla.get("titulo") or plantilla.get("name")),
            "confianza": s(plantilla.get("confianza") or plantilla.get("confidence") or "baja"),
            "motivo": s(plantilla.get("motivo") or plantilla.get("reason")),
        },
        "informacion_secundaria": {
            "paciente_nombre_completo": paciente,
            "edad": s(info.get("edad")),
            "sexo": s(info.get("sexo")),
            "ocupacion_lugar_trabajo": s(info.get("ocupacion_lugar_trabajo") or info.get("ocupacion") or info.get("lugar_trabajo")),
            "institucion_lugar": s(info.get("institucion_lugar") or info.get("institucion") or info.get("lugar")),
            "motivo_examen": s(info.get("motivo_examen") or info.get("motivo")),
            "antecedentes": s(info.get("antecedentes")),
        },
        "hallazgos_radiologicos": s(data.get("hallazgos_radiologicos") or data.get("hallazgos") or text),
        "advertencias": warnings,
        "necesita_revision": bool(data.get("necesita_revision", True)),
        "metodo": s(data.get("metodo") or "ia_v2"),
    }


def extract_information_from_text_v2(text: str, db=None) -> dict[str, Any]:
    raw = s(text)
    templates = collect_templates(db)

    if not raw:
        return {
            "plantilla_sugerida": {
                "id": None,
                "nombre": "",
                "confianza": "baja",
                "motivo": "Texto vacío.",
            },
            "informacion_secundaria": {},
            "hallazgos_radiologicos": "",
            "advertencias": ["No hay texto para analizar."],
            "necesita_revision": True,
            "metodo": "vacio_v2",
        }

    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    # Si no hay API key, usar heurística robusta.
    if not api_key:
        return heuristic_extract(raw, templates)

    template_brief = [
        {
            "id": t.get("id"),
            "nombre": t.get("nombre"),
            "modalidad": t.get("modalidad", ""),
            "origen": t.get("origen", ""),
        }
        for t in templates[:160]
    ]

    prompt = f"""
Eres un extractor estructurado para dictado radiológico.

NO generes informe final.

Devuelve SOLO JSON válido:
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
  "metodo": "ia_v2"
}}

Reglas:
- Si el texto dice "paciente Juan Pérez, tiene..." debes extraer paciente_nombre_completo = "Juan Pérez".
- Si dice "tomografía computada de tórax, abdomen y pelvis", la plantilla probable es una TC de tórax abdomen pelvis / TC TAP.
- Usa la lista de plantillas disponibles.
- No inventes datos.
- Si falta un dato, deja string vacío.
- Información secundaria: paciente, edad, sexo, institución, trabajo, motivo, antecedentes.
- Hallazgos radiológicos: solo lo imagenológico.
- No generes informe final.

PLANTILLAS:
{json.dumps(template_brief, ensure_ascii=False)}

TEXTO:
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

        parsed = json_from_text(resp.choices[0].message.content or "")
        if not parsed:
            out = heuristic_extract(raw, templates)
            out["advertencias"].append("La IA no devolvió JSON válido. Se usó heurística v2.")
            return out

        return normalize_ai(parsed, raw, templates)

    except Exception as exc:
        out = heuristic_extract(raw, templates)
        out["advertencias"].append(f"Falló extracción IA. Se usó heurística v2. Error: {exc}")
        return out
