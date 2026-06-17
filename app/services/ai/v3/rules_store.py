from __future__ import annotations

import os
from pathlib import Path


DEFAULT_RULES_TEXT = """# Reglas radiológicas generales

## Principios
- Usar la transcripción literal y el texto adicional como fuente primaria de instrucciones del médico.
- No omitir hallazgos positivos dictados.
- No inventar hallazgos no dictados.
- Usar la plantilla seleccionada como molde estructural.
- Conservar texto normal de la plantilla solo si no contradice lo dictado.
- Si un bloque marcado con xxxxx contiene alternativas, elegir solo la alternativa aplicable.
- No dejar xxxxx, separadores visuales ni alternativas no usadas en el informe final.
- Si existe duda de lateralidad, sexo/anatomía o autocorrección, mantener el hallazgo y agregar advertencia.
- El validador puede advertir, pero no debe reescribir el informe completo.
"""


def rules_file_path() -> Path:
    raw = os.getenv("IAD_RULES_FILE", "/data/reglas_radiologicas.md")
    return Path(raw)


def ensure_rules_file() -> Path:
    path = rules_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_RULES_TEXT, encoding="utf-8")
    return path


def read_rules_text() -> str:
    path = ensure_rules_file()
    return path.read_text(encoding="utf-8")


def write_rules_text(text: str) -> int:
    if not isinstance(text, str):
        raise TypeError("rules_text debe ser texto")
    path = ensure_rules_file()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return len(text.encode("utf-8"))
