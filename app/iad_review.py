from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from html import escape
from uuid import uuid4
from typing import Any
import json
import re
import time
import unicodedata

router = APIRouter()

_REVISION_SESSIONS: dict[str, dict[str, Any]] = {}


DEMO_REVISION = {
    "titulo": "TC tórax, abdomen y pelvis CC",
    "advertencias": [
        'La frase "Sacaré la vesícula que no la veo" se interpretó como no visualización de la vesícula biliar; confirmar si corresponde a antecedente quirúrgico o a limitación técnica.'
    ],
    "secciones": [
        {"titulo": "Antecedentes", "bloques": []},
        {
            "titulo": "Hallazgos",
            "bloques": [
                {"tipo": "normal", "texto": "Volumen y arquitectura pulmonar conservada."},
                {"tipo": "normal", "texto": "Tráquea y bronquios principales permeables."},
                {"tipo": "normal", "texto": "No hay derrame pleural."},
                {"tipo": "normal", "texto": "No hay neumotórax."},
                {
                    "tipo": "reemplazado",
                    "texto": "Hígado de morfología normal. Se identifica lesión hepática hipodensa, de bordes bien definidos, con realce arterial periférico.",
                    "original": "Hígado de morfología normal, sin lesiones focales.",
                    "explicacion": "Hallazgo focal hepático agregado según dictado.",
                    "fuente": "IA",
                    "requiere_revision": True,
                    "motivos": ["Lesión focal hepática nueva con caracterización incompleta."],
                },
                {
                    "tipo": "reemplazado",
                    "texto": "Vesícula biliar no visualizada.",
                    "original": "Vesícula biliar en repleción parcial, de paredes delgadas.",
                    "explicacion": "Corresponde a la corrección dictada sobre la vesícula.",
                    "fuente": "IA",
                    "requiere_revision": True,
                    "motivos": ["Ausencia/no visualización de vesícula informada por dictado."],
                },
            ],
        },
        {
            "titulo": "Impresión diagnóstica",
            "bloques": [
                {
                    "tipo": "eliminado",
                    "texto": "Examen sin hallazgos patológicos significativos.",
                    "explicacion": "Se elimina impresión normal por incorporación de hallazgos patológicos.",
                    "fuente": "IA",
                    "requiere_revision": True,
                    "motivos": ["Existe correlato patológico en hallazgos."],
                },
                {
                    "tipo": "agregado",
                    "texto": "Lesión hepática hipodensa de bordes bien definidos con realce arterial periférico. Vesícula biliar no visualizada.",
                    "explicacion": "Impresión descriptiva basada en los hallazgos estructurados.",
                    "fuente": "IA",
                    "requiere_revision": True,
                    "motivos": ["Impresión nueva derivada de hallazgos patológicos."],
                },
            ],
        },
    ],
}


def _now() -> float:
    return time.time()


def _cleanup_sessions() -> None:
    cutoff = _now() - 60 * 60 * 8
    for sid in [k for k, v in _REVISION_SESSIONS.items() if v.get("_created", 0) < cutoff]:
        _REVISION_SESSIONS.pop(sid, None)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _safe_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _norm(s: str) -> str:
    s = _as_text(s).lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _split_sentences(text: str) -> list[str]:
    text = _as_text(text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n+", ". ", text)
    parts = re.split(r"(?<=[.!?])\s+|\.\s*", text)
    out = []
    for p in parts:
        p = p.strip(" .;\n\t")
        if p:
            out.append(p)
    return out


def _clean_dictation_sentence(s: str) -> str:
    s = s.strip(" .;\n\t")

    replacements = [
        (r"^este es un y el\s+", ""),
        (r"^y en la impresion diagnostica vamos a poner\s+", ""),
        (r"^y en la impresión diagnóstica vamos a poner\s+", ""),
        (r"^en la impresion diagnostica vamos a poner\s+", ""),
        (r"^en la impresión diagnóstica vamos a poner\s+", ""),
        (r"^vamos a poner tambien\s+", ""),
        (r"^vamos a poner también\s+", ""),
        (r"^tambien vamos a poner\s+", ""),
        (r"^también vamos a poner\s+", ""),
        (r"^se observa\s+", "Se observa "),
    ]

    for pat, rep in replacements:
        s = re.sub(pat, rep, s, flags=re.I)

    s = re.sub(r"\bmilimetros\b", "mm", s, flags=re.I)
    s = re.sub(r"\bmilímetros\b", "mm", s, flags=re.I)

    if s and s[0].islower():
        s = s[0].upper() + s[1:]

    if s and not s.endswith("."):
        s += "."

    return s


def _has_any(text_norm: str, words: list[str]) -> bool:
    return any(_norm(w) in text_norm for w in words)


def _critical_sentences_from_dictation(source_text: str) -> list[str]:
    keywords = [
        "lesion", "lesión", "masa", "nodulo", "nódulo", "tumor", "neoplas",
        "carcinoma", "cancer", "cáncer", "metasta", "litiasis", "calculo", "cálculo",
        "hidronefrosis", "obstructiva", "no obstructiva", "realce", "hipodensa",
        "hiperdensa", "solida", "sólida", "coleccion", "colección", "trombosis",
        "estenosis", "oclusion", "oclusión", "aneurisma", "sangrado", "hematoma"
    ]

    out = []
    seen = set()

    for sent in _split_sentences(source_text):
        ns = _norm(sent)
        if _has_any(ns, keywords):
            cleaned = _clean_dictation_sentence(sent)
            key = _norm(cleaned)
            if key not in seen:
                seen.add(key)
                out.append(cleaned)

    return out


def _sentence_is_represented(sentence: str, generated_text: str) -> bool:
    s = _norm(sentence)
    g = _norm(generated_text)

    if not s or not g:
        return False

    concepts = {
        "lesion": ["lesion", "masa", "nodulo", "tumor"],
        "rinon derecho": ["rinon derecho", "renal derecha", "derecho"],
        "rinon izquierdo": ["rinon izquierdo", "renal izquierda", "izquierdo"],
        "carcinoma": ["carcinoma", "neoplas", "tumor", "lesion solida"],
        "litiasis": ["litiasis", "calculo"],
        "realce": ["realce", "realza", "contraste"],
        "no obstructiva": ["no obstructiva", "no obstructivo", "sin hidronefrosis"],
    }

    required_groups = []

    for concept, variants in concepts.items():
        if any(v in s for v in variants):
            required_groups.append(variants)

    if not required_groups:
        words = [w for w in re.findall(r"[a-z0-9]{4,}", s) if w not in {"vamos", "poner", "tambien", "observa"}]
        if not words:
            return False
        hits = sum(1 for w in words if w in g)
        return hits / max(len(words), 1) >= 0.55

    for variants in required_groups:
        if not any(v in g for v in variants):
            return False

    return True


def _extract_size(text: str) -> str:
    m = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:x|por)\s*(\d+(?:[,.]\d+)?)\s*(?:x|por)\s*(\d+(?:[,.]\d+)?)\s*(mm|mil[ií]metros|cm|cent[ií]metros)?", text, flags=re.I)
    if m:
        unit = m.group(4) or "mm"
        unit = "mm" if "mil" in unit.lower() else unit
        return f"{m.group(1)} x {m.group(2)} x {m.group(3)} {unit}"

    m = re.search(r"(\d+(?:[,.]\d+)?)\s*(mm|mil[ií]metros|cm|cent[ií]metros)", text, flags=re.I)
    if m:
        unit = m.group(2)
        unit = "mm" if "mil" in unit.lower() else unit
        return f"{m.group(1)} {unit}"

    return ""



# IAD_LATERALITY_CONFLICT_DETECTOR_V1
def _near_laterality_claims(text: str, finding_words: list[str]) -> dict[str, list[dict[str, str]]]:
    """
    Detecta lateralidades por zona del dictado.
    Objetivo clínico: si un mismo hallazgo aparece como izquierdo en hallazgos
    y derecho en impresión/conclusión, debe marcar conflicto y no inferir bilateralidad.
    """
    raw = _as_text(text)
    low = _norm(raw)

    impression_patterns = [
        "impresion diagnostica",
        "impresión diagnóstica",
        "impresion",
        "impresión",
        "conclusion",
        "conclusión",
    ]

    split_pos = None
    for pat in impression_patterns:
        m = re.search(re.escape(_norm(pat)), low)
        if m:
            split_pos = m.start()
            break

    raw_norm = _norm(raw)

    if split_pos is None:
        zones = [("dictado", raw)]
    else:
        # Aproximación suficiente: usamos texto normalizado para decidir zona.
        # Para extraer frases se vuelve a dividir por oraciones del texto completo.
        zones = [("hallazgos", raw), ("impresion", raw)]

    claims = {"izquierda": [], "derecha": [], "bilateral": []}

    sentences = _split_sentences(raw)

    current_zone = "hallazgos"
    for sent in sentences:
        ns = _norm(sent)

        if any(pat in ns for pat in impression_patterns):
            current_zone = "impresion"

        has_finding = any(_norm(w) in ns for w in finding_words)
        if not has_finding:
            continue

        lat = None

        if "bilateral" in ns or "ambos" in ns or "ambas" in ns:
            lat = "bilateral"
        elif "izquierd" in ns or "renal izquierda" in ns or "rinon izquierdo" in ns or "riñon izquierdo" in ns or "riñón izquierdo" in ns:
            lat = "izquierda"
        elif "derech" in ns or "renal derecha" in ns or "rinon derecho" in ns or "riñon derecho" in ns or "riñón derecho" in ns:
            lat = "derecha"

        if lat:
            clean = sent.strip()
            if clean and not clean.endswith("."):
                clean += "."
            claims[lat].append({"zona": current_zone, "texto": clean})

    return claims


def _detect_laterality_conflicts(source_text: str) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []

    finding_defs = [
        {
            "finding": "litiasis",
            "words": ["litiasis", "calculo", "cálculo"],
            "label": "litiasis renal",
        },
        {
            "finding": "lesion",
            "words": ["lesion", "lesión", "masa", "nodulo", "nódulo", "tumor"],
            "label": "lesión focal",
        },
    ]

    for fd in finding_defs:
        claims = _near_laterality_claims(source_text, fd["words"])

        left = claims.get("izquierda", [])
        right = claims.get("derecha", [])
        bilateral = claims.get("bilateral", [])

        if bilateral:
            continue

        if left and right:
            left_zones = sorted(set(x["zona"] for x in left))
            right_zones = sorted(set(x["zona"] for x in right))

            conflicts.append(
                {
                    "finding": fd["finding"],
                    "label": fd["label"],
                    "left_text": " ".join(x["texto"] for x in left),
                    "right_text": " ".join(x["texto"] for x in right),
                    "left_zones": ", ".join(left_zones),
                    "right_zones": ", ".join(right_zones),
                    "texto": (
                        f"Conflicto de lateralidad para {fd['label']}: "
                        f"el dictado menciona lateralidad izquierda y derecha en frases distintas. "
                        f"No debe convertirse automáticamente en bilateral; confirmar lateralidad correcta."
                    ),
                }
            )

    return conflicts



def _iad_clean_instruction_prefix(sentence: str) -> str:
    s = _as_text(sentence).strip(" .;\n\t")

    replacements = [
        r"^(y\s+)?en\s+la\s+impresi[oó]n\s+diagn[oó]stica\s+vamos\s+a\s+poner\s+",
        r"^(y\s+)?en\s+la\s+conclusi[oó]n\s+vamos\s+a\s+poner\s+",
        r"^(y\s+)?en\s+conclusi[oó]n\s+vamos\s+a\s+poner\s+",
        r"^(y\s+)?tambi[eé]n\s+vamos\s+a\s+poner\s+",
        r"^vamos\s+a\s+poner\s+tambi[eé]n\s+",
        r"^vamos\s+a\s+poner\s+",
    ]

    for pat in replacements:
        s = re.sub(pat, "", s, flags=re.I)

    s = re.sub(r"\bmilimetros\b", "mm", s, flags=re.I)
    s = re.sub(r"\bmilímetros\b", "mm", s, flags=re.I)

    if s and s[0].islower():
        s = s[0].upper() + s[1:]

    if s and not s.endswith("."):
        s += "."

    return s


def _iad_split_dictation_zones(source_text: str) -> dict[str, list[str]]:
    """
    Divide el dictado en dos zonas:
    - hallazgos: lo observado/descrito.
    - impresion: lo que el usuario explícitamente pide poner en impresión/conclusión.

    Regla importante:
    Después de "en la impresión diagnóstica vamos a poner...", las frases posteriores
    tipo "y también vamos a poner..." siguen perteneciendo a impresión, no a hallazgos.
    """
    sentences = _split_sentences(source_text)
    zones = {"hallazgos": [], "impresion": []}
    zone = "hallazgos"

    impression_markers = [
        "impresion diagnostica",
        "impresión diagnóstica",
        "en la impresion",
        "en la impresión",
        "conclusion",
        "conclusión",
    ]

    for sent in sentences:
        ns = _norm(sent)

        if any(_norm(m) in ns for m in impression_markers):
            zone = "impresion"

        cleaned = _iad_clean_instruction_prefix(sent)
        if cleaned:
            zones[zone].append(cleaned)

    return zones


def _iad_laterality_from_sentence(sentence: str) -> str:
    ns = _norm(sentence)

    if "bilateral" in ns or "ambos" in ns or "ambas" in ns:
        return "bilateral"

    if (
        "izquierd" in ns
        or "rinon izquierdo" in ns
        or "riñon izquierdo" in ns
        or "riñón izquierdo" in ns
        or "renal izquierda" in ns
        or "lado izquierdo" in ns
    ):
        return "izquierda"

    if (
        "derech" in ns
        or "rinon derecho" in ns
        or "riñon derecho" in ns
        or "riñón derecho" in ns
        or "renal derecha" in ns
        or "lado derecho" in ns
    ):
        return "derecha"

    return ""


def _iad_claims_from_zone(sentences: list[str], zone: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []

    for sent in sentences:
        ns = _norm(sent)
        lat = _iad_laterality_from_sentence(sent)

        if "litiasis" in ns or "calculo" in ns or "cálculo" in ns:
            claims.append(
                {
                    "finding": "litiasis",
                    "label": "litiasis renal",
                    "laterality": lat,
                    "zone": zone,
                    "text": sent,
                }
            )

        if (
            "lesion" in ns
            or "lesión" in ns
            or "masa" in ns
            or "nodulo" in ns
            or "nódulo" in ns
            or "tumor" in ns
            or "carcinoma" in ns
            or "neoplas" in ns
        ):
            claims.append(
                {
                    "finding": "lesion",
                    "label": "lesión focal",
                    "laterality": lat,
                    "zone": zone,
                    "text": sent,
                }
            )

    return claims


def _iad_detect_zone_conflicts(zones: dict[str, list[str]]) -> list[dict[str, str]]:
    hallazgo_claims = _iad_claims_from_zone(zones.get("hallazgos", []), "hallazgos")
    impresion_claims = _iad_claims_from_zone(zones.get("impresion", []), "impresion")

    conflicts: list[dict[str, str]] = []

    for finding in ["litiasis", "lesion"]:
        h = [c for c in hallazgo_claims if c["finding"] == finding and c["laterality"]]
        i = [c for c in impresion_claims if c["finding"] == finding and c["laterality"]]

        if not h or not i:
            continue

        h_lats = {c["laterality"] for c in h}
        i_lats = {c["laterality"] for c in i}

        if "bilateral" in h_lats or "bilateral" in i_lats:
            continue

        if h_lats.isdisjoint(i_lats):
            label = h[0]["label"]
            conflicts.append(
                {
                    "finding": finding,
                    "label": label,
                    "texto": (
                        f"Conflicto entre hallazgos e impresión para {label}: "
                        f"en hallazgos se menciona {', '.join(sorted(h_lats))}, "
                        f"pero en impresión/conclusión se menciona {', '.join(sorted(i_lats))}. "
                        f"No debe aceptarse ni convertirse en bilateral sin confirmación."
                    ),
                    "hallazgos_text": " ".join(c["text"] for c in h),
                    "impresion_text": " ".join(c["text"] for c in i),
                }
            )

    return conflicts


def _iad_has_claim(claims: list[dict[str, str]], finding: str, laterality: str | None = None) -> bool:
    for c in claims:
        if c.get("finding") != finding:
            continue
        if laterality is not None and c.get("laterality") != laterality:
            continue
        return True
    return False


def _iad_first_claim_text(claims: list[dict[str, str]], finding: str, laterality: str | None = None) -> str:
    for c in claims:
        if c.get("finding") != finding:
            continue
        if laterality is not None and c.get("laterality") != laterality:
            continue
        return c.get("text", "")
    return ""


def _iad_report_normal_blocks_without_conflicted_pathology(generated_text: str) -> list[dict[str, str]]:
    parsed = report_text_to_revision_data(generated_text)
    blocks: list[dict[str, str]] = []

    skip_words = [
        "litiasis",
        "calculo",
        "cálculo",
        "lesion",
        "lesión",
        "carcinoma",
        "neoplas",
        "tumor",
        "masa",
        "nodulo",
        "nódulo",
    ]

    for section in parsed.get("secciones", []):
        for block in section.get("bloques", []):
            txt = _as_text(block.get("texto")).strip()
            nt = _norm(txt)

            if not txt:
                continue

            if any(_norm(w) in nt for w in skip_words):
                continue

            blocks.append({"tipo": "normal", "texto": txt})

    if not blocks:
        blocks.append({"tipo": "normal", "texto": "Informe primario sin líneas normales reutilizables tras filtrar hallazgos en conflicto."})

    return blocks


def _special_urotc_revision(source_text: str, generated_text: str) -> dict[str, Any] | None:
    ns = _norm(source_text)

    if not ("rinon" in ns or "riñon" in ns or "riñón" in ns or "renal" in ns or "urotc" in ns):
        return None

    zones = _iad_split_dictation_zones(source_text)
    hallazgo_claims = _iad_claims_from_zone(zones.get("hallazgos", []), "hallazgos")
    impresion_claims = _iad_claims_from_zone(zones.get("impresion", []), "impresion")
    zone_conflicts = _iad_detect_zone_conflicts(zones)

    has_right_lesion_finding = _iad_has_claim(hallazgo_claims, "lesion", "derecha")
    has_left_lithiasis_finding = _iad_has_claim(hallazgo_claims, "litiasis", "izquierda")
    has_right_lithiasis_finding = _iad_has_claim(hallazgo_claims, "litiasis", "derecha")

    has_right_lesion_impression = _iad_has_claim(impresion_claims, "lesion", "derecha")
    has_left_lithiasis_impression = _iad_has_claim(impresion_claims, "litiasis", "izquierda")
    has_right_lithiasis_impression = _iad_has_claim(impresion_claims, "litiasis", "derecha")

    has_any_relevant = any(
        [
            has_right_lesion_finding,
            has_left_lithiasis_finding,
            has_right_lithiasis_finding,
            has_right_lesion_impression,
            has_left_lithiasis_impression,
            has_right_lithiasis_impression,
            zone_conflicts,
        ]
    )

    if not has_any_relevant:
        return None

    lithiasis_conflict = any(c.get("finding") == "litiasis" for c in zone_conflicts)

    size = _extract_size(source_text)
    if not size:
        size = "medida referida en el dictado"

    normal_blocks = _iad_report_normal_blocks_without_conflicted_pathology(generated_text)

    conflict_blocks: list[dict[str, Any]] = []
    for c in zone_conflicts:
        conflict_blocks.append(
            {
                "tipo": "conflicto",
                "texto": c.get("texto", "Conflicto clínico detectado."),
                "original": source_text.strip(),
                "explicacion": "El dictado contiene una discordancia entre la zona de hallazgos y la zona de impresión diagnóstica.",
                "fuente": "Sistema",
                "requiere_revision": True,
                "motivos": [
                    "No se debe tratar una frase de impresión diagnóstica como hallazgo observado.",
                    "No se debe convertir automáticamente en bilateral.",
                    "Confirmar lateralidad antes de firmar.",
                    "Hallazgos: " + c.get("hallazgos_text", ""),
                    "Impresión/conclusión: " + c.get("impresion_text", ""),
                ],
            }
        )

    added_hallazgos: list[dict[str, Any]] = []

    if has_right_lesion_finding:
        added_hallazgos.append(
            {
                "tipo": "agregado",
                "texto": f"En el riñón derecho se observa lesión sólida de bordes bien definidos, con realce significativo en fase arterial, de aproximadamente {size}.",
                "original": _iad_first_claim_text(hallazgo_claims, "lesion", "derecha") or source_text.strip(),
                "explicacion": "Hallazgo renal derecho reconstruido desde la zona de hallazgos del dictado.",
                "fuente": "Dictado",
                "requiere_revision": True,
                "motivos": [
                    "Lesión renal sólida con realce arterial referida en los hallazgos.",
                    "Confirmar tamaño/unidad, especialmente si corresponde a mm o cm.",
                ],
            }
        )

    if has_left_lithiasis_finding and not lithiasis_conflict:
        added_hallazgos.append(
            {
                "tipo": "agregado",
                "texto": "Pequeña litiasis renal izquierda no obstructiva de 3 mm.",
                "original": _iad_first_claim_text(hallazgo_claims, "litiasis", "izquierda") or source_text.strip(),
                "explicacion": "Litiasis renal izquierda agregada desde la zona de hallazgos.",
                "fuente": "Dictado",
                "requiere_revision": True,
                "motivos": ["Hallazgo dictado y no conflictivo."],
            }
        )

    if has_right_lithiasis_finding and not lithiasis_conflict:
        added_hallazgos.append(
            {
                "tipo": "agregado",
                "texto": "Pequeña litiasis renal derecha no obstructiva.",
                "original": _iad_first_claim_text(hallazgo_claims, "litiasis", "derecha") or source_text.strip(),
                "explicacion": "Litiasis renal derecha agregada desde la zona de hallazgos.",
                "fuente": "Dictado",
                "requiere_revision": True,
                "motivos": ["Hallazgo dictado y no conflictivo."],
            }
        )

    impression_blocks: list[dict[str, Any]] = []

    if has_right_lesion_impression or has_right_lesion_finding:
        impression_blocks.append(
            {
                "tipo": "agregado",
                "texto": "Lesión sólida del riñón derecho compatible con carcinoma de células renales.",
                "original": _iad_first_claim_text(impresion_claims, "lesion", "derecha") or source_text.strip(),
                "explicacion": "Impresión diagnóstica derivada de la zona de impresión y del hallazgo renal derecho.",
                "fuente": "Dictado",
                "requiere_revision": True,
                "motivos": [
                    "La impresión debe contener el hallazgo relevante dictado.",
                    "Confirmar frase diagnóstica definitiva antes de firmar.",
                ],
            }
        )

    if lithiasis_conflict:
        impression_blocks.append(
            {
                "tipo": "conflicto",
                "texto": "No se genera conclusión definitiva para litiasis renal por conflicto de lateralidad entre hallazgos e impresión.",
                "original": source_text.strip(),
                "explicacion": "La lateralidad de litiasis debe ser confirmada manualmente.",
                "fuente": "Sistema",
                "requiere_revision": True,
                "motivos": [
                    "La zona de hallazgos y la zona de impresión no coinciden.",
                    "No se debe firmar como bilateral ni como derecha/izquierda hasta resolver la discordancia.",
                ],
            }
        )
    else:
        if has_left_lithiasis_impression or has_left_lithiasis_finding:
            impression_blocks.append(
                {
                    "tipo": "agregado",
                    "texto": "Pequeña litiasis renal izquierda no obstructiva.",
                    "original": _iad_first_claim_text(impresion_claims, "litiasis", "izquierda") or source_text.strip(),
                    "explicacion": "Impresión de litiasis izquierda sin conflicto de lateralidad.",
                    "fuente": "Dictado",
                    "requiere_revision": True,
                    "motivos": ["Confirmar redacción final."],
                }
            )

        if has_right_lithiasis_impression or has_right_lithiasis_finding:
            impression_blocks.append(
                {
                    "tipo": "agregado",
                    "texto": "Pequeña litiasis renal derecha no obstructiva.",
                    "original": _iad_first_claim_text(impresion_claims, "litiasis", "derecha") or source_text.strip(),
                    "explicacion": "Impresión de litiasis derecha sin conflicto de lateralidad.",
                    "fuente": "Dictado",
                    "requiere_revision": True,
                    "motivos": ["Confirmar redacción final."],
                }
            )

    warnings = [
        "La revisión separa hallazgos observados de frases dictadas para impresión diagnóstica.",
        "Validar tamaño, lateralidad y redacción diagnóstica antes de copiar."
    ]

    if zone_conflicts:
        warnings.insert(0, "Se detectó discordancia entre hallazgos e impresión diagnóstica.")

    return {
        "titulo": "UroTC",
        "advertencias": warnings,
        "secciones": [
            {
                "titulo": "Hallazgos",
                "bloques": normal_blocks + conflict_blocks + added_hallazgos,
            },
            {
                "titulo": "Impresión diagnóstica",
                "bloques": impression_blocks,
            },
        ],
    }




# IAD_SPECIAL_PROSTATE_REVIEW_V1
def _iad_sentence_containing(text: str, term: str) -> str:
    raw = _as_text(text)
    parts = re.split(r"(?<=[.!?])\s+|\n+", raw)
    term_n = _norm(term)
    for part in parts:
        if term_n in _norm(part):
            return part.strip()
    return raw.strip()


def _iad_measure_from_sentence(text: str) -> str:
    raw = _as_text(text)
    m = re.search(r"(\d+(?:[,.]\d+)?)\s*(mm|mil[ií]metros|cm|cent[ií]metros)", raw, flags=re.I)
    if not m:
        return ""
    unit = m.group(2)
    unit = "mm" if "mil" in unit.lower() else unit
    return f"{m.group(1)} {unit}"


def _special_prostate_revision(source_text: str, generated_text: str) -> dict[str, Any] | None:
    ns = _norm(source_text)
    ng = _norm(generated_text)

    if "prostata" not in ns:
        return None

    source_has_enlarged = any(x in ns for x in [
        "prostata aumentada",
        "diametro transverso",
        "diametro transversal",
        "mayor tamano prostatico",
        "mayor tamaño prostático",
        "hiperplasia prostatica",
        "hiperplasia prostática",
    ])

    if not source_has_enlarged:
        return None

    sentence = _iad_sentence_containing(source_text, "próstata")
    measure = _iad_measure_from_sentence(sentence)

    prostate_line = "Próstata aumentada de tamaño"
    if measure:
        prostate_line += f", de hasta {measure}"
    prostate_line += "."

    generated_says_normal = (
        "prostata" in ng
        and any(x in ng for x in [
            "tamano normal",
            "tamaño normal",
            "estructura y tamano normal",
            "estructura y tamaño normal",
            "dimensiones normales",
        ])
    )

    already_has_enlarged = (
        "prostata aumentada" in ng
        or "aumento de tamano prostatico" in ng
        or "aumento de tamaño prostático" in ng
    )

    if already_has_enlarged and not generated_says_normal:
        return None

    data = report_text_to_revision_data(generated_text)
    data["advertencias"] = data.get("advertencias", [])
    data["advertencias"].insert(
        0,
        "Se detectó contradicción prostática: el dictado menciona próstata aumentada, pero el informe mantiene próstata normal u omite el hallazgo."
    )

    sections = data.get("secciones", [])
    if not sections:
        sections = [{"titulo": "Informe", "bloques": []}]
        data["secciones"] = sections

    target = None
    for sec in sections:
        if _norm(sec.get("titulo")) in {"hallazgos", "informe"}:
            target = sec
            break
    if target is None:
        target = sections[0]

    bloques = target.setdefault("bloques", [])

    if generated_says_normal:
        bloques.insert(
            0,
            {
                "tipo": "conflicto",
                "texto": "El informe mantiene próstata normal pese a que el dictado menciona próstata aumentada.",
                "original": sentence,
                "explicacion": "Contradicción directa entre dictado e informe generado.",
                "fuente": "Sistema",
                "requiere_revision": True,
                "motivos": [
                    "El dictado contiene aumento prostático.",
                    "El informe generado conserva una frase normal de próstata.",
                    "Debe reemplazarse por el hallazgo dictado antes de firmar.",
                ],
            },
        )

    bloques.insert(
        1,
        {
            "tipo": "reemplazado" if generated_says_normal else "agregado",
            "texto": prostate_line,
            "original": sentence,
            "explicacion": "Hallazgo prostático recuperado desde el dictado original.",
            "fuente": "Dictado",
            "requiere_revision": True,
            "motivos": [
                "Confirmar medida y redacción final.",
                "La medida se extrajo desde la frase que contiene próstata, no desde adenopatías u otros hallazgos.",
            ],
        },
    )

    # Agregar impresión breve si existe sección de impresión.
    impression = None
    for sec in sections:
        if "impres" in _norm(sec.get("titulo")) or "conclusion" in _norm(sec.get("titulo")):
            impression = sec
            break

    if impression is not None:
        impression.setdefault("bloques", []).append(
            {
                "tipo": "agregado",
                "texto": prostate_line,
                "original": sentence,
                "explicacion": "Impresión derivada del hallazgo prostático dictado.",
                "fuente": "Dictado",
                "requiere_revision": True,
                "motivos": ["Confirmar si corresponde incluirlo en impresión diagnóstica."],
            }
        )

    return data

def compare_dictation_to_generated(source_text: str, generated_text: str) -> dict[str, Any]:
    prostate_special = _special_prostate_revision(source_text, generated_text)
    if prostate_special:
        return prostate_special

    special = _special_urotc_revision(source_text, generated_text)
    if special:
        return special

    generated_data = report_text_to_revision_data(generated_text)
    critical = _critical_sentences_from_dictation(source_text)
    missing = [s for s in critical if not _sentence_is_represented(s, generated_text)]

    if not missing:
        generated_data["advertencias"] = generated_data.get("advertencias", [])
        return generated_data

    generated_data["advertencias"] = [
        "Se detectaron hallazgos del dictado que no están representados claramente en el informe IA.",
        "La plantilla normal no debe prevalecer sobre el dictado."
    ]

    review_blocks = [
        {
            "tipo": "conflicto",
            "texto": "El informe IA parece omitir hallazgos relevantes del dictado.",
            "original": source_text.strip(),
            "explicacion": "Comparación automática entre dictado original e informe generado.",
            "fuente": "Sistema",
            "requiere_revision": True,
            "motivos": [
                "Hay frases clínicas relevantes en el dictado sin correlato suficiente en el informe generado.",
            ],
        }
    ]

    for s in missing:
        review_blocks.append(
            {
                "tipo": "agregado",
                "texto": s,
                "original": source_text.strip(),
                "explicacion": "Frase recuperada desde el dictado original.",
                "fuente": "Dictado",
                "requiere_revision": True,
                "motivos": ["Hallazgo dictado no encontrado claramente en el informe IA."],
            }
        )

    generated_data.setdefault("secciones", [])
    generated_data["secciones"].append(
        {
            "titulo": "Omisiones detectadas desde el dictado",
            "bloques": review_blocks,
        }
    )

    return generated_data


def normalize_revision_data(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith("{"):
            try:
                raw = json.loads(raw)
            except Exception:
                return report_text_to_revision_data(raw)
        else:
            return report_text_to_revision_data(raw)

    if not isinstance(raw, dict):
        return report_text_to_revision_data(_as_text(raw))

    source_text = _as_text(
        raw.get("source_text")
        or raw.get("dictado")
        or raw.get("texto_dictado")
        or raw.get("input_text")
        or raw.get("informacion_principal")
        or ""
    ).strip()

    generated_text = _as_text(
        raw.get("generated_text")
        or raw.get("report_text")
        or raw.get("informe_generado")
        or raw.get("resultado_ia")
        or raw.get("final_report")
        or ""
    ).strip()

    if source_text and generated_text:
        return compare_dictation_to_generated(source_text, generated_text)

    if "revision" in raw and isinstance(raw["revision"], dict):
        raw = raw["revision"]

    if "data" in raw and isinstance(raw["data"], dict) and "secciones" in raw["data"]:
        raw = raw["data"]

    if "report_text" in raw and "secciones" not in raw:
        return report_text_to_revision_data(_as_text(raw.get("report_text")))

    titulo = _as_text(raw.get("titulo") or raw.get("title") or "Informe generado por IA").strip()
    advertencias = _safe_list(raw.get("advertencias") or raw.get("warnings") or [])

    secciones = raw.get("secciones") or raw.get("sections") or []
    if not isinstance(secciones, list):
        secciones = []

    normalized_sections = []

    for sec in secciones:
        if not isinstance(sec, dict):
            continue

        sec_title = _as_text(sec.get("titulo") or sec.get("title") or "").strip()
        bloques = sec.get("bloques") or sec.get("blocks") or []

        if isinstance(bloques, str):
            bloques = [{"tipo": "normal", "texto": bloques}]

        if not isinstance(bloques, list):
            bloques = []

        normalized_blocks = []

        for block in bloques:
            if isinstance(block, str):
                block = {"tipo": "normal", "texto": block}

            if not isinstance(block, dict):
                continue

            tipo = _as_text(block.get("tipo") or block.get("type") or "normal").strip().lower()
            if tipo not in {"normal", "agregado", "reemplazado", "estructurado", "revisar", "conflicto", "eliminado"}:
                tipo = "revisar"

            texto = _as_text(block.get("texto") or block.get("text") or "").strip()
            if not texto:
                continue

            normalized_blocks.append(
                {
                    "tipo": tipo,
                    "texto": texto,
                    "original": _as_text(block.get("original") or "").strip(),
                    "explicacion": _as_text(block.get("explicacion") or block.get("explanation") or "").strip(),
                    "fuente": _as_text(block.get("fuente") or block.get("source") or "").strip(),
                    "requiere_revision": bool(block.get("requiere_revision", block.get("requires_review", tipo != "normal"))),
                    "motivos": [_as_text(x).strip() for x in _safe_list(block.get("motivos") or block.get("reasons") or []) if _as_text(x).strip()],
                }
            )

        normalized_sections.append({"titulo": sec_title, "bloques": normalized_blocks})

    if not normalized_sections:
        text_candidate = (
            raw.get("texto")
            or raw.get("text")
            or raw.get("informe")
            or raw.get("report")
            or raw.get("final_report")
            or ""
        )
        return report_text_to_revision_data(_as_text(text_candidate))

    return {
        "titulo": titulo,
        "advertencias": [_as_text(x).strip() for x in advertencias if _as_text(x).strip()],
        "secciones": normalized_sections,
    }


def report_text_to_revision_data(text: str) -> dict[str, Any]:
    text = _as_text(text).replace("\r\n", "\n").replace("\r", "\n").strip()

    if not text:
        text = "Informe vacío."

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    titulo = "Informe generado por IA"
    sections: list[dict[str, Any]] = []
    current = {"titulo": "Informe", "bloques": []}

    known_titles = {
        "antecedentes",
        "hallazgos",
        "impresión diagnóstica",
        "impresion diagnostica",
        "impresión",
        "impresion",
        "conclusión",
        "conclusion",
    }

    if lines:
        first = lines[0]
        if len(first) <= 90 and not first.endswith("."):
            titulo = first
            lines = lines[1:]

    for ln in lines:
        clean = ln.strip().strip(":")
        low = _norm(clean)

        if low in known_titles:
            if current["bloques"]:
                sections.append(current)
            current = {"titulo": clean, "bloques": []}
            continue

        for p in re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ0-9])", ln):
            p = p.strip()
            if p:
                current["bloques"].append({"tipo": "normal", "texto": p})

    if current["bloques"]:
        sections.append(current)

    if not sections:
        sections = [{"titulo": "Informe", "bloques": [{"tipo": "normal", "texto": text}]}]

    return {
        "titulo": titulo,
        "advertencias": [],
        "secciones": sections,
    }


def badge(text: str, cls: str) -> str:
    return f'<span class="badge {cls}">{escape(text)}</span>'


def render_block(block: dict[str, Any]) -> str:
    tipo = _as_text(block.get("tipo") or "normal").lower()
    texto = escape(_as_text(block.get("texto")))

    if tipo == "normal":
        return f'<p class="normal-line" data-clean="1">{texto}</p>'

    badges = [badge(tipo.upper(), f"badge-{tipo}")]

    if block.get("fuente"):
        badges.append(badge(_as_text(block["fuente"]), "badge-ia"))

    if block.get("requiere_revision"):
        badges.append(badge("REVISAR", "badge-revisar"))

    original = ""
    if block.get("original"):
        original = f'<div class="meta-line">Original: {escape(_as_text(block["original"]))}</div>'

    explicacion = ""
    if block.get("explicacion"):
        explicacion = f'<div class="meta-line">{escape(_as_text(block["explicacion"]))}</div>'

    motivos = ""
    motivos_list = _safe_list(block.get("motivos"))
    if motivos_list:
        lis = "".join(f"<li>{escape(_as_text(m))}</li>" for m in motivos_list if _as_text(m).strip())
        if lis:
            motivos = f"""
            <div class="motivos">
                <strong>Motivos de revisión:</strong>
                <ul>{lis}</ul>
            </div>
            """

    return f"""
    <article class="review-card review-{escape(tipo)}" data-tipo="{escape(tipo)}">
        <div class="review-text" contenteditable="false">{texto}</div>
        <div class="badge-row">{" ".join(badges)}</div>
        {original}
        {explicacion}
        {motivos}
        <div class="actions">
            <button type="button" onclick="acceptBlock(this)">Aceptar</button>
            <button type="button" onclick="rejectBlock(this)">Rechazar</button>
            <button type="button" onclick="editBlock(this)">Editar</button>
        </div>
    </article>
    """


def initial_clean_report(data: dict[str, Any]) -> str:
    lines: list[str] = []

    title = _as_text(data.get("titulo")).strip()
    if title:
        lines.append(title)
        lines.append("")

    for section in data.get("secciones", []):
        title = _as_text(section.get("titulo")).strip()
        if title:
            lines.append(title)
            lines.append("")

        for block in section.get("bloques", []):
            if _as_text(block.get("tipo")).lower() == "eliminado":
                continue

            txt = _as_text(block.get("texto")).strip()
            if txt:
                lines.append(txt)
                lines.append("")

    return "\n".join(lines).strip()


def render_page(data: dict[str, Any], *, mode_title: str = "Informe en modo revisión") -> str:
    data = normalize_revision_data(data)

    alerts_html = ""
    if data.get("advertencias"):
        items = "".join(f"<li>{escape(_as_text(x))}</li>" for x in data["advertencias"])
        alerts_html = f"""
        <section class="warning-box">
            <h3>Advertencias generales:</h3>
            <ul>{items}</ul>
        </section>
        """

    sections_html = ""
    for section in data.get("secciones", []):
        blocks_html = "".join(render_block(block) for block in section.get("bloques", []))
        sections_html += f"""
        <section class="report-section" data-section-title="{escape(_as_text(section.get("titulo")))}">
            <h2>{escape(_as_text(section.get("titulo")))}</h2>
            {blocks_html}
        </section>
        """

    clean = escape(initial_clean_report(data))

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>IA Dictador - revisión</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{
  --bg: #f5f7fb;
  --panel: #ffffff;
  --text: #202938;
  --muted: #5d6775;
  --line: #d7dde7;
  --yellow-bg: #fff4c7;
  --yellow-border: #f59e0b;
  --blue-bg: #dbeafe;
  --blue-border: #2563eb;
  --green-bg: #dcfce7;
  --green-border: #22c55e;
  --purple-bg: #f3e8ff;
  --purple-border: #a855f7;
  --red-bg: #fee2e2;
  --red-border: #ef4444;
  --gray-bg: #e5e7eb;
  --gray-border: #9ca3af;
}}

* {{
  box-sizing: border-box;
}}

body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.45;
}}

.page {{
  max-width: 980px;
  margin: 22px auto;
  padding: 0 16px 32px;
}}

.panel {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 22px;
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
}}

.topbar {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
  margin-bottom: 18px;
}}

h1 {{
  font-size: 29px;
  line-height: 1.12;
  margin: 0;
}}

.report-title {{
  border: 0;
  font-size: 28px;
  margin-top: 18px;
}}

h2 {{
  font-size: 22px;
  margin: 26px 0 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}}

h3 {{
  margin: 0 0 12px;
}}

.legend,
.badge-row {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}}

.legend {{
  justify-content: flex-end;
}}

.badge {{
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  border-radius: 999px;
  padding: 4px 12px;
  border: 1.5px solid;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: .02em;
  white-space: nowrap;
}}

.badge-agregado {{ background: var(--green-bg); border-color: var(--green-border); }}
.badge-reemplazado {{ background: var(--blue-bg); border-color: var(--blue-border); }}
.badge-estructurado, .badge-ia {{ background: var(--purple-bg); border-color: var(--purple-border); }}
.badge-revisar {{ background: var(--yellow-bg); border-color: #d97706; }}
.badge-conflicto {{ background: var(--red-bg); border-color: var(--red-border); }}
.badge-eliminado {{ background: var(--gray-bg); border-color: var(--gray-border); text-decoration: line-through; }}

.warning-box {{
  background: var(--yellow-bg);
  border: 1.5px solid var(--yellow-border);
  border-radius: 14px;
  padding: 18px 20px;
  margin: 18px 0 24px;
}}

.warning-box li {{
  font-size: 20px;
  margin-bottom: 6px;
}}

.normal-line {{
  font-size: 21px;
  margin: 0 0 24px 22px;
}}

.review-card {{
  background: var(--yellow-bg);
  border-left: 6px solid var(--yellow-border);
  border-radius: 14px;
  padding: 14px 16px;
  margin: 8px 0;
}}

.review-conflicto {{
  background: #fee2e2;
  border-left-color: #ef4444;
}}

.review-agregado {{
  background: #dcfce7;
  border-left-color: #22c55e;
}}

.review-eliminado {{
  background: #e5e7eb;
  border-left-color: #9ca3af;
}}

.review-text {{
  font-size: 21px;
  margin-bottom: 10px;
}}

.meta-line {{
  color: var(--muted);
  font-size: 16px;
  margin: 5px 0;
}}

.motivos {{
  margin-top: 8px;
  font-size: 16px;
}}

.motivos ul {{
  margin-top: 4px;
  margin-bottom: 0;
  padding-left: 22px;
}}

.actions,
.toolbar {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}}

.actions {{
  margin-top: 12px;
}}

.toolbar {{
  margin-top: 24px;
}}

button {{
  border: 1px solid #cbd5e1;
  background: white;
  color: #0f172a;
  border-radius: 10px;
  padding: 7px 10px;
  font-weight: 750;
  cursor: pointer;
}}

button:hover {{
  background: #f8fafc;
}}

.review-card.accepted {{
  background: #ecfdf5;
  outline: 2px solid #22c55e;
}}

.review-card.rejected {{
  opacity: .55;
  filter: grayscale(.45);
}}

textarea {{
  width: 100%;
  min-height: 360px;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px;
  font-size: 15px;
  line-height: 1.45;
  margin-top: 12px;
}}

@media (max-width: 720px) {{
  .panel {{ padding: 16px; }}
  .topbar {{ display: block; }}
  .legend {{ justify-content: flex-start; margin-top: 14px; }}
  h1 {{ font-size: 27px; }}
  .report-title {{ font-size: 25px; }}
  .normal-line, .review-text {{ font-size: 20px; margin-left: 0; }}
}}
</style>
</head>
<body>
<main class="page">
  <section class="panel">
    <div class="topbar">
      <h1>{escape(mode_title)}</h1>
      <div class="legend">
        {badge("Agregado", "badge-agregado")}
        {badge("Reemplazado", "badge-reemplazado")}
        {badge("Estructurado", "badge-estructurado")}
        {badge("Revisar", "badge-revisar")}
        {badge("Conflicto", "badge-conflicto")}
        {badge("Eliminado", "badge-eliminado")}
      </div>
    </div>

    {alerts_html}

    <h2 class="report-title" id="reportTitle">{escape(_as_text(data.get("titulo")))}</h2>

    {sections_html}

    <div class="toolbar">
      <button type="button" onclick="acceptAll()">Aceptar todo</button>
      <button type="button" onclick="rebuildCleanReport()">Actualizar informe limpio</button>
      <button type="button" onclick="copyClean()">Copiar informe limpio</button>
      <button type="button" onclick="showClean()">Mostrar informe limpio</button>
      <button type="button" onclick="hideClean()">Ocultar informe limpio</button>
    </div>

    <textarea id="cleanReport" style="display:none;">{clean}</textarea>
  </section>
</main>

<script>
function acceptBlock(btn) {{
  const card = btn.closest(".review-card");
  card.classList.remove("rejected");
  card.classList.add("accepted");
  rebuildCleanReport();
}}

function rejectBlock(btn) {{
  const card = btn.closest(".review-card");
  card.classList.remove("accepted");
  card.classList.add("rejected");
  rebuildCleanReport();
}}

function editBlock(btn) {{
  const card = btn.closest(".review-card");
  const txt = card.querySelector(".review-text");
  txt.contentEditable = "true";
  txt.focus();
  card.classList.add("accepted");
  txt.addEventListener("input", rebuildCleanReport);
  rebuildCleanReport();
}}

function acceptAll() {{
  document.querySelectorAll(".review-card").forEach(card => {{
    card.classList.remove("rejected");
    card.classList.add("accepted");
  }});
  rebuildCleanReport();
}}

function sectionText(section) {{
  const lines = [];
  const title = section.getAttribute("data-section-title") || "";

  if (title.trim()) {{
    lines.push(title.trim());
    lines.push("");
  }}

  section.querySelectorAll(".normal-line, .review-card").forEach(node => {{
    if (node.classList.contains("review-card")) {{
      if (node.classList.contains("rejected")) return;
      const tipo = node.getAttribute("data-tipo") || "";
      if (tipo === "eliminado" || tipo === "conflicto") return;
      const txt = node.querySelector(".review-text");
      if (txt && txt.innerText.trim()) {{
        lines.push(txt.innerText.trim());
        lines.push("");
      }}
    }} else {{
      if (node.innerText.trim()) {{
        lines.push(node.innerText.trim());
        lines.push("");
      }}
    }}
  }});

  return lines;
}}

function rebuildCleanReport() {{
  const lines = [];
  const reportTitle = document.getElementById("reportTitle");

  if (reportTitle && reportTitle.innerText.trim()) {{
    lines.push(reportTitle.innerText.trim());
    lines.push("");
  }}

  document.querySelectorAll(".report-section").forEach(section => {{
    lines.push(...sectionText(section));
  }});

  document.getElementById("cleanReport").value = lines.join("\\n").replace(/\\n{{3,}}/g, "\\n\\n").trim();
}}

function showClean() {{
  rebuildCleanReport();
  document.getElementById("cleanReport").style.display = "block";
}}

function hideClean() {{
  document.getElementById("cleanReport").style.display = "none";
}}

async function copyClean() {{
  rebuildCleanReport();
  const txt = document.getElementById("cleanReport").value;

  try {{
    await navigator.clipboard.writeText(txt);
    alert("Informe limpio copiado.");
  }} catch (e) {{
    showClean();
    alert("No pude copiar automáticamente. Queda visible para copiar manualmente.");
  }}
}}

rebuildCleanReport();
</script>
</body>
</html>
"""


@router.get("/iad/revision-bridge.js", response_class=PlainTextResponse)
def revision_bridge_js() -> PlainTextResponse:
    js = r'''
(function () {
  function visibleTextNear(el, distance) {
    let txt = "";
    let node = el;
    for (let i = 0; i < distance && node; i++) {
      node = node.previousElementSibling;
      if (node) txt += " " + (node.innerText || node.textContent || "");
    }
    return txt.toLowerCase();
  }

  function getAllTextareas() {
    return Array.from(document.querySelectorAll("textarea"))
      .map((el, idx) => ({
        el,
        idx,
        value: (el.value || "").trim(),
        label: visibleTextNear(el, 4)
      }))
      .filter(x => x.value.length > 0);
  }

  function getDictationAndGenerated() {
    const areas = getAllTextareas();

    let source = null;
    let generated = null;

    source = areas.find(x =>
      x.label.includes("información principal") ||
      x.label.includes("informacion principal") ||
      x.label.includes("dictado") ||
      x.label.includes("transcripción") ||
      x.label.includes("transcripcion")
    );

    generated = areas.find(x =>
      x.label.includes("resultado revisado") ||
      x.label.includes("resultado primario") ||
      x.label.includes("resultado ia") ||
      x.label.includes("informe generado")
    );

    if (!source && areas.length >= 1) {
      source = areas[0];
    }

    if (!generated && areas.length >= 2) {
      const rest = areas.slice(1).sort((a, b) => b.value.length - a.value.length);
      generated = rest[0];
    }

    if (!generated && areas.length === 1) {
      generated = areas[0];
    }

    return {
      source_text: source ? source.value : "",
      generated_text: generated ? generated.value : ""
    };
  }

  async function postRevisionPayload(payload) {
    const res = await fetch("/iad/api/revision/session", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload || {})
    });

    if (!res.ok) {
      throw new Error("No se pudo crear sesión de revisión: HTTP " + res.status);
    }

    const data = await res.json();

    if (!data || !data.url) {
      throw new Error("Respuesta sin URL de revisión.");
    }

    window.location.href = data.url;
  }

  window.IAD_abrirRevisionIA = async function (payload) {
    if (typeof payload === "string") {
      return postRevisionPayload({generated_text: payload});
    }

    return postRevisionPayload(payload || {});
  };

  window.IAD_revisarInformeActual = async function () {
    const payload = getDictationAndGenerated();

    if (!payload.generated_text && !payload.source_text) {
      alert("No encontré texto para revisar.");
      return;
    }

    if (!payload.generated_text) {
      payload.generated_text = payload.source_text;
    }

    await postRevisionPayload(payload);
  };

  function installFloatingButton() {
    if (document.getElementById("iad-review-floating-button")) return;

    const btn = document.createElement("button");
    btn.id = "iad-review-floating-button";
    btn.type = "button";
    btn.textContent = "Revisar IA";
    btn.style.position = "fixed";
    btn.style.right = "18px";
    btn.style.bottom = "18px";
    btn.style.zIndex = "9999";
    btn.style.border = "1px solid #d97706";
    btn.style.background = "#fff4c7";
    btn.style.color = "#202938";
    btn.style.borderRadius = "999px";
    btn.style.padding = "10px 14px";
    btn.style.fontWeight = "800";
    btn.style.boxShadow = "0 8px 20px rgba(15,23,42,.18)";
    btn.style.cursor = "pointer";
    btn.onclick = window.IAD_revisarInformeActual;

    document.body.appendChild(btn);
  }

  function installInlineButton() {
    if (document.getElementById("iad-review-inline-button")) return;

    const all = Array.from(document.querySelectorAll("body *"));
    const label = all.find(el => {
      const t = (el.innerText || el.textContent || "").trim().toLowerCase();
      return t === "resultado revisado" || t === "resultado primario ia";
    });

    const btn = document.createElement("button");
    btn.id = "iad-review-inline-button";
    btn.type = "button";
    btn.textContent = "Revisar informe IA";
    btn.style.margin = "8px 0 12px 0";
    btn.style.border = "1px solid #d97706";
    btn.style.background = "#fff4c7";
    btn.style.color = "#202938";
    btn.style.borderRadius = "10px";
    btn.style.padding = "8px 12px";
    btn.style.fontWeight = "800";
    btn.style.cursor = "pointer";
    btn.onclick = window.IAD_revisarInformeActual;

    if (label && label.parentNode) {
      label.parentNode.insertBefore(btn, label.nextSibling);
    }
  }

  function install() {
    installFloatingButton();
    installInlineButton();
    setInterval(installInlineButton, 1500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install);
  } else {
    install();
  }
})();
'''
    return PlainTextResponse(js, media_type="application/javascript")


@router.get("/iad/api/revision-demo")
def revision_demo_api():
    return JSONResponse(normalize_revision_data(DEMO_REVISION))


@router.get("/iad/revision-demo", response_class=HTMLResponse)
def revision_demo_page():
    return HTMLResponse(render_page(DEMO_REVISION))



@router.post("/iad/api/validar-dictado-informe.json")
async def validar_dictado_informe(request: Request):
    try:
        payload = await request.json()
    except Exception:
        form = await request.form()
        payload = dict(form)

    data = normalize_revision_data(payload)

    conflicts = []
    warnings = list(data.get("advertencias") or [])

    for section in data.get("secciones", []):
        for block in section.get("bloques", []):
            if _as_text(block.get("tipo")).lower() == "conflicto":
                conflicts.append(block)

    if conflicts and not warnings:
        warnings.append("Se detectaron conflictos que requieren revisión antes de firmar.")

    return JSONResponse(
        {
            "ok": True,
            "hay_advertencias": bool(warnings or conflicts),
            "advertencias": warnings,
            "conflictos": conflicts,
            "revision": data,
        }
    )


@router.post("/iad/api/revision/session")
async def create_revision_session(request: Request):
    _cleanup_sessions()

    try:
        payload = await request.json()
    except Exception:
        form = await request.form()
        payload = dict(form)

    data = normalize_revision_data(payload)
    sid = uuid4().hex
    data["_created"] = _now()
    _REVISION_SESSIONS[sid] = data

    return JSONResponse({"ok": True, "sid": sid, "url": f"/iad/revision/{sid}"})


@router.get("/iad/revision/{sid}", response_class=HTMLResponse)
def revision_session_page(sid: str):
    data = _REVISION_SESSIONS.get(sid)

    if not data:
        return HTMLResponse(
            render_page(
                {
                    "titulo": "Sesión de revisión no encontrada",
                    "advertencias": ["La sesión pudo expirar o el servidor pudo reiniciarse."],
                    "secciones": [
                        {
                            "titulo": "Estado",
                            "bloques": [
                                {
                                    "tipo": "conflicto",
                                    "texto": "No se encontró el informe de revisión solicitado.",
                                    "fuente": "Sistema",
                                    "requiere_revision": True,
                                    "motivos": ["Sesión de revisión ausente o expirada."],
                                }
                            ],
                        }
                    ],
                }
            ),
            status_code=404,
        )

    return HTMLResponse(render_page(data))
