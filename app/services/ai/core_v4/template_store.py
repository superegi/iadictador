from __future__ import annotations

import json
from typing import Any


def _s(value: Any) -> str:
    return str(value or "").strip()


def _normalize_newlines(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _section(title: str, body: Any) -> str:
    body_text = _normalize_newlines(str(body or ""))
    if not body_text:
        return ""
    return f"{title}\n{body_text}"


def _build_from_export_dict(obj: dict[str, Any], fallback_name: str = "") -> str:
    title = (
        _s(obj.get("titulo_informe"))
        or _s(obj.get("nombre_plantilla"))
        or _s(obj.get("nombre"))
        or _s(obj.get("template_name"))
        or fallback_name
    )

    parts: list[str] = []
    if title:
        parts.append(title)

    for title_key, value in [
        ("Técnica", obj.get("tecnica") or obj.get("técnica")),
        ("Antecedentes", obj.get("antecedentes")),
        ("Hallazgos", obj.get("hallazgos")),
        (
            "Impresión diagnóstica",
            obj.get("impresion_diagnostica")
            or obj.get("impresión_diagnóstica")
            or obj.get("impresion")
            or obj.get("impresión")
            or obj.get("conclusion")
            or obj.get("conclusión"),
        ),
    ]:
        sec = _section(title_key, value)
        if sec:
            parts.append(sec)

    return "\n\n".join(parts).strip()


def normalize_template(obj: Any, idx: int = 0) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None

    tid = _s(obj.get("id")) or _s(obj.get("template_id")) or f"tpl_{idx}"
    name = (
        _s(obj.get("nombre"))
        or _s(obj.get("nombre_plantilla"))
        or _s(obj.get("template_name"))
        or _s(obj.get("name"))
        or _s(obj.get("titulo_informe"))
        or tid
    )

    content = (
        _s(obj.get("contenido"))
        or _s(obj.get("content"))
        or _s(obj.get("template"))
        or _s(obj.get("texto"))
        or _s(obj.get("informe"))
        or ""
    )

    if not content:
        content = _build_from_export_dict(obj, fallback_name=name)

    content = _normalize_newlines(content)

    if not content:
        return None

    modality = _s(obj.get("modalidad")) or _s(obj.get("modality"))
    region = (
        _s(obj.get("region_del_cuerpo"))
        or _s(obj.get("body_region"))
        or _s(obj.get("region"))
    )

    return {
        "id": tid,
        "nombre": name,
        "modalidad": modality,
        "region_del_cuerpo": region,
        "source": _s(obj.get("source")) or _s(obj.get("path")) or "db",
        "contenido": content,
        "raw": obj,
    }


def _templates_from_collect_templates(db: Any) -> list[dict[str, Any]]:
    try:
        from app.services.ai.tasks.radiology_flow import collect_templates
    except Exception:
        return []

    try:
        raw_templates = collect_templates(db)
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_templates or []):
        tpl = normalize_template(item, idx=idx)
        if tpl:
            out.append(tpl)
    return out


def _templates_from_db_introspection(db: Any) -> list[dict[str, Any]]:
    try:
        from sqlalchemy import inspect, text
    except Exception:
        return []

    try:
        bind = db.get_bind()
        inspector = inspect(bind)
        table_names = inspector.get_table_names()
    except Exception:
        return []

    candidate_tables = [
        t for t in table_names
        if "template" in t.lower()
        or "plantilla" in t.lower()
        or "report" in t.lower()
    ]

    out: list[dict[str, Any]] = []

    for table in candidate_tables:
        try:
            rows = db.execute(text(f'SELECT * FROM "{table}" LIMIT 500')).mappings().all()
        except Exception:
            continue

        for idx, row in enumerate(rows):
            item = dict(row)
            item.setdefault("source", f"db:{table}")
            tpl = normalize_template(item, idx=len(out) + idx)
            if tpl:
                out.append(tpl)

    return out


def load_available_templates(db: Any, username: str = "") -> list[dict[str, Any]]:
    """
    Carga las plantillas disponibles.

    Primero usa el recolector existente del proyecto porque ya conoce la app.
    Si falla, usa introspección de DB.
    """
    templates = _templates_from_collect_templates(db)
    if not templates:
        templates = _templates_from_db_introspection(db)

    # Deduplicación por nombre + contenido.
    seen = set()
    out: list[dict[str, Any]] = []
    for tpl in templates:
        key = (
            str(tpl.get("nombre") or "").lower(),
            str(tpl.get("contenido") or "")[:200].lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(tpl)

    return out


def build_template_catalog(templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    catalog = []
    for tpl in templates:
        content = str(tpl.get("contenido") or "")
        preview = " ".join(content.split())[:900]
        catalog.append(
            {
                "id": tpl.get("id") or "",
                "nombre": tpl.get("nombre") or "",
                "modalidad": tpl.get("modalidad") or "",
                "region_del_cuerpo": tpl.get("region_del_cuerpo") or "",
                "source": tpl.get("source") or "",
                "preview": preview,
            }
        )
    return catalog


def find_template_by_id_or_name(
    templates: list[dict[str, Any]],
    *,
    template_id: str = "",
    template_name: str = "",
) -> dict[str, Any] | None:
    tid = str(template_id or "").strip().lower()
    tname = str(template_name or "").strip().lower()

    if tid:
        for tpl in templates:
            if str(tpl.get("id") or "").strip().lower() == tid:
                return tpl

    if tname:
        for tpl in templates:
            if str(tpl.get("nombre") or "").strip().lower() == tname:
                return tpl

        for tpl in templates:
            if tname in str(tpl.get("nombre") or "").strip().lower():
                return tpl

    return templates[0] if templates else None
