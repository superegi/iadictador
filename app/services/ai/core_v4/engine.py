from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

from .json_utils import extract_json_object
from .prompt import build_prompt
from .usage import UsageLog, now_ms


def read_text_file(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def write_text(path: str | Path, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(str(text or ""), encoding="utf-8")


def write_json(path: str | Path, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def transcribe_audio_files(
    audio_paths: list[str | Path],
    usage_log: UsageLog | None = None,
) -> str:
    if not audio_paths:
        raise ValueError("No se recibieron audios.")

    client = OpenAI()
    model = os.getenv("IAD_AI_MODEL_TRANSCRIBE", "gpt-4o-mini-transcribe")

    parts: list[str] = []

    for idx, audio_path in enumerate(audio_paths, start=1):
        p = Path(audio_path)
        if not p.exists():
            raise FileNotFoundError(str(p))

        started = now_ms()
        with p.open("rb") as f:
            result = client.audio.transcriptions.create(
                model=model,
                file=f,
                language="es",
            )
        ended = now_ms()

        text = getattr(result, "text", "") or str(result)

        if usage_log is not None:
            usage_log.add(
                stage="transcription",
                provider="openai",
                model=model,
                started_at_ms=started,
                ended_at_ms=ended,
                usage=getattr(result, "usage", None),
                extra={
                    "audio_index": idx,
                    "audio_file": str(p),
                    "output_chars": len(text),
                },
            )

        parts.append(f"[Audio {idx}: {p.name}]\n{text.strip()}")

    return "\n\n".join(parts).strip()


def build_report(
    *,
    transcripcion: str,
    reglas: str,
    plantilla: dict[str, Any],
    texto_adicional: str = "",
    usage_log: UsageLog | None = None,
) -> tuple[dict[str, Any], str, str]:
    client = OpenAI()
    model = (
        os.getenv("IAD_AI_MODEL_REPORT_V4")
        or os.getenv("IAD_AI_MODEL_AUDIO_FIRST_TEMPLATE_BRIDGE")
        or os.getenv("OPENAI_MODEL")
        or "gpt-4o-mini"
    )

    prompt = build_prompt(
        transcripcion=transcripcion,
        reglas=reglas,
        plantilla=plantilla,
        texto_adicional=texto_adicional,
    )

    kwargs = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Eres un editor estricto de plantillas radiológicas. "
                    "Devuelve solo JSON válido. "
                    "El informe_final debe ser la plantilla editada, con saltos de línea. "
                    "Extrae metadata_clinica en la misma respuesta."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    started = now_ms()
    try:
        completion = client.chat.completions.create(**kwargs)
    except Exception:
        kwargs.pop("response_format", None)
        completion = client.chat.completions.create(**kwargs)
    ended = now_ms()

    if usage_log is not None:
        usage_log.add(
            stage="report_generation",
            provider="openai",
            model=model,
            started_at_ms=started,
            ended_at_ms=ended,
            usage=getattr(completion, "usage", None),
            extra={
                "template_name": plantilla.get("nombre") or "",
                "template_chars": len(str(plantilla.get("contenido") or "")),
                "transcription_chars": len(str(transcripcion or "")),
                "rules_chars": len(str(reglas or "")),
            },
        )

    raw = completion.choices[0].message.content or ""
    data = extract_json_object(raw)

    if not isinstance(data, dict):
        data = {}

    data.setdefault("ok", True)
    data["metodo"] = "core_v4_audio_rules_template"
    data.setdefault("transcripcion", transcripcion)

    data.setdefault(
        "metadata_clinica",
        {
            "nombre_paciente": "",
            "edad": "",
            "sexo": "",
            "centro": "",
            "estudio": "",
            "antecedentes": "",
            "tecnica": "",
        },
    )

    if not isinstance(data.get("metadata_clinica"), dict):
        data["metadata_clinica"] = {
            "nombre_paciente": "",
            "edad": "",
            "sexo": "",
            "centro": "",
            "estudio": "",
            "antecedentes": "",
            "tecnica": "",
        }

    data.setdefault(
        "plantilla_usada",
        {
            "id": plantilla.get("id") or "",
            "nombre": plantilla.get("nombre") or "",
            "source": plantilla.get("source") or "",
        },
    )

    data.setdefault("hallazgos_estructurados", [])
    data.setdefault("advertencias", [])
    data.setdefault("posibles_omisiones", [])
    data.setdefault("impresion_diagnostica", "")

    if not isinstance(data["advertencias"], list):
        data["advertencias"] = [str(data["advertencias"])]

    informe = str(data.get("informe_final") or "")
    template_text = str(plantilla.get("contenido") or "")

    if template_text and "\n" in template_text and "\n" not in informe:
        data["advertencias"].append(
            "V4: informe_final no contiene saltos de línea pese a que la plantilla sí los tenía."
        )

    if template_text and len(informe.strip()) < max(300, int(len(template_text.strip()) * 0.25)):
        data["advertencias"].append(
            "V4: informe_final parece demasiado corto respecto de la plantilla."
        )

    if "xxxxx" in informe.lower():
        data["advertencias"].append("V4: informe_final todavía contiene xxxxx.")

    data["v4_debug"] = {
        "model": model,
        "template_chars": len(template_text),
        "report_chars": len(informe),
        "report_newlines": informe.count("\n"),
        "raw_preview": raw[:2000],
    }

    return data, prompt, raw
