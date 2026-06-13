from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator
import json
import os
import re
import unicodedata

from app.services.ai.provider import ai_json_call


ZonaOrigen = Literal["hallazgos", "impresion", "antecedentes", "tecnica", "administrativo", "desconocido"]
Lateralidad = Literal["derecha", "izquierda", "bilateral", "linea_media", "no_aplica", "no_especificada"]
Criticidad = Literal["baja", "media", "alta"]
TipoConflicto = Literal[
    "lateralidad",
    "hallazgo_vs_impresion",
    "omision",
    "contradiccion",
    "medida",
    "diagnostico_no_sustentado",
    "otro",
]


class ClinicalFinding(BaseModel):
    organo_o_region: str = ""
    hallazgo: str = ""
    lateralidad: Lateralidad = "no_especificada"
    medida: str = ""
    caracteristicas: list[str] = Field(default_factory=list)
    estado: str = ""
    zona_origen: ZonaOrigen = "hallazgos"
    texto_original: str = ""
    interpretacion: str = ""
    requiere_revision: bool = True
    criticidad: Criticidad = "media"
    motivos_revision: list[str] = Field(default_factory=list)


class ClinicalConflict(BaseModel):
    tipo: TipoConflicto = "otro"
    hallazgo: str = ""
    detalle: str = ""
    texto_hallazgos: str = ""
    texto_impresion: str = ""
    requiere_revision: bool = True


class SuggestedTemplate(BaseModel):
    id: str | None = None
    nombre: str = ""
    confianza: Literal["alta", "media", "baja"] = "baja"
    motivo: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_template_id(cls, value):
        if value is None or value == "":
            return None
        return str(value)


class ClinicalExtraction(BaseModel):
    ok: bool = True
    version: str = "clinical_json_v1"
    plantilla_sugerida: SuggestedTemplate = Field(default_factory=SuggestedTemplate)
    modalidad: str = ""
    estudio: str = ""
    dictado_original: str = ""
    hallazgos: list[ClinicalFinding] = Field(default_factory=list)
    impresion_solicitada: list[ClinicalFinding] = Field(default_factory=list)
    negativos_relevantes: list[str] = Field(default_factory=list)
    conflictos: list[ClinicalConflict] = Field(default_factory=list)
    advertencias: list[str] = Field(default_factory=list)
    necesita_revision: bool = True
    metodo: str = "heuristico"


def s(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def noacc(text: str) -> str:
    text = s(text).lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    raw = s(text).replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"\n+", ". ", raw)
    parts = re.split(r"(?<=[.!?])\s+|\.\s*", raw)
    out = []
    for part in parts:
        part = part.strip(" \t\n.;")
        if part:
            out.append(part)
    return out


def clean_instruction_prefix(sentence: str) -> str:
    out = s(sentence).strip(" .;\n\t")

    patterns = [
        r"^(y\s+)?en\s+la\s+impresi[oó]n\s+diagn[oó]stica\s+vamos\s+a\s+poner\s+",
        r"^(y\s+)?en\s+la\s+conclusi[oó]n\s+vamos\s+a\s+poner\s+",
        r"^(y\s+)?en\s+conclusi[oó]n\s+vamos\s+a\s+poner\s+",
        r"^(y\s+)?tambi[eé]n\s+vamos\s+a\s+poner\s+",
        r"^vamos\s+a\s+poner\s+tambi[eé]n\s+",
        r"^vamos\s+a\s+poner\s+",
        r"^se\s+observa\s+",
    ]

    for pat in patterns:
        out = re.sub(pat, "", out, flags=re.I)

    out = re.sub(r"\bmilimetros\b", "mm", out, flags=re.I)
    out = re.sub(r"\bmilímetros\b", "mm", out, flags=re.I)

    if out and out[0].islower():
        out = out[0].upper() + out[1:]

    if out and not out.endswith("."):
        out += "."

    return out


def split_zones(text: str) -> dict[str, list[str]]:
    zones = {
        "hallazgos": [],
        "impresion": [],
        "administrativo": [],
    }

    current = "hallazgos"

    impression_markers = [
        "impresion diagnostica",
        "impresion",
        "conclusion",
        "diagnostico",
    ]

    administrative_markers = [
        "paciente",
        "edad",
        "anos",
        "años",
        "institucion",
        "institución",
        "motivo",
        "antecedente",
    ]

    for sent in split_sentences(text):
        ns = noacc(sent)

        if any(m in ns for m in impression_markers):
            current = "impresion"

        cleaned = clean_instruction_prefix(sent)
        if not cleaned:
            continue

        if current == "hallazgos" and any(m in ns for m in administrative_markers):
            # Solo administrativo si no contiene hallazgos imagenológicos.
            if not any(x in ns for x in [
                "lesion", "masa", "nodulo", "litiasis", "calculo", "derrame", "estenosis",
                "oclusion", "aneurisma", "hematoma", "hidronefrosis", "realce"
            ]):
                zones["administrativo"].append(cleaned)
                continue

        zones[current].append(cleaned)

    return zones


def detect_laterality(text: str) -> Lateralidad:
    n = noacc(text)

    if "bilateral" in n or "ambos" in n or "ambas" in n:
        return "bilateral"

    if "izquierd" in n or "renal izquierda" in n or "rinon izquierdo" in n or "riñon izquierdo" in n:
        return "izquierda"

    if "derech" in n or "renal derecha" in n or "rinon derecho" in n or "riñon derecho" in n:
        return "derecha"

    if "linea media" in n or "medial" in n:
        return "linea_media"

    return "no_especificada"


def extract_measure(text: str) -> str:
    raw = s(text)

    m = re.search(
        r"(\d+(?:[,.]\d+)?)\s*(?:x|por)\s*(\d+(?:[,.]\d+)?)\s*(?:x|por)\s*(\d+(?:[,.]\d+)?)\s*(mm|mil[ií]metros|cm|cent[ií]metros)?",
        raw,
        flags=re.I,
    )
    if m:
        unit = m.group(4) or "mm"
        unit = "mm" if "mil" in unit.lower() else unit
        return f"{m.group(1)} x {m.group(2)} x {m.group(3)} {unit}"

    m = re.search(r"(\d+(?:[,.]\d+)?)\s*(mm|mil[ií]metros|cm|cent[ií]metros)", raw, flags=re.I)
    if m:
        unit = m.group(2)
        unit = "mm" if "mil" in unit.lower() else unit
        return f"{m.group(1)} {unit}"

    return ""


def sentence_to_finding(sentence: str, zone: ZonaOrigen) -> ClinicalFinding | None:
    n = noacc(sentence)

    finding = None
    organ = ""
    interpretation = ""
    chars: list[str] = []
    criticidad: Criticidad = "media"
    motivos: list[str] = []

    if any(x in n for x in ["litiasis", "calculo", "calculos", "nefrolitiasis"]):
        finding = "litiasis renal"
        organ = "riñón"
        if "no obstructiva" in n or "no obstructivo" in n or "sin hidronefrosis" in n:
            chars.append("no obstructiva")
        elif "obstructiva" in n or "hidronefrosis" in n:
            chars.append("posiblemente obstructiva")
            criticidad = "alta"
            motivos.append("Litiasis con posible carácter obstructivo.")

    elif any(x in n for x in ["lesion", "masa", "nodulo", "tumor", "neoplas", "carcinoma"]):
        finding = "lesión focal"
        if "renal" in n or "rinon" in n or "riñon" in n or "riñón" in n:
            organ = "riñón"
        elif "hepatic" in n or "higado" in n or "hígado" in n:
            organ = "hígado"
        else:
            organ = "órgano/región no especificado"

        if "solida" in n or "sólida" in n:
            chars.append("sólida")
        if "bordes bien definidos" in n:
            chars.append("bordes bien definidos")
        if "realce" in n or "realza" in n:
            chars.append("realce con contraste")
        if "arterial" in n:
            chars.append("realce arterial")

        if "carcinoma" in n:
            interpretation = "compatible con carcinoma según dictado"
            criticidad = "alta"
            motivos.append("El dictado menciona carcinoma explícitamente.")
        elif "neoplas" in n or "tumor" in n:
            interpretation = "sospecha neoplásica según dictado"
            criticidad = "alta"
            motivos.append("El dictado menciona sospecha tumoral/neoplásica.")

    elif any(x in n for x in ["vesicula no visualizada", "no se visualiza vesicula", "vesicula ausente", "colecistectomia"]):
        finding = "vesícula biliar no visualizada"
        organ = "vesícula biliar"
        chars.append("no visualizada")

    # IAD_CLINICAL_JSON_PROSTATE_V1
    elif "prostata" in n and any(x in n for x in ["aumentada", "mayor tamano", "mayor tamaño", "hiperplasia", "60", "diametro transverso", "diámetro transverso"]):
        finding = "aumento de tamaño prostático"
        organ = "próstata"
        chars.append("aumentada de tamaño")
        criticidad = "media"
        motivos.append("Hallazgo prostático explícito en el dictado.")

    if not finding:
        return None

    lat = detect_laterality(sentence)
    measure = extract_measure(sentence)

    if organ == "próstata":
        lat = "no_aplica"

    if lat == "no_especificada" and organ in {"riñón", "órgano/región no especificado"}:
        motivos.append("No se detectó lateralidad explícita.")

    if any(x in n for x in ["realce", "carcinoma", "neoplas", "tumor"]) and not measure:
        motivos.append("Hallazgo relevante sin medida clara o medida no detectada.")

    return ClinicalFinding(
        organo_o_region=organ,
        hallazgo=finding,
        lateralidad=lat,
        medida=measure,
        caracteristicas=chars,
        estado="positivo",
        zona_origen=zone,
        texto_original=sentence,
        interpretacion=interpretation,
        requiere_revision=bool(motivos) or zone == "impresion",
        criticidad=criticidad,
        motivos_revision=motivos,
    )


def detect_conflicts(hallazgos: list[ClinicalFinding], impresion: list[ClinicalFinding]) -> list[ClinicalConflict]:
    conflicts: list[ClinicalConflict] = []

    for h in hallazgos:
        for i in impresion:
            same_type = h.hallazgo == i.hallazgo
            same_organ = h.organo_o_region == i.organo_o_region or not h.organo_o_region or not i.organo_o_region

            if not same_type or not same_organ:
                continue

            if h.lateralidad not in {"no_especificada", "no_aplica"} and i.lateralidad not in {"no_especificada", "no_aplica"}:
                if h.lateralidad != i.lateralidad and "bilateral" not in {h.lateralidad, i.lateralidad}:
                    conflicts.append(
                        ClinicalConflict(
                            tipo="hallazgo_vs_impresion",
                            hallazgo=h.hallazgo,
                            detalle=(
                                f"Discordancia de lateralidad: hallazgos dice {h.lateralidad}, "
                                f"pero impresión/conclusión dice {i.lateralidad}."
                            ),
                            texto_hallazgos=h.texto_original,
                            texto_impresion=i.texto_original,
                            requiere_revision=True,
                        )
                    )

    return conflicts


def heuristic_extract_clinical_json(text: str, analysis: dict[str, Any] | None = None) -> ClinicalExtraction:
    analysis = analysis or {}
    zones = split_zones(text)

    hallazgos: list[ClinicalFinding] = []
    impresion: list[ClinicalFinding] = []

    for sent in zones["hallazgos"]:
        item = sentence_to_finding(sent, "hallazgos")
        if item:
            hallazgos.append(item)

    for sent in zones["impresion"]:
        item = sentence_to_finding(sent, "impresion")
        if item:
            impresion.append(item)

    conflicts = detect_conflicts(hallazgos, impresion)

    tpl = analysis.get("plantilla_sugerida") or {}
    warnings: list[str] = []

    if conflicts:
        warnings.append("Se detectaron conflictos entre hallazgos e impresión/conclusión.")

    if not hallazgos and not impresion:
        warnings.append("No se extrajeron hallazgos estructurados. Revisar dictado o usar fallback textual.")

    return ClinicalExtraction(
        plantilla_sugerida=SuggestedTemplate(
            id=s(tpl.get("id")) or None,
            nombre=s(tpl.get("nombre")),
            confianza=s(tpl.get("confianza") or "baja") if s(tpl.get("confianza")) in {"alta", "media", "baja"} else "baja",
            motivo=s(tpl.get("motivo")),
        ),
        modalidad=s(tpl.get("modalidad")),
        estudio=s(tpl.get("nombre")),
        dictado_original=s(text),
        hallazgos=hallazgos,
        impresion_solicitada=impresion,
        negativos_relevantes=[],
        conflictos=conflicts,
        advertencias=warnings,
        necesita_revision=bool(warnings or conflicts or any(x.requiere_revision for x in hallazgos + impresion)),
        metodo="heuristico_clinical_json_v1",
    )


def clinical_json_schema() -> dict[str, Any]:
    schema = ClinicalExtraction.model_json_schema()
    # OpenAI strict JSON schema se porta mejor con additionalProperties explícito.
    schema["additionalProperties"] = False
    return schema


def system_prompt() -> str:
    return """
Eres un extractor clínico estructurado para dictado radiológico en español.

No debes redactar el informe final.
No debes completar ni suavizar el dictado.
No debes inventar diagnósticos.
Tu tarea es convertir el dictado en JSON clínico verificable.

Reglas obligatorias:
1. Separa hallazgos observados de frases solicitadas para impresión diagnóstica.
2. Si el usuario dice "en la impresión diagnóstica vamos a poner...", desde ahí estás en zona impresión.
3. Una frase de impresión no debe tratarse como hallazgo observado.
4. Conserva lateralidad, medidas, órgano/región, realce, negaciones e incertidumbre.
5. Si hallazgos e impresión tienen lateralidad distinta para el mismo hallazgo, crea un conflicto.
6. Si hay conflicto, no lo conviertas en bilateral salvo que el dictado diga explícitamente bilateral.
7. Si una interpretación diagnóstica aparece solo en impresión, márcala como zona_origen="impresion".
8. Si un hallazgo relevante no tiene lateralidad o medida clara, requiere_revision=true.
9. Devuelve exclusivamente JSON válido según el esquema.
""".strip()


def user_prompt(text: str, analysis: dict[str, Any] | None = None) -> str:
    return f"""
DICTADO ORIGINAL:
{text}

ANALISIS PRELIMINAR / PLANTILLA SUGERIDA:
{json.dumps(analysis or {}, ensure_ascii=False, indent=2)}

Devuelve el JSON clínico estructurado.
""".strip()


def extract_clinical_json(text: str, analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = s(text)
    analysis = analysis or {}

    if not raw:
        return ClinicalExtraction(
            ok=False,
            dictado_original="",
            advertencias=["Texto vacío."],
            necesita_revision=True,
            metodo="vacio_clinical_json_v1",
        ).model_dump()

    try:
        parsed = ai_json_call(
            task="RADIOLOGY_CLINICAL_JSON",
            system_prompt=system_prompt(),
            user_prompt=user_prompt(raw, analysis),
            schema_name="iad_radiology_clinical_json",
            json_schema=clinical_json_schema(),
        )

        obj = ClinicalExtraction.model_validate(parsed)

        # Guardrail determinístico adicional: si el modelo no marcó conflictos obvios, agregarlos.
        heuristic = heuristic_extract_clinical_json(raw, analysis)
        heuristic_conflicts = heuristic.conflictos or []

        existing_keys = {
            (c.tipo, c.hallazgo, c.texto_hallazgos, c.texto_impresion)
            for c in obj.conflictos
        }

        for c in heuristic_conflicts:
            key = (c.tipo, c.hallazgo, c.texto_hallazgos, c.texto_impresion)
            if key not in existing_keys:
                obj.conflictos.append(c)

        if heuristic_conflicts and "Se detectaron conflictos entre hallazgos e impresión/conclusión." not in obj.advertencias:
            obj.advertencias.append("Se detectaron conflictos entre hallazgos e impresión/conclusión.")

        obj.metodo = "ia_clinical_json_v1"
        obj.necesita_revision = bool(
            obj.advertencias
            or obj.conflictos
            or any(x.requiere_revision for x in obj.hallazgos + obj.impresion_solicitada)
        )
        return obj.model_dump()

    except Exception as exc:
        # IAD_SAFE_CLINICAL_FALLBACK_V1
        try:
            fallback = heuristic_extract_clinical_json(raw, analysis)
            fallback.advertencias.append(f"Falló extracción clínica estructurada por IA. Se usó heurística. Error: {exc}")
            fallback.metodo = "heuristico_por_error_clinical_json_v1"
            return fallback.model_dump()
        except Exception as fallback_exc:
            return ClinicalExtraction(
                ok=False,
                dictado_original=raw,
                advertencias=[
                    f"Falló extracción clínica estructurada por IA: {exc}",
                    f"Falló fallback heurístico: {fallback_exc}",
                ],
                necesita_revision=True,
                metodo="error_total_clinical_json_v1",
            ).model_dump()


def clinical_json_to_hallazgos_text(payload: dict[str, Any]) -> str:
    try:
        obj = ClinicalExtraction.model_validate(payload)
    except Exception:
        obj = heuristic_extract_clinical_json(json.dumps(payload, ensure_ascii=False))

    lines: list[str] = []

    if obj.hallazgos:
        lines.append("[HALLAZGOS ESTRUCTURADOS]")
        for item in obj.hallazgos:
            parts = []
            if item.organo_o_region:
                parts.append(item.organo_o_region)
            if item.lateralidad not in {"no_especificada", "no_aplica"}:
                parts.append(item.lateralidad)
            if item.hallazgo:
                parts.append(item.hallazgo)
            if item.medida:
                parts.append(item.medida)
            if item.caracteristicas:
                parts.append(", ".join(item.caracteristicas))
            if item.interpretacion:
                parts.append(item.interpretacion)

            base = ": ".join([parts[0], "; ".join(parts[1:])]) if len(parts) > 1 else " ".join(parts)
            if item.texto_original:
                base += f" | Texto original: {item.texto_original}"
            lines.append("- " + base.strip())

    if obj.impresion_solicitada:
        lines.append("")
        lines.append("[IMPRESION SOLICITADA POR DICTADO]")
        for item in obj.impresion_solicitada:
            txt = item.texto_original or item.interpretacion or item.hallazgo
            lines.append("- " + txt.strip())

    if obj.conflictos:
        lines.append("")
        lines.append("[CONFLICTOS - NO RESOLVER AUTOMATICAMENTE]")
        for c in obj.conflictos:
            lines.append(f"- {c.detalle or c.hallazgo}. Hallazgos: {c.texto_hallazgos}. Impresión: {c.texto_impresion}")

    if obj.negativos_relevantes:
        lines.append("")
        lines.append("[NEGATIVOS RELEVANTES]")
        for n in obj.negativos_relevantes:
            lines.append("- " + n)

    return "\n".join(lines).strip()


def clinical_json_to_review_payload(payload: dict[str, Any]) -> dict[str, Any]:
    obj = ClinicalExtraction.model_validate(payload)

    hallazgo_blocks = []

    for c in obj.conflictos:
        hallazgo_blocks.append(
            {
                "tipo": "conflicto",
                "texto": c.detalle or c.hallazgo,
                "original": obj.dictado_original,
                "explicacion": "Conflicto detectado en JSON clínico intermedio.",
                "fuente": "JSON clínico",
                "requiere_revision": True,
                "motivos": [
                    c.texto_hallazgos,
                    c.texto_impresion,
                ],
            }
        )

    for item in obj.hallazgos:
        hallazgo_blocks.append(
            {
                "tipo": "agregado",
                "texto": item.texto_original or item.hallazgo,
                "original": obj.dictado_original,
                "explicacion": f"Hallazgo estructurado: {item.organo_o_region}, lateralidad {item.lateralidad}.",
                "fuente": "JSON clínico",
                "requiere_revision": item.requiere_revision,
                "motivos": item.motivos_revision,
            }
        )

    impresion_blocks = []
    for item in obj.impresion_solicitada:
        tipo = "revisar" if item.requiere_revision else "agregado"
        impresion_blocks.append(
            {
                "tipo": tipo,
                "texto": item.texto_original or item.interpretacion or item.hallazgo,
                "original": obj.dictado_original,
                "explicacion": "Impresión solicitada desde dictado.",
                "fuente": "JSON clínico",
                "requiere_revision": item.requiere_revision,
                "motivos": item.motivos_revision,
            }
        )

    return {
        "titulo": obj.estudio or obj.plantilla_sugerida.nombre or "Informe radiológico",
        "advertencias": obj.advertencias,
        "secciones": [
            {"titulo": "Hallazgos", "bloques": hallazgo_blocks},
            {"titulo": "Impresión diagnóstica", "bloques": impresion_blocks},
        ],
    }
