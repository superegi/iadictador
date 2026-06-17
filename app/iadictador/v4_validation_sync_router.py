from __future__ import annotations

import datetime as _dt
import difflib
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

router = APIRouter()


def _db_dep():
    return __import__("app.iadictador.router", fromlist=["get_db"]).get_db


def _require_user(request: Request, db: Session) -> Any:
    from app.iadictador.router import require_user
    return require_user(request, db)


def _json_loads(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _first_text(payload: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _diff(old: str, new: str) -> str:
    old_lines = str(old or "").splitlines()
    new_lines = str(new or "").splitlines()
    return "\n".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="informe_ia",
            tofile="informe_validado",
            lineterm="",
        )
    )


def _merge_metadata(existing: Any, patch: dict[str, Any]) -> str:
    data = _json_loads(existing)
    if not isinstance(data, dict):
        data = {}

    data.update({
        "estado_validacion": "validada",
        "validated_at": _dt.datetime.utcnow().isoformat() + "Z",
    })

    validation = data.get("validation")
    if not isinstance(validation, dict):
        validation = {}

    validation.update(patch)
    data["validation"] = validation

    return _json_dumps(data)


def _find_history_row(db: Session, job_id: str) -> dict[str, Any] | None:
    row = db.execute(
        text("""
            SELECT *
            FROM iad_history2_work_items
            WHERE source_ref = :job_id
            ORDER BY id DESC
            LIMIT 1
        """),
        {"job_id": job_id},
    ).mappings().first()

    if row:
        return dict(row)

    row = db.execute(
        text("""
            SELECT *
            FROM iad_history2_work_items
            WHERE metadata_json LIKE :needle
            ORDER BY id DESC
            LIMIT 1
        """),
        {"needle": f"%{job_id}%"},
    ).mappings().first()

    return dict(row) if row else None


def _find_training_row(db: Session, job_id: str, training_id: Any = None) -> dict[str, Any] | None:
    if training_id:
        row = db.execute(
            text("""
                SELECT *
                FROM iad_training_corrections
                WHERE id = :id
                LIMIT 1
            """),
            {"id": training_id},
        ).mappings().first()
        if row:
            return dict(row)

    row = db.execute(
        text("""
            SELECT *
            FROM iad_training_corrections
            WHERE metadata_json LIKE :needle
            ORDER BY id DESC
            LIMIT 1
        """),
        {"needle": f"%{job_id}%"},
    ).mappings().first()

    return dict(row) if row else None


def _find_validation_row(db: Session, job_id: str) -> dict[str, Any] | None:
    row = db.execute(
        text("""
            SELECT *
            FROM iad_validation_history
            WHERE metadata_json LIKE :needle
            ORDER BY id DESC
            LIMIT 1
        """),
        {"needle": f"%{job_id}%"},
    ).mappings().first()

    return dict(row) if row else None


@router.post("/iad/api/validacion/core-v4/update-existing.json")
async def iad_validacion_core_v4_update_existing_json(
    request: Request,
    db: Session = Depends(_db_dep()),
):
    user = _require_user(request, db)
    username = str(getattr(user, "username", "") or "")

    payload = await request.json()

    job_id = (
        str(payload.get("core_v4_job_id") or "").strip()
        or str(payload.get("job_id") or "").strip()
        or str(payload.get("source_ref") or "").strip()
    )

    if not job_id:
        raise HTTPException(status_code=400, detail="Falta core_v4_job_id/source_ref.")

    history = _find_history_row(db, job_id)
    if not history:
        raise HTTPException(status_code=404, detail=f"No encontré trabajo V4 para job_id={job_id}")

    informe_ia = _first_text(
        payload,
        [
            "informe_ia",
            "propuesta_ia",
            "original_report",
            "originalReport",
            "ia_report",
        ],
    ) or str(history.get("propuesta_ia") or "")

    informe_validado = _first_text(
        payload,
        [
            "informe_validado",
            "informe_corregido",
            "version_final_usuario",
            "final_report",
            "finalReport",
            "informe_final",
            "validated_report",
            "report",
        ],
    )

    if not informe_validado:
        raise HTTPException(status_code=400, detail="Falta informe validado/final.")

    diferencias = _diff(informe_ia, informe_validado)

    clinical_json = history.get("clinical_json") or "{}"
    tags_json = history.get("tags_json") or "[]"
    puntos_json = history.get("puntos_conflictivos_json") or "[]"

    validation_patch = {
        "validated_by": username,
        "core_v4_job_id": job_id,
        "source": "core_v4_validated",
        "source_previous": history.get("source"),
        "history2_work_item_id": history.get("id"),
        "training_id": history.get("training_id"),
        "payload_keys": sorted(list(payload.keys())),
    }

    history_metadata = _merge_metadata(history.get("metadata_json"), validation_patch)

    db.execute(
        text("""
            UPDATE iad_history2_work_items
            SET
                updated_at = CURRENT_TIMESTAMP,
                estado = :estado,
                version_final_usuario = :version_final_usuario,
                diff = :diff,
                metadata_json = :metadata_json,
                source = :source
            WHERE id = :id
        """),
        {
            "estado": "validada",
            "version_final_usuario": informe_validado,
            "diff": diferencias,
            "metadata_json": history_metadata,
            "source": "core_v4_validated",
            "id": history["id"],
        },
    )

    training = _find_training_row(db, job_id, history.get("training_id"))
    training_id = training.get("id") if training else None

    if training:
        training_metadata = _merge_metadata(training.get("metadata_json"), validation_patch)
        db.execute(
            text("""
                UPDATE iad_training_corrections
                SET
                    informe_corregido = :informe_corregido,
                    diferencias_detectadas = :diferencias_detectadas,
                    metadata_json = :metadata_json,
                    source = :source
                WHERE id = :id
            """),
            {
                "informe_corregido": informe_validado,
                "diferencias_detectadas": diferencias,
                "metadata_json": training_metadata,
                "source": "core_v4_validated",
                "id": training["id"],
            },
        )

    validation = _find_validation_row(db, job_id)
    validation_id = validation.get("id") if validation else None

    if validation:
        validation_metadata = _merge_metadata(validation.get("metadata_json"), validation_patch)
        db.execute(
            text("""
                UPDATE iad_validation_history
                SET
                    estado = :estado,
                    informe_validado = :informe_validado,
                    diferencias_detectadas = :diferencias_detectadas,
                    metadata_json = :metadata_json,
                    source = :source
                WHERE id = :id
            """),
            {
                "estado": "validada",
                "informe_validado": informe_validado,
                "diferencias_detectadas": diferencias,
                "metadata_json": validation_metadata,
                "source": "core_v4_validated",
                "id": validation["id"],
            },
        )
    else:
        db.execute(
            text("""
                INSERT INTO iad_validation_history (
                    created_at,
                    usuario,
                    template_name,
                    dictado_original,
                    transcripcion,
                    clinical_json,
                    informe_ia,
                    informe_validado,
                    diferencias_detectadas,
                    modelo_usado,
                    metadata_json,
                    source,
                    estado,
                    ot_id
                )
                VALUES (
                    CURRENT_TIMESTAMP,
                    :usuario,
                    :template_name,
                    :dictado_original,
                    :transcripcion,
                    :clinical_json,
                    :informe_ia,
                    :informe_validado,
                    :diferencias_detectadas,
                    :modelo_usado,
                    :metadata_json,
                    :source,
                    :estado,
                    :ot_id
                )
            """),
            {
                "usuario": username,
                "template_name": history.get("template_name"),
                "dictado_original": history.get("transcripcion"),
                "transcripcion": history.get("transcripcion"),
                "clinical_json": clinical_json,
                "informe_ia": informe_ia,
                "informe_validado": informe_validado,
                "diferencias_detectadas": diferencias,
                "modelo_usado": history.get("modelo_ia"),
                "metadata_json": _merge_metadata({}, validation_patch),
                "source": "core_v4_validated",
                "estado": "validada",
                "ot_id": history.get("ot_id"),
            },
        )
        try:
            validation_id = int(db.execute(text("SELECT last_insert_rowid()")).scalar())
        except Exception:
            validation_id = None

    db.commit()

    return {
        "ok": True,
        "message": "Validación V4 actualizada sobre el trabajo existente.",
        "source": "core_v4_validated",
        "source_ref": job_id,
        "estado": "validada",
        "saved_training": bool(training_id),
        "saved_validation": True,
        "updated_existing": True,
        "ids": {
            "history2_work_item_id": history.get("id"),
            "training_correction_id": training_id,
            "validation_history_id": validation_id,
        },
        "diff_lines": len(diferencias.splitlines()) if diferencias else 0,
    }
