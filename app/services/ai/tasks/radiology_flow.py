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


def _db_rows(db, sql: str, params: dict[str, Any] | None = None):
    if db is None:
        return []

    try:
        from sqlalchemy import text as sa_text
        return db.execute(sa_text(sql), params or {}).fetchall()
    except Exception:
        return []


def _column_score_for_content(col: str) -> int:
    c = col.lower()
    score = 0

    if c in {
        "contenido",
        "content",
        "texto",
        "texto_base",
        "body",
        "template",
        "plantilla",
        "report_text",
        "informe",
        "texto_informe",
        "texto_plantilla",
        "template_text",
    }:
        score += 100

    if any(k in c for k in ("contenido", "content", "texto", "body", "informe", "template", "plantilla")):
        score += 30

    if any(k in c for k in ("created", "updated", "fecha", "id", "nombre", "name", "titulo", "title")):
        score -= 80

    return score


def _best_content_from_row(colnames: list[str], row_values: tuple[Any, ...]) -> str:
    """
    Algunas tablas no tienen el nombre esperado del campo de texto.
    Elegimos el campo textual largo más probable.
    """
    candidates = []

    for col, val in zip(colnames, row_values):
        txt = s(val)
        if not txt:
            continue

        score = _column_score_for_content(col)
        score += min(len(txt), 5000) // 20

        if len(txt) < 30:
            score -= 30

        candidates.append((score, col, txt))

    if not candidates:
        return ""

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][2]


def collect_templates_from_db(db) -> list[dict[str, Any]]:
    if db is None:
        return []

    tables = _db_rows(db, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    out: list[dict[str, Any]] = []

    for row in tables:
        table = row[0]
        table_l = table.lower()

        if not any(k in table_l for k in ("template", "plantilla", "macro")):
            continue

        cols = _db_rows(db, f'PRAGMA table_info("{table}")')
        colnames = [c[1] for c in cols]

        if not colnames:
            continue

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

        if not name_col:
            continue

        modality_col = None
        for candidate in ("modalidad", "modality"):
            if candidate in colnames:
                modality_col = candidate
                break

        type_col = None
        for candidate in ("tipo", "type", "tipo_informe", "report_type", "categoria", "category"):
            if candidate in colnames:
                type_col = candidate
                break

        tags_col = None
        for candidate in ("tags", "etiquetas", "keywords", "palabras_clave"):
            if candidate in colnames:
                tags_col = candidate
                break

        # Traemos columnas completas para elegir mejor el texto largo.
        quoted_cols = ", ".join(f'"{c}"' for c in colnames)
        sql = f'''
            SELECT {quoted_cols}
            FROM "{table}"
            ORDER BY "{name_col}"
            LIMIT 1000
        '''

        rows = _db_rows(db, sql)

        for r in rows:
            row_map = dict(zip(colnames, r))

            name = s(row_map.get(name_col))
            if not name:
                continue

            content = _best_content_from_row(colnames, r)

            # Si el mejor campo terminó siendo el nombre, limpiar.
            if noacc(content) == noacc(name):
                content = ""

            out.append(
                {
                    "id": row_map.get(id_col) if id_col else None,
                    "nombre": name,
                    "contenido": content,
                    "modalidad": s(row_map.get(modality_col)) if modality_col else "",
                    "tipo": s(row_map.get(type_col)) if type_col else "",
                    "tags": s(row_map.get(tags_col)) if tags_col else "",
                    "origen": f"db:{table}",
                    "tabla": table,
                }
            )

    seen = set()
    clean = []

    for item in out:
        key = noacc(item.get("nombre"))
        if key and key not in seen:
            seen.add(key)
            clean.append(item)

    return clean


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

            content = ""
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass

            out.append(
                {
                    "id": None,
                    "nombre": name,
                    "contenido": content,
                    "modalidad": "",
                    "tipo": "",
                    "tags": "",
                    "origen": f"file:{path}",
                    "path": str(path),
                }
            )

    return out


def collect_templates(db=None) -> list[dict[str, Any]]:
    items = collect_templates_from_db(db) + collect_templates_from_files()

    seen = set()
    clean = []

    for item in items:
        key = noacc(item.get("nombre"))
        if key and key not in seen:
            seen.add(key)
            clean.append(item)

    return clean


def template_score(raw_text: str, template: dict[str, Any]) -> int:
    text = noacc(raw_text)
    name = noacc(template.get("nombre"))
    modalidad = noacc(template.get("modalidad"))
    tipo = noacc(template.get("tipo"))
    tags = noacc(template.get("tags"))
    content = noacc(template.get("contenido"))[:2500]

    combined = f"{name} {modalidad} {tipo} {tags} {content}"

    score = 0

    if name and name in text:
        score += 220

    for token in name.split():
        if len(token) >= 3 and token in text:
            score += 18

    text_flags = {
        "ct": any(x in text for x in ["tc", "tac", "tomografia", "tomografia computada"]),
        "torax": any(x in text for x in ["torax", "toracico", "toracica", "pulmon", "pulmonar"]),
        "abdomen": any(x in text for x in ["abdomen", "abdominal", "higado", "hepat", "vesicula", "pancreas"]),
        "pelvis": any(x in text for x in ["pelvis", "pelvico", "pelvica", "utero", "uterino", "ovario", "vejiga"]),
        "contraste": any(x in text for x in ["cc", "contraste", "contrastado", "con contraste"]),
        "rm": any(x in text for x in ["rm", "resonancia", "magnetica"]),
        "eco": any(x in text for x in ["ecografia", "ecografico", "ultrasonido", "eco"]),
        "mamografia": any(x in text for x in ["mamografia", "mamaria", "mama", "birads", "bi rads"]),
        "rodilla": any(x in text for x in ["rodilla", "menisco", "cruzado", "lca", "lcp"]),
    }

    tpl_flags = {
        "ct": any(x in combined for x in ["tc", "tac", "tomografia", "tomografia computada"]),
        "torax": any(x in combined for x in ["torax", "toracico", "pulmon"]),
        "abdomen": any(x in combined for x in ["abdomen", "abdominal", "higado", "vesicula", "pancreas"]),
        "pelvis": any(x in combined for x in ["pelvis", "pelvico", "utero", "ovario", "vejiga"]),
        "contraste": any(x in combined for x in ["cc", "contraste", "contrastado", "con contraste"]),
        "tap": any(x in combined for x in ["tap", "torax abdomen pelvis", "torax abdomen y pelvis"]),
        "rm": any(x in combined for x in ["rm", "resonancia", "magnetica"]),
        "eco": any(x in combined for x in ["ecografia", "ecografico", "ultrasonido", "eco"]),
        "mamografia": any(x in combined for x in ["mamografia", "mamaria", "mama", "birads", "bi rads"]),
        "rodilla": any(x in combined for x in ["rodilla", "menisco", "cruzado", "lca", "lcp"]),
    }

    if text_flags["ct"] and text_flags["torax"] and text_flags["abdomen"] and text_flags["pelvis"]:
        if tpl_flags["tap"] or (
            tpl_flags["ct"] and tpl_flags["torax"] and tpl_flags["abdomen"] and tpl_flags["pelvis"]
        ):
            score += 350

    pairs = [
        ("ct", 45),
        ("torax", 65),
        ("abdomen", 65),
        ("pelvis", 65),
        ("contraste", 25),
        ("rm", 60),
        ("eco", 60),
        ("mamografia", 60),
        ("rodilla", 60),
    ]

    for key, weight in pairs:
        if text_flags[key] and tpl_flags[key]:
            score += weight

    if text_flags["torax"] and text_flags["abdomen"] and text_flags["pelvis"]:
        if tpl_flags["torax"] and not tpl_flags["abdomen"] and not tpl_flags["pelvis"]:
            score -= 90
        if tpl_flags["abdomen"] and not tpl_flags["torax"] and not tpl_flags["pelvis"]:
            score -= 90
        if tpl_flags["pelvis"] and not tpl_flags["torax"] and not tpl_flags["abdomen"]:
            score -= 90

    return score


def suggest_template(text: str, templates: list[dict[str, Any]]) -> dict[str, Any]:
    if not templates:
        return {
            "id": None,
            "nombre": "",
            "confianza": "baja",
            "motivo": "No hay plantillas disponibles.",
            "origen": "",
            "contenido": "",
        }

    ranked = sorted(
        ((template_score(text, tpl), tpl) for tpl in templates),
        key=lambda item: item[0],
        reverse=True,
    )

    score, best = ranked[0]

    if score >= 200:
        confianza = "alta"
    elif score >= 70:
        confianza = "media"
    else:
        confianza = "baja"

    return {
        "id": best.get("id"),
        "nombre": s(best.get("nombre")),
        "confianza": confianza,
        "motivo": f"Sugerida por coincidencia radiológica. Puntaje: {score}. Origen: {best.get('origen', '')}",
        "origen": best.get("origen", ""),
        "contenido": s(best.get("contenido")),
        "modalidad": s(best.get("modalidad")),
        "tipo": s(best.get("tipo")),
        "tags": s(best.get("tags")),
    }


def is_normal_request(text: str) -> bool:
    t = noacc(text)

    normal_patterns = [
        "informe normal",
        "examen normal",
        "normal",
        "sin hallazgos",
        "sin hallazgos patologicos",
        "sin alteraciones",
        "sin alteraciones significativas",
        "sin hallazgos patologicos significativos",
        "no hay hallazgos",
        "todo normal",
    ]

    positive_markers = [
        "nodulo",
        "masa",
        "lesion",
        "derrame",
        "neumotorax",
        "condensacion",
        "atelectasia",
        "adenopatia",
        "hidronefrosis",
        "litiasis",
        "coleccion",
        "fractura",
        "estenosis",
        "aneurisma",
        "trombo",
        "oclusion",
    ]

    has_normal = any(p in t for p in normal_patterns)
    has_positive = any(p in t for p in positive_markers)

    return has_normal and not has_positive


def heuristic_hallazgos(text: str) -> str:
    raw = " ".join(s(text).split())

    if is_normal_request(raw):
        return "Informe normal. Sin hallazgos patológicos significativos."

    patterns = [
        r"\b(vamos a dictar|vamos a revisar|siguiente paciente|quiero usar|vamos a ocupar|ocupar una plantilla de|usar una plantilla de)\b",
        r"\b(plantilla de|tomograf[ií]a computada de|tc de|tac de)\s+[^.。;]+[.;]?",
        r"\b(el|la)?\s*paciente\s+[^.。;]{1,80}?(?:tiene|presenta|con)\b",
    ]

    out = raw
    for pat in patterns:
        out = re.sub(pat, " ", out, flags=re.I)

    out = re.sub(r"\s+", " ", out).strip(" ,.;:")

    return out or raw


def analyze_radiology(text: str, db=None) -> dict[str, Any]:
    raw = s(text)
    templates = collect_templates(db)

    if not raw:
        return {
            "ok": False,
            "error": "texto_vacio",
            "plantilla_sugerida": {},
            "hallazgos_radiologicos": "",
            "advertencias": ["No hay texto/audio transcrito para analizar."],
            "metodo": "vacio",
        }

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    suggested = suggest_template(raw, templates)

    if not api_key:
        return {
            "ok": True,
            "plantilla_sugerida": suggested,
            "hallazgos_radiologicos": heuristic_hallazgos(raw),
            "advertencias": ["Análisis heurístico. Revisar hallazgos antes de generar informe."],
            "metodo": "heuristico",
        }

    template_brief = [
        {
            "id": t.get("id"),
            "nombre": t.get("nombre"),
            "modalidad": t.get("modalidad"),
            "tipo": t.get("tipo"),
            "tags": t.get("tags"),
            "origen": t.get("origen"),
        }
        for t in templates[:180]
    ]

    prompt = f"""
Eres un asistente de dictado radiológico.

TAREA:
Desde el texto dictado, debes:
1. Sugerir la plantilla radiológica más adecuada.
2. Extraer SOLO hallazgos radiológicos.
3. No extraer datos administrativos ni paciente/edad/ocupación.
4. No generar informe final todavía.

Devuelve SOLO JSON válido:
{{
  "plantilla_sugerida": {{
    "id": null,
    "nombre": "",
    "confianza": "alta|media|baja",
    "motivo": ""
  }},
  "hallazgos_radiologicos": "",
  "advertencias": [],
  "metodo": "ia_radiologia"
}}

Reglas:
- La transcripción visible es un producto intermedio, no el objetivo final.
- Si el usuario dice "tomografía computada de tórax, abdomen y pelvis", sugiere una plantilla TC TAP / TC tórax abdomen pelvis si existe.
- Si el usuario dice que el informe/examen está normal, los hallazgos deben indicar examen normal, sin resumir todavía la plantilla.
- Hallazgos radiológicos: conservar medidas, lateralidad, localización y características.
- No incluyas frases administrativas como "siguiente paciente", "paciente Juan Pérez", "tiene diez años", etc.
- No inventes hallazgos.
- No generes informe final.

PLANTILLAS DISPONIBLES:
{json.dumps(template_brief, ensure_ascii=False)}

TEXTO DICTADO:
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
            return {
                "ok": True,
                "plantilla_sugerida": suggested,
                "hallazgos_radiologicos": heuristic_hallazgos(raw),
                "advertencias": ["La IA no devolvió JSON válido. Se usó análisis heurístico."],
                "metodo": "heuristico_por_json_invalido",
            }

        ai_tpl = parsed.get("plantilla_sugerida") or {}
        if not isinstance(ai_tpl, dict):
            ai_tpl = {}

        if not s(ai_tpl.get("nombre")) or (
            s(ai_tpl.get("confianza")).lower() == "baja" and suggested.get("confianza") in {"alta", "media"}
        ):
            ai_tpl = suggested

        warnings = parsed.get("advertencias") or []
        if isinstance(warnings, str):
            warnings = [warnings]
        if not isinstance(warnings, list):
            warnings = []

        hallazgos = s(parsed.get("hallazgos_radiologicos") or parsed.get("hallazgos") or heuristic_hallazgos(raw))
        if is_normal_request(raw):
            hallazgos = "Informe normal. Sin hallazgos patológicos significativos."

        return {
            "ok": True,
            "plantilla_sugerida": {
                "id": ai_tpl.get("id"),
                "nombre": s(ai_tpl.get("nombre") or ai_tpl.get("titulo") or ai_tpl.get("name")),
                "confianza": s(ai_tpl.get("confianza") or ai_tpl.get("confidence") or suggested.get("confianza")),
                "motivo": s(ai_tpl.get("motivo") or ai_tpl.get("reason") or suggested.get("motivo")),
                "contenido": suggested.get("contenido", ""),
                "origen": suggested.get("origen", ""),
                "modalidad": suggested.get("modalidad", ""),
                "tipo": suggested.get("tipo", ""),
                "tags": suggested.get("tags", ""),
            },
            "hallazgos_radiologicos": hallazgos,
            "advertencias": warnings,
            "metodo": s(parsed.get("metodo") or "ia_radiologia"),
        }

    except Exception as exc:
        return {
            "ok": True,
            "plantilla_sugerida": suggested,
            "hallazgos_radiologicos": heuristic_hallazgos(raw),
            "advertencias": [f"Falló IA radiológica. Se usó heurística. Error: {exc}"],
            "metodo": "heuristico_por_error",
        }


def find_template_by_name_or_id(db, template_name: str = "", template_id: str = "") -> dict[str, Any]:
    templates = collect_templates(db)

    if template_id:
        for tpl in templates:
            if s(tpl.get("id")) == s(template_id):
                return tpl

    target = noacc(template_name)

    if target:
        for tpl in templates:
            if noacc(tpl.get("nombre")) == target:
                return tpl

        for tpl in templates:
            tpl_name = noacc(tpl.get("nombre"))
            if target in tpl_name or tpl_name in target:
                return tpl

        # Fallback por score contra nombre solicitado.
        ranked = sorted(
            ((template_score(template_name, tpl), tpl) for tpl in templates),
            key=lambda item: item[0],
            reverse=True,
        )
        if ranked and ranked[0][0] > 50:
            return ranked[0][1]

    return {}


def _template_text_or_title(template: dict[str, Any], template_name: str = "") -> str:
    content = s(template.get("contenido"))
    title = s(template.get("nombre") or template_name)

    if content:
        # Si el contenido no trae título, anteponerlo.
        if title and noacc(title) not in noacc(content[:200]):
            return f"{title}\n\n{content}".strip()
        return content.strip()

    return title.strip()



def sanitize_template_for_generation(template_text: str, hallazgos: str = "") -> str:
    """
    Limpia la plantilla antes de generar informe.

    Objetivo:
    - eliminar marcas internas tipo xxxxx / VESICULA / ORGANOsexual
    - eliminar opciones alternativas que no fueron dictadas
    - conservar la plantilla normal completa
    """
    raw = s(template_text)
    h = noacc(hallazgos)

    if not raw:
        return ""

    keep_lines = []
    lines = raw.splitlines()

    # Flags de hallazgos dictados.
    mentions_vesicula_absent = any(
        x in h
        for x in [
            "vesicula no visualizada",
            "no se visualiza vesicula",
            "vesicula ausente",
            "colecistectomia",
            "colecistectomizado",
            "sin vesicula",
        ]
    )

    mentions_nephrolithiasis = any(
        x in h
        for x in [
            "litiasis",
            "nefrolitiasis",
            "calculo",
            "calculos",
            "piedra",
            "piedras",
        ]
    )

    mentions_diverticula = any(
        x in h
        for x in [
            "diverticulo",
            "diverticulos",
            "diverticulosis",
        ]
    )

    mentions_uterus = any(
        x in h
        for x in [
            "utero",
            "uterino",
            "uterina",
            "anexial",
            "anexiales",
            "ovario",
            "ovarios",
        ]
    )

    mentions_prostate = any(
        x in h
        for x in [
            "prostata",
            "prostatico",
            "prostatica",
        ]
    )

    for line in lines:
        original = line.rstrip()
        stripped = original.strip()
        n = noacc(stripped)

        if not stripped:
            keep_lines.append("")
            continue

        # Eliminar separadores/marcadores internos.
        if "xxxxx" in n:
            continue

        if "vesiculabiliar" in n or "vesicula biliar" == n:
            continue

        if "organosexual" in n or n == "organo sexual":
            continue

        # Eliminar líneas de plantilla que son opciones alternativas no seleccionadas.
        # Vesícula:
        if "vesicula biliar no visualizada" in n or "vesicula no visualizada" in n:
            if not mentions_vesicula_absent:
                continue

        if "vesicula biliar en replecion parcial" in n:
            if mentions_vesicula_absent:
                continue

        # Litiasis renal opcional:
        if any(x in n for x in ["nefrolitiasis", "litiasis no obstructiva", "litiasis renal"]):
            if not mentions_nephrolithiasis:
                continue

        # Divertículos opcionales:
        if any(x in n for x in ["diverticulos", "diverticulosis"]):
            if not mentions_diverticula:
                continue

        # Bloque sexual: por defecto conservar próstata normal y remover útero si no se dictó.
        if "utero en anteversion" in n or "utero no visualizado" in n:
            if not mentions_uterus:
                continue

        # Si se dictó útero, eliminar próstata normal salvo que también se mencione próstata.
        if mentions_uterus and not mentions_prostate:
            if "prostata de estructura" in n or "prostata homogenea" in n:
                continue

        # Si no se dictó próstata aumentada, eliminar opción de próstata aumentada.
        if "prostata homogenea" in n and "aumento" in n:
            if not mentions_prostate:
                continue

        keep_lines.append(original)

    cleaned = "\n".join(keep_lines)

    # Limpiar saltos excesivos.
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")

    return cleaned.strip()


def has_positive_findings(hallazgos: str) -> bool:
    h = noacc(hallazgos)
    if not h:
        return False

    if is_normal_request(h):
        return False

    positive_markers = [
        "nodulo",
        "masa",
        "lesion",
        "litiasis",
        "nefrolitiasis",
        "calculo",
        "calculos",
        "hidronefrosis",
        "derrame",
        "neumotorax",
        "condensacion",
        "atelectasia",
        "adenopatia",
        "coleccion",
        "fractura",
        "estenosis",
        "aneurisma",
        "trombo",
        "oclusion",
        "utero no visualizado",
        "vesicula no visualizada",
        "no se observa utero",
        "no se visualiza utero",
    ]

    return any(marker in h for marker in positive_markers)


def build_heuristic_impression(hallazgos: str) -> str:
    """
    Fallback determinístico para impresión diagnóstica.
    La IA puede mejorar esto, pero nunca debe faltar impresión si hay hallazgos.
    """
    h_raw = s(hallazgos)
    h = noacc(h_raw)

    impressions = []

    if any(x in h for x in ["litiasis", "nefrolitiasis", "calculo", "calculos"]):
        side = ""
        if "izquierda" in h or "izquierdo" in h:
            side = "izquierda"
        elif "derecha" in h or "derecho" in h:
            side = "derecha"
        elif "bilateral" in h or "bilaterales" in h:
            side = "bilateral"

        obstructive = "no obstructiva" if "no obstructiva" in h or "no obstructivo" in h else ""

        phrase = "Litiasis"
        if side:
            phrase += f" {side}"
        if obstructive:
            phrase += f" {obstructive}"
        phrase += "."
        impressions.append(phrase)

    if "nodulo" in h and ("pulmon" in h or "pulmonar" in h):
        # Mantener medida si está clara.
        m = re.search(r"(\d+(?:[,.]\d+)?)\s*mm", h_raw, flags=re.I)
        if m:
            impressions.append(f"Nódulo pulmonar de {m.group(1)} mm.")
        else:
            impressions.append("Nódulo pulmonar.")

    if any(x in h for x in ["lesion hepatica", "lesion focal hepatica", "hepatic"]):
        impressions.append("Lesión hepática focal.")

    if any(x in h for x in ["utero no visualizado", "no se observa utero", "no se visualiza utero"]):
        impressions.append("Útero no visualizado.")

    if any(x in h for x in ["vesicula no visualizada", "no se visualiza vesicula", "vesicula ausente"]):
        impressions.append("Vesícula biliar no visualizada.")

    if not impressions:
        cleaned = h_raw.strip()
        if cleaned:
            # Último fallback: usar hallazgo como impresión, limpiando frases administrativas.
            cleaned = re.sub(r"(?i)^hallazgos?:", "", cleaned).strip(" .;:")
            impressions.append(cleaned + ".")

    # Dedupe conservando orden.
    seen = set()
    out = []
    for item in impressions:
        key = noacc(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())

    return " ".join(out).strip()


def remove_normal_impression_lines(report: str) -> str:
    lines = report.splitlines()
    out = []

    normal_patterns = [
        "examen sin hallazgos patologicos significativos",
        "sin hallazgos patologicos significativos",
        "examen normal",
        "informe normal",
    ]

    for line in lines:
        n = noacc(line)
        if any(p in n for p in normal_patterns):
            continue
        out.append(line)

    cleaned = "\n".join(out)
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    return cleaned.strip()


def strip_existing_impression_block(report: str) -> str:
    """
    Elimina una impresión diagnóstica final previa para reemplazarla por una nueva.
    Conservador: corta desde el último título de impresión si aparece cerca del final.
    """
    raw = s(report)
    if not raw:
        return ""

    patterns = [
        r"\n\s*Impresi[oó]n diagn[oó]stica\s*:?\s*\n",
        r"\n\s*Conclusi[oó]n\s*:?\s*\n",
    ]

    last_start = -1
    last_match = None

    for pat in patterns:
        for m in re.finditer(pat, raw, flags=re.I):
            if m.start() > last_start:
                last_start = m.start()
                last_match = m

    if last_match and last_start > len(raw) * 0.55:
        return raw[:last_start].strip()

    return raw.strip()


def append_diagnostic_impression(report: str, impression: str, use_heading: bool = False) -> str:
    body = strip_existing_impression_block(report)
    impression = s(impression).strip()

    if not impression:
        return body

    if use_heading:
        final = f"{body.rstrip()}\n\nImpresión diagnóstica:\n{impression}"
    else:
        final = f"{body.rstrip()}\n\n{impression}"

    while "\n\n\n" in final:
        final = final.replace("\n\n\n", "\n\n")

    return final.strip()


def ensure_diagnostic_impression(report: str, hallazgos: str, api_key: str = "") -> str:
    """
    Segunda pasada:
    - si normal: no fuerza impresión patológica.
    - si hay hallazgos positivos: elimina impresión normal y agrega impresión diagnóstica.
    """
    report = s(report)
    hallazgos = s(hallazgos)

    if not report:
        return report

    if not has_positive_findings(hallazgos):
        return report

    report_without_normal = remove_normal_impression_lines(report)

    heuristic = build_heuristic_impression(hallazgos)

    if not api_key:
        return append_diagnostic_impression(report_without_normal, heuristic, use_heading=False)

    prompt = f"""
Eres radiólogo. Debes crear una impresión diagnóstica breve a partir de los hallazgos dictados y del informe ya integrado.

REGLAS:
- No inventes hallazgos.
- No incluyas datos administrativos.
- No repitas todo el informe.
- Máximo 2 frases.
- Si hay litiasis izquierda no obstructiva, la impresión debe decir eso de forma breve.
- Devuelve solo la impresión diagnóstica, sin título.

HALLAZGOS DICTADOS:
{hallazgos}

INFORME INTEGRADO:
{report_without_normal}
""".strip()

    try:
        from openai import OpenAI

        model = os.getenv("OPENAI_MODEL") or os.getenv("IAD_AI_MODEL_TEMPLATE_IMPORT") or "gpt-4o-mini"
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Genera una impresión diagnóstica breve, sin inventar hallazgos."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.05,
        )
        impression = s(resp.choices[0].message.content)
        if not impression:
            impression = heuristic

        return append_diagnostic_impression(report_without_normal, impression, use_heading=False)

    except Exception:
        return append_diagnostic_impression(report_without_normal, heuristic, use_heading=False)


def consistency_second_pass(report: str, hallazgos: str, api_key: str = "") -> str:
    """
    Segunda lectura de consistencia interna.
    Por ahora hace:
    - asegurar impresión diagnóstica cuando hay hallazgos positivos.
    - evitar impresión normal si hay hallazgos positivos.
    """
    checked = ensure_diagnostic_impression(report, hallazgos, api_key=api_key)

    # Limpieza menor de espacios.
    checked = re.sub(r"[ \t]+\n", "\n", checked)
    while "\n\n\n" in checked:
        checked = checked.replace("\n\n\n", "\n\n")

    return checked.strip()

def generate_report_from_template(
    hallazgos: str,
    template_name: str = "",
    template_id: str = "",
    db=None,
) -> dict[str, Any]:
    hallazgos = s(hallazgos)
    template = find_template_by_name_or_id(db, template_name=template_name, template_id=template_id)

    template_title = s(template.get("nombre") or template_name)
    template_text = _template_text_or_title(template, template_name=template_name)
    template_text = sanitize_template_for_generation(template_text, hallazgos=hallazgos)

    if not hallazgos:
        return {
            "ok": False,
            "error": "hallazgos_vacios",
            "informe_final": "",
            "advertencias": ["No hay hallazgos radiológicos para procesar."],
        }

    if not template_text:
        template_text = template_title or "[Plantilla no encontrada]"

    normal = is_normal_request(hallazgos)

    # Regla central: si es normal y tenemos plantilla, no resumir. Devolver plantilla completa.
    if normal and len(template_text) > 80 and "[Plantilla sin contenido" not in template_text:
        return {
            "ok": True,
            "informe_final": consistency_second_pass(template_text.strip(), hallazgos, api_key=os.getenv("OPENAI_API_KEY", "").strip()),
            "advertencias": [],
            "metodo": "plantilla_normal_completa",
            "plantilla_usada": {
                "id": template.get("id"),
                "nombre": template_title,
                "origen": template.get("origen", ""),
            },
        }

    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        if normal:
            final = template_text.strip()
        else:
            final = (
                f"{template_text.strip()}\n\n"
                f"Hallazgos dictados para integrar:\n{hallazgos}"
            ).strip()

        return {
            "ok": True,
            "informe_final": consistency_second_pass(final, hallazgos, api_key=""),
            "advertencias": ["Sin OPENAI_API_KEY. No hubo integración inteligente de hallazgos positivos."],
            "metodo": "fallback_sin_ia",
            "plantilla_usada": {
                "id": template.get("id"),
                "nombre": template_title,
                "origen": template.get("origen", ""),
            },
        }

    prompt = f"""
Eres un radiólogo asistente que edita informes desde una plantilla base.

TAREA:
Modificar la plantilla base usando los hallazgos radiológicos dictados.

REGLAS ESTRICTAS:
- La plantilla base manda.
- No redactes desde cero si hay plantilla.
- No resumas la plantilla.
- No conviertas una plantilla larga en una frase corta.
- No reincorpores líneas marcadas como xxxxx, separadores internos ni opciones alternativas eliminadas.
- Si el hallazgo solo menciona un nódulo pulmonar pequeño, modifica la línea pulmonar correspondiente y conserva el resto normal.
- No agregues nefrolitiasis, divertículos, vesícula no visualizada, útero o próstata aumentada si no fueron dictados explícitamente.
- Conserva todos los párrafos normales de la plantilla cuando no sean contradichos.
- Si los hallazgos indican informe normal / examen normal / sin hallazgos, devuelve la plantilla normal completa, sin recortar.
- Modifica solo lo que contradicen los hallazgos explícitos.
- Agrega hallazgos positivos con redacción radiológica limpia.
- No inventes hallazgos.
- No agregues datos administrativos.
- No menciones que usaste IA.
- Entrega solo el informe final, sin explicación.
- Prohibido incluir basura de plantilla: APENAPEN, LITIASISLITIASIS, xxxxx o delimitadores internos.
- Si el dictado dice mujer/femenino o menciona útero/anexos/ovarios, elimina próstata y vesículas seminales.
- Si el dictado dice hombre/masculino o menciona próstata, elimina útero/anexos/ovarios salvo que el dictado los mencione como ausencia/anomalía específica.
- Si hay cardiomegalia, no puede quedar “Corazón de tamaño normal”.
- Si hay derrame pleural, no puede quedar “No hay derrame pleural”.
- Si hay un hallazgo positivo, elimina frases normales que lo contradigan.
- No agregues frases globales inventadas tipo “sin otros hallazgos agudos”.
- La impresión diagnóstica no debe duplicarse.
- Después de integrar hallazgos, asegúrate de que exista una impresión diagnóstica final si hay hallazgos positivos.
- Si hay hallazgos positivos, no mantengas una impresión normal como “Examen sin hallazgos patológicos significativos”.
- La impresión debe ser breve y derivada solo de los hallazgos dictados.

PLANTILLA BASE:
{template_text}

HALLAZGOS RADIOLOGICOS DICTADOS:
{hallazgos}
""".strip()

    try:
        from openai import OpenAI

        model = os.getenv("OPENAI_MODEL") or os.getenv("IAD_AI_MODEL_TEMPLATE_IMPORT") or "gpt-4o-mini"
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "Edita informes radiológicos usando una plantilla base completa. No resumas. No inventes hallazgos.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )

        final = s(resp.choices[0].message.content)

        # Defensa: si el resultado es sospechosamente corto y el caso era normal, usar plantilla completa.
        if normal and len(final) < max(120, len(template_text) * 0.5):
            final = template_text.strip()

        return {
            "ok": True,
            "informe_final": consistency_second_pass(final, hallazgos, api_key=api_key),
            "advertencias": [],
            "metodo": "ia_plantilla_completa",
            "plantilla_usada": {
                "id": template.get("id"),
                "nombre": template_title,
                "origen": template.get("origen", ""),
            },
        }

    except Exception as exc:
        if normal:
            final = template_text.strip()
        else:
            final = (
                f"{template_text.strip()}\n\n"
                f"Hallazgos dictados para integrar:\n{hallazgos}"
            ).strip()

        return {
            "ok": True,
            "informe_final": consistency_second_pass(final, hallazgos, api_key=""),
            "advertencias": [f"Falló generación IA. Se usó fallback. Error: {exc}"],
            "metodo": "fallback_error_ia",
            "plantilla_usada": {
                "id": template.get("id"),
                "nombre": template_title,
                "origen": template.get("origen", ""),
            },
        }


# IAD_MODEL_GUARDRAILS_V4
# Guardrails duros para salida radiológica:
# - limpieza de marcadores/basura de plantillas
# - coherencia anatómica sexo-específica
# - corrección de contradicciones obvias
# - impresión diagnóstica sin duplicados

def iad_guard_context_from_text(text: str) -> dict:
    raw = s(text)
    h = noacc(raw)

    female = any(x in h for x in [
        "mujer",
        "femenina",
        "sexo femenino",
        "paciente femenina",
        "utero",
        "uterino",
        "uterina",
        "anexo",
        "anexial",
        "anexiales",
        "ovario",
        "ovarios",
        "no tiene utero",
        "sin utero",
        "ausencia de utero",
        "utero no visualizado",
        "no se observa utero",
        "no se visualiza utero",
    ])

    male = any(x in h for x in [
        "hombre",
        "varon",
        "masculino",
        "sexo masculino",
        "paciente masculino",
        "prostata",
        "prostatico",
        "prostatica",
        "vesiculas seminales",
    ])

    uterus_absent = any(x in h for x in [
        "no tiene utero",
        "sin utero",
        "ausencia de utero",
        "utero ausente",
        "utero no visualizado",
        "no se observa utero",
        "no se visualiza utero",
    ])

    return {
        "female": bool(female and not male),
        "male": bool(male and not female),
        "uterus_absent": bool(uterus_absent),
    }


def iad_guard_has_positive_findings(text: str) -> bool:
    h = noacc(text)

    if not h:
        return False

    if is_normal_request(h):
        return False

    positives = [
        "litiasis",
        "nefrolitiasis",
        "calculo",
        "calculos",
        "hidronefrosis",
        "hidroureteronefrosis",
        "dilatacion pielocaliciaria",
        "fractura",
        "ausencia del rinon",
        "rinon ausente",
        "derrame pleural",
        "ginecomastia",
        "cardiomegalia",
        "nodulo",
        "masa",
        "lesion",
        "aneurisma",
        "estenosis",
        "oclusion",
        "trombo",
        "coleccion",
        "neumotorax",
        "condensacion",
        "atelectasia",
    ]

    return any(x in h for x in positives)


def iad_guard_is_garbage_line(line: str) -> bool:
    raw = s(line)
    h = noacc(raw)

    if not raw:
        return False

    if "xxxx" in raw.lower() or "xxxxx" in raw.lower():
        return True

    compact = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", raw).upper()

    repeated_markers = [
        "APEN",
        "LITIASIS",
        "VESICULA",
        "VESICULABILIAR",
        "ORGANOSEXUAL",
    ]

    for marker in repeated_markers:
        if compact.count(marker) >= 2:
            return True

    if re.fullmatch(r"[Xx\s._\-]{6,}", raw):
        return True

    # Líneas internas de control de plantilla.
    if any(x in h for x in [
        "organosexual",
        "organo sexual",
        "vesiculabiliar",
        "litiasislitiasis",
        "apenapen",
    ]):
        return True

    return False


def iad_guard_clean_context_markers(report: str) -> str:
    lines = []

    for line in str(report or "").splitlines():
        n = noacc(line)

        if "contexto no informar" in n:
            continue

        if "contexto_no_informar" in n:
            continue

        lines.append(line)

    return "\n".join(lines).strip()


def iad_guard_apply_basic_contradictions(line: str, context_text: str) -> str:
    raw = str(line or "")
    h = noacc(context_text)

    out = raw

    # Cardiomegalia: nunca dejar "corazón normal".
    if any(x in h for x in ["cardiomegalia", "corazon aumentado", "aumento del tamano cardiaco"]):
        out = re.sub(
            r"Coraz[oó]n\s+de\s+tama[nñ]o\s+normal\.?",
            "Corazón de tamaño aumentado.",
            out,
            flags=re.I,
        )

    # Derrame pleural dictado: no conservar negación.
    if "derrame pleural" in h and not any(x in h for x in ["no hay derrame pleural", "no se observa derrame pleural", "sin derrame pleural"]):
        if re.search(r"^\s*No hay derrame pleural\.?\s*$", out, flags=re.I):
            if "bilateral" in h:
                if "leve" in h:
                    out = "Leve derrame pleural bilateral."
                else:
                    out = "Derrame pleural bilateral."
            elif "izquierd" in h:
                out = "Derrame pleural izquierdo."
            elif "derech" in h:
                out = "Derrame pleural derecho."
            else:
                out = "Derrame pleural."

    return out


def iad_guard_template_clean_lines(text: str, context_text: str = "") -> list[str]:
    ctx = iad_guard_context_from_text(context_text)
    out = []

    for line in str(text or "").splitlines():
        raw = line.rstrip()
        n = noacc(raw)

        if iad_guard_is_garbage_line(raw):
            continue

        # No mantener frases globales inventadas o demasiado amplias.
        if any(n.startswith(x) for x in [
            "sin otros hallazgos",
            "no se identifican otros hallazgos",
            "no se observan otros hallazgos",
            "sin hallazgos tomograficos agudos",
            "sin otros hallazgos tomograficos",
        ]):
            continue

        # Coherencia sexo-específica.
        if ctx["female"]:
            if any(x in n for x in [
                "prostata",
                "vesiculas seminales",
                "vesicula seminal",
                "prostatic",
            ]):
                continue

        if ctx["male"]:
            if any(x in n for x in [
                "utero",
                "uterino",
                "uterina",
                "ovario",
                "ovarios",
                "anexial",
                "anexiales",
            ]):
                continue

        raw = iad_guard_apply_basic_contradictions(raw, context_text)
        out.append(raw)

    return out


def iad_guard_insert_female_pelvis_if_needed(lines: list[str], context_text: str) -> list[str]:
    ctx = iad_guard_context_from_text(context_text)

    if not ctx["female"]:
        return lines

    joined = noacc("\n".join(lines))

    # Si ya hay línea uterina o ausencia uterina, no agregar.
    if any(x in joined for x in [
        "utero",
        "ausencia de utero",
        "sin utero",
        "masas anexiales",
        "anexiales",
    ]):
        return lines

    if ctx["uterus_absent"]:
        pelvis_line = "Útero no visualizado. No se observan masas anexiales."
    else:
        pelvis_line = "Útero normal. No hay masas anexiales."

    inserted = False
    out = []

    for line in lines:
        out.append(line)

        if not inserted and "vejiga" in noacc(line):
            out.append(pelvis_line)
            inserted = True

    if not inserted:
        out.append(pelvis_line)

    return out


def iad_guard_clean_template_text(template_text: str, context_text: str = "") -> str:
    lines = iad_guard_template_clean_lines(template_text, context_text)
    lines = iad_guard_insert_female_pelvis_if_needed(lines, context_text)

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)

    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")

    return cleaned.strip()


def iad_guard_redundant_impression_line(line_norm: str, previous_norms: list[str]) -> bool:
    if not line_norm:
        return True

    if line_norm in previous_norms:
        return True

    previous_joined = " ".join(previous_norms)

    if line_norm in previous_joined:
        return True

    # Si una línea nueva solo repite hallazgos ya listados en frases previas.
    key_terms = [
        "cardiomegalia",
        "derrame pleural",
        "ginecomastia",
        "litiasis",
        "hidroureteronefrosis",
        "fractura",
        "ausencia del rinon",
        "nodulo pulmonar",
    ]

    hits = [term for term in key_terms if term in line_norm]

    if hits and all(term in previous_joined for term in hits):
        return True

    return False


def iad_guard_clean_impression(report: str, context_text: str) -> str:
    raw = str(report or "").strip()

    if not raw:
        return ""

    matches = list(re.finditer(r"\n\s*Impresi[oó]n(?:\s+diagn[oó]stica)?\s*:?\s*\n", raw, flags=re.I))

    if not matches:
        return raw

    m = matches[-1]
    head = raw[:m.end()].rstrip()
    tail = raw[m.end():].strip()

    positive = iad_guard_has_positive_findings(context_text)

    clean_lines = []
    seen_norms = []

    for line in tail.splitlines():
        stripped = line.strip()

        if not stripped:
            continue

        n = noacc(stripped)

        if iad_guard_is_garbage_line(stripped):
            continue

        if positive and any(x in n for x in [
            "examen normal",
            "informe normal",
            "examen abdominal normal",
            "sin hallazgos patologicos significativos",
            "sin hallazgos agudos",
            "sin otros hallazgos",
        ]):
            continue

        # Útero ausente / próstata no deberían dominar la impresión si son contexto anatómico.
        if any(x in n for x in [
            "utero no visualizado",
            "ausencia de utero",
            "sin utero",
            "prostata",
            "vesiculas seminales",
        ]):
            continue

        if iad_guard_redundant_impression_line(n, seen_norms):
            continue

        clean_lines.append(stripped)
        seen_norms.append(n)

    if not clean_lines:
        # Si no queda impresión útil, eliminar encabezado vacío.
        return raw[:m.start()].strip()

    final = head + "\n" + "\n".join(clean_lines)

    while "\n\n\n" in final:
        final = final.replace("\n\n\n", "\n\n")

    return final.strip()


def iad_guard_enforce_final_report(report: str, hallazgos: str = "", template_name: str = "", template_text: str = "") -> str:
    context_text = " ".join([s(hallazgos), s(template_name), s(template_text)])

    report = iad_guard_clean_context_markers(report)

    lines = iad_guard_template_clean_lines(report, context_text)
    lines = iad_guard_insert_female_pelvis_if_needed(lines, context_text)

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)

    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")

    cleaned = iad_guard_clean_impression(cleaned, context_text)

    return cleaned.strip()


def iad_guard_prompt_extra() -> str:
    return """
REGLAS DURAS ADICIONALES:
- Prohibido incluir basura de plantilla: APENAPEN, LITIASISLITIASIS, xxxxx o delimitadores internos.
- Si el dictado dice mujer/femenino o menciona útero/anexos/ovarios, elimina próstata y vesículas seminales.
- Si el dictado dice hombre/masculino o menciona próstata, elimina útero/anexos/ovarios salvo que el dictado los mencione como ausencia/anomalía específica.
- Si hay cardiomegalia, no puede quedar "Corazón de tamaño normal".
- Si hay derrame pleural, no puede quedar "No hay derrame pleural".
- Si hay un hallazgo positivo, elimina frases normales que lo contradigan.
- No agregues frases globales inventadas tipo "sin otros hallazgos agudos".
- La impresión diagnóstica no debe duplicarse.
- La impresión debe contener solo hallazgos relevantes, no datos anatómicos contextuales como útero ausente salvo que sea el objetivo clínico.
""".strip()


# Sobrescribir sanitizador previo, si existía.
_IAD_GUARD_ORIG_SANITIZE_TEMPLATE_V4 = globals().get("sanitize_template_for_generation")

def sanitize_template_for_generation(template_text: str, hallazgos: str = "") -> str:
    raw = template_text

    if _IAD_GUARD_ORIG_SANITIZE_TEMPLATE_V4:
        try:
            raw = _IAD_GUARD_ORIG_SANITIZE_TEMPLATE_V4(template_text, hallazgos=hallazgos)
        except TypeError:
            raw = _IAD_GUARD_ORIG_SANITIZE_TEMPLATE_V4(template_text)
        except Exception:
            raw = template_text

    return iad_guard_clean_template_text(raw, hallazgos)


# Wrapper de análisis: conserva sexo como contexto no imprimible y corrige contenido cruzado de plantilla.
_IAD_GUARD_ORIG_ANALYZE_RADIOLOGY_V4 = globals().get("analyze_radiology")

def analyze_radiology(text: str, db=None) -> dict:
    if not _IAD_GUARD_ORIG_ANALYZE_RADIOLOGY_V4:
        return {"ok": False, "error": "analyze_radiology_original_missing"}

    result = _IAD_GUARD_ORIG_ANALYZE_RADIOLOGY_V4(text, db=db)

    try:
        ctx = iad_guard_context_from_text(text)

        if isinstance(result, dict) and result.get("ok"):
            result["contexto_no_informable"] = ctx

            hall = s(result.get("hallazgos_radiologicos"))

            # Mantener sexo para generación, pero marcado como no imprimible.
            if ctx["female"] and "sexo femenino" not in noacc(hall):
                hall = "[CONTEXTO_NO_INFORMAR: sexo femenino]. " + hall

            if ctx["male"] and "sexo masculino" not in noacc(hall):
                hall = "[CONTEXTO_NO_INFORMAR: sexo masculino]. " + hall

            result["hallazgos_radiologicos"] = hall.strip()

            # Corregir contenido cruzado de plantilla sugerida.
            tpl = result.get("plantilla_sugerida") or {}

            if isinstance(tpl, dict) and db is not None:
                matched = find_template_by_name_or_id(
                    db,
                    template_name=s(tpl.get("nombre")),
                    template_id=s(tpl.get("id")),
                )

                if matched:
                    tpl["id"] = matched.get("id")
                    tpl["nombre"] = s(matched.get("nombre") or tpl.get("nombre"))
                    tpl["contenido"] = s(matched.get("contenido"))
                    tpl["origen"] = matched.get("origen", tpl.get("origen", ""))
                    tpl["modalidad"] = s(matched.get("modalidad", tpl.get("modalidad", "")))
                    tpl["tipo"] = s(matched.get("tipo", tpl.get("tipo", "")))
                    tpl["tags"] = s(matched.get("tags", tpl.get("tags", "")))

                result["plantilla_sugerida"] = tpl

    except Exception as exc:
        try:
            warnings = result.setdefault("advertencias", [])
            warnings.append(f"Guardrail analyze warning: {exc}")
        except Exception:
            pass

    return result


# Wrapper de generación: postprocesa salida final siempre.
_IAD_GUARD_ORIG_GENERATE_REPORT_V4 = globals().get("generate_report_from_template")

def generate_report_from_template(
    hallazgos: str,
    template_name: str = "",
    template_id: str = "",
    db=None,
) -> dict:
    if not _IAD_GUARD_ORIG_GENERATE_REPORT_V4:
        return {"ok": False, "error": "generate_report_from_template_original_missing", "informe_final": ""}

    result = _IAD_GUARD_ORIG_GENERATE_REPORT_V4(
        hallazgos=hallazgos,
        template_name=template_name,
        template_id=template_id,
        db=db,
    )

    try:
        template_text = ""

        if db is not None:
            matched = find_template_by_name_or_id(
                db,
                template_name=template_name,
                template_id=template_id,
            )

            if matched:
                template_text = s(matched.get("contenido"))

        if isinstance(result, dict) and result.get("informe_final"):
            result["informe_final"] = iad_guard_enforce_final_report(
                result.get("informe_final", ""),
                hallazgos=hallazgos,
                template_name=template_name,
                template_text=template_text,
            )

            result.setdefault("guardrails", {})
            result["guardrails"]["v4"] = True

    except Exception as exc:
        try:
            warnings = result.setdefault("advertencias", [])
            warnings.append(f"Guardrail final warning: {exc}")
        except Exception:
            pass

    return result
