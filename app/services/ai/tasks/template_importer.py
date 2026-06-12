import json
import re
import unicodedata
from typing import Any

from app.services.ai.provider import AIProviderError, ai_json_call


MODALITIES = ["TC", "MR", "US", "RX", "XA", "MG", "PET", "NM", "OTRO", ""]
BODY_REGIONS = [
    "Cabeza, cuello y columna",
    "Torax, abdomen y pelvis",
    "Extremidades y articulaciones",
    "Mamaria y ginecología",
    "",
]


def _clean_text(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{5,}", "\n\n\n", s)
    return s.strip()


def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"\s+", " ", s)
    return s


def _is_placeholder_only(s: str) -> bool:
    x = _norm(s)
    x = re.sub(r"[\s._\-xX]+", "", x)
    return not x


def _guess_modality(text: str) -> str:
    t = " " + _norm(text) + " "

    rules = [
        ("RX", [" rx ", " radiografia ", " radiografias ", " rayos "]),
        ("TC", [" tc ", " tac ", " tomografia ", " scanner ", " ct "]),
        ("MR", [" rm ", " resonancia ", " mri ", " mr "]),
        ("US", [" ecografia ", " ultrasonido ", " us "]),
        ("XA", [" angiografia ", " arteriografia ", " xa "]),
        ("MG", [" mamografia ", " mg "]),
        ("PET", [" pet "]),
        ("NM", [" cintigrama ", " spect ", " medicina nuclear "]),
    ]

    for modality, needles in rules:
        if any(n in t for n in needles):
            return modality

    return ""


def _guess_body_region(text: str) -> str:
    t = " " + _norm(text) + " "

    head = [
        " craneo ", " encefalo ", " cerebro ", " cabeza ", " cara ", " cuello ",
        " cervical ", " columna ", " dorsal ", " lumbar ", " medula ", " silla turca ",
        " hipofisis ", " senos paranasales ", " orbitas "
    ]
    tap = [
        " torax ", " pulmon ", " pulmonar ", " abdomen ", " pelvis ", " hepatico ",
        " higado ", " vesicula ", " pancreas ", " renal ", " rinon ", " bazo ",
        " suprarrenal ", " colon ", " intestino ", " tap "
    ]
    extrem = [
        " rodilla ", " rodillas ", " hombro ", " codo ", " muñeca ", " muneca ",
        " mano ", " cadera ", " tobillo ", " pie ", " femur ", " tibia ", " perone ",
        " extremidad ", " articulacion ", " articulaciones "
    ]
    gyn = [
        " mama ", " mamaria ", " mamografia ", " ginecologia ", " ginecologica ",
        " utero ", " ovario ", " ovarios ", " endometrio ", " transvaginal "
    ]

    if any(x in t for x in head):
        return "Cabeza, cuello y columna"
    if any(x in t for x in tap):
        return "Torax, abdomen y pelvis"
    if any(x in t for x in extrem):
        return "Extremidades y articulaciones"
    if any(x in t for x in gyn):
        return "Mamaria y ginecología"

    return ""


def _extract_labeled_inline(block: str, labels: list[str]) -> str:
    wanted = [_norm(x) for x in labels]

    for line in block.splitlines():
        raw = line.strip()
        low = _norm(raw).strip(":")

        for label in wanted:
            if low.startswith(label + ":"):
                val = raw.split(":", 1)[1].strip()
                return "" if _is_placeholder_only(val) else val

    return ""


def _find_section_starts(lines: list[str]) -> list[tuple[int, str, str]]:
    label_map = {
        "technique": ["tecnica", "tecnica del examen", "protocolo", "metodo"],
        "background": ["antecedentes", "antecedente", "contexto", "historia clinica", "indicacion"],
        "findings": ["hallazgos", "hallazgo", "descripcion", "informe", "cuerpo del informe"],
        "impression": ["impresion diagnostica", "impresion", "conclusion", "diagnostico"],
        "rules": ["reglas especificas", "notas de uso", "reglas", "instrucciones"],
    }

    starts: list[tuple[int, str, str]] = []

    for i, line in enumerate(lines):
        raw = line.strip()
        low = _norm(raw).strip(":").strip()

        for key, labels in label_map.items():
            for label in labels:
                if low == label or low.startswith(label + ":"):
                    inline = ""
                    if ":" in raw:
                        inline = raw.split(":", 1)[1].strip()
                    starts.append((i, key, inline))
                    break
            else:
                continue
            break

    return starts


def _slice_section(lines: list[str], starts: list[tuple[int, str, str]], key: str, clear_placeholder: bool = False) -> str:
    for pos, (line_idx, section_key, inline) in enumerate(starts):
        if section_key != key:
            continue

        next_idx = len(lines)
        if pos + 1 < len(starts):
            next_idx = starts[pos + 1][0]

        body = []
        if inline:
            body.append(inline)

        body.extend(lines[line_idx + 1:next_idx])
        value = _clean_text("\n".join(body))

        if clear_placeholder and _is_placeholder_only(value):
            return ""

        return value

    return ""


def _split_blocks_local(raw: str) -> list[str]:
    raw = _clean_text(raw)
    if not raw:
        return []

    parts = re.split(r"(?m)^\s*---+\s*$", raw)
    parts = [_clean_text(p) for p in parts if _clean_text(p)]
    if len(parts) > 1:
        return parts

    lines = raw.splitlines()
    starts: list[int] = []

    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue

        if len(s) <= 100 and ":" not in s and _guess_modality(s):
            window = "\n".join(lines[i:i + 14])
            if re.search(r"(?im)^\s*hallazgos\s*:{1,2}\s*$", window):
                starts.append(i)

    starts = sorted(set(starts))

    if len(starts) <= 1:
        return [raw]

    blocks = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        block = _clean_text("\n".join(lines[start:end]))
        if block:
            blocks.append(block)

    return blocks or [raw]


def _local_suggestions(candidate: dict[str, Any], title_line_count: int) -> list[str]:
    suggestions = []

    if not candidate.get("modality"):
        suggestions.append("No se pudo inferir modalidad con seguridad.")

    if not candidate.get("body_region"):
        suggestions.append("No se pudo inferir región del cuerpo con seguridad.")

    if title_line_count > 2:
        suggestions.append("Se detectaron más de dos líneas posibles de título; revisar si parte del título quedó fuera.")

    if not candidate.get("findings"):
        suggestions.append("No se detectó sección Hallazgos.")

    if not candidate.get("impression"):
        suggestions.append("No se detectó sección Impresión diagnóstica.")

    return suggestions


def local_parse_templates(raw_text: str) -> list[dict[str, Any]]:
    blocks = _split_blocks_local(raw_text)
    candidates = []

    for idx, block in enumerate(blocks, 1):
        lines = block.splitlines()
        starts = _find_section_starts(lines)

        first_section_idx = min([s[0] for s in starts], default=len(lines))
        header_lines = [x.strip() for x in lines[:first_section_idx] if x.strip()]

        explicit_name = _extract_labeled_inline(block, ["Nombre plantilla", "Nombre", "Plantilla"])
        explicit_title = _extract_labeled_inline(block, ["Título informe", "Titulo informe", "Título", "Titulo"])
        explicit_modality = _extract_labeled_inline(block, ["Modalidad"])
        explicit_region = _extract_labeled_inline(block, ["Región del cuerpo", "Region del cuerpo", "Región", "Region"])

        template_name = explicit_name
        if not template_name and header_lines:
            first = header_lines[0]
            if ":" not in first and len(first) <= 120:
                template_name = first

        title_lines = []
        raw_title_candidates = []

        if explicit_title:
            title_lines = [explicit_title]
            raw_title_candidates = [explicit_title]
        else:
            start_idx = 1 if header_lines and header_lines[0] == template_name else 0
            for h in header_lines[start_idx:]:
                hn = _norm(h)
                if hn.startswith(("modalidad:", "region:", "región:", "nombre plantilla:", "plantilla:")):
                    continue
                raw_title_candidates.append(h)
                if len(title_lines) < 2:
                    title_lines.append(h)

        title = _clean_text("\n".join(title_lines))

        technique = _slice_section(lines, starts, "technique", clear_placeholder=True)
        background = _slice_section(lines, starts, "background", clear_placeholder=True)
        findings = _slice_section(lines, starts, "findings", clear_placeholder=False)
        impression = _slice_section(lines, starts, "impression", clear_placeholder=False)
        rules = _slice_section(lines, starts, "rules", clear_placeholder=True)

        combined = (template_name or "") + "\n" + title + "\n" + block
        modality = (explicit_modality or _guess_modality(combined)).upper()
        body_region = explicit_region or _guess_body_region(combined)

        if body_region not in BODY_REGIONS:
            body_region = ""

        if not template_name:
            template_name = f"Plantilla importada {idx}"

        if not title:
            title = template_name

        candidate = {
            "template_name": template_name,
            "modality": modality,
            "body_region": body_region,
            "title": title,
            "technique": technique,
            "background": background,
            "findings": findings,
            "impression": impression,
            "specific_rules_json": rules,
            "tags": [],
            "suggestions": [],
            "confidence": 0.65,
            "warnings": [],
        }

        candidate["suggestions"] = _local_suggestions(candidate, len(raw_title_candidates))
        candidates.append(candidate)

    return candidates


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "templates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "template_name": {"type": "string"},
                        "modality": {"type": "string", "enum": MODALITIES},
                        "body_region": {"type": "string", "enum": BODY_REGIONS},
                        "title": {"type": "string"},
                        "technique": {"type": "string"},
                        "background": {"type": "string"},
                        "findings": {"type": "string"},
                        "impression": {"type": "string"},
                        "specific_rules_json": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "suggestions": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number"},
                        "warnings": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "template_name",
                        "modality",
                        "body_region",
                        "title",
                        "technique",
                        "background",
                        "findings",
                        "impression",
                        "specific_rules_json",
                        "tags",
                        "suggestions",
                        "confidence",
                        "warnings",
                    ],
                },
            },
            "global_warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["templates", "global_warnings"],
    }


def _system_prompt() -> str:
    return """
Eres un importador inteligente de plantillas radiológicas en español.

Tu tarea es convertir texto plano desordenado en plantillas estructuradas para un sistema de informes.
Esto es solo un importador. No eres corrector clínico ni editor de contenido.

Debes detectar:
- template_name: nombre interno de la plantilla. Usualmente es la primera línea del bloque.
- modality: inferida del nombre o título. Usa TC, MR, US, RX, XA, MG, PET, NM u OTRO.
- body_region: una de estas opciones exactas: Cabeza, cuello y columna; Torax, abdomen y pelvis; Extremidades y articulaciones; Mamaria y ginecología. Si no estás seguro, deja string vacío.
- title: título visible del informe. Puede tener una o dos líneas. Preserva saltos de línea si hay dos líneas.
- technique: puede estar ausente. Si solo contiene xxxxx, _____, puntos o rellenos, dejar vacío.
- background: antecedentes. Puede estar ausente o ser relleno; si es relleno, dejar vacío.
- findings: hallazgos. Preserva el texto clínico y sus saltos de línea.
- impression: impresión diagnóstica. Preserva el texto clínico y sus saltos de línea.
- specific_rules_json: usualmente vacío, salvo que el texto traiga reglas explícitas de uso.
- tags: deja siempre una lista vacía. Los tags serán escritos manualmente por el usuario.
- suggestions: sugerencias para que el usuario revise antes de guardar si detectas inconsistencias, secciones dudosas, título ambiguo, modalidad insegura, región insegura, ausencia de Hallazgos o ausencia de Impresión diagnóstica.

Reglas estrictas:
1. No inventes hallazgos ni impresiones. El texto ingresado se debe mantener tal cual.
2. No corrijas el contenido clínico. Esto es solo un importador.
3. No elimines xxxxx dentro de hallazgos o impresión: esos placeholders pueden ser intencionales.
4. Sí debes convertir Técnica o Antecedentes compuestos solo por xxxxx, _____ o rellenos en string vacío.
5. Si hay múltiples plantillas, devuelve múltiples objetos.
6. Si un bloque comienza con una línea como "RX rodillas artrosis", eso es template_name.
7. Las líneas inmediatamente posteriores al nombre y antes de "Hallazgos" suelen ser title. Puede ser una o dos líneas.
8. "Hallazgos::" y "Hallazgos:" son equivalentes.
9. "Impresión diagnóstica:" e "Impresión:" son equivalentes.
10. Devuelve exclusivamente JSON válido según el esquema.
11. Devuelve suggestions si detectas inconsistencias. Se lo mostraremos al usuario para que haga sus modificaciones.
12. No escribas tags. Devuelve tags como lista vacía.

No modifiques acentos, lateralidad, medidas, negaciones, placeholders ni redacción clínica del texto fuente dentro de Hallazgos o Impresión diagnóstica.
No sugieras nada por Técnica o Antecedentes vacíos, porque suelen estar vacíos.
""".strip()


def _user_prompt(raw_text: str, local_candidates: list[dict[str, Any]]) -> str:
    return f"""
Texto original a importar:

{raw_text}

Primer análisis local heurístico, úsalo solo como orientación para segmentar. Corrige únicamente la estructura, no el texto clínico:

{json.dumps(local_candidates, ensure_ascii=False, indent=2)}
""".strip()


def _normalize_ai_candidate(c: dict[str, Any], idx: int) -> dict[str, Any]:
    suggestions = c.get("suggestions", [])
    if isinstance(suggestions, str):
        suggestions = [suggestions]
    if not isinstance(suggestions, list):
        suggestions = []

    warnings = c.get("warnings", [])
    if isinstance(warnings, str):
        warnings = [warnings]
    if not isinstance(warnings, list):
        warnings = []

    modality = str(c.get("modality") or "").strip().upper()
    if modality not in MODALITIES:
        modality = "OTRO" if modality else ""

    body_region = str(c.get("body_region") or "").strip()
    if body_region not in BODY_REGIONS:
        body_region = ""

    return {
        "template_name": str(c.get("template_name") or f"Plantilla importada {idx}").strip(),
        "modality": modality,
        "body_region": body_region,
        "title": str(c.get("title") or "").strip(),
        "technique": str(c.get("technique") or "").strip(),
        "background": str(c.get("background") or "").strip(),
        "findings": str(c.get("findings") or "").strip(),
        "impression": str(c.get("impression") or "").strip(),
        "specific_rules_json": str(c.get("specific_rules_json") or "").strip(),
        "tags": [],
        "suggestions": suggestions,
        "confidence": float(c.get("confidence") or 0),
        "warnings": warnings,
    }


def import_templates_intelligent(raw_text: str, use_ai: bool = True) -> dict[str, Any]:
    raw_text = _clean_text(raw_text)

    if not raw_text:
        return {
            "engine": "none",
            "templates": [],
            "global_warnings": ["Entrada vacía."],
        }

    local_candidates = local_parse_templates(raw_text)

    result = {
        "engine": "local",
        "templates": local_candidates,
        "global_warnings": [],
    }

    if not use_ai:
        return result

    try:
        parsed = ai_json_call(
            task="TEMPLATE_IMPORT",
            system_prompt=_system_prompt(),
            user_prompt=_user_prompt(raw_text, local_candidates),
            schema_name="iad_template_import",
            json_schema=_schema(),
        )

        templates = [
            _normalize_ai_candidate(c, i + 1)
            for i, c in enumerate(parsed.get("templates", []))
        ]

        if not templates:
            raise AIProviderError("La IA no devolvió plantillas.")

        return {
            "engine": "ai",
            "templates": templates,
            "global_warnings": parsed.get("global_warnings", []),
        }

    except Exception as exc:
        result["global_warnings"].append(
            f"IA no disponible o falló. Se usó parser local. Detalle: {exc}"
        )
        return result
