from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


def _quote_concat_path(path: Path) -> str:
    # Formato seguro para concat demuxer de ffmpeg.
    return "file '" + str(path).replace("'", "'\\''") + "'"


def merge_audio_files_for_transcription(
    audio_paths: list[str | Path],
    job_dir: str | Path,
) -> tuple[list[Path], dict[str, Any]]:
    paths = [Path(p) for p in audio_paths if Path(p).exists()]

    info: dict[str, Any] = {
        "enabled": False,
        "used": False,
        "reason": "",
        "input_count": len(paths),
        "input_files": [str(p) for p in paths],
        "output_file": "",
        "ffmpeg_available": bool(shutil.which("ffmpeg")),
        "strategy": "",
        "error": "",
    }

    if len(paths) <= 1:
        info["reason"] = "Solo hay un audio; no se requiere fusionar."
        return paths, info

    if not shutil.which("ffmpeg"):
        info["reason"] = "ffmpeg no disponible; fallback a transcripción por archivo."
        return paths, info

    info["enabled"] = True

    job = Path(job_dir)
    audio_dir = job / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    concat_file = audio_dir / "ffmpeg_concat_list.txt"
    merged = audio_dir / "merged_for_transcription.webm"

    concat_file.write_text("\n".join(_quote_concat_path(p) for p in paths) + "\n", encoding="utf-8")

    commands = [
        {
            "strategy": "concat_copy",
            "cmd": [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                str(merged),
            ],
        },
        {
            "strategy": "concat_reencode_opus",
            "cmd": [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_file),
                "-vn",
                "-acodec", "libopus",
                "-b:a", "32k",
                str(merged),
            ],
        },
    ]

    last_error = ""

    for item in commands:
        try:
            subprocess.run(
                item["cmd"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if merged.exists() and merged.stat().st_size > 0:
                info["used"] = True
                info["strategy"] = item["strategy"]
                info["output_file"] = str(merged)
                info["reason"] = f"Audios fusionados con {item['strategy']}."
                return [merged], info
        except Exception as exc:
            last_error = str(exc)

    info["error"] = last_error
    info["reason"] = "No se pudo fusionar; fallback a transcripción por archivo."
    return paths, info
