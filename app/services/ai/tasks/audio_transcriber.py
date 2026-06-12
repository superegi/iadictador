from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


class AudioTranscriptionError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


def _guess_suffix(filename: str, content_type: str = "") -> str:
    filename = filename or ""
    content_type = content_type or ""

    if "." in filename:
        suffix = "." + filename.rsplit(".", 1)[-1].lower()
        if 2 <= len(suffix) <= 10:
            return suffix

    if "webm" in content_type:
        return ".webm"
    if "mpeg" in content_type or "mp3" in content_type:
        return ".mp3"
    if "wav" in content_type:
        return ".wav"
    if "ogg" in content_type:
        return ".ogg"
    if "m4a" in content_type or "mp4" in content_type:
        return ".m4a"

    return ".webm"


async def transcribe_audio_upload(upload: Any) -> dict:
    provider = _env("IAD_AI_PROVIDER_AUDIO_TRANSCRIPTION", _env("IAD_AI_PROVIDER", "openai")).lower()
    model = _env("IAD_AI_MODEL_AUDIO_TRANSCRIPTION", "gpt-4o-mini-transcribe")

    if provider not in ["openai", ""]:
        raise AudioTranscriptionError(f"Proveedor de transcripción no soportado: {provider}")

    api_key = _env("OPENAI_API_KEY")
    if not api_key:
        raise AudioTranscriptionError("OPENAI_API_KEY no está configurada dentro del contenedor.")

    try:
        from openai import OpenAI
    except Exception as exc:
        raise AudioTranscriptionError(f"No se pudo importar paquete openai: {exc}") from exc

    filename = getattr(upload, "filename", "") or "audio.webm"
    content_type = getattr(upload, "content_type", "") or ""
    suffix = _guess_suffix(filename, content_type)

    raw = await upload.read()
    if not raw:
        raise AudioTranscriptionError("El archivo de audio está vacío.")

    tmp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)

        client = OpenAI(api_key=api_key)

        with tmp_path.open("rb") as f:
            result = client.audio.transcriptions.create(
                model=model,
                file=f,
            )

        text = str(getattr(result, "text", "") or "").strip()

        return {
            "ok": True,
            "provider": "openai",
            "model": model,
            "text": text,
            "detail": "",
        }

    except Exception as exc:
        raise AudioTranscriptionError(str(exc)) from exc

    finally:
        if tmp_path:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
