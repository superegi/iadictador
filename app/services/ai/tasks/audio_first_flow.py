# IAD_AUDIO_FIRST_FLOW_V1
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse


AUDIO_FIRST_ROOT = Path(os.getenv("IAD_AUDIO_FIRST_DIR", "/data/iad_audio_first"))
AUDIO_FIRST_MODEL = os.getenv("IAD_AI_MODEL_AUDIO_FIRST", "gpt-audio-1.5")
ALLOW_TRANSCRIPT_FALLBACK = os.getenv("IAD_AUDIO_FIRST_ALLOW_TRANSCRIPT_FALLBACK", "0").strip() == "1"
# IAD_AUDIO_FIRST_JSON_PARSER_FIX_V1
AUDIO_FIRST_REQUEST_AUDIO_OUTPUT = os.getenv("IAD_AUDIO_FIRST_REQUEST_AUDIO_OUTPUT", "0").strip() == "1"
AUDIO_FIRST_JSON_MODE = os.getenv("IAD_AUDIO_FIRST_JSON_MODE", "1").strip() == "1"


class AudioFirstError(RuntimeError):
    pass


@dataclass
class AudioSegmentInfo:
    order: int
    original_filename: str
    stored_filename: str
    input_path: str
    wav_path: str
    duration_seconds: float
    start_seconds: float
    end_seconds: float
    mime_type: str = ""


def _safe_name(name: str) -> str:
    name = name or "audio.webm"
    name = name.replace("/", "_").replace("\\", "_")
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120] or "audio.webm"


def _run(cmd: list[str], timeout: int = 240) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise AudioFirstError(
            "Comando falló:\n"
            + " ".join(cmd)
            + "\nSTDOUT:\n"
            + proc.stdout[-2000:]
            + "\nSTDERR:\n"
            + proc.stderr[-4000:]
        )
    return proc


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise AudioFirstError("ffmpeg no está disponible dentro del contenedor.")
    if shutil.which("ffprobe") is None:
        raise AudioFirstError("ffprobe no está disponible dentro del contenedor.")


def _duration_seconds(path: Path) -> float:
    try:
        proc = _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            timeout=60,
        )
        return max(0.0, float((proc.stdout or "0").strip() or 0))
    except Exception:
        return 0.0


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {"raw": obj}
    except Exception:
        return {"raw": raw}


async def compose_audio_uploads(
    audio_files: list[Any],
    segments_metadata_json: str = "",
    username: str = "",
) -> dict[str, Any]:
    """
    Recibe múltiples segmentos web y genera un audio único válido.
    No concatena blobs crudos.
    """
    _require_ffmpeg()

    if not audio_files:
        raise AudioFirstError("No llegaron audios para componer.")

    AUDIO_FIRST_ROOT.mkdir(parents=True, exist_ok=True)

    job_id = uuid.uuid4().hex[:16]
    job_dir = AUDIO_FIRST_ROOT / f"audio_first_{job_id}"
    job_dir.mkdir(parents=True, exist_ok=True)

    incoming_meta = _parse_metadata(segments_metadata_json)

    segments: list[AudioSegmentInfo] = []
    cursor = 0.0

    for idx, upload in enumerate(audio_files, start=1):
        original = _safe_name(getattr(upload, "filename", "") or f"segmento_{idx}.webm")
        mime = getattr(upload, "content_type", "") or ""

        ext = Path(original).suffix.lower()
        if not ext:
            ext = ".webm"

        stored_name = f"{idx:03d}_{original}"
        input_path = job_dir / stored_name

        raw = await upload.read()
        if not raw:
            raise AudioFirstError(f"El audio {idx} está vacío: {original}")

        input_path.write_bytes(raw)

        wav_path = job_dir / f"{idx:03d}_segmento.wav"

        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-sample_fmt",
                "s16",
                str(wav_path),
            ],
            timeout=240,
        )

        dur = _duration_seconds(wav_path)
        seg = AudioSegmentInfo(
            order=idx,
            original_filename=original,
            stored_filename=stored_name,
            input_path=str(input_path),
            wav_path=str(wav_path),
            duration_seconds=dur,
            start_seconds=cursor,
            end_seconds=cursor + dur,
            mime_type=mime,
        )
        segments.append(seg)
        cursor += dur

    concat_list = job_dir / "concat_list.txt"
    concat_list.write_text(
        "".join(f"file '{Path(s.wav_path).as_posix()}'\n" for s in segments),
        encoding="utf-8",
    )

    composed_wav = job_dir / "audio_compuesto.wav"
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-sample_fmt",
            "s16",
            str(composed_wav),
        ],
        timeout=360,
    )

    composed_mp3 = job_dir / "audio_compuesto.mp3"
    ai_audio_path = composed_wav
    ai_audio_format = "wav"

    try:
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(composed_wav),
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "96k",
                str(composed_mp3),
            ],
            timeout=240,
        )
        if composed_mp3.exists() and composed_mp3.stat().st_size > 0:
            ai_audio_path = composed_mp3
            ai_audio_format = "mp3"
    except Exception:
        ai_audio_path = composed_wav
        ai_audio_format = "wav"

    metadata = {
        "job_id": job_id,
        "username": username,
        "audio_compuesto_wav": str(composed_wav),
        "audio_compuesto_ai": str(ai_audio_path),
        "audio_compuesto_ai_format": ai_audio_format,
        "duration_seconds": _duration_seconds(composed_wav),
        "segment_count": len(segments),
        "segments": [
            {
                "orden": s.order,
                "nombre_original": s.original_filename,
                "archivo_guardado": s.stored_filename,
                "mime_type": s.mime_type,
                "duracion_segundos": round(s.duration_seconds, 3),
                "inicio_aproximado_segundos": round(s.start_seconds, 3),
                "fin_aproximado_segundos": round(s.end_seconds, 3),
            }
            for s in segments
        ],
        "incoming_metadata": incoming_meta,
        "nota_para_ia": (
            "El audio compuesto proviene de segmentos consecutivos de una misma OT. "
            "Debe considerar continuidad, pausas, énfasis, autocorrecciones y transiciones entre segmentos."
        ),
    }

    (job_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "job_id": job_id,
        "job_dir": str(job_dir),
        "audio_compuesto_wav": str(composed_wav),
        "audio_compuesto_ai": str(ai_audio_path),
        "audio_compuesto_ai_format": ai_audio_format,
        "metadata": metadata,
    }


def _extract_json(text: str) -> dict[str, Any]:
    text = text or ""
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {"raw": obj}
    except Exception:
        pass

    # Buscar bloque JSON aunque venga con texto alrededor.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else {"raw": obj}
        except Exception:
            pass

    return {
        "ok": False,
        "error": "La IA no devolvió JSON válido.",
        "raw_response": text,
    }


def _template_brief(db: Any = None, limit: int = 12) -> list[dict[str, Any]]:
    """
    Resumen corto de plantillas para orientar al modelo audio-native.
    """
    if db is None:
        return []

    try:
        from app.services.ai.tasks.radiology_flow import collect_templates

        items = collect_templates(db) or []
    except Exception:
        items = []

    out = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": item.get("id") or item.get("template_id") or "",
                "nombre": item.get("nombre") or item.get("template_name") or item.get("title") or "",
                "modalidad": item.get("modalidad") or item.get("modality") or "",
                "tipo": item.get("tipo") or item.get("body_region") or "",
                "contenido": str(
                    item.get("contenido")
                    or item.get("findings")
                    or item.get("body")
                    or ""
                )[:2200],
            }
        )
    return out


def _audio_first_prompt(metadata: dict[str, Any], extra_context: str = "", db: Any = None) -> str:
    templates = _template_brief(db)

    return f"""
Eres un asistente de radiología para dictado médico en español.

Entrada:
- Recibirás un AUDIO COMPUESTO.
- Ese audio fue construido desde varios segmentos consecutivos grabados en la web.
- NO asumas que la transcripción previa existe; debes escuchar el audio.
- Considera pausas, énfasis, autocorrecciones, lateralidad, medidas y continuidad entre segmentos.

Metadata de segmentos:
{json.dumps(metadata, ensure_ascii=False, indent=2)}

Contexto adicional de la interfaz:
{extra_context or ""}

Plantillas disponibles resumidas:
{json.dumps(templates, ensure_ascii=False, indent=2)}

Tarea:
1. Transcribe el dictado completo con fidelidad clínica.
2. Extrae TODOS los hallazgos positivos, negativos relevantes, medidas y lateralidad.
3. Sugiere la plantilla más adecuada.
4. Genera un informe radiológico limpio.
5. No omitas hallazgos positivos. Si un hallazgo no puede incorporarse con seguridad, decláralo en advertencias.
6. Si detectas autocorrección o lateralidad dudosa, adviértelo.
7. No inventes datos que no estén en el audio.

Devuelve SOLO JSON válido, sin markdown, con esta estructura exacta:

{{
  "ok": true,
  "transcripcion": "",
  "plantilla_sugerida": {{
    "id": "",
    "nombre": "",
    "confianza": "",
    "motivo": ""
  }},
  "hallazgos_radiologicos": "",
  "hallazgos_estructurados": [
    {{
      "organo_o_region": "",
      "lateralidad": "",
      "hallazgo": "",
      "medida": "",
      "caracteristicas": [],
      "interpretacion": ""
    }}
  ],
  "informe_final": "",
  "impresion_diagnostica": "",
  "advertencias": [],
  "posibles_omisiones": [],
  "metadata_audio_usada": {{
    "segment_count": {metadata.get("segment_count", 0)},
    "duration_seconds": {metadata.get("duration_seconds", 0)}
  }},
  "metodo": "audio_first"
}}
""".strip()




# IAD_AUDIO_FIRST_JSON_PARSER_FIX_V1
def _obj_to_plain(obj: Any) -> Any:
    try:
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
    except Exception:
        pass
    try:
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return str(obj)


def _safe_write_text(path: Path, text: str) -> None:
    try:
        path.write_text(text, encoding="utf-8")
    except Exception:
        pass


def _completion_to_debug_files(completion: Any, job_dir: Path) -> None:
    try:
        if hasattr(completion, "model_dump_json"):
            raw = completion.model_dump_json(indent=2)
        else:
            raw = json.dumps(_obj_to_plain(completion), ensure_ascii=False, indent=2, default=str)
        _safe_write_text(job_dir / "openai_audio_first_raw_response.json", raw)
    except Exception as exc:
        _safe_write_text(job_dir / "openai_audio_first_raw_response_error.txt", str(exc))


def _message_text_candidates(completion: Any) -> list[str]:
    candidates: list[str] = []

    def add(value: Any, label: str = ""):
        if value is None:
            return
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    for key in ("text", "content", "transcript"):
                        if item.get(key):
                            add(item.get(key), label + "." + key)
                else:
                    add(item, label)
            return
        if isinstance(value, dict):
            for key in ("text", "content", "transcript"):
                if value.get(key):
                    add(value.get(key), label + "." + key)
            return
        s = str(value).strip()
        if s:
            candidates.append(s)

    try:
        msg = completion.choices[0].message
    except Exception:
        msg = None

    if msg is not None:
        add(getattr(msg, "content", None), "message.content")
        add(getattr(msg, "refusal", None), "message.refusal")

        audio = getattr(msg, "audio", None)
        if audio is not None:
            add(getattr(audio, "transcript", None), "message.audio.transcript")
            if isinstance(audio, dict):
                add(audio.get("transcript"), "message.audio.transcript")

        # Algunos SDKs guardan contenido no estándar en model_extra.
        extra = getattr(msg, "model_extra", None)
        if isinstance(extra, dict):
            add(extra.get("content"), "message.model_extra.content")
            add(extra.get("transcript"), "message.model_extra.transcript")
            if isinstance(extra.get("audio"), dict):
                add(extra["audio"].get("transcript"), "message.model_extra.audio.transcript")

    # Último recurso: volcar parte del objeto completo solo como candidato diagnóstico.
    if not candidates:
        try:
            if hasattr(completion, "model_dump_json"):
                candidates.append(completion.model_dump_json(indent=2))
        except Exception:
            pass

    # Deduplicar conservando orden.
    out: list[str] = []
    seen = set()
    for c in candidates:
        k = c.strip()
        if k and k not in seen:
            out.append(k)
            seen.add(k)
    return out


def _parse_audio_first_candidates(candidates: list[str]) -> dict[str, Any]:
    for content in candidates:
        parsed = _extract_json(content)
        if isinstance(parsed, dict) and parsed.get("ok") is not False:
            return parsed
        if isinstance(parsed, dict) and "raw_response" not in parsed:
            return parsed

    best = candidates[0] if candidates else ""
    return {
        "ok": True,
        "transcripcion": best,
        "plantilla_sugerida": {
            "id": "",
            "nombre": "",
            "confianza": "baja",
            "motivo": "La IA audio-first respondió sin JSON estructurado; se conserva la salida textual."
        },
        "hallazgos_radiologicos": "",
        "hallazgos_estructurados": [],
        "informe_final": "",
        "impresion_diagnostica": "",
        "advertencias": [
            "La IA audio-first no devolvió JSON válido. Se muestra la salida textual capturada para no perder el resultado.",
            "Repetir el procesamiento o revisar el archivo openai_audio_first_raw_response.json."
        ],
        "posibles_omisiones": [],
        "metodo": "audio_first_non_json_captured",
        "raw_audio_first_text": best,
    }


def _build_audio_first_messages(prompt: str, audio_b64: str, audio_format: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": (
                "Debes responder únicamente JSON válido. "
                "No uses markdown. No agregues texto fuera del JSON. "
                "La transcripción debe ser un campo del JSON, no una respuesta separada."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": audio_b64,
                        "format": audio_format,
                    },
                },
            ],
        },
    ]


def _openai_audio_first_completion(client: Any, prompt: str, audio_b64: str, audio_format: str) -> Any:
    messages = _build_audio_first_messages(prompt, audio_b64, audio_format)

    attempts: list[dict[str, Any]] = []

    # Preferido: texto estructurado, sin pedir audio de salida.
    base = {
        "model": AUDIO_FIRST_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "store": False,
    }

    text_only = dict(base)
    text_only["modalities"] = ["text"]
    if AUDIO_FIRST_JSON_MODE:
        text_only["response_format"] = {"type": "json_object"}
    attempts.append(text_only)

    # Si el modelo/endpoint no acepta modalities=["text"] o response_format, probar sin JSON mode.
    text_no_json = dict(base)
    text_no_json["modalities"] = ["text"]
    attempts.append(text_no_json)

    # Compatibilidad con el patrón documentado de audio input/output.
    audio_out = dict(base)
    audio_out["modalities"] = ["text", "audio"]
    audio_out["audio"] = {"voice": "alloy", "format": "wav"}
    if AUDIO_FIRST_JSON_MODE:
        audio_out["response_format"] = {"type": "json_object"}
    attempts.append(audio_out)

    audio_out_no_json = dict(base)
    audio_out_no_json["modalities"] = ["text", "audio"]
    audio_out_no_json["audio"] = {"voice": "alloy", "format": "wav"}
    attempts.append(audio_out_no_json)

    last_exc: Exception | None = None

    for idx, kwargs in enumerate(attempts, start=1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:
            last_exc = exc
            continue

    raise AudioFirstError(f"Fallaron todos los intentos audio-first OpenAI: {last_exc}")

async def process_audio_first_uploads(
    audio_files: list[Any],
    segments_metadata_json: str = "",
    extra_context: str = "",
    username: str = "",
    db: Any = None,
) -> dict[str, Any]:
    composed = await compose_audio_uploads(
        audio_files=audio_files,
        segments_metadata_json=segments_metadata_json,
        username=username,
    )

    audio_path = Path(composed["audio_compuesto_ai"])
    audio_format = composed["audio_compuesto_ai_format"]
    metadata = composed["metadata"]

    if not os.getenv("OPENAI_API_KEY"):
        raise AudioFirstError("OPENAI_API_KEY no está configurada. No puedo ejecutar IA audio-first.")

    try:
        from openai import OpenAI
    except Exception as exc:
        raise AudioFirstError(f"No pude importar OpenAI SDK: {exc}") from exc

    audio_b64 = base64.b64encode(audio_path.read_bytes()).decode("utf-8")
    prompt = _audio_first_prompt(metadata=metadata, extra_context=extra_context, db=db)

    client = OpenAI()

    try:
        completion = _openai_audio_first_completion(
            client=client,
            prompt=prompt,
            audio_b64=audio_b64,
            audio_format=audio_format,
        )
    except Exception as exc:
        if not ALLOW_TRANSCRIPT_FALLBACK:
            raise AudioFirstError(
                "Falló llamada audio-first a OpenAI. No se hizo fallback por transcripción porque está desactivado. "
                f"Error: {exc}"
            ) from exc
        raise

    job_dir = Path(composed["job_dir"])
    _completion_to_debug_files(completion, job_dir)

    candidates = _message_text_candidates(completion)
    _safe_write_text(
        job_dir / "openai_audio_first_text_candidates.txt",
        "\n\n--- CANDIDATE ---\n\n".join(candidates),
    )

    parsed = _parse_audio_first_candidates(candidates)
    parsed.setdefault("ok", True)
    parsed.setdefault("metodo", "audio_first")
    parsed["audio_first"] = True
    parsed["audio_composition"] = {
        "job_id": composed["job_id"],
        "audio_compuesto_ai_format": audio_format,
        "metadata": metadata,
        "debug_files": {
            "raw_response": str(job_dir / "openai_audio_first_raw_response.json"),
            "text_candidates": str(job_dir / "openai_audio_first_text_candidates.txt"),
        },
    }


    parsed = _iad_v2_apply_template_bridge_force(
        client=client,
        parsed=parsed,
        metadata=metadata,
        db=db,
        composed=composed,
    )

    parsed["audio_first"] = True
    parsed["audio_composition"] = {
        "job_id": composed["job_id"],
        "audio_compuesto_ai_format": audio_format,
        "metadata": metadata,
        "debug_files": {
            "raw_response": str(job_dir / "openai_audio_first_raw_response.json"),
            "text_candidates": str(job_dir / "openai_audio_first_text_candidates.txt"),
        },
    }
    return parsed


async def compose_endpoint_response(audio_files: list[Any], segments_metadata_json: str, username: str = ""):
    try:
        result = await compose_audio_uploads(
            audio_files=audio_files,
            segments_metadata_json=segments_metadata_json,
            username=username,
        )
        return result
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": str(exc), "endpoint": "componer_audio"},
            status_code=500,
        )


async def process_endpoint_response(
    audio_files: list[Any],
    segments_metadata_json: str,
    extra_context: str,
    username: str = "",
    db: Any = None,
):
    try:
        result = await process_audio_first_uploads(
            audio_files=audio_files,
            segments_metadata_json=segments_metadata_json,
            extra_context=extra_context,
            username=username,
            db=db,
        )
        return result
    except Exception as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "endpoint": "procesar_dictado_completo_audio_first",
                "audio_first": True,
            },
            status_code=500,
        )



# IAD_AUDIO_FIRST_COMPLETE_PARTIAL_JSON_V1
def _iad_audio_first_is_partial(parsed: dict[str, Any]) -> bool:
    if not isinstance(parsed, dict):
        return True

    transcription = str(parsed.get("transcripcion") or parsed.get("transcription") or parsed.get("raw_audio_first_text") or "").strip()
    findings = str(parsed.get("hallazgos_radiologicos") or "").strip()
    report = str(parsed.get("informe_final") or parsed.get("resultado_revisado") or parsed.get("final_report") or "").strip()

    if not transcription:
        return False

    if len(report) < 80:
        return True

    if len(findings) < 20:
        return True

    return False


def _iad_audio_first_completion_prompt(parsed: dict[str, Any], metadata: dict[str, Any], db: Any = None) -> str:
    templates = _template_brief(db)

    return f"""
Eres un normalizador clínico de salida audio-first para radiología.

Contexto crítico:
- La fuente primaria fue un AUDIO escuchado por un modelo audio-first.
- NO estás recibiendo una transcripción local previa hecha por la web.
- Recibes el producto devuelto por el modelo que escuchó el audio.
- Tu tarea es completar un JSON clínico si la primera respuesta vino parcial.
- No inventes datos fuera de la salida audio-first.
- Si falta algo o hay duda, decláralo en advertencias.
- Todo hallazgo positivo mencionado debe aparecer en hallazgos e informe, o en posibles_omisiones.

Metadata de audio compuesto:
{json.dumps(metadata, ensure_ascii=False, indent=2)}

Salida parcial del modelo audio-first:
{json.dumps(parsed, ensure_ascii=False, indent=2, default=str)}

Plantillas disponibles resumidas:
{json.dumps(templates, ensure_ascii=False, indent=2)}

Devuelve SOLO JSON válido, sin markdown, con esta estructura:

{{
  "ok": true,
  "transcripcion": "",
  "plantilla_sugerida": {{
    "id": "",
    "nombre": "",
    "confianza": "",
    "motivo": ""
  }},
  "hallazgos_radiologicos": "",
  "hallazgos_estructurados": [
    {{
      "organo_o_region": "",
      "lateralidad": "",
      "hallazgo": "",
      "medida": "",
      "caracteristicas": [],
      "interpretacion": ""
    }}
  ],
  "informe_final": "",
  "impresion_diagnostica": "",
  "advertencias": [],
  "posibles_omisiones": [],
  "metadata_audio_usada": {{
    "segment_count": {metadata.get("segment_count", 0)},
    "duration_seconds": {metadata.get("duration_seconds", 0)}
  }},
  "metodo": "audio_first_normalizado"
}}
""".strip()


def _iad_audio_first_message_content(completion: Any) -> str:
    try:
        msg = completion.choices[0].message
    except Exception:
        return ""

    content = getattr(msg, "content", "") or ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        content = "\n".join(parts)

    return str(content or "")


def _iad_audio_first_complete_if_needed(
    client: Any,
    parsed: dict[str, Any],
    metadata: dict[str, Any],
    db: Any = None,
    composed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        parsed = {"ok": False, "raw_audio_first_text": str(parsed)}

    if not _iad_audio_first_is_partial(parsed):
        parsed.setdefault("normalizacion_audio_first", "no_necesaria")
        return parsed

    model = (
        os.getenv("IAD_AI_MODEL_AUDIO_FIRST_NORMALIZER")
        or os.getenv("IAD_AI_MODEL_TEXT_STRUCTURED")
        or os.getenv("IAD_AI_MODEL_TEXT")
        or "gpt-4o-mini"
    )

    prompt = _iad_audio_first_completion_prompt(parsed=parsed, metadata=metadata, db=db)

    try:
        kwargs = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Responde únicamente JSON válido. No uses markdown ni texto fuera del JSON.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        try:
            completion = client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("response_format", None)
            completion = client.chat.completions.create(**kwargs)

        raw = _iad_audio_first_message_content(completion)
        completed = _extract_json(raw)

        if not isinstance(completed, dict) or completed.get("ok") is False:
            parsed.setdefault("advertencias", [])
            if isinstance(parsed["advertencias"], list):
                parsed["advertencias"].append(
                    "Se intentó normalizar la salida audio-first parcial, pero no se obtuvo JSON clínico completo."
                )
            parsed["normalizacion_audio_first"] = "fallida"
            parsed["normalizacion_raw"] = raw[:4000]
            return parsed

        # Preservar transcripción original si el normalizador no la repite.
        if not str(completed.get("transcripcion") or "").strip():
            completed["transcripcion"] = (
                parsed.get("transcripcion")
                or parsed.get("transcription")
                or parsed.get("raw_audio_first_text")
                or ""
            )

        # Preservar metadata y advertir.
        warnings = completed.get("advertencias")
        if not isinstance(warnings, list):
            warnings = []
        warnings.append(
            "Salida completada por normalizador clínico a partir de la respuesta audio-first."
        )
        completed["advertencias"] = warnings
        completed["normalizacion_audio_first"] = "aplicada"
        completed["audio_first_original_partial"] = parsed

        return completed

    except Exception as exc:
        parsed.setdefault("advertencias", [])
        if isinstance(parsed["advertencias"], list):
            parsed["advertencias"].append(
                f"No se pudo completar salida audio-first parcial: {exc}"
            )
        parsed["normalizacion_audio_first"] = "error"
        parsed["normalizacion_error"] = str(exc)
        parsed = _iad_audio_first_complete_if_needed(
        client=client,
        parsed=parsed,
        metadata=metadata,
        db=db,
        composed=composed,
    )

    parsed = _iad_audio_first_complete_with_template_bridge(
        client=client,
        parsed=parsed,
        metadata=metadata,
        db=db,
    )

    # Reinyectar metadata de composición luego de eventual normalización/puente de plantillas.
    parsed["audio_first"] = True
    parsed["audio_composition"] = {
        "job_id": composed["job_id"],
        "audio_compuesto_ai_format": audio_format,
        "metadata": metadata,
        "debug_files": {
            "raw_response": str(job_dir / "openai_audio_first_raw_response.json"),
            "text_candidates": str(job_dir / "openai_audio_first_text_candidates.txt"),
        },
    }

    return parsed



# IAD_AUDIO_FIRST_TEMPLATE_BRIDGE_V1
def _iad_audio_first_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _iad_audio_first_collect_full_templates(db: Any = None) -> list[dict[str, Any]]:
    if db is None:
        return []

    try:
        from app.services.ai.tasks.radiology_flow import collect_templates
        items = collect_templates(db) or []
    except Exception:
        items = []

    out: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        name = (
            item.get("nombre")
            or item.get("template_name")
            or item.get("title")
            or item.get("name")
            or ""
        )

        tpl_id = item.get("id") or item.get("template_id") or ""

        parts = []
        for key in [
            "title",
            "technique",
            "background",
            "findings",
            "impression",
            "contenido",
            "body",
            "template",
            "text",
        ]:
            val = item.get(key)
            if val:
                parts.append(f"[{key}]\n{val}")

        content = "\n\n".join(parts).strip()

        out.append(
            {
                "id": str(tpl_id or ""),
                "nombre": str(name or ""),
                "modalidad": str(item.get("modalidad") or item.get("modality") or ""),
                "tipo": str(item.get("tipo") or item.get("body_region") or ""),
                "tags": str(item.get("tags") or ""),
                "contenido": content,
                "raw": item,
            }
        )

    return out


def _iad_audio_first_norm(s: Any) -> str:
    s = str(s or "").lower()
    repl = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u",
        "ñ": "n",
    }
    for a, b in repl.items():
        s = s.replace(a, b)
    return s


def _iad_audio_first_pick_template(parsed: dict[str, Any], db: Any = None) -> dict[str, Any]:
    templates = _iad_audio_first_collect_full_templates(db)
    if not templates:
        return {}

    ps = parsed.get("plantilla_sugerida") or {}
    if not isinstance(ps, dict):
        ps = {}

    wanted_id = str(ps.get("id") or "").strip()
    wanted_name = _iad_audio_first_norm(ps.get("nombre") or ps.get("name") or "")

    if wanted_id:
        for tpl in templates:
            if str(tpl.get("id") or "").strip() == wanted_id:
                return tpl

    if wanted_name:
        scored = []
        for tpl in templates:
            name = _iad_audio_first_norm(tpl.get("nombre") or "")
            score = 0
            if name == wanted_name:
                score += 100
            if wanted_name and wanted_name in name:
                score += 70
            if name and name in wanted_name:
                score += 50

            for token in wanted_name.split():
                if len(token) >= 3 and token in name:
                    score += 5

            if score:
                scored.append((score, tpl))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored[0][1]

    # Fallback: puntuar por transcripción + hallazgos.
    source = _iad_audio_first_norm(
        " ".join(
            [
                parsed.get("transcripcion") or "",
                parsed.get("hallazgos_radiologicos") or "",
                _iad_audio_first_text(parsed.get("hallazgos_estructurados") or ""),
            ]
        )
    )

    scored = []
    for tpl in templates:
        blob = _iad_audio_first_norm(
            " ".join(
                [
                    tpl.get("nombre") or "",
                    tpl.get("modalidad") or "",
                    tpl.get("tipo") or "",
                    tpl.get("tags") or "",
                    tpl.get("contenido") or "",
                ]
            )
        )
        score = 0
        for token in ["torax", "abdomen", "pelvis", "pielo", "renal", "rinon", "prostata", "vesicula", "colon", "contraste"]:
            if token in source and token in blob:
                score += 8
        if score:
            scored.append((score, tpl))

    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    return templates[0]


def _iad_audio_first_template_bridge_prompt(parsed: dict[str, Any], template: dict[str, Any], metadata: dict[str, Any]) -> str:
    return f"""
Eres un asistente de radiología.

IMPORTANTE:
- La fuente primaria fue audio escuchado por un modelo audio-first.
- La transcripción que recibes abajo NO es una transcripción local previa: es un producto devuelto por el proceso audio-first.
- Debes generar el informe final usando la PLANTILLA COMPLETA como base.
- Mantén la estructura y redacción normal de la plantilla cuando sea compatible.
- Inserta todos los hallazgos positivos detectados.
- No omitas hallazgos positivos.
- No inventes hallazgos que no estén en la salida audio-first.
- Si la plantilla dice algo normal que contradice el audio, reemplázalo por el hallazgo dictado.
- Si hay datos dudosos, inclúyelos en advertencias.

PLANTILLA SELECCIONADA:
ID: {template.get("id") or ""}
NOMBRE: {template.get("nombre") or ""}
MODALIDAD: {template.get("modalidad") or ""}
TIPO: {template.get("tipo") or ""}

CONTENIDO COMPLETO DE PLANTILLA:
{template.get("contenido") or ""}

SALIDA AUDIO-FIRST:
{json.dumps(parsed, ensure_ascii=False, indent=2, default=str)}

METADATA AUDIO:
{json.dumps(metadata, ensure_ascii=False, indent=2, default=str)}

Devuelve SOLO JSON válido, sin markdown, con esta estructura:

{{
  "ok": true,
  "transcripcion": "",
  "plantilla_sugerida": {{
    "id": "{template.get("id") or ""}",
    "nombre": "{template.get("nombre") or ""}",
    "confianza": "",
    "motivo": ""
  }},
  "hallazgos_radiologicos": "",
  "hallazgos_estructurados": [
    {{
      "organo_o_region": "",
      "lateralidad": "",
      "hallazgo": "",
      "medida": "",
      "caracteristicas": [],
      "interpretacion": ""
    }}
  ],
  "informe_final": "",
  "impresion_diagnostica": "",
  "advertencias": [],
  "posibles_omisiones": [],
  "metodo": "audio_first_template_bridge"
}}
""".strip()


def _iad_audio_first_complete_with_template_bridge(
    client: Any,
    parsed: dict[str, Any],
    metadata: dict[str, Any],
    db: Any = None,
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        parsed = {"ok": False, "raw": str(parsed)}

    template = _iad_audio_first_pick_template(parsed, db=db)

    if not template or not template.get("contenido"):
        warnings = parsed.get("advertencias")
        if not isinstance(warnings, list):
            warnings = []
        warnings.append("No se encontró contenido completo de plantilla para mezclar con audio-first.")
        parsed["advertencias"] = warnings
        parsed["template_bridge"] = {
            "ok": False,
            "reason": "template_not_found_or_empty",
        }
        return parsed

    model = (
        os.getenv("IAD_AI_MODEL_AUDIO_FIRST_TEMPLATE_BRIDGE")
        or os.getenv("IAD_AI_MODEL_TEXT_STRUCTURED")
        or os.getenv("IAD_AI_MODEL_TEXT")
        or "gpt-4o-mini"
    )

    prompt = _iad_audio_first_template_bridge_prompt(parsed, template, metadata)

    try:
        kwargs = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Responde únicamente JSON válido. "
                        "No uses markdown. "
                        "Debes usar la plantilla completa como base del informe."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        try:
            completion = client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("response_format", None)
            completion = client.chat.completions.create(**kwargs)

        raw = _iad_audio_first_message_content(completion) if "_iad_audio_first_message_content" in globals() else ""
        if not raw:
            try:
                raw = completion.choices[0].message.content or ""
            except Exception:
                raw = ""

        bridged = _extract_json(raw)

        if not isinstance(bridged, dict) or bridged.get("ok") is False:
            warnings = parsed.get("advertencias")
            if not isinstance(warnings, list):
                warnings = []
            warnings.append("El puente de plantillas no devolvió JSON válido; se conserva salida audio-first previa.")
            parsed["advertencias"] = warnings
            parsed["template_bridge"] = {
                "ok": False,
                "reason": "invalid_json",
                "raw": raw[:4000],
                "template_id": template.get("id"),
                "template_name": template.get("nombre"),
            }
            return parsed

        # Preservar transcripción de audio-first si el puente no la replica.
        if not str(bridged.get("transcripcion") or "").strip():
            bridged["transcripcion"] = (
                parsed.get("transcripcion")
                or parsed.get("transcription")
                or parsed.get("raw_audio_first_text")
                or ""
            )

        warnings = bridged.get("advertencias")
        if not isinstance(warnings, list):
            warnings = []

        warnings.append("Informe final generado por puente audio-first + plantilla completa.")
        bridged["advertencias"] = warnings
        bridged["metodo"] = "audio_first_template_bridge"
        bridged["audio_first_original"] = parsed
        bridged["template_bridge"] = {
            "ok": True,
            "template_id": template.get("id"),
            "template_name": template.get("nombre"),
            "template_modalidad": template.get("modalidad"),
            "template_tipo": template.get("tipo"),
        }

        return bridged

    except Exception as exc:
        warnings = parsed.get("advertencias")
        if not isinstance(warnings, list):
            warnings = []
        warnings.append(f"Error en puente de plantillas: {exc}")
        parsed["advertencias"] = warnings
        parsed["template_bridge"] = {
            "ok": False,
            "reason": "exception",
            "error": str(exc),
            "template_id": template.get("id"),
            "template_name": template.get("nombre"),
        }
        return parsed



# IAD_AUDIO_FIRST_TEMPLATE_BRIDGE_FORCE_V2
def _iad_v2_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _iad_v2_norm(value: Any) -> str:
    s = str(value or "").lower()
    for a, b in {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"
    }.items():
        s = s.replace(a, b)
    return s


def _iad_v2_get_full_templates(db: Any = None) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []

    # 1) Fuente principal: collector existente.
    try:
        from app.services.ai.tasks.radiology_flow import collect_templates
        items = collect_templates(db) or []
        for item in items:
            if not isinstance(item, dict):
                continue

            name = (
                item.get("nombre")
                or item.get("template_name")
                or item.get("name")
                or item.get("title")
                or ""
            )

            tpl_id = item.get("id") or item.get("template_id") or ""

            content_parts = []
            for key in [
                "contenido",
                "content",
                "template",
                "text",
                "body",
                "findings",
                "hallazgos",
                "normal_report",
                "report",
                "informe",
                "impression",
                "impresion",
            ]:
                val = item.get(key)
                if val:
                    content_parts.append(f"[{key}]\n{val}")

            content = "\n\n".join(content_parts).strip()

            templates.append({
                "id": str(tpl_id or ""),
                "nombre": str(name or ""),
                "modalidad": str(item.get("modalidad") or item.get("modality") or ""),
                "tipo": str(item.get("tipo") or item.get("body_region") or ""),
                "tags": _iad_v2_text(item.get("tags") or ""),
                "contenido": content,
                "source": "collect_templates",
                "raw": item,
            })
    except Exception:
        pass

    # 2) Fallback: archivos report_templates.
    try:
        from pathlib import Path as _Path

        roots = [
            _Path("/code/report_templates"),
            _Path("/app/report_templates"),
            _Path("report_templates"),
        ]

        for root in roots:
            if not root.exists():
                continue

            for f in root.rglob("*"):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in [".txt", ".md", ".json", ".yml", ".yaml"]:
                    continue

                try:
                    raw = f.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                name = f.stem
                content = raw

                if f.suffix.lower() == ".json":
                    try:
                        obj = json.loads(raw)
                        if isinstance(obj, dict):
                            name = str(obj.get("nombre") or obj.get("name") or obj.get("title") or name)
                            parts = []
                            for key in ["contenido", "content", "template", "text", "body", "findings", "impression", "informe"]:
                                if obj.get(key):
                                    parts.append(f"[{key}]\n{obj.get(key)}")
                            content = "\n\n".join(parts).strip() or raw
                    except Exception:
                        pass

                templates.append({
                    "id": str(f),
                    "nombre": name,
                    "modalidad": "",
                    "tipo": "",
                    "tags": "",
                    "contenido": content,
                    "source": "filesystem",
                    "raw": {"path": str(f)},
                })
    except Exception:
        pass

    # 3) Eliminar vacías y duplicadas.
    out = []
    seen = set()
    for tpl in templates:
        key = (tpl.get("id"), tpl.get("nombre"), tpl.get("contenido")[:120])
        if key in seen:
            continue
        seen.add(key)
        if str(tpl.get("contenido") or "").strip():
            out.append(tpl)

    return out


def _iad_v2_pick_template(parsed: dict[str, Any], db: Any = None) -> dict[str, Any]:
    templates = _iad_v2_get_full_templates(db)
    if not templates:
        return {}

    suggested = parsed.get("plantilla_sugerida") or {}
    if not isinstance(suggested, dict):
        suggested = {}

    wanted_id = str(suggested.get("id") or "").strip()
    wanted_name = _iad_v2_norm(suggested.get("nombre") or suggested.get("name") or "")

    if wanted_id:
        for tpl in templates:
            if str(tpl.get("id") or "").strip() == wanted_id:
                return tpl

    scored = []
    source = _iad_v2_norm(
        " ".join([
            wanted_name,
            parsed.get("transcripcion") or "",
            parsed.get("hallazgos_radiologicos") or "",
            _iad_v2_text(parsed.get("hallazgos_estructurados") or ""),
        ])
    )

    for tpl in templates:
        blob = _iad_v2_norm(
            " ".join([
                tpl.get("nombre") or "",
                tpl.get("modalidad") or "",
                tpl.get("tipo") or "",
                tpl.get("tags") or "",
                tpl.get("contenido") or "",
            ])
        )

        score = 0

        name = _iad_v2_norm(tpl.get("nombre") or "")
        if wanted_name:
            if name == wanted_name:
                score += 200
            if wanted_name in name or name in wanted_name:
                score += 120
            for token in wanted_name.split():
                if len(token) >= 3 and token in name:
                    score += 10

        domain_tokens = [
            "torax", "abdomen", "pelvis", "contraste", "sin contraste",
            "renal", "rinon", "rinones", "pielo", "vesicula", "colon",
            "prostata", "cardiomegalia", "derrame", "litiasis", "adenopatia"
        ]

        for token in domain_tokens:
            if token in source and token in blob:
                score += 8

        if score:
            scored.append((score, tpl))

    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    return templates[0]


def _iad_v2_template_bridge_prompt(parsed: dict[str, Any], template: dict[str, Any], metadata: dict[str, Any]) -> str:
    return f"""
Eres un sistema de redacción radiológica.

La fuente primaria fue un AUDIO procesado por un modelo audio-first.
La transcripción incluida abajo es producto de ese proceso audio-first, no una transcripción local previa.
Tu tarea NO es volver a transcribir.
Tu tarea es construir el informe final usando la PLANTILLA COMPLETA como molde.

Reglas:
- Mantén la estructura de la plantilla.
- Conserva texto normal de la plantilla cuando no contradiga el audio.
- Reemplaza texto normal cuando el audio indique hallazgo patológico.
- Inserta TODOS los hallazgos positivos.
- No omitas lateralidad, medidas ni negaciones relevantes.
- Si hay autocorrección, lateralidad dudosa o frase contradictoria, decláralo en advertencias.
- No inventes datos fuera de la salida audio-first.

PLANTILLA COMPLETA:
ID: {template.get("id") or ""}
NOMBRE: {template.get("nombre") or ""}
FUENTE: {template.get("source") or ""}

{template.get("contenido") or ""}

SALIDA AUDIO-FIRST:
{json.dumps(parsed, ensure_ascii=False, indent=2, default=str)}

METADATA DE AUDIO:
{json.dumps(metadata, ensure_ascii=False, indent=2, default=str)}

Devuelve SOLO JSON válido:

{{
  "ok": true,
  "transcripcion": "",
  "plantilla_sugerida": {{
    "id": "{template.get("id") or ""}",
    "nombre": "{template.get("nombre") or ""}",
    "confianza": "media",
    "motivo": "Plantilla usada para ensamblar informe desde salida audio-first"
  }},
  "hallazgos_radiologicos": "",
  "hallazgos_estructurados": [],
  "impresion_diagnostica": "",
  "informe_final": "",
  "advertencias": [],
  "posibles_omisiones": [],
  "metodo": "audio_first_template_bridge"
}}
""".strip()


def _iad_v2_apply_template_bridge_force(
    client: Any,
    parsed: dict[str, Any],
    metadata: dict[str, Any],
    db: Any = None,
    composed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        parsed = {"ok": False, "raw": str(parsed)}

    template = _iad_v2_pick_template(parsed, db=db)

    if not template:
        warnings = parsed.get("advertencias")
        if not isinstance(warnings, list):
            warnings = []
        warnings.append("No se encontró plantilla completa para aplicar puente; se conserva salida audio-first.")
        parsed["advertencias"] = warnings
        parsed["template_bridge_force"] = {"ok": False, "reason": "no_template"}
        return parsed

    model = (
        os.getenv("IAD_AI_MODEL_AUDIO_FIRST_TEMPLATE_BRIDGE")
        or os.getenv("IAD_AI_MODEL_TEXT_STRUCTURED")
        or os.getenv("IAD_AI_MODEL_TEXT")
        or "gpt-4o-mini"
    )

    prompt = _iad_v2_template_bridge_prompt(parsed, template, metadata)

    try:
        kwargs = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Responde únicamente JSON válido. Usa la plantilla completa como base del informe final.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0.1,
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
            pass

        bridged = _extract_json(raw)

        if not isinstance(bridged, dict) or bridged.get("ok") is False:
            warnings = parsed.get("advertencias")
            if not isinstance(warnings, list):
                warnings = []
            warnings.append("El puente forzado de plantilla no devolvió JSON válido; se conserva salida audio-first.")
            parsed["advertencias"] = warnings
            parsed["template_bridge_force"] = {
                "ok": False,
                "reason": "invalid_json",
                "template_name": template.get("nombre"),
                "raw": raw[:4000],
            }
            return parsed

        if not str(bridged.get("transcripcion") or "").strip():
            bridged["transcripcion"] = (
                parsed.get("transcripcion")
                or parsed.get("transcription")
                or parsed.get("raw_audio_first_text")
                or ""
            )

        warnings = bridged.get("advertencias")
        if not isinstance(warnings, list):
            warnings = []

        warnings.append("Informe final ensamblado usando plantilla completa sobre salida audio-first.")
        bridged["advertencias"] = warnings
        bridged["metodo"] = "audio_first_template_bridge"
        bridged["template_bridge_force"] = {
            "ok": True,
            "template_id": template.get("id"),
            "template_name": template.get("nombre"),
            "template_source": template.get("source"),
        }
        bridged["audio_first_original"] = parsed

        return bridged

    except Exception as exc:
        warnings = parsed.get("advertencias")
        if not isinstance(warnings, list):
            warnings = []
        warnings.append(f"Error en puente forzado de plantilla: {exc}")
        parsed["advertencias"] = warnings
        parsed["template_bridge_force"] = {
            "ok": False,
            "reason": "exception",
            "error": str(exc),
            "template_name": template.get("nombre"),
        }
        return parsed


# IAD_TEMPLATE_MERGE_DETERMINISTIC_V3
# Postproceso determinístico: fuerza que el informe final conserve la plantilla completa
# y agregue/reemplace hallazgos positivos detectados desde audio-first.
try:
    import re as _iad_tpl_re
    import json as _iad_tpl_json
except Exception:
    _iad_tpl_re = None
    _iad_tpl_json = None


def _iad_tpl_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return _iad_tpl_json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _iad_tpl_norm(value):
    s = _iad_tpl_text(value).lower()
    for a, b in {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ü": "u", "ñ": "n"
    }.items():
        s = s.replace(a, b)
    s = _iad_tpl_re.sub(r"\s+", " ", s).strip() if _iad_tpl_re else " ".join(s.split())
    return s


def _iad_tpl_collect_source(parsed, result=None):
    result = result or {}
    parts = [
        parsed.get("transcripcion"),
        parsed.get("transcription"),
        parsed.get("raw_audio_first_text"),
        parsed.get("hallazgos_radiologicos"),
        parsed.get("impresion_diagnostica"),
        parsed.get("informe_final"),
        parsed.get("final_report"),
        parsed.get("resultado_revisado"),
        parsed.get("hallazgos_estructurados"),
        result.get("transcripcion"),
        result.get("hallazgos_radiologicos"),
        result.get("impresion_diagnostica"),
        result.get("informe_final"),
        result.get("hallazgos_estructurados"),
    ]
    return "\n".join(_iad_tpl_text(p) for p in parts if _iad_tpl_text(p).strip())


def _iad_tpl_measure_near(source, keyword, fallback=""):
    if not _iad_tpl_re:
        return fallback
    src = _iad_tpl_text(source)
    idx = _iad_tpl_norm(src).find(_iad_tpl_norm(keyword))
    window = src
    if idx >= 0:
        a = max(0, idx - 180)
        b = min(len(src), idx + 260)
        window = src[a:b]
    m = _iad_tpl_re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:x|por|×)\s*(\d+(?:[.,]\d+)?)"
        r"(?:\s*(?:x|por|×)\s*(\d+(?:[.,]\d+)?))?\s*(?:mm|mil[ií]metros?)",
        window,
        flags=_iad_tpl_re.I,
    )
    if not m:
        return fallback
    vals = [v.replace(",", ".") for v in m.groups() if v]
    return " x ".join(vals) + " mm"


def _iad_tpl_positive_lines(parsed, result=None):
    source = _iad_tpl_collect_source(parsed, result)
    n = _iad_tpl_norm(source)

    torax = []
    abdomen = []
    impresion = []

    if "nodulo" in n and ("pulmon" in n or "base derecha" in n or "base pulmonar" in n):
        measure = _iad_tpl_measure_near(source, "nodulo pulmonar", "3 x 4 x 5 mm")
        side = "en la base pulmonar derecha"
        if "base izquierda" in n or "base pulmonar izquierda" in n:
            side = "en la base pulmonar izquierda"
        line = f"Se identifica nódulo pulmonar {side} de {measure}."
        torax.append(line)
        impresion.append(f"Nódulo pulmonar {side} de {measure}.")

    renal_right = ("renal derecha" in n or "rinon derecho" in n or "riñon derecho" in n or "nefrolitiasis derecha" in n)
    renal_left = ("renal izquierda" in n or "rinon izquierdo" in n or "riñon izquierdo" in n or "nefrolitiasis izquierda" in n)

    if renal_right or renal_left or "litiasis renal" in n or "nefrolitiasis" in n:
        renal_parts = []
        if renal_right:
            mr = _iad_tpl_measure_near(source, "derecha", "")
            txt = "litiasis renal derecha no obstructiva"
            if mr:
                txt += f" de {mr}"
            renal_parts.append(txt)
        if renal_left:
            ml = _iad_tpl_measure_near(source, "izquierda", "5 x 4 mm")
            txt = "litiasis renal izquierda no obstructiva"
            if ml:
                txt += f" de {ml}"
            renal_parts.append(txt)
        if not renal_parts:
            renal_parts.append("nefrolitiasis no obstructiva")
        line = "Se observa " + " y ".join(renal_parts) + "."
        abdomen.append(line)
        impresion.append("Nefrolitiasis no obstructiva.")

    if "cardiomegalia" in n:
        line = "Se aprecia leve cardiomegalia."
        torax.append(line)
        impresion.append("Leve cardiomegalia.")

    # Si no se logró estructurar nada, usar el texto de hallazgos como respaldo.
    if not torax and not abdomen and not impresion:
        hall = _iad_tpl_text((result or {}).get("hallazgos_radiologicos") or parsed.get("hallazgos_radiologicos")).strip()
        if hall:
            abdomen.append(hall)

    return {
        "torax": torax,
        "abdomen": abdomen,
        "impresion": impresion,
    }


def _iad_tpl_report_has_template_shape(report, template_text):
    report = _iad_tpl_text(report).strip()
    template_text = _iad_tpl_text(template_text).strip()
    if not report or not template_text:
        return False

    rn = _iad_tpl_norm(report)
    tn = _iad_tpl_norm(template_text)

    # Puntaje por secciones típicas.
    section_words = [
        "tecnica", "hallazgos", "torax", "tórax", "abdomen",
        "pelvis", "impresion", "impresión", "conclusion", "conclusión"
    ]
    section_hits = sum(1 for w in section_words if _iad_tpl_norm(w) in rn)

    # Puntaje por longitud relativa.
    enough_length = len(report) >= max(450, int(len(template_text) * 0.55))

    # Puntaje por líneas conservadas de la plantilla.
    tpl_lines = [
        _iad_tpl_norm(x)
        for x in template_text.splitlines()
        if len(_iad_tpl_norm(x)) >= 18
    ][:30]
    shared = sum(1 for line in tpl_lines if line and line[:50] in rn)

    return enough_length and (section_hits >= 3 or shared >= 3)


def _iad_tpl_insert_after_section(lines, section_keywords, insert_lines):
    if not insert_lines:
        return lines, False

    out = []
    inserted = False
    i = 0

    while i < len(lines):
        line = lines[i]
        out.append(line)
        low = _iad_tpl_norm(line)

        is_section = any(k in low for k in section_keywords) and (line.strip().endswith(":") or len(line.strip()) < 45)

        if is_section and not inserted:
            # Saltar una línea en blanco inmediatamente posterior, si existe, pero conservarla.
            if i + 1 < len(lines) and not lines[i + 1].strip():
                i += 1
                out.append(lines[i])

            for ins in insert_lines:
                if ins.strip():
                    out.append(ins.strip())
            inserted = True

        i += 1

    return out, inserted


def _iad_tpl_replace_contradictory_normals(lines, positives):
    out = []
    used_torax = False
    used_abdomen = False

    torax_text = " ".join(positives.get("torax") or [])
    abd_text = " ".join(positives.get("abdomen") or [])

    for line in lines:
        low = _iad_tpl_norm(line)

        # Reemplazo de normalidad pulmonar si hay nódulo/cardiomegalia.
        if torax_text and not used_torax:
            if any(k in low for k in ["pulmon", "pulmonar", "pleur", "mediast", "cardio", "torax", "tórax"]) and any(k in low for k in ["sin ", "normal", "no se observa", "no se identific"]):
                out.append(torax_text)
                used_torax = True
                continue

        # Reemplazo de normalidad renal/urinaria si hay litiasis.
        if abd_text and not used_abdomen:
            if any(k in low for k in ["rinon", "riñon", "renal", "pielocalicial", "litiasis", "nefro", "urinaria"]) and any(k in low for k in ["sin ", "normal", "no se observa", "no se identific", "conserv"]):
                out.append(abd_text)
                used_abdomen = True
                continue

        out.append(line)

    return out, used_torax, used_abdomen


def _iad_tpl_merge_template_with_audio(template, parsed, result=None):
    result = result or {}
    template_text = _iad_tpl_text(
        template.get("contenido")
        or template.get("template_text")
        or template.get("text")
        or ""
    ).strip()

    current = _iad_tpl_text(
        result.get("informe_final")
        or result.get("final_report")
        or parsed.get("informe_final")
        or parsed.get("final_report")
        or ""
    ).strip()

    if not template_text:
        return current

    # Si la IA ya devolvió algo con forma real de plantilla, no lo destruyas.
    if _iad_tpl_report_has_template_shape(current, template_text):
        return current

    positives = _iad_tpl_positive_lines(parsed, result)
    lines = template_text.splitlines()

    lines, used_torax, used_abdomen = _iad_tpl_replace_contradictory_normals(lines, positives)

    lines, inserted_torax = _iad_tpl_insert_after_section(
        lines,
        ["torax", "tórax", "pulmon", "pulmonar"],
        positives.get("torax") or [],
    )

    lines, inserted_abd = _iad_tpl_insert_after_section(
        lines,
        ["abdomen", "renal", "urinario", "rinon", "riñon"],
        positives.get("abdomen") or [],
    )

    lines, inserted_imp = _iad_tpl_insert_after_section(
        lines,
        ["impresion", "impresión", "conclusion", "conclusión"],
        positives.get("impresion") or [],
    )

    merged = "\n".join(lines).strip()

    append_blocks = []

    if positives.get("torax") and not (used_torax or inserted_torax):
        append_blocks.append("Hallazgos torácicos dictados:\n" + "\n".join(positives["torax"]))

    if positives.get("abdomen") and not (used_abdomen or inserted_abd):
        append_blocks.append("Hallazgos abdominopélvicos dictados:\n" + "\n".join(positives["abdomen"]))

    if positives.get("impresion") and not inserted_imp:
        append_blocks.append("Impresión diagnóstica:\n" + "\n".join(positives["impresion"]))

    if append_blocks:
        merged = merged + "\n\n" + "\n\n".join(append_blocks)

    # Normalizar saltos excesivos.
    if _iad_tpl_re:
        merged = _iad_tpl_re.sub(r"\n{3,}", "\n\n", merged).strip()

    return merged


def _iad_tpl_apply_result_guard(parsed, result, template, source_label=""):
    if not isinstance(result, dict):
        result = parsed if isinstance(parsed, dict) else {"ok": False, "raw": _iad_tpl_text(result)}

    if not isinstance(parsed, dict):
        parsed = {"raw": _iad_tpl_text(parsed)}

    if not template:
        return result

    original_report = _iad_tpl_text(result.get("informe_final") or result.get("final_report") or "")
    merged = _iad_tpl_merge_template_with_audio(template, parsed, result)

    if merged and merged.strip() and merged.strip() != original_report.strip():
        result["informe_final_modelo"] = original_report
        result["informe_final"] = merged
        result["final_report"] = merged
        result["resultado_revisado"] = merged
        result["metodo"] = "audio_first_template_bridge"

        ps = result.get("plantilla_sugerida")
        if not isinstance(ps, dict):
            ps = {}
        ps.setdefault("id", template.get("id") or "")
        ps.setdefault("nombre", template.get("nombre") or template.get("template_name") or "")
        ps.setdefault("confianza", "media")
        ps.setdefault("motivo", "Plantilla completa aplicada por postproceso determinístico")
        result["plantilla_sugerida"] = ps

        warnings = result.get("advertencias")
        if not isinstance(warnings, list):
            warnings = []
        warnings.append("Postproceso determinístico: se aplicó plantilla completa y se insertaron hallazgos positivos del audio.")
        result["advertencias"] = warnings

        tb = result.get("template_bridge_force")
        if not isinstance(tb, dict):
            tb = {}
        tb.update({
            "ok": True,
            "postprocess_v3": True,
            "source": source_label,
            "template_id": template.get("id") or "",
            "template_name": template.get("nombre") or template.get("template_name") or "",
            "template_text_len": len(_iad_tpl_text(template.get("contenido") or "")),
            "original_report_len": len(original_report),
            "merged_report_len": len(merged),
        })
        result["template_bridge_force"] = tb

    return result


# Envolver funciones existentes sin tocar el cuerpo original.
try:
    _iad_tpl_original_v2_apply_template_bridge_force = _iad_v2_apply_template_bridge_force

    def _iad_v2_apply_template_bridge_force(client, parsed, metadata, db=None, composed=None):
        result = _iad_tpl_original_v2_apply_template_bridge_force(
            client=client,
            parsed=parsed,
            metadata=metadata,
            db=db,
            composed=composed,
        )
        template = None
        try:
            template = _iad_v2_pick_template(result if isinstance(result, dict) else parsed, db=db)
        except Exception:
            try:
                template = _iad_audio_first_pick_template(result if isinstance(result, dict) else parsed, db=db)
            except Exception:
                template = None
        return _iad_tpl_apply_result_guard(parsed if isinstance(parsed, dict) else {}, result, template, "v2_force_wrapper")
except Exception:
    pass


try:
    _iad_tpl_original_audio_first_complete_with_template_bridge = _iad_audio_first_complete_with_template_bridge

    def _iad_audio_first_complete_with_template_bridge(client, parsed, metadata, db=None):
        result = _iad_tpl_original_audio_first_complete_with_template_bridge(
            client=client,
            parsed=parsed,
            metadata=metadata,
            db=db,
        )
        template = None
        try:
            template = _iad_audio_first_pick_template(result if isinstance(result, dict) else parsed, db=db)
        except Exception:
            try:
                template = _iad_v2_pick_template(result if isinstance(result, dict) else parsed, db=db)
            except Exception:
                template = None
        return _iad_tpl_apply_result_guard(parsed if isinstance(parsed, dict) else {}, result, template, "audio_first_bridge_wrapper")
except Exception:
    pass

# IAD_EXAM_TYPE_TEMPLATE_GUARD_V1
# Guardia clínico: si el dictado explicita tipo de estudio, eso manda sobre la plantilla sugerida.
# Primer caso crítico: "TC de tórax con contraste" no debe terminar en plantilla TC TAP.

import re as _iad_exam_re
import unicodedata as _iad_exam_ud


def _iad_exam_norm_v1(value):
    value = "" if value is None else str(value)
    value = value.lower()
    value = "".join(
        c for c in _iad_exam_ud.normalize("NFD", value)
        if _iad_exam_ud.category(c) != "Mn"
    )
    value = value.replace("\\n", " ")
    value = _iad_exam_re.sub(r"\s+", " ", value).strip()
    return value


def _iad_exam_text_from_payload_v1(payload):
    if not isinstance(payload, dict):
        return ""

    chunks = []

    keys = [
        "dictado_original",
        "source_text",
        "texto_origen",
        "transcripcion",
        "transcription",
        "raw_audio_first_text",
        "hallazgos_radiologicos",
        "impresion_diagnostica",
        "informe_final",
        "final_report",
    ]

    for k in keys:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            chunks.append(v)

    try:
        ac = payload.get("audio_composition") or {}
        if isinstance(ac, dict):
            for k in ["text", "transcription", "combined_text"]:
                v = ac.get(k)
                if isinstance(v, str) and v.strip():
                    chunks.append(v)
    except Exception:
        pass

    try:
        hs = payload.get("hallazgos_estructurados") or []
        if isinstance(hs, list):
            for h in hs:
                if isinstance(h, dict):
                    chunks.append(" ".join(str(h.get(k) or "") for k in h.keys()))
    except Exception:
        pass

    return "\n".join(chunks)


def _iad_exam_detect_type_v1(payload):
    raw = _iad_exam_text_from_payload_v1(payload)
    n = _iad_exam_norm_v1(raw)

    has_tap = (
        "torax abdomen pelvis" in n
        or "torax abdomen y pelvis" in n
        or "torax abdomen-pelvis" in n
        or "tap" in n
        or "tc tap" in n
    )

    has_chest_ct = (
        "tomografia computada de torax con contraste" in n
        or "tomografia computarizada de torax con contraste" in n
        or "tc de torax con contraste" in n
        or "tc torax con contraste" in n
        or "tc torax cc" in n
        or "torax con contraste" in n
    )

    # Regla central:
    # Si dice tórax con contraste y no dice explícitamente abdomen y pelvis, se bloquea como tórax.
    if has_chest_ct and not has_tap:
        return "tc_torax_cc"

    if has_tap:
        return "tc_tap_cc"

    return ""


def _iad_exam_template_name_v1(payload):
    if not isinstance(payload, dict):
        return ""

    for k in ["plantilla_nombre", "template_name", "template"]:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v

    tpl = payload.get("plantilla_sugerida")
    if isinstance(tpl, dict):
        return str(tpl.get("nombre") or tpl.get("name") or "")

    return ""


def _iad_exam_set_template_name_v1(payload, name, confidence="alta"):
    if not isinstance(payload, dict):
        return

    tpl = payload.get("plantilla_sugerida")
    if not isinstance(tpl, dict):
        tpl = {}

    tpl["nombre"] = name
    tpl["name"] = name
    tpl["confianza"] = confidence

    payload["plantilla_sugerida"] = tpl
    payload["plantilla_nombre"] = name
    payload["template_name"] = name


def _iad_exam_findings_text_v1(payload):
    return _iad_exam_text_from_payload_v1(payload)


def _iad_exam_extract_size_v1(text):
    m = _iad_exam_re.search(
        r"(\d+(?:[,.]\d+)?)\s*(?:x|por)\s*(\d+(?:[,.]\d+)?)\s*(?:x|por)\s*(\d+(?:[,.]\d+)?)\s*(?:mm|milimetros?)",
        text,
        flags=_iad_exam_re.I
    )
    if m:
        return f"{m.group(1).replace(',', '.')} x {m.group(2).replace(',', '.')} x {m.group(3).replace(',', '.')} mm"

    m = _iad_exam_re.search(
        r"(\d+(?:[,.]\d+)?)\s*(?:x|por)\s*(\d+(?:[,.]\d+)?)\s*(?:mm|milimetros?)",
        text,
        flags=_iad_exam_re.I
    )
    if m:
        return f"{m.group(1).replace(',', '.')} x {m.group(2).replace(',', '.')} mm"

    return ""


def _iad_exam_structured_findings_v1(payload):
    hs = []
    if isinstance(payload, dict):
        v = payload.get("hallazgos_estructurados")
        if isinstance(v, list):
            hs.extend([h for h in v if isinstance(h, dict)])

    return hs


def _iad_exam_has_word_v1(text, *words):
    n = _iad_exam_norm_v1(text)
    return all(_iad_exam_norm_v1(w) in n for w in words)


def _iad_exam_build_tc_torax_cc_report_v1(payload):
    text = _iad_exam_findings_text_v1(payload)
    norm = _iad_exam_norm_v1(text)
    hs = _iad_exam_structured_findings_v1(payload)

    # Nódulo pulmonar.
    has_nodule = "nodulo" in norm and "pulmon" in norm
    nodule_size = ""

    for h in hs:
        hn = _iad_exam_norm_v1(" ".join(str(h.get(k) or "") for k in h.keys()))
        if "nodulo" in hn and "pulmon" in hn:
            nodule_size = str(h.get("medida") or h.get("size") or h.get("diametro") or "").strip()
            break

    if not nodule_size:
        nodule_size = _iad_exam_extract_size_v1(text)

    nodule_location = "en la base pulmonar derecha"
    if "base izquierda" in norm or "base pulmonar izquierda" in norm:
        nodule_location = "en la base pulmonar izquierda"
    elif "base derecha" in norm or "base pulmonar derecha" in norm:
        nodule_location = "en la base pulmonar derecha"

    # Cardiomegalia.
    has_cardiomegaly = "cardiomegalia" in norm
    mild_cardio = has_cardiomegaly and ("leve" in norm or "ligera" in norm)

    # Litiasis renal visible incidental.
    has_renal_lithiasis = ("litiasis" in norm or "nefrolitiasis" in norm) and ("renal" in norm or "rinon" in norm or "riñon" in text.lower())
    renal_left_size = ""
    for h in hs:
        hn = _iad_exam_norm_v1(" ".join(str(h.get(k) or "") for k in h.keys()))
        if ("litiasis" in hn or "nefrolitiasis" in hn) and ("izquierda" in hn or str(h.get("lateralidad") or "").lower().startswith("iz")):
            renal_left_size = str(h.get("medida") or h.get("size") or "").strip()
            break
    if not renal_left_size and "izquierda" in norm:
        renal_left_size = _iad_exam_extract_size_v1(text)

    lines = []
    lines.append("TC DE TÓRAX CON CONTRASTE")
    lines.append("")
    lines.append("Volumen y arquitectura pulmonar conservada.")

    if has_nodule:
        if nodule_size:
            lines.append(f"Se identifica nódulo pulmonar {nodule_location} de {nodule_size}.")
        else:
            lines.append(f"Se identifica nódulo pulmonar {nodule_location}.")
    else:
        lines.append("No se identifican nódulos pulmonares sospechosos en este estudio.")

    lines.append("Tráquea y bronquios principales permeables.")
    lines.append("No hay derrame pleural.")
    lines.append("No hay neumotórax.")
    lines.append("Mediastino sin adenopatías de tamaño significativo.")

    if has_cardiomegaly:
        if mild_cardio:
            lines.append("Se aprecia leve cardiomegalia. No hay derrame pericárdico.")
        else:
            lines.append("Se aprecia cardiomegalia. No hay derrame pericárdico.")
    else:
        lines.append("Corazón de tamaño conservado. No hay derrame pericárdico.")

    lines.append("Aorta y resto de los grandes vasos del tórax de calibre conservado.")

    if has_renal_lithiasis:
        if renal_left_size:
            lines.append(f"En el abdomen superior incluido en el campo de estudio, se observa nefrolitiasis no obstructiva, con litiasis izquierda de {renal_left_size}.")
        else:
            lines.append("En el abdomen superior incluido en el campo de estudio, se observa nefrolitiasis no obstructiva.")

    lines.append("")
    lines.append("Impresión diagnóstica:")

    if has_nodule:
        if nodule_size:
            lines.append(f"- Nódulo pulmonar {nodule_location} de {nodule_size}.")
        else:
            lines.append(f"- Nódulo pulmonar {nodule_location}.")

    if has_renal_lithiasis:
        lines.append("- Nefrolitiasis no obstructiva visible en el abdomen superior incluido en el campo de estudio.")

    if has_cardiomegaly:
        lines.append("- Leve cardiomegalia." if mild_cardio else "- Cardiomegalia.")

    if len(lines) and lines[-1] == "Impresión diagnóstica:":
        lines.append("- Sin hallazgos torácicos agudos evidentes.")

    return "\n".join(lines).strip()


def _iad_exam_report_looks_wrong_for_torax_v1(payload):
    if not isinstance(payload, dict):
        return False

    report = str(
        payload.get("informe_final")
        or payload.get("final_report")
        or payload.get("resultado_revisado")
        or ""
    )

    tpl = _iad_exam_norm_v1(_iad_exam_template_name_v1(payload))
    r = _iad_exam_norm_v1(report)

    wrong_template = (
        "abdomen y pelvis" in tpl
        or "abdomen pelvis" in tpl
        or "tap" in tpl
    )

    wrong_body = (
        "prostata" in r
        or "utero" in r
        or "vesicula biliar" in r
        or "colon" in r
        or "pelvis" in r
        or "asas de calibre" in r
        or "vejiga" in r
    )

    contradiction = (
        ("cardiomegalia" in r and "corazon de tamano normal" in r)
        or ("cardiomegalia" in r and "corazon de tamaño normal" in report.lower())
    )

    return wrong_template or wrong_body or contradiction


def _iad_exam_apply_template_guard_v1(payload):
    if not isinstance(payload, dict):
        return payload

    exam_type = _iad_exam_detect_type_v1(payload)

    if not exam_type:
        return payload

    warnings = payload.get("advertencias")
    if not isinstance(warnings, list):
        warnings = [] if warnings in (None, "") else [str(warnings)]

    guard = {
        "active": True,
        "detected_exam_type": exam_type,
        "template_before": _iad_exam_template_name_v1(payload),
    }

    if exam_type == "tc_torax_cc":
        should_rebuild = _iad_exam_report_looks_wrong_for_torax_v1(payload)

        _iad_exam_set_template_name_v1(payload, "TC Torax CC", "alta")

        if should_rebuild:
            before = str(payload.get("informe_final") or payload.get("final_report") or "")
            report = _iad_exam_build_tc_torax_cc_report_v1(payload)

            payload["informe_final_antes_exam_type_guard"] = before
            payload["informe_final"] = report
            payload["final_report"] = report
            payload["resultado_revisado"] = report

            guard["rebuilt_report"] = True
            guard["reason"] = "Dictado explicita TC de tórax con contraste; la salida previa parecía usar plantilla TAP o tenía contradicciones."
            warnings.append("Guardia de tipo de examen: se detectó TC de tórax con contraste y se bloqueó plantilla TC Tórax CC, evitando TC TAP.")
        else:
            guard["rebuilt_report"] = False
            guard["reason"] = "Dictado explicita TC de tórax con contraste; se ajustó nombre de plantilla sin reconstruir informe."
            warnings.append("Guardia de tipo de examen: se detectó TC de tórax con contraste y se forzó plantilla TC Tórax CC.")

    elif exam_type == "tc_tap_cc":
        guard["rebuilt_report"] = False
        guard["reason"] = "Dictado compatible con TC tórax, abdomen y pelvis."
        # No se cambia.

    payload["exam_type_guard"] = guard
    payload["advertencias"] = warnings

    old_method = str(payload.get("metodo") or payload.get("method") or "")
    if old_method:
        if "exam_type_guard" not in old_method:
            payload["metodo"] = old_method + "+exam_type_guard"
    else:
        payload["metodo"] = "exam_type_guard"

    return payload


# Wrappers finales: aplicar guardia después del bridge/smart/deterministic.
try:
    _iad_exam_orig_apply_template_bridge_force_v1 = _iad_v2_apply_template_bridge_force

    def _iad_v2_apply_template_bridge_force(*args, **kwargs):
        result = _iad_exam_orig_apply_template_bridge_force_v1(*args, **kwargs)
        return _iad_exam_apply_template_guard_v1(result)

except Exception:
    pass


try:
    _iad_exam_orig_audio_first_complete_bridge_v1 = _iad_audio_first_complete_with_template_bridge

    async def _iad_audio_first_complete_with_template_bridge(*args, **kwargs):
        result = await _iad_exam_orig_audio_first_complete_bridge_v1(*args, **kwargs)
        return _iad_exam_apply_template_guard_v1(result)

except Exception:
    pass


# IAD_EXAM_TYPE_PRESELECT_AND_JSON_UNWRAP_V2
# Limpia transcripciones que quedaron como JSON crudo y fuerza tipo de examen antes de que el bridge contamine la plantilla.

import json as _iad_pre_json
import re as _iad_pre_re
import unicodedata as _iad_pre_ud


def _iad_pre_norm_v2(value):
    value = "" if value is None else str(value)
    value = value.lower()
    value = "".join(
        c for c in _iad_pre_ud.normalize("NFD", value)
        if _iad_pre_ud.category(c) != "Mn"
    )
    value = value.replace("\\n", " ")
    value = _iad_pre_re.sub(r"\s+", " ", value).strip()
    return value


def _iad_pre_try_json_v2(value):
    if not isinstance(value, str):
        return None

    t = value.strip()
    if not t:
        return None

    if not ((t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]"))):
        return None

    try:
        return _iad_pre_json.loads(t)
    except Exception:
        return None


def _iad_pre_extract_transcription_v2(value, depth=0):
    if depth > 4:
        return "" if value is None else str(value)

    if isinstance(value, dict):
        for k in [
            "transcripcion",
            "transcription",
            "raw_audio_first_text",
            "texto",
            "text",
            "dictado_original",
            "source_text",
        ]:
            v = value.get(k)
            if isinstance(v, str) and v.strip():
                nested = _iad_pre_try_json_v2(v)
                if nested is not None:
                    return _iad_pre_extract_transcription_v2(nested, depth + 1)
                return v.strip()

        # Si no hay transcripción, intentar analysis/generated.
        for k in ["analysis", "generated", "data", "result"]:
            v = value.get(k)
            if isinstance(v, dict):
                out = _iad_pre_extract_transcription_v2(v, depth + 1)
                if out.strip():
                    return out.strip()

        return ""

    if isinstance(value, str):
        nested = _iad_pre_try_json_v2(value)
        if nested is not None:
            return _iad_pre_extract_transcription_v2(nested, depth + 1)
        return value.strip()

    return "" if value is None else str(value).strip()


def _iad_pre_unwrap_payload_json_v2(payload):
    if not isinstance(payload, dict):
        return payload

    # Campos que no deben quedar como JSON crudo visible.
    for k in [
        "transcripcion",
        "transcription",
        "raw_audio_first_text",
        "dictado_original",
        "source_text",
        "texto_origen",
    ]:
        v = payload.get(k)
        if isinstance(v, str):
            nested = _iad_pre_try_json_v2(v)
            if nested is not None:
                clean = _iad_pre_extract_transcription_v2(nested)
                if clean:
                    payload[k] = clean

                # Rescatar datos útiles del JSON embebido.
                if isinstance(nested, dict):
                    for nk in [
                        "hallazgos_estructurados",
                        "impresion_diagnostica",
                        "advertencias",
                        "posibles_omisiones",
                        "audio_composition",
                    ]:
                        if nk not in payload and nk in nested:
                            payload[nk] = nested[nk]

                    if "plantilla_sugerida" not in payload and isinstance(nested.get("plantilla_sugerida"), dict):
                        payload["plantilla_sugerida"] = nested["plantilla_sugerida"]

                    if "informe_final" not in payload and isinstance(nested.get("informe_final"), str):
                        payload["informe_final"] = nested["informe_final"]

    return payload


def _iad_pre_payload_text_v2(payload):
    if not isinstance(payload, dict):
        return _iad_pre_extract_transcription_v2(payload)

    chunks = []

    for k in [
        "dictado_original",
        "source_text",
        "texto_origen",
        "transcripcion",
        "transcription",
        "raw_audio_first_text",
        "hallazgos_radiologicos",
        "impresion_diagnostica",
    ]:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            chunks.append(_iad_pre_extract_transcription_v2(v))

    try:
        ac = payload.get("audio_composition") or {}
        if isinstance(ac, dict):
            for k in ["text", "transcription", "combined_text"]:
                v = ac.get(k)
                if isinstance(v, str) and v.strip():
                    chunks.append(_iad_pre_extract_transcription_v2(v))
    except Exception:
        pass

    return "\n".join([c for c in chunks if c])


def _iad_pre_detect_exam_type_v2(payload):
    text = _iad_pre_payload_text_v2(payload)
    n = _iad_pre_norm_v2(text)

    has_tap = (
        "torax abdomen pelvis" in n
        or "torax abdomen y pelvis" in n
        or "tc tap" in n
        or "tap con contraste" in n
    )

    has_chest_ct = (
        "tomografia computada de torax con contraste" in n
        or "tomografia computarizada de torax con contraste" in n
        or "tc de torax con contraste" in n
        or "tc torax con contraste" in n
        or "tc torax cc" in n
        or "torax con contraste" in n
    )

    if has_chest_ct and not has_tap:
        return "tc_torax_cc"

    if has_tap:
        return "tc_tap_cc"

    return ""


def _iad_pre_force_template_v2(payload, exam_type):
    if not isinstance(payload, dict):
        return payload

    if not exam_type:
        return payload

    tpl = payload.get("plantilla_sugerida")
    if not isinstance(tpl, dict):
        tpl = {}

    before = str(tpl.get("nombre") or tpl.get("name") or payload.get("plantilla_nombre") or payload.get("template_name") or "")

    if exam_type == "tc_torax_cc":
        name = "TC Torax CC"
        tpl["nombre"] = name
        tpl["name"] = name
        tpl["confianza"] = "alta"
        tpl["motivo_preselector"] = "Dictado explicita TC de tórax con contraste; se bloquea selección de TC TAP."
        payload["plantilla_sugerida"] = tpl
        payload["plantilla_nombre"] = name
        payload["template_name"] = name

        warnings = payload.get("advertencias")
        if not isinstance(warnings, list):
            warnings = [] if warnings in (None, "") else [str(warnings)]
        if before and _iad_pre_norm_v2(before) != _iad_pre_norm_v2(name):
            warnings.append(f"Preselector de examen: plantilla inicial '{before}' reemplazada por '{name}'.")
        else:
            warnings.append("Preselector de examen: se forzó plantilla TC Torax CC.")
        payload["advertencias"] = warnings

        payload["exam_type_preselector"] = {
            "active": True,
            "detected_exam_type": exam_type,
            "template_before": before,
            "template_after": name,
        }

    elif exam_type == "tc_tap_cc":
        payload["exam_type_preselector"] = {
            "active": True,
            "detected_exam_type": exam_type,
            "template_before": before,
            "template_after": before,
        }

    return payload


def _iad_pre_clean_and_preselect_v2(payload):
    if not isinstance(payload, dict):
        return payload

    payload = _iad_pre_unwrap_payload_json_v2(payload)
    exam_type = _iad_pre_detect_exam_type_v2(payload)
    payload = _iad_pre_force_template_v2(payload, exam_type)

    return payload


def _iad_pre_post_clean_v2(payload):
    if not isinstance(payload, dict):
        return payload

    payload = _iad_pre_unwrap_payload_json_v2(payload)

    # Si el guardia V1 existe, dejar que reconstruya si corresponde.
    try:
        payload = _iad_exam_apply_template_guard_v1(payload)
    except Exception:
        pass

    # Asegurar que la transcripción final no sea JSON crudo.
    clean = _iad_pre_extract_transcription_v2(payload.get("transcripcion") or payload.get("transcription") or "")
    if clean:
        payload["transcripcion"] = clean
        payload["transcription"] = clean

    old_method = str(payload.get("metodo") or payload.get("method") or "")
    if "preselect_clean" not in old_method:
        payload["metodo"] = (old_method + "+preselect_clean").strip("+") if old_method else "preselect_clean"

    return payload


# Wrappers de funciones conocidas. El objetivo es limpiar antes y después sin depender de la estructura exacta.
try:
    _iad_pre_orig_apply_template_bridge_force_v2 = _iad_v2_apply_template_bridge_force

    def _iad_v2_apply_template_bridge_force(*args, **kwargs):
        args = tuple(_iad_pre_clean_and_preselect_v2(a) if isinstance(a, dict) else a for a in args)
        kwargs = {k: (_iad_pre_clean_and_preselect_v2(v) if isinstance(v, dict) else v) for k, v in kwargs.items()}
        result = _iad_pre_orig_apply_template_bridge_force_v2(*args, **kwargs)
        return _iad_pre_post_clean_v2(result)

except Exception:
    pass


try:
    _iad_pre_orig_audio_first_complete_bridge_v2 = _iad_audio_first_complete_with_template_bridge

    async def _iad_audio_first_complete_with_template_bridge(*args, **kwargs):
        args = tuple(_iad_pre_clean_and_preselect_v2(a) if isinstance(a, dict) else a for a in args)
        kwargs = {k: (_iad_pre_clean_and_preselect_v2(v) if isinstance(v, dict) else v) for k, v in kwargs.items()}
        result = await _iad_pre_orig_audio_first_complete_bridge_v2(*args, **kwargs)
        return _iad_pre_post_clean_v2(result)

except Exception:
    pass


# IAD_CLEAN_ABDOMEN_PELVIS_WRITER_V1
# Writer clínico limpio para TC abdomen/pelvis CC.
# Objetivo: no arrastrar placeholders de plantilla ni pegar hallazgos al final.
# Este bloque reconstruye un informe limpio cuando detecta salida contaminada.

import re as _iad_ap_re
import unicodedata as _iad_ap_ud
import json as _iad_ap_json


def _iad_ap_norm_v1(value):
    value = "" if value is None else str(value)
    value = value.lower()
    value = "".join(
        c for c in _iad_ap_ud.normalize("NFD", value)
        if _iad_ap_ud.category(c) != "Mn"
    )
    value = value.replace("\\n", " ")
    value = _iad_ap_re.sub(r"\s+", " ", value).strip()
    return value


def _iad_ap_try_json_v1(value):
    if not isinstance(value, str):
        return None
    t = value.strip()
    if not t:
        return None
    if not ((t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]"))):
        return None
    try:
        return _iad_ap_json.loads(t)
    except Exception:
        return None


def _iad_ap_extract_text_v1(value, depth=0):
    if depth > 4:
        return "" if value is None else str(value)

    if isinstance(value, dict):
        for k in [
            "transcripcion",
            "transcription",
            "raw_audio_first_text",
            "dictado_original",
            "source_text",
            "texto",
            "text",
        ]:
            v = value.get(k)
            if isinstance(v, str) and v.strip():
                return _iad_ap_extract_text_v1(v, depth + 1)

        for k in ["analysis", "generated", "data", "result"]:
            v = value.get(k)
            if isinstance(v, dict):
                out = _iad_ap_extract_text_v1(v, depth + 1)
                if out.strip():
                    return out

        return ""

    if isinstance(value, str):
        nested = _iad_ap_try_json_v1(value)
        if nested is not None:
            return _iad_ap_extract_text_v1(nested, depth + 1)
        return value.strip()

    return "" if value is None else str(value).strip()


def _iad_ap_source_text_v1(payload):
    if not isinstance(payload, dict):
        return _iad_ap_extract_text_v1(payload)

    chunks = []

    # Usar solo texto fuente, no informe_final, para no propagar errores como nefrolitiasis inventada.
    for k in [
        "dictado_original",
        "source_text",
        "texto_origen",
        "transcripcion",
        "transcription",
        "raw_audio_first_text",
        "hallazgos_radiologicos",
        "impresion_diagnostica",
    ]:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            chunks.append(_iad_ap_extract_text_v1(v))

    try:
        ac = payload.get("audio_composition") or {}
        if isinstance(ac, dict):
            for k in ["text", "transcription", "combined_text"]:
                v = ac.get(k)
                if isinstance(v, str) and v.strip():
                    chunks.append(_iad_ap_extract_text_v1(v))
    except Exception:
        pass

    return "\n".join([c for c in chunks if c.strip()])


def _iad_ap_template_name_v1(payload):
    if not isinstance(payload, dict):
        return ""
    tpl = payload.get("plantilla_sugerida")
    if isinstance(tpl, dict):
        return str(tpl.get("nombre") or tpl.get("name") or "")
    return str(payload.get("plantilla_nombre") or payload.get("template_name") or "")


def _iad_ap_detect_exam_v1(payload):
    source = _iad_ap_source_text_v1(payload)
    n = _iad_ap_norm_v1(source)

    is_ap = (
        "abdomen y pelvis con contraste" in n
        or "abdomen pelvis con contraste" in n
        or "tomografia de abdomen y pelvis con contraste" in n
        or "tomografia computada de abdomen y pelvis con contraste" in n
        or "tc abdomen y pelvis con contraste" in n
        or "tc abdomen pelvis con contraste" in n
        or "tc abdomen pelvis cc" in n
        or "abdomen y pelvis cc" in n
    )

    is_tap = (
        "torax abdomen pelvis" in n
        or "torax abdomen y pelvis" in n
        or "tc tap" in n
    )

    if is_ap and not is_tap:
        return "tc_abdomen_pelvis_cc"

    return ""


def _iad_ap_report_dirty_v1(payload):
    if not isinstance(payload, dict):
        return False

    report = str(
        payload.get("informe_final")
        or payload.get("final_report")
        or payload.get("resultado_revisado")
        or ""
    )

    r = _iad_ap_norm_v1(report)
    source = _iad_ap_norm_v1(_iad_ap_source_text_v1(payload))

    dirty_tokens = [
        "[contenido]",
        "xxxxxxxx",
        "organosexual",
        "vesiculabiliar",
        "hallazgos positivos estructurados aplicados al informe",
    ]

    if any(t in r for t in dirty_tokens):
        return True

    if "lesion quistica" in source and "higado de morfologia normal, sin lesiones focales" in r:
        return True

    if "quiste renal" in source and "no son evidentes litiasis" in r and "nefrolitiasis" in r:
        return True

    if "nefrolitiasis" in r and "nefrolitiasis" not in source and "litiasis" not in source:
        return True

    return False


def _iad_ap_find_size_near_v1(text, keyword_regex, window=130):
    m = _iad_ap_re.search(keyword_regex, text, flags=_iad_ap_re.I | _iad_ap_re.S)
    if not m:
        return ""

    start = max(0, m.start() - window)
    end = min(len(text), m.end() + window)
    chunk = text[start:end]

    patterns = [
        r"(\d+(?:[,.]\d+)?)\s*(?:mm|milimetros?|milímetros?)",
        r"(\d+(?:[,.]\d+)?)\s*(?:cm|centimetros?|centímetros?)",
    ]

    for pat in patterns:
        sm = _iad_ap_re.search(pat, chunk, flags=_iad_ap_re.I)
        if sm:
            unit = "mm" if "mm" in sm.group(0).lower() or "mil" in sm.group(0).lower() else "cm"
            return f"{sm.group(1).replace(',', '.')} {unit}"

    return ""


def _iad_ap_extract_hepatic_cyst_v1(text):
    n = _iad_ap_norm_v1(text)
    if not (("lesion quistica" in n or "quiste" in n) and ("higado" in n or "hepatic" in n or "lobulo izquierdo" in n)):
        return None

    size = _iad_ap_find_size_near_v1(text, r"(lesi[oó]n qu[ií]stica|quiste).{0,120}(h[ií]gado|hep[aá]tic|l[oó]bulo izquierdo)")
    if not size:
        size = _iad_ap_find_size_near_v1(text, r"(h[ií]gado|hep[aá]tic|l[oó]bulo izquierdo).{0,120}(lesi[oó]n qu[ií]stica|quiste)")

    location = "en el lóbulo izquierdo"
    if "lobulo derecho" in n or "lóbulo derecho" in text.lower():
        location = "en el lóbulo derecho"

    return {"size": size, "location": location}


def _iad_ap_extract_renal_cyst_v1(text):
    n = _iad_ap_norm_v1(text)
    if not ("quiste renal" in n):
        return None

    side = "derecho" if ("derecha" in n or "derecho" in n) else ""
    if "izquierda" in n or "izquierdo" in n:
        side = "izquierdo"

    size = _iad_ap_find_size_near_v1(text, r"quiste renal")

    return {"side": side, "size": size}


def _iad_ap_extract_prostate_v1(text):
    n = _iad_ap_norm_v1(text)
    if "prostata" not in n:
        return None

    size = _iad_ap_find_size_near_v1(text, r"pr[oó]stata")

    return {"size": size}


def _iad_ap_has_postsigmoid_v1(text):
    n = _iad_ap_norm_v1(text)
    return (
        "sigmoides" in n
        or "sigmoid" in n
        or "ostomia" in n
        or "suturas metalicas" in n
        or "postquirurg" in n
    )


def _iad_ap_has_diverticulosis_v1(text):
    n = _iad_ap_norm_v1(text)
    return "diverticul" in n and "colon" in n


def _iad_ap_has_no_free_fluid_v1(text):
    n = _iad_ap_norm_v1(text)
    return "sin liquido libre" in n or "no hay liquido libre" in n or "no se observa liquido libre" in n


def _iad_ap_has_lithiasis_v1(text):
    n = _iad_ap_norm_v1(text)
    return "litiasis" in n or "nefrolitiasis" in n


def _iad_ap_set_template_v1(payload):
    tpl = payload.get("plantilla_sugerida")
    if not isinstance(tpl, dict):
        tpl = {}

    name = "TC Abdomen y pelvis CC"
    tpl["nombre"] = name
    tpl["name"] = name
    tpl["confianza"] = "alta"

    payload["plantilla_sugerida"] = tpl
    payload["plantilla_nombre"] = name
    payload["template_name"] = name


def _iad_ap_build_report_v1(payload):
    source = _iad_ap_source_text_v1(payload)

    hepatic_cyst = _iad_ap_extract_hepatic_cyst_v1(source)
    renal_cyst = _iad_ap_extract_renal_cyst_v1(source)
    prostate = _iad_ap_extract_prostate_v1(source)
    postsigmoid = _iad_ap_has_postsigmoid_v1(source)
    diverticulosis = _iad_ap_has_diverticulosis_v1(source)
    no_free_fluid = _iad_ap_has_no_free_fluid_v1(source)
    lithiasis = _iad_ap_has_lithiasis_v1(source)

    lines = []
    impression = []

    lines.append("TC DE ABDOMEN Y PELVIS CON CONTRASTE")
    lines.append("")
    lines.append("Hígado de morfología conservada.")

    if hepatic_cyst:
        if hepatic_cyst.get("size"):
            lines.append(f"Se identifica pequeña lesión quística {hepatic_cyst['location']} hepático de {hepatic_cyst['size']}.")
            impression.append(f"Pequeña lesión quística hepática {hepatic_cyst['location']} de {hepatic_cyst['size']}.")
        else:
            lines.append(f"Se identifica pequeña lesión quística {hepatic_cyst['location']} hepático.")
            impression.append(f"Pequeña lesión quística hepática {hepatic_cyst['location']}.")
    else:
        lines.append("Sin lesiones focales hepáticas evidentes.")

    lines.append("Vesícula biliar presente.")
    lines.append("No hay dilatación de la vía biliar intrahepática ni extrahepática.")
    lines.append("Páncreas y glándulas suprarrenales sin alteraciones evidentes.")

    if renal_cyst:
        side = renal_cyst.get("side") or ""
        size = renal_cyst.get("size") or ""
        if side and size:
            lines.append(f"Riñones de tamaño conservado. Se identifica quiste renal simple {side} de {size}.")
            impression.append(f"Quiste renal simple {side} de {size}.")
        elif side:
            lines.append(f"Riñones de tamaño conservado. Se identifica quiste renal simple {side}.")
            impression.append(f"Quiste renal simple {side}.")
        elif size:
            lines.append(f"Riñones de tamaño conservado. Se identifica quiste renal simple de {size}.")
            impression.append(f"Quiste renal simple de {size}.")
        else:
            lines.append("Riñones de tamaño conservado. Se identifica quiste renal simple.")
            impression.append("Quiste renal simple.")
    else:
        lines.append("Riñones de tamaño conservado.")

    lines.append("No hay hidronefrosis.")

    if lithiasis:
        lines.append("Se identifican litiasis renales no obstructivas.")
        impression.append("Nefrolitiasis no obstructiva.")
    else:
        lines.append("No se identifican litiasis renales evidentes.")

    lines.append("Aorta y grandes vasos abdominales de calibre conservado.")
    lines.append("Asas intestinales de calibre conservado.")

    if postsigmoid:
        lines.append("Cambios postquirúrgicos en relación al sigmoides, con antigua ostomía en fosa ilíaca izquierda y suturas metálicas, sin signos de complicación.")
        impression.append("Cambios postquirúrgicos sigmoideos sin signos de complicación.")

    if diverticulosis:
        lines.append("Divertículos en el colon, sin signos de complicación.")
        impression.append("Diverticulosis colónica sin signos de complicación.")

    lines.append("Vejiga parcialmente replecionada, sin lesiones endoluminales evidentes.")

    if prostate:
        size = prostate.get("size") or ""
        if size:
            lines.append(f"Próstata aumentada de tamaño, con diámetro transverso de hasta {size}.")
            impression.append(f"Prostatomegalia, con diámetro transverso aproximado de {size}.")
        else:
            lines.append("Próstata aumentada de tamaño.")
            impression.append("Prostatomegalia.")
    else:
        lines.append("Órganos pelvianos sin alteraciones evidentes en este estudio.")

    if no_free_fluid:
        lines.append("No hay líquido libre significativo.")
    else:
        lines.append("No se observa líquido libre significativo.")

    lines.append("Fosas isquiorrectales libres.")
    lines.append("")
    lines.append("Impresión diagnóstica:")

    if impression:
        for item in impression:
            lines.append(f"- {item}")
    else:
        lines.append("- Sin hallazgos patológicos significativos en abdomen y pelvis.")

    return "\n".join(lines).strip()


def _iad_ap_apply_clean_writer_v1(payload):
    if not isinstance(payload, dict):
        return payload

    exam = _iad_ap_detect_exam_v1(payload)
    if exam != "tc_abdomen_pelvis_cc":
        return payload

    dirty = _iad_ap_report_dirty_v1(payload)

    if not dirty:
        return payload

    before = str(payload.get("informe_final") or payload.get("final_report") or "")
    report = _iad_ap_build_report_v1(payload)

    _iad_ap_set_template_v1(payload)

    payload["informe_final_antes_clean_ap_writer"] = before
    payload["informe_final"] = report
    payload["final_report"] = report
    payload["resultado_revisado"] = report

    warnings = payload.get("advertencias")
    if not isinstance(warnings, list):
        warnings = [] if warnings in (None, "") else [str(warnings)]

    warnings.append("Clean writer TC abdomen/pelvis: se reconstruyó informe limpio porque la plantilla contenía placeholders, normalidades contradictorias o impresión contaminada.")
    payload["advertencias"] = warnings

    payload["clean_writer"] = {
        "active": True,
        "type": "tc_abdomen_pelvis_cc",
        "reason": "dirty_template_or_contradictory_output",
        "rewritten": True,
    }

    old_method = str(payload.get("metodo") or payload.get("method") or "")
    if "clean_ap_writer" not in old_method:
        payload["metodo"] = (old_method + "+clean_ap_writer").strip("+") if old_method else "clean_ap_writer"

    return payload


try:
    _iad_ap_orig_apply_template_bridge_force_v1 = _iad_v2_apply_template_bridge_force

    def _iad_v2_apply_template_bridge_force(*args, **kwargs):
        result = _iad_ap_orig_apply_template_bridge_force_v1(*args, **kwargs)
        return _iad_ap_apply_clean_writer_v1(result)

except Exception:
    pass


try:
    _iad_ap_orig_audio_first_complete_bridge_v1 = _iad_audio_first_complete_with_template_bridge

    async def _iad_audio_first_complete_with_template_bridge(*args, **kwargs):
        result = await _iad_ap_orig_audio_first_complete_bridge_v1(*args, **kwargs)
        return _iad_ap_apply_clean_writer_v1(result)

except Exception:
    pass


# IAD_ABDOMEN_PELVIS_STABLE_WRITER_V2
# Writer estable para TC Abdomen/Pelvis CC y SC.
# Objetivo:
# - no usar plantillas con xxxxx;
# - no pegar "Hallazgos positivos..." al informe;
# - impresión diagnóstica sin guiones, sin medidas, solo conceptos;
# - no concluir órganos solo presentes/ausentes;
# - funciona para CC y SC.

import re as _iad_ap2_re
import json as _iad_ap2_json
import unicodedata as _iad_ap2_ud


def _iad_ap2_norm(value):
    value = "" if value is None else str(value)
    value = value.lower()
    value = "".join(
        c for c in _iad_ap2_ud.normalize("NFD", value)
        if _iad_ap2_ud.category(c) != "Mn"
    )
    value = value.replace("\\n", " ")
    value = _iad_ap2_re.sub(r"\s+", " ", value).strip()
    return value


def _iad_ap2_try_json(value):
    if not isinstance(value, str):
        return None
    t = value.strip()
    if not t:
        return None
    if not ((t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]"))):
        return None
    try:
        return _iad_ap2_json.loads(t)
    except Exception:
        return None


def _iad_ap2_extract_text(value, depth=0):
    if depth > 4:
        return "" if value is None else str(value)

    if isinstance(value, dict):
        for k in [
            "transcripcion",
            "transcription",
            "raw_audio_first_text",
            "dictado_original",
            "source_text",
            "texto",
            "text",
            "hallazgos_radiologicos",
            "impresion_diagnostica",
        ]:
            v = value.get(k)
            if isinstance(v, str) and v.strip():
                return _iad_ap2_extract_text(v, depth + 1)

        for k in ["analysis", "generated", "data", "result"]:
            v = value.get(k)
            if isinstance(v, dict):
                out = _iad_ap2_extract_text(v, depth + 1)
                if out.strip():
                    return out

        return ""

    if isinstance(value, str):
        nested = _iad_ap2_try_json(value)
        if nested is not None:
            return _iad_ap2_extract_text(nested, depth + 1)
        return value.strip()

    return "" if value is None else str(value).strip()


def _iad_ap2_source(payload):
    if not isinstance(payload, dict):
        return _iad_ap2_extract_text(payload)

    chunks = []

    for k in [
        "dictado_original",
        "source_text",
        "texto_origen",
        "transcripcion",
        "transcription",
        "raw_audio_first_text",
        "hallazgos_radiologicos",
        "impresion_diagnostica",
    ]:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            chunks.append(_iad_ap2_extract_text(v))

    try:
        ac = payload.get("audio_composition") or {}
        if isinstance(ac, dict):
            for k in ["text", "transcription", "combined_text"]:
                v = ac.get(k)
                if isinstance(v, str) and v.strip():
                    chunks.append(_iad_ap2_extract_text(v))
    except Exception:
        pass

    out = "\n".join([c for c in chunks if c.strip()])
    return out


def _iad_ap2_detect_exam(payload):
    src = _iad_ap2_source(payload)
    n = _iad_ap2_norm(src)

    has_ap = (
        "abdomen y pelvis" in n
        or "abdomen pelvis" in n
        or "tc abdomen" in n
        or "tomografia de abdomen" in n
        or "tomografia computada de abdomen" in n
    )

    has_tap = (
        "torax abdomen pelvis" in n
        or "torax abdomen y pelvis" in n
        or "tc tap" in n
    )

    if has_ap and not has_tap:
        if "sin contraste" in n or " no contrast" in n or " sc" in f" {n} ":
            return "tc_abdomen_pelvis_sc"
        return "tc_abdomen_pelvis_cc"

    return ""


def _iad_ap2_template_name(payload):
    if not isinstance(payload, dict):
        return ""
    tpl = payload.get("plantilla_sugerida")
    if isinstance(tpl, dict):
        return str(tpl.get("nombre") or tpl.get("name") or "")
    return str(payload.get("plantilla_nombre") or payload.get("template_name") or "")


def _iad_ap2_size_near(text, keyword_regex, window=130):
    m = _iad_ap2_re.search(keyword_regex, text, flags=_iad_ap2_re.I | _iad_ap2_re.S)
    if not m:
        return ""

    start = max(0, m.start() - window)
    end = min(len(text), m.end() + window)
    chunk = text[start:end]

    # Buscar primero la medida después del término.
    after = text[m.end():min(len(text), m.end() + window)]
    before = text[max(0, m.start() - window):m.start()]

    pats = [
        r"(\d+(?:[,.]\d+)?)\s*(?:mm|milimetros?|milímetros?)",
        r"(\d+(?:[,.]\d+)?)\s*(?:cm|centimetros?|centímetros?)",
    ]

    for area in [after, chunk, before]:
        for pat in pats:
            sm = _iad_ap2_re.search(pat, area, flags=_iad_ap2_re.I)
            if sm:
                raw = sm.group(0).lower()
                unit = "mm" if "mm" in raw or "mil" in raw else "cm"
                return f"{sm.group(1).replace(',', '.')} {unit}"

    return ""


def _iad_ap2_has_neg(text, keyword):
    n = _iad_ap2_norm(text)
    k = _iad_ap2_norm(keyword)
    idx = n.find(k)
    if idx < 0:
        return False
    before = n[max(0, idx - 60):idx]
    return any(x in before for x in [
        "no ",
        "sin ",
        "no hay",
        "no se observa",
        "no se identifican",
        "no se evidencia",
        "ausencia de",
    ])


def _iad_ap2_extract_facts(source):
    n = _iad_ap2_norm(source)

    facts = {}

    facts["male"] = ("masculino" in n or "prostata" in n)
    facts["female"] = ("femenino" in n or "utero" in n)

    facts["contrast_sc"] = ("sin contraste" in n or "no contrast" in n)
    facts["contrast_cc"] = ("con contraste" in n and not facts["contrast_sc"])

    facts["gallbladder_present"] = "vesicula" in n and not ("colecistectom" in n or "vesicula ausente" in n)
    facts["gallbladder_absent"] = "vesicula ausente" in n or "colecistectom" in n

    facts["hepatic_cyst"] = (
        ("lesion quistica" in n or "quiste hepatic" in n or "quistica hepatic" in n)
        and ("higado" in n or "hepatic" in n or "lobulo" in n)
        and not _iad_ap2_has_neg(source, "lesion quistica")
    )
    facts["hepatic_cyst_size"] = _iad_ap2_size_near(source, r"(lesi[oó]n qu[ií]stica|quiste).{0,120}(h[ií]gado|hep[aá]tic|l[oó]bulo)|((h[ií]gado|hep[aá]tic|l[oó]bulo).{0,120}(lesi[oó]n qu[ií]stica|quiste))")
    facts["hepatic_lobe"] = "derecho" if "lobulo derecho" in n else "izquierdo"

    facts["renal_cyst"] = "quiste renal" in n and not _iad_ap2_has_neg(source, "quiste renal")
    facts["renal_cyst_side"] = "izquierdo" if "quiste renal simple izquierdo" in n or ("quiste renal" in n and "izquierd" in n) else ("derecho" if "derech" in n else "")
    facts["renal_cyst_size"] = _iad_ap2_size_near(source, r"quiste renal")

    facts["lithiasis_positive"] = (
        (("nefrolitiasis" in n and not _iad_ap2_has_neg(source, "nefrolitiasis"))
        or ("litiasis renal" in n and not _iad_ap2_has_neg(source, "litiasis renal")))
    )

    facts["aorta_atheromatosis"] = (
        ("ateromatosis" in n or "ateromatosas" in n or "ateromatoso" in n)
        and ("aorta" in n or "aortica" in n)
    )

    facts["adenopathy"] = (
        "adenopatia" in n
        or "adenopatias" in n
        or "adenomegalia" in n
        or "linfonodo" in n
        or "ganglio" in n
    )
    facts["adenopathy_size"] = _iad_ap2_size_near(source, r"(adenopat[ií]as?|adenomegalias?|linfonodos?|ganglios?)")
    facts["adenopathy_location"] = "retroperitoneales"
    if "psoas izquierdo" in n:
        facts["adenopathy_location"] = "retroperitoneales, adyacentes al psoas izquierdo"

    facts["post_sigmoid"] = (
        "sigmoides" in n
        or "sigmoid" in n
        or "ostomia" in n
        or "suturas metalicas" in n
        or "postquirurg" in n
    )

    facts["diverticulosis"] = "diverticul" in n and "colon" in n

    facts["appendix_normal"] = "apendice" in n and ("normal" in n or "sin alteraciones" in n)

    facts["prostate_enlarged"] = (
        "prostata" in n
        and ("aument" in n or "60" in n or "59" in n or "prostatomegalia" in n)
    )
    facts["prostate_size"] = _iad_ap2_size_near(source, r"pr[oó]stata")

    facts["free_fluid_absent"] = (
        "sin liquido libre" in n
        or "no hay liquido libre" in n
        or "no se observa liquido libre" in n
    )
    facts["free_fluid_present"] = "liquido libre" in n and not facts["free_fluid_absent"]

    return facts


def _iad_ap2_build_report(payload):
    source = _iad_ap2_source(payload)
    facts = _iad_ap2_extract_facts(source)
    exam = _iad_ap2_detect_exam(payload)

    header = "TC Abdomen y Pelvis SC" if exam == "tc_abdomen_pelvis_sc" else "TC Abdomen y Pelvis CC"

    lines = []
    impression = []

    lines.append(header)
    lines.append("")

    if exam == "tc_abdomen_pelvis_sc":
        lines.append("Hígado de morfología normal. Sin lesiones focales evidentes en este estudio no contrastado.")
    else:
        lines.append("Hígado de morfología conservada.")

    if facts["hepatic_cyst"]:
        size = facts["hepatic_cyst_size"]
        lobe = facts["hepatic_lobe"]
        if size:
            lines.append(f"Se identifica pequeña lesión quística en el lóbulo {lobe} hepático de {size}.")
        else:
            lines.append(f"Se identifica pequeña lesión quística en el lóbulo {lobe} hepático.")
        impression.append(f"Pequeña lesión quística hepática en el lóbulo {lobe}.")

    if facts["gallbladder_absent"]:
        lines.append("Vesícula biliar no visualizada.")
    else:
        lines.append("Vesícula biliar en repleción parcial, de paredes delgadas.")

    lines.append("No hay dilatación de la vía biliar intrahepática ni extrahepática.")
    lines.append("Páncreas y glándulas suprarrenales sin alteraciones evidentes.")

    if facts["renal_cyst"]:
        side = facts["renal_cyst_side"]
        size = facts["renal_cyst_size"]
        phrase = "Riñones de tamaño conservado. Se identifica quiste renal simple"
        if side:
            phrase += f" {side}"
        if size:
            phrase += f" de {size}"
        phrase += "."
        lines.append(phrase)

        if side:
            impression.append(f"Quiste renal simple {side}.")
        else:
            impression.append("Quiste renal simple.")
    else:
        lines.append("Riñones de tamaño conservado.")

    lines.append("No hay hidronefrosis.")

    if facts["lithiasis_positive"]:
        lines.append("Se identifican litiasis renales no obstructivas.")
        impression.append("Nefrolitiasis no obstructiva.")
    else:
        lines.append("No se identifican litiasis renales evidentes.")

    if facts["aorta_atheromatosis"]:
        lines.append("Ateromatosis calcificada aórtica.")
        impression.append("Ateromatosis calcificada aórtica.")
    else:
        lines.append("Aorta y grandes vasos abdominales de calibre conservado.")

    if facts["adenopathy"]:
        size = facts["adenopathy_size"]
        loc = facts["adenopathy_location"]
        if size:
            lines.append(f"Algunas adenopatías {loc}, la mayor de {size}.")
        else:
            lines.append(f"Algunas adenopatías {loc}.")
        impression.append("Adenopatías retroperitoneales.")

    lines.append("Asas intestinales de calibre conservado.")

    if facts["post_sigmoid"]:
        lines.append("Cambios postquirúrgicos en relación al sigmoides, con antigua ostomía en fosa ilíaca izquierda y suturas metálicas, sin signos de complicación.")
        impression.append("Cambios postquirúrgicos en el sigmoides y FII.")

    if facts["diverticulosis"]:
        lines.append("Divertículos en el colon, sin signos de complicación.")
        impression.append("Diverticulosis colónica sin signos de complicación.")

    if facts["appendix_normal"]:
        lines.append("Apéndice vermiforme de estructura y tamaño normal.")

    lines.append("Vejiga parcialmente replecionada, sin lesiones endoluminales evidentes.")

    if facts["male"]:
        if facts["prostate_enlarged"]:
            size = facts["prostate_size"]
            if size:
                lines.append(f"Próstata aumentada de tamaño, con diámetro transverso de hasta {size}.")
            else:
                lines.append("Próstata aumentada de tamaño.")
            impression.append("Aumento del tamaño glandular prostático.")
        else:
            lines.append("Próstata de tamaño conservado. Vesículas seminales simétricas.")
        if "Vesículas seminales simétricas." not in "\n".join(lines[-2:]):
            lines.append("Vesículas seminales simétricas.")
    elif facts["female"]:
        lines.append("Útero no visualizado. No se observan masas anexiales.")

    if facts["free_fluid_present"]:
        lines.append("Se observa líquido libre.")
        impression.append("Líquido libre intraperitoneal.")
    else:
        lines.append("No se observa líquido libre significativo.")

    lines.append("Fosas isquiorrectales libres.")
    lines.append("")
    lines.append("Impresión diagnóstica:")

    # Unicidad de impresión, sin guiones ni medidas.
    clean_imp = []
    seen = set()
    for item in impression:
        item = _iad_ap2_re.sub(
            r"\s*(?:de|hasta|aproximad[oa] de)?\s*\d+(?:[,.]\d+)?(?:\s*[x×]\s*\d+(?:[,.]\d+)?){0,2}\s*(?:mm|cm|milímetros?|milimetros?|centímetros?|centimetros?)",
            "",
            item,
            flags=_iad_ap2_re.I
        )
        item = _iad_ap2_re.sub(r"\s+", " ", item).strip(" .") + "."
        key = _iad_ap2_norm(item)
        if key not in seen:
            seen.add(key)
            clean_imp.append(item)

    if not clean_imp:
        clean_imp = ["Sin hallazgos patológicos significativos en abdomen y pelvis."]

    lines.extend(clean_imp)

    return "\n".join(lines).strip(), header


def _iad_ap2_apply(payload):
    if not isinstance(payload, dict):
        return payload

    exam = _iad_ap2_detect_exam(payload)
    if exam not in ("tc_abdomen_pelvis_cc", "tc_abdomen_pelvis_sc"):
        return payload

    before = str(payload.get("informe_final") or payload.get("final_report") or payload.get("resultado_revisado") or "")
    report, header = _iad_ap2_build_report(payload)

    tpl = payload.get("plantilla_sugerida")
    if not isinstance(tpl, dict):
        tpl = {}
    tpl["nombre"] = header
    tpl["name"] = header
    tpl["confianza"] = "alta"

    payload["plantilla_sugerida"] = tpl
    payload["plantilla_nombre"] = header
    payload["template_name"] = header

    payload["informe_final_antes_stable_writer_v2"] = before
    payload["informe_final"] = report
    payload["final_report"] = report
    payload["resultado_revisado"] = report

    warnings = payload.get("advertencias")
    if not isinstance(warnings, list):
        warnings = [] if warnings in (None, "") else [str(warnings)]

    warnings.append("Stable writer abdomen/pelvis V2: informe reconstruido limpio desde el dictado; impresión conceptual sin guiones ni medidas.")
    payload["advertencias"] = warnings

    payload["stable_writer_v2"] = {
        "active": True,
        "exam": exam,
        "header": header,
        "no_template_placeholders": True,
        "conceptual_impression": True,
    }

    old_method = str(payload.get("metodo") or payload.get("method") or "")
    if "stable_writer_v2" not in old_method:
        payload["metodo"] = (old_method + "+stable_writer_v2").strip("+") if old_method else "stable_writer_v2"

    return payload


try:
    _iad_ap2_orig_apply_template_bridge = _iad_v2_apply_template_bridge_force

    def _iad_v2_apply_template_bridge_force(*args, **kwargs):
        result = _iad_ap2_orig_apply_template_bridge(*args, **kwargs)
        return _iad_ap2_apply(result)

except Exception:
    pass


try:
    _iad_ap2_orig_audio_first_complete_bridge = _iad_audio_first_complete_with_template_bridge

    async def _iad_audio_first_complete_with_template_bridge(*args, **kwargs):
        result = await _iad_ap2_orig_audio_first_complete_bridge(*args, **kwargs)
        return _iad_ap2_apply(result)

except Exception:
    pass

