from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

from .report_bridge import build_report_with_ai
from .rules_store import read_rules_text


class IADV3Error(RuntimeError):
    pass


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _write_debug_json(path: Path, data: Any) -> None:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _write_debug_text(path: Path, text: str) -> None:
    try:
        path.write_text(str(text or ""), encoding="utf-8")
    except Exception:
        pass


async def process_v3_audio_first_uploads(
    *,
    audio_files: list[Any],
    segments_metadata_json: str = "",
    extra_context: str = "",
    username: str = "",
    db: Any = None,
) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise IADV3Error("OPENAI_API_KEY no está configurada.")

    # Reutilizamos solo composición + audio-first base.
    # NO usamos el bridge legacy ni sus wrappers.
    from app.services.ai.tasks.audio_first_flow import (
        compose_audio_uploads,
        _audio_first_prompt,
        _openai_audio_first_completion,
        _completion_to_debug_files,
        _message_text_candidates,
        _parse_audio_first_candidates,
        _safe_write_text,
        _iad_v2_pick_template,
    )

    composed = await compose_audio_uploads(
        audio_files=audio_files,
        segments_metadata_json=segments_metadata_json,
        username=username,
    )

    audio_path = Path(composed["audio_compuesto_ai"])
    audio_format = composed["audio_compuesto_ai_format"]
    metadata = composed["metadata"]
    job_dir = Path(composed["job_dir"])

    audio_b64 = base64.b64encode(audio_path.read_bytes()).decode("utf-8")

    audio_prompt = _audio_first_prompt(
        metadata=metadata,
        extra_context=extra_context,
        db=db,
    )

    client = OpenAI()

    completion = _openai_audio_first_completion(
        client=client,
        prompt=audio_prompt,
        audio_b64=audio_b64,
        audio_format=audio_format,
    )

    _completion_to_debug_files(completion, job_dir)

    candidates = _message_text_candidates(completion)
    _safe_write_text(
        job_dir / "v3_openai_audio_first_text_candidates.txt",
        "\n\n--- CANDIDATE ---\n\n".join(candidates),
    )

    audio_first_raw = _parse_audio_first_candidates(candidates)
    if not isinstance(audio_first_raw, dict):
        audio_first_raw = {"raw": str(audio_first_raw)}

    audio_first_raw.setdefault("ok", True)
    audio_first_raw.setdefault("metodo", "audio_first_v3_base")

    transcripcion = _first_text(
        audio_first_raw.get("transcripcion"),
        audio_first_raw.get("transcription"),
        audio_first_raw.get("raw_audio_first_text"),
        "\n".join(candidates),
    )

    template = _iad_v2_pick_template(audio_first_raw, db=db)
    if not template:
        template = {
            "id": "",
            "nombre": "",
            "source": "",
            "contenido": "",
        }

    reglas = read_rules_text()

    _write_debug_text(job_dir / "v3_template.txt", str(template.get("contenido") or ""))
    _write_debug_json(job_dir / "v3_template_meta.json", template)
    _write_debug_text(job_dir / "v3_rules.txt", reglas)
    _write_debug_text(job_dir / "v3_transcripcion.txt", transcripcion)
    _write_debug_json(job_dir / "v3_audio_first_raw.json", audio_first_raw)

    bridged = build_report_with_ai(
        client=client,
        transcripcion=transcripcion,
        texto_adicional=extra_context,
        plantilla=template,
        reglas_generales=reglas,
        audio_first_raw=audio_first_raw,
        metadata=metadata,
    )

    if not str(bridged.get("transcripcion") or "").strip():
        bridged["transcripcion"] = transcripcion

    # Forzar trazabilidad al final.
    bridged["ok"] = bool(bridged.get("ok", True))
    bridged["audio_first"] = True
    bridged["metodo"] = "iad_v3_clean_parallel"
    bridged["iad_audio_flow_mode"] = "v3"

    bridged["audio_composition"] = {
        "job_id": composed.get("job_id"),
        "audio_compuesto_ai_format": audio_format,
        "metadata": metadata,
        "debug_files": {
            "raw_response": str(job_dir / "openai_audio_first_raw_response.json"),
            "text_candidates": str(job_dir / "v3_openai_audio_first_text_candidates.txt"),
            "v3_template": str(job_dir / "v3_template.txt"),
            "v3_template_meta": str(job_dir / "v3_template_meta.json"),
            "v3_rules": str(job_dir / "v3_rules.txt"),
            "v3_transcripcion": str(job_dir / "v3_transcripcion.txt"),
            "v3_audio_first_raw": str(job_dir / "v3_audio_first_raw.json"),
            "v3_result": str(job_dir / "v3_result.json"),
        },
    }

    bridged["v3_debug"] = {
        "template_id": template.get("id"),
        "template_name": template.get("nombre"),
        "template_source": template.get("source"),
        "template_content_chars": len(str(template.get("contenido") or "")),
        "rules_file": os.getenv("IAD_RULES_FILE", "/data/reglas_radiologicas.md"),
        "legacy_wrappers_used": False,
        "note": "V3 reutiliza composición/transcripción legacy, pero no usa el bridge legacy ni sus wrappers.",
    }

    bridged["audio_first_original"] = audio_first_raw

    _write_debug_json(job_dir / "v3_result.json", bridged)

    return bridged


async def process_v3_endpoint_response(
    *,
    audio_files: list[Any],
    segments_metadata_json: str = "",
    extra_context: str = "",
    username: str = "",
    db: Any = None,
) -> dict[str, Any]:
    try:
        return await process_v3_audio_first_uploads(
            audio_files=audio_files,
            segments_metadata_json=segments_metadata_json,
            extra_context=extra_context,
            username=username,
            db=db,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "metodo": "iad_v3_clean_parallel",
            "iad_audio_flow_mode": "v3",
        }
