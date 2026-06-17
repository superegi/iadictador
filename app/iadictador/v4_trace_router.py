from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

router = APIRouter()


def _get_db_dep():
    from app.iadictador.router import get_db
    return get_db


def _require_user(request: Request, db: Session) -> Any:
    from app.iadictador.router import require_user
    return require_user(request, db)


def _loads(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return value


def _json_dict(value: Any) -> dict[str, Any]:
    obj = _loads(value)
    return obj if isinstance(obj, dict) else {}


def _summarize_usage(usage: dict[str, Any]) -> dict[str, Any]:
    calls = usage.get("calls") or []
    out_calls = []
    total_tokens = 0

    for call in calls:
        u = call.get("usage") or {}
        tokens = u.get("total_tokens")
        if isinstance(tokens, int):
            total_tokens += tokens

        out_calls.append({
            "stage": call.get("stage"),
            "provider": call.get("provider"),
            "model": call.get("model"),
            "duration_ms": call.get("duration_ms"),
            "tokens": tokens,
            "usage": u,
        })

    return {
        "total_calls": usage.get("total_calls", len(calls)),
        "total_tokens": total_tokens or None,
        "duration_ms": usage.get("duration_ms"),
        "calls": out_calls,
    }


def _build_payload(row: dict[str, Any], table: str) -> dict[str, Any]:
    metadata = _json_dict(row.get("metadata_json"))
    clinical = _json_dict(row.get("clinical_json"))

    usage = metadata.get("openai_usage") or {}
    rules_manifest = metadata.get("rules_manifest") or {}
    audio_merge = metadata.get("audio_merge") or {}

    job_id = metadata.get("job_id") or row.get("source_ref") or ""
    job_dir = metadata.get("job_dir") or ""

    return {
        "ok": True,
        "table": table,
        "id": row.get("id"),
        "created_at": row.get("created_at"),
        "usuario": row.get("usuario"),
        "estado": row.get("estado") or metadata.get("estado_validacion") or "",
        "source": row.get("source") or metadata.get("source") or "",
        "source_ref": row.get("source_ref") or job_id,
        "job_id": job_id,
        "job_dir": job_dir,
        "template_name": row.get("template_name"),
        "modelo": row.get("modelo_ia") or row.get("modelo_usado"),
        "version_ia": row.get("version_ia") or metadata.get("metodo") or "",
        "metadata_clinica": clinical.get("metadata_clinica") or metadata.get("metadata_clinica") or {},
        "plantilla_sugerida": clinical.get("plantilla_sugerida") or {},
        "advertencias": clinical.get("advertencias") or [],
        "posibles_omisiones": clinical.get("posibles_omisiones") or [],
        "usage_summary": _summarize_usage(usage if isinstance(usage, dict) else {}),
        "rules_manifest": rules_manifest,
        "audio_merge": audio_merge,
        "extra_context_normalized": metadata.get("extra_context_normalized") or "",
        "raw_metadata": metadata,
    }


@router.get("/iad/api/v4/trace/history2/{work_id}.json")
async def iad_v4_trace_history2_json(
    work_id: int,
    request: Request,
    db: Session = Depends(_get_db_dep()),
):
    _require_user(request, db)

    row = db.execute(
        text("""
            SELECT *
            FROM iad_history2_work_items
            WHERE id = :id
            LIMIT 1
        """),
        {"id": work_id},
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")

    return _build_payload(dict(row), "iad_history2_work_items")


@router.get("/iad/api/v4/trace/training/{training_id}.json")
async def iad_v4_trace_training_json(
    training_id: int,
    request: Request,
    db: Session = Depends(_get_db_dep()),
):
    _require_user(request, db)

    row = db.execute(
        text("""
            SELECT *
            FROM iad_training_corrections
            WHERE id = :id
            LIMIT 1
        """),
        {"id": training_id},
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Training no encontrado.")

    return _build_payload(dict(row), "iad_training_corrections")


@router.get("/iad/api/v4/trace/latest.json")
async def iad_v4_trace_latest_json(
    request: Request,
    db: Session = Depends(_get_db_dep()),
):
    _require_user(request, db)

    row = db.execute(
        text("""
            SELECT *
            FROM iad_history2_work_items
            WHERE source = :source
            ORDER BY id DESC
            LIMIT 1
        """),
        {"source": "core_v4_auto"},
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="No hay trabajos V4.")

    return _build_payload(dict(row), "iad_history2_work_items")
