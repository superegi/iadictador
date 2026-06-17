#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.services.ai.core_v4.engine import (
    build_report,
    read_text_file,
    transcribe_audio_files,
    write_json,
    write_text,
)
from app.services.ai.core_v4.template_loader import load_template


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Core V4: audio/transcripción + reglas + plantilla -> informe final."
    )
    parser.add_argument("--audio", nargs="*", default=[], help="Uno o más archivos de audio.")
    parser.add_argument("--transcript", default="", help="Archivo de transcripción ya existente.")
    parser.add_argument("--template", required=True, help="Plantilla exportada JSON/TXT.")
    parser.add_argument("--rules", required=True, help="Archivo de reglas radiológicas.")
    parser.add_argument("--extra-text", default="", help="Texto adicional opcional.")
    parser.add_argument("--out", default="", help="Carpeta de salida.")
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("ERROR: OPENAI_API_KEY no está configurada.")

    out_dir = Path(args.out or f"runs/v4_{Path(args.template).stem}")
    out_dir.mkdir(parents=True, exist_ok=True)

    plantilla = load_template(args.template)
    reglas = read_text_file(args.rules)

    if args.transcript:
        transcripcion = read_text_file(args.transcript)
    elif args.audio:
        transcripcion = transcribe_audio_files(args.audio)
    else:
        raise SystemExit("ERROR: usa --audio o --transcript.")

    result, prompt, raw = build_report(
        transcripcion=transcripcion,
        reglas=reglas,
        plantilla=plantilla,
        texto_adicional=args.extra_text,
    )

    informe = str(result.get("informe_final") or "")

    write_text(out_dir / "transcripcion.txt", transcripcion)
    write_text(out_dir / "reglas.txt", reglas)
    write_text(out_dir / "plantilla.txt", str(plantilla.get("contenido") or ""))
    write_json(out_dir / "plantilla_meta.json", plantilla)
    write_text(out_dir / "prompt.txt", prompt)
    write_text(out_dir / "raw_model_response.txt", raw)
    write_json(out_dir / "result.json", result)
    write_text(out_dir / "informe_final.txt", informe)

    print("OK")
    print(f"OUT={out_dir}")
    print(f"METODO={result.get('metodo')}")
    print(f"PLANTILLA={plantilla.get('nombre')}")
    print(f"TEMPLATE_CHARS={len(str(plantilla.get('contenido') or ''))}")
    print(f"REPORT_CHARS={len(informe)}")
    print(f"REPORT_NEWLINES={informe.count(chr(10))}")
    print("WARNINGS:")
    for w in result.get("advertencias") or []:
        print(f" - {w}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
