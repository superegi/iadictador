from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _db_dep():
    return __import__("app.iadictador.router", fromlist=["get_db"]).get_db


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
        return None


def _usage_from_metadata(metadata_json: Any) -> dict[str, Any]:
    data = _loads(metadata_json)
    if not isinstance(data, dict):
        return {}

    usage = data.get("openai_usage")
    if isinstance(usage, dict):
        return usage

    # Algunos registros pueden guardar openai_usage dentro de validation o v4_debug en el futuro.
    for key in ["v4_debug", "validation", "audio_composition"]:
        obj = data.get(key)
        if isinstance(obj, dict) and isinstance(obj.get("openai_usage"), dict):
            return obj["openai_usage"]

    return {}


def _job_id_from_metadata(row: dict[str, Any]) -> str:
    data = _loads(row.get("metadata_json"))
    if isinstance(data, dict):
        return str(data.get("job_id") or row.get("source_ref") or "")
    return str(row.get("source_ref") or "")


def _int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except Exception:
        return 0


def _summarize_job(row: dict[str, Any]) -> dict[str, Any]:
    usage = _usage_from_metadata(row.get("metadata_json"))
    calls = usage.get("calls") if isinstance(usage.get("calls"), list) else []

    total_tokens = 0
    total_calls = len(calls)
    duration_ms = _int(usage.get("duration_ms"))

    stages = []
    models = []

    for call in calls:
        if not isinstance(call, dict):
            continue

        stage = str(call.get("stage") or "")
        model = str(call.get("model") or "")
        provider = str(call.get("provider") or "")
        call_usage = call.get("usage") if isinstance(call.get("usage"), dict) else {}
        tokens = _int(call_usage.get("total_tokens"))
        total_tokens += tokens

        if model:
            models.append(model)

        stages.append({
            "stage": stage,
            "provider": provider,
            "model": model,
            "duration_ms": _int(call.get("duration_ms")),
            "tokens": tokens,
            "prompt_tokens": _int(call_usage.get("prompt_tokens") or call_usage.get("input_tokens")),
            "completion_tokens": _int(call_usage.get("completion_tokens") or call_usage.get("output_tokens")),
            "audio_tokens": _int((call_usage.get("input_token_details") or {}).get("audio_tokens")),
        })

    return {
        "id": row.get("id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "usuario": row.get("usuario"),
        "estado": row.get("estado"),
        "source": row.get("source"),
        "source_ref": row.get("source_ref"),
        "job_id": _job_id_from_metadata(row),
        "template_name": row.get("template_name"),
        "modelo_ia": row.get("modelo_ia"),
        "version_ia": row.get("version_ia"),
        "total_calls": total_calls,
        "total_tokens": total_tokens,
        "duration_ms": duration_ms,
        "models": sorted(set(models)),
        "stages": stages,
    }


@router.get("/iad/api/v4/usage/summary.json")
async def iad_v4_usage_summary_json(
    request: Request,
    limit: int = 1000,
    db: Session = Depends(_db_dep()),
):
    user = _require_user(request, db)
    username = str(getattr(user, "username", "") or "")

    limit = max(1, min(int(limit or 1000), 5000))

    rows = db.execute(
        text("""
            SELECT
                id, created_at, updated_at, usuario, estado, template_name,
                modelo_ia, version_ia, metadata_json, source, source_ref
            FROM iad_history2_work_items
            WHERE
                metadata_json LIKE '%openai_usage%'
                OR source LIKE 'core_v4%'
                OR version_ia LIKE 'core_v4%'
            ORDER BY id DESC
            LIMIT :limit
        """),
        {"limit": limit},
    ).mappings().all()

    jobs = [_summarize_job(dict(row)) for row in rows]

    total_jobs = len(jobs)
    total_calls = sum(_int(j.get("total_calls")) for j in jobs)
    total_tokens = sum(_int(j.get("total_tokens")) for j in jobs)
    total_duration_ms = sum(_int(j.get("duration_ms")) for j in jobs)

    by_model: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "model": "",
        "calls": 0,
        "tokens": 0,
        "duration_ms": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "audio_tokens": 0,
    })

    by_stage: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "stage": "",
        "calls": 0,
        "tokens": 0,
        "duration_ms": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "audio_tokens": 0,
    })

    by_day: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "date": "",
        "jobs": 0,
        "calls": 0,
        "tokens": 0,
        "duration_ms": 0,
    })

    for job in jobs:
        date = str(job.get("created_at") or "")[:10] or "sin_fecha"
        by_day[date]["date"] = date
        by_day[date]["jobs"] += 1
        by_day[date]["calls"] += _int(job.get("total_calls"))
        by_day[date]["tokens"] += _int(job.get("total_tokens"))
        by_day[date]["duration_ms"] += _int(job.get("duration_ms"))

        for call in job.get("stages") or []:
            model = str(call.get("model") or "modelo_no_registrado")
            stage = str(call.get("stage") or "stage_no_registrado")

            by_model[model]["model"] = model
            by_model[model]["calls"] += 1
            by_model[model]["tokens"] += _int(call.get("tokens"))
            by_model[model]["duration_ms"] += _int(call.get("duration_ms"))
            by_model[model]["prompt_tokens"] += _int(call.get("prompt_tokens"))
            by_model[model]["completion_tokens"] += _int(call.get("completion_tokens"))
            by_model[model]["audio_tokens"] += _int(call.get("audio_tokens"))

            by_stage[stage]["stage"] = stage
            by_stage[stage]["calls"] += 1
            by_stage[stage]["tokens"] += _int(call.get("tokens"))
            by_stage[stage]["duration_ms"] += _int(call.get("duration_ms"))
            by_stage[stage]["prompt_tokens"] += _int(call.get("prompt_tokens"))
            by_stage[stage]["completion_tokens"] += _int(call.get("completion_tokens"))
            by_stage[stage]["audio_tokens"] += _int(call.get("audio_tokens"))

    return {
        "ok": True,
        "username": username,
        "limit": limit,
        "summary": {
            "jobs": total_jobs,
            "calls": total_calls,
            "tokens": total_tokens,
            "duration_ms": total_duration_ms,
        },
        "by_model": sorted(by_model.values(), key=lambda x: x["tokens"], reverse=True),
        "by_stage": sorted(by_stage.values(), key=lambda x: x["tokens"], reverse=True),
        "by_day": sorted(by_day.values(), key=lambda x: x["date"], reverse=True),
        "recent_jobs": jobs[:80],
        "note": "Costo monetario no está hardcodeado. Usar tokens y modelos para estimación según tarifas vigentes/configurables.",
    }


@router.get("/iad/uso-openai", response_class=HTMLResponse)
async def iad_uso_openai_page(
    request: Request,
    db: Session = Depends(_db_dep()),
):
    _require_user(request, db)
    return templates.TemplateResponse(
        "iadictador_usage_openai.html",
        {"request": request},
    )
