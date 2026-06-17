from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_newlines(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _section(title: str, body: Any) -> str:
    body_text = _normalize_newlines(str(body or ""))
    if not body_text:
        return ""
    return f"{title}\n{body_text}"


def _build_template_from_export_dict(obj: dict[str, Any], fallback_name: str) -> str:
    """
    Reconstruye una plantilla exportada desde la app.

    Formato esperado:
    {
      "nombre_plantilla": "...",
      "titulo_informe": "...",
      "tecnica": "...",
      "antecedentes": "...",
      "hallazgos": "...",
      "impresion_diagnostica": "..."
    }
    """
    title = (
        _text(obj.get("titulo_informe"))
        or _text(obj.get("nombre_plantilla"))
        or _text(obj.get("nombre"))
        or _text(obj.get("template_name"))
        or fallback_name
    )

    parts: list[str] = []
    if title:
        parts.append(title)

    tecnica = _section("Técnica", obj.get("tecnica") or obj.get("técnica"))
    antecedentes = _section("Antecedentes", obj.get("antecedentes"))
    hallazgos = _section("Hallazgos", obj.get("hallazgos"))
    impresion = _section(
        "Impresión diagnóstica",
        obj.get("impresion_diagnostica")
        or obj.get("impresión_diagnóstica")
        or obj.get("impresion")
        or obj.get("impresión")
        or obj.get("conclusion")
        or obj.get("conclusión")
    )

    for item in [tecnica, antecedentes, hallazgos, impresion]:
        if item:
            parts.append(item)

    return "\n\n".join(parts).strip()


def _find_template_text(obj: Any, fallback_name: str = "") -> str:
    if isinstance(obj, str):
        return _normalize_newlines(obj)

    if isinstance(obj, dict):
        # Caso preferente: exportación estructurada de la app.
        structured_keys = {
            "nombre_plantilla",
            "titulo_informe",
            "tecnica",
            "técnica",
            "antecedentes",
            "hallazgos",
            "impresion_diagnostica",
            "impresión_diagnóstica",
        }
        if any(k in obj for k in structured_keys):
            built = _build_template_from_export_dict(obj, fallback_name)
            if built:
                return built

        # Caso: texto completo en un campo.
        for key in [
            "contenido",
            "content",
            "template",
            "texto",
            "body",
            "report",
            "informe",
            "plantilla",
        ]:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_newlines(value)

        # Caso: secciones anidadas.
        sections = obj.get("sections") or obj.get("secciones")
        if isinstance(sections, dict):
            parts = []
            for key, value in sections.items():
                if isinstance(value, str) and value.strip():
                    parts.append(f"{key}\n{_normalize_newlines(value)}")
            if parts:
                return "\n\n".join(parts).strip()

    return ""


def load_template(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="ignore")

    name = p.stem
    source = str(p)

    if p.suffix.lower() == ".json":
        try:
            obj = json.loads(raw)
        except Exception as exc:
            raise ValueError(f"No pude leer JSON de plantilla: {exc}") from exc

        original_obj = obj

        if isinstance(obj, list):
            if not obj:
                raise ValueError("La plantilla JSON es una lista vacía.")
            obj = obj[0]

        text = _find_template_text(obj, fallback_name=name)
        if not text.strip():
            raise ValueError("La plantilla JSON no contiene texto reconocible.")

        if isinstance(obj, dict):
            nombre = (
                _text(obj.get("nombre"))
                or _text(obj.get("nombre_plantilla"))
                or _text(obj.get("name"))
                or _text(obj.get("template_name"))
                or _text(obj.get("titulo_informe"))
                or name
            )
            tid = _text(obj.get("id"))
        else:
            nombre = name
            tid = ""

        return {
            "id": tid,
            "nombre": nombre,
            "source": source,
            "contenido": text,
            "raw": original_obj,
        }

    if not raw.strip():
        raise ValueError("La plantilla está vacía.")

    return {
        "id": "",
        "nombre": name,
        "source": source,
        "contenido": _normalize_newlines(raw),
        "raw": raw,
    }
