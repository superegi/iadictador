from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from openai import OpenAI

from .engine import build_report, transcribe_audio_files, write_json, write_text
from .audio_merge import merge_audio_files_for_transcription
from .json_utils import extract_json_object
from .template_store import (
    build_template_catalog,
    find_template_by_id_or_name,
    load_available_templates,
)
from .usage import UsageLog, now_ms
from .persistence import persist_v4_job
from .rules_store import load_effective_rules, write_job_rule_audit


class CoreV4WebError(RuntimeError):
    pass


def _upload_base_dir() -> Path:
    return Path(os.getenv("IADICTADOR_UPLOAD_DIR", "/data/uploads_iadictador"))


def _rules_path() -> Path:
    return Path(os.getenv("IAD_RULES_FILE", "/data/reglas_radiologicas.md"))



def _normalize_extra_context(extra_context: str) -> tuple[str, dict[str, Any]]:
    raw = str(extra_context or "").strip()

    meta: dict[str, Any] = {
        "raw_chars": len(raw),
        "parsed_json": False,
        "keys": [],
        "used_fields": [],
    }

    if not raw:
        return "", meta

    ignored_keys = {
        "url",
        "title",
        "selected_template",
        "note",
        "flow",
        "debug",
    }

    priority_keys = [
        "user_complement_text",
        "texto_complementario_usuario",
        "extra_context_user_text",
        "texto_complementario",
        "complemento",
        "complementary_text",
        "patient_visible",
        "antecedentes",
        "centro",
        "nombre",
        "edad",
        "sexo",
    ]

    try:
        obj = json.loads(raw)
    except Exception:
        meta["parsed_json"] = False
        return raw, meta

    if not isinstance(obj, dict):
        return raw, meta

    meta["parsed_json"] = True
    meta["keys"] = list(obj.keys())

    parts: list[str] = []

    for key in priority_keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}: {value.strip()}")
            meta["used_fields"].append(key)

    # Agregar otros campos útiles no técnicos.
    for key, value in obj.items():
        if key in ignored_keys or key in priority_keys:
            continue
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}: {value.strip()}")
            meta["used_fields"].append(key)

    text = "\n".join(parts).strip()
    return text, meta

def _read_rules() -> str:
    path = _rules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "# Reglas radiológicas generales\n\n"
            "- No omitir hallazgos positivos dictados.\n"
            "- El informe final debe ser la plantilla completa editada.\n"
            "- Todo hallazgo positivo en Impresión diagnóstica debe estar descrito en Hallazgos.\n"
            "- No dejar bloques xxxxx ni alternativas contradictorias.\n",
            encoding="utf-8",
        )
    return path.read_text(encoding="utf-8")


async def _save_uploads(audio_files: list[Any], job_dir: Path) -> list[Path]:
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []

    for idx, upload in enumerate(audio_files or [], start=1):
        name = getattr(upload, "filename", "") or f"audio_{idx}.webm"
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
        path = audio_dir / f"{idx:02d}_{safe}"

        data = await upload.read()
        if not data:
            continue

        path.write_bytes(data)
        paths.append(path)

    if not paths:
        raise CoreV4WebError("No se recibieron audios válidos.")

    return paths


def _select_template_with_ai(
    *,
    client: OpenAI,
    transcript: str,
    extra_context: str,
    catalog: list[dict[str, Any]],
    job_dir: Path,
    usage_log: UsageLog | None = None,
) -> dict[str, Any]:
    model = (
        os.getenv("IAD_AI_MODEL_TEMPLATE_SELECT")
        or os.getenv("IAD_AI_MODEL_REPORT_V4")
        or os.getenv("OPENAI_MODEL")
        or "gpt-4o-mini"
    )

    prompt = f"""
Debes seleccionar la plantilla radiológica más adecuada.

Usa la transcripción y el texto adicional para elegir UNA plantilla del catálogo.

Regla crítica:
Si el médico dicta explícitamente el tipo de examen, esa instrucción manda sobre los hallazgos incidentales.
No elijas TC TAP solo porque se mencione hígado u otro órgano abdominal incidental en un TC de tórax.

TRANSCRIPCIÓN:
{transcript}

TEXTO ADICIONAL:
{extra_context}

CATÁLOGO DE PLANTILLAS:
{json.dumps(catalog, ensure_ascii=False, indent=2)}

Devuelve SOLO JSON válido:
{{
  "template_id": "",
  "template_name": "",
  "confidence": "alta|media|baja",
  "reason": ""
}}
""".strip()

    write_text(job_dir / "v4_template_selection_prompt.txt", prompt)

    kwargs = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Selecciona una plantilla de informe radiológico. Devuelve solo JSON válido.",
            },
            {
                "role": "user",
                "content": prompt,
            },
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
            stage="template_selection",
            provider="openai",
            model=model,
            started_at_ms=started,
            ended_at_ms=ended,
            usage=getattr(completion, "usage", None),
            extra={
                "templates_in_catalog": len(catalog),
                "transcription_chars": len(str(transcript or "")),
            },
        )

    raw = completion.choices[0].message.content or ""
    write_text(job_dir / "v4_template_selection_raw.txt", raw)

    data = extract_json_object(raw)
    if not isinstance(data, dict):
        data = {}

    data.setdefault("template_id", "")
    data.setdefault("template_name", "")
    data.setdefault("confidence", "baja")
    data.setdefault("reason", "Sin motivo devuelto por modelo.")
    data["model"] = model

    write_json(job_dir / "v4_template_selection.json", data)
    return data


async def process_web_endpoint_response(
    *,
    audio_files: list[Any],
    segments_metadata_json: str = "",
    extra_context: str = "",
    username: str = "",
    db: Any = None,
) -> dict[str, Any]:
    try:
        if not os.getenv("OPENAI_API_KEY"):
            raise CoreV4WebError("OPENAI_API_KEY no está configurada.")

        job_id = f"core_v4_{uuid.uuid4().hex[:16]}"
        job_dir = _upload_base_dir() / "core_v4_jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        usage_log = UsageLog(
            job_id=job_id,
            username=username,
            ot_id="",
        )

        raw_audio_paths = await _save_uploads(audio_files, job_dir)
        audio_paths, audio_merge_info = merge_audio_files_for_transcription(raw_audio_paths, job_dir)

        extra_context_normalized, extra_context_meta = _normalize_extra_context(extra_context)

        write_text(job_dir / "extra_context.txt", extra_context)
        write_text(job_dir / "extra_context_normalized.txt", extra_context_normalized)
        write_json(job_dir / "extra_context_meta.json", extra_context_meta)
        write_json(job_dir / "audio_merge.json", audio_merge_info)
        write_text(job_dir / "segments_metadata_json.txt", segments_metadata_json)

        transcript = transcribe_audio_files(audio_paths, usage_log=usage_log)

        rules_bundle = load_effective_rules(username=username)
        rules = rules_bundle["compiled_rules"]

        write_text(job_dir / "transcripcion.txt", transcript)
        write_text(job_dir / "reglas.md", rules)
        write_job_rule_audit(job_dir, rules_bundle)

        templates = load_available_templates(db, username=username)
        if not templates:
            raise CoreV4WebError("No hay plantillas disponibles para seleccionar.")

        catalog = build_template_catalog(templates)
        write_json(job_dir / "template_catalog.json", catalog)

        client = OpenAI()
        selection = _select_template_with_ai(
            client=client,
            transcript=transcript,
            extra_context=extra_context_normalized,
            catalog=catalog,
            job_dir=job_dir,
            usage_log=usage_log,
        )

        selected = find_template_by_id_or_name(
            templates,
            template_id=selection.get("template_id") or "",
            template_name=selection.get("template_name") or "",
        )

        if not selected:
            raise CoreV4WebError("No se pudo resolver la plantilla seleccionada.")

        write_json(job_dir / "selected_template_meta.json", selected)
        write_text(job_dir / "selected_template.txt", selected.get("contenido") or "")

        result, prompt, raw = build_report(
            transcripcion=transcript,
            reglas=rules,
            plantilla=selected,
            texto_adicional=extra_context_normalized,
            usage_log=usage_log,
        )

        informe = str(result.get("informe_final") or "")

        result["ok"] = bool(result.get("ok", True))
        result["metodo"] = "core_v4_audio_rules_template"
        result["metodo_visible"] = "core_v4_audio_rules_template"
        result["iad_audio_flow_mode"] = "v4"
        result["audio_first"] = False

        result["transcripcion"] = result.get("transcripcion") or transcript
        result["plantilla_sugerida"] = {
            "id": selected.get("id") or "",
            "nombre": selected.get("nombre") or "",
            "confianza": selection.get("confidence") or "media",
            "motivo": selection.get("reason") or "",
            "source": selected.get("source") or "",
        }

        result.setdefault("hallazgos_estructurados", [])
        result.setdefault("advertencias", [])
        result.setdefault("posibles_omisiones", [])
        result.setdefault("impresion_diagnostica", "")

        if not isinstance(result.get("metadata_clinica"), dict):
            result["metadata_clinica"] = {
                "nombre_paciente": "",
                "edad": "",
                "sexo": "",
                "centro": "",
                "estudio": "",
                "antecedentes": "",
                "tecnica": "",
            }

        result["openai_usage"] = usage_log.to_dict()

        result["v4_debug"] = {
            **(result.get("v4_debug") if isinstance(result.get("v4_debug"), dict) else {}),
            "job_id": job_id,
            "job_dir": str(job_dir),
            "audio_files_received": len(raw_audio_paths),
            "audio_files_transcribed": len(audio_paths),
            "audio_merge": audio_merge_info,
            "extra_context_meta": extra_context_meta,
            "templates_available": len(templates),
            "selected_template_id": selected.get("id") or "",
            "selected_template_name": selected.get("nombre") or "",
            "selected_template_chars": len(str(selected.get("contenido") or "")),
            "rules_manifest": rules_bundle.get("manifest", {}),
            "report_chars": len(informe),
            "report_newlines": informe.count("\n"),
        }

        result["audio_composition"] = {
            "job_id": job_id,
            "metadata": {
                "segments_metadata_json": segments_metadata_json,
                "username": username,
                "raw_audio_files": [str(p) for p in raw_audio_paths],
                "transcription_audio_files": [str(p) for p in audio_paths],
                "audio_merge": audio_merge_info,
                "extra_context_meta": extra_context_meta,
            },
            "debug_files": {
                "job_dir": str(job_dir),
                "transcripcion": str(job_dir / "transcripcion.txt"),
                "reglas": str(job_dir / "reglas.md"),
                "reglas_app": str(job_dir / "reglas_app.md"),
                "reglas_generales": str(job_dir / "reglas_generales.md"),
                "reglas_usuario": str(job_dir / "reglas_usuario.md"),
                "reglas_compiladas": str(job_dir / "reglas_compiladas.md"),
                "rules_manifest": str(job_dir / "rules_manifest.json"),
                "extra_context_normalized": str(job_dir / "extra_context_normalized.txt"),
                "extra_context_meta": str(job_dir / "extra_context_meta.json"),
                "audio_merge": str(job_dir / "audio_merge.json"),
                "template_catalog": str(job_dir / "template_catalog.json"),
                "selected_template": str(job_dir / "selected_template.txt"),
                "usage": str(job_dir / "usage.json"),
                "prompt": str(job_dir / "prompt.txt"),
                "raw_model_response": str(job_dir / "raw_model_response.txt"),
                "result": str(job_dir / "result.json"),
                "informe_final": str(job_dir / "informe_final.txt"),
            },
        }

        result["auto_persist"] = persist_v4_job(
            db=db,
            job_id=job_id,
            job_dir=str(job_dir),
            result=result,
            username=username,
            selected_template=selected,
            transcript=transcript,
            extra_context_normalized=extra_context_normalized,
            audio_merge_info=audio_merge_info,
        )

        write_text(job_dir / "prompt.txt", prompt)
        write_text(job_dir / "raw_model_response.txt", raw)
        write_json(job_dir / "usage.json", result["openai_usage"])
        write_json(job_dir / "result.json", result)
        write_text(job_dir / "informe_final.txt", informe)

        return result

    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "metodo": "core_v4_audio_rules_template",
            "metodo_visible": "core_v4_audio_rules_template",
            "iad_audio_flow_mode": "v4",
        }
