from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

from .json_utils import extract_json_object
from .prompt_builder import build_report_bridge_prompt
from .schemas import normalize_v3_output
from .validator import validate_report_payload


def _template_headings(template_text: str) -> list[str]:
    headings = []
    for heading in [
        "Técnica",
        "Tecnica",
        "Antecedentes",
        "Hallazgos",
        "Impresión diagnóstica",
        "Impresion diagnostica",
        "Conclusión",
        "Conclusion",
    ]:
        if heading.lower() in template_text.lower():
            headings.append(heading)
    return headings


def build_report_with_ai(
    *,
    client: OpenAI,
    transcripcion: str,
    texto_adicional: str,
    plantilla: dict[str, Any],
    reglas_generales: str,
    audio_first_raw: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    model = (
        os.getenv("IAD_AI_MODEL_AUDIO_FIRST_TEMPLATE_BRIDGE")
        or os.getenv("IAD_AI_MODEL_TEXT_STRUCTURED")
        or os.getenv("OPENAI_MODEL")
        or "gpt-4o-mini"
    )

    template_text = str(plantilla.get("contenido") or plantilla.get("content") or "")
    prompt = build_report_bridge_prompt(
        transcripcion=transcripcion,
        texto_adicional=texto_adicional,
        plantilla=plantilla,
        reglas_generales=reglas_generales,
        audio_first_raw=audio_first_raw,
        metadata=metadata,
    )

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Eres un editor estricto de plantillas radiológicas. "
                    "Tu salida debe ser JSON válido. "
                    "El informe_final debe ser una plantilla completa editada, no un resumen."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    try:
        completion = client.chat.completions.create(**kwargs)
    except Exception:
        kwargs.pop("response_format", None)
        completion = client.chat.completions.create(**kwargs)

    raw = ""
    try:
        raw = completion.choices[0].message.content or ""
    except Exception:
        raw = ""

    parsed = extract_json_object(raw)
    parsed = normalize_v3_output(parsed)

    report_text = str(parsed.get("informe_final") or "")
    warnings = parsed.get("advertencias")
    if not isinstance(warnings, list):
        warnings = []

    if not template_text.strip():
        warnings.append("V3: plantilla seleccionada sin contenido; no se puede hacer mezcla con plantilla completa.")
    else:
        expected = _template_headings(template_text)
        missing = [h for h in expected if h.lower() not in report_text.lower()]

        if len(report_text.strip()) < max(350, int(len(template_text.strip()) * 0.25)):
            warnings.append(
                "V3: el informe final parece demasiado corto respecto de la plantilla; probablemente es resumen y no plantilla editada."
            )

        if expected and missing:
            warnings.append(
                "V3: el informe final no conserva encabezados esperados de la plantilla: "
                + ", ".join(missing[:8])
            )

    parsed["advertencias"] = warnings
    parsed = validate_report_payload(parsed)

    # Forzar trazabilidad V3 después de validar.
    parsed["ok"] = bool(parsed.get("ok", True))
    parsed["metodo"] = "iad_v3_clean_parallel"
    parsed["iad_audio_flow_mode"] = "v3"

    parsed["v3_bridge"] = {
        "ok": bool(parsed.get("ok", True)),
        "model": model,
        "template_id": plantilla.get("id") or "",
        "template_name": plantilla.get("nombre") or plantilla.get("template_name") or "",
        "template_content_chars": len(template_text),
        "report_chars": len(report_text),
        "expected_template_headings": _template_headings(template_text),
        "raw_preview": raw[:2000],
    }

    return parsed
