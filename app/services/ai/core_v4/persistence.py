from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _model_for_stage(result: dict[str, Any], stage: str) -> str:
    usage = result.get("openai_usage") or {}
    for call in usage.get("calls") or []:
        if call.get("stage") == stage:
            return str(call.get("model") or "")
    return ""


def _patient_label(metadata: dict[str, Any]) -> str:
    name = str(metadata.get("nombre_paciente") or "").strip()
    age = str(metadata.get("edad") or "").strip()
    sex = str(metadata.get("sexo") or "").strip()

    parts = [p for p in [name, age, sex] if p]
    return " · ".join(parts)


def _infer_modality(study: str, template_name: str) -> str:
    raw = f"{study} {template_name}".lower()

    if "tomografía" in raw or "tomografia" in raw or raw.startswith("tc ") or " tc " in raw:
        return "TC"
    if "resonancia" in raw or raw.startswith("rm ") or " rm " in raw:
        return "RM"
    if "ecografía" in raw or "ecografia" in raw or "eco" in raw:
        return "US"
    if "radiografía" in raw or "radiografia" in raw or "rx" in raw:
        return "RX"

    return ""


def _exists_by_source_ref(db: Any, table: str, source: str, source_ref: str) -> bool:
    try:
        row = db.execute(
            text(f"SELECT id FROM {table} WHERE source = :source AND source_ref = :source_ref LIMIT 1"),
            {"source": source, "source_ref": source_ref},
        ).first()
        return row is not None
    except Exception:
        return False


def _exists_by_metadata_job(db: Any, table: str, job_id: str) -> bool:
    try:
        row = db.execute(
            text(f"SELECT id FROM {table} WHERE metadata_json LIKE :needle LIMIT 1"),
            {"needle": f"%{job_id}%"},
        ).first()
        return row is not None
    except Exception:
        return False


def _last_id(db: Any) -> int | None:
    try:
        value = db.execute(text("SELECT last_insert_rowid()")).scalar()
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def persist_v4_job(
    *,
    db: Any,
    job_id: str,
    job_dir: str,
    result: dict[str, Any],
    username: str,
    selected_template: dict[str, Any],
    transcript: str,
    extra_context_normalized: str,
    audio_merge_info: dict[str, Any],
) -> dict[str, Any]:
    if db is None:
        return {
            "ok": False,
            "reason": "db is None",
            "source": "core_v4_auto",
            "source_ref": job_id,
        }

    source = "core_v4_auto"
    estado = "no_validado"

    metadata_clinica = result.get("metadata_clinica") or {}
    if not isinstance(metadata_clinica, dict):
        metadata_clinica = {}

    plantilla_sugerida = result.get("plantilla_sugerida") or {}
    if not isinstance(plantilla_sugerida, dict):
        plantilla_sugerida = {}

    template_name = (
        str(plantilla_sugerida.get("nombre") or "")
        or str(selected_template.get("nombre") or "")
        or str(selected_template.get("template_name") or "")
    )

    study = str(metadata_clinica.get("estudio") or template_name or "")
    patient = _patient_label(metadata_clinica)
    modality = _infer_modality(study, template_name)
    report = str(result.get("informe_final") or "")
    model = _model_for_stage(result, "report_generation") or str((result.get("v4_debug") or {}).get("model") or "")

    hallazgos = result.get("hallazgos_estructurados") or []
    advertencias = result.get("advertencias") or []
    posibles = result.get("posibles_omisiones") or []

    clinical_payload = {
        "metadata_clinica": metadata_clinica,
        "plantilla_sugerida": plantilla_sugerida,
        "hallazgos_estructurados": hallazgos,
        "impresion_diagnostica": result.get("impresion_diagnostica") or "",
        "advertencias": advertencias,
        "posibles_omisiones": posibles,
    }

    metadata_payload = {
        "job_id": job_id,
        "job_dir": job_dir,
        "metodo": result.get("metodo"),
        "iad_audio_flow_mode": result.get("iad_audio_flow_mode"),
        "openai_usage": result.get("openai_usage"),
        "rules_manifest": (result.get("v4_debug") or {}).get("rules_manifest"),
        "audio_merge": audio_merge_info,
        "extra_context_normalized": extra_context_normalized,
        "audio_composition": result.get("audio_composition"),
        "v4_debug": result.get("v4_debug"),
        "estado_validacion": estado,
    }

    ids: dict[str, Any] = {
        "history2_work_item_id": None,
        "training_correction_id": None,
        "validation_history_id": None,
    }

    inserted: list[str] = []
    skipped: list[str] = []

    try:
        # 1) Training IA: muestra el trabajo aunque no esté validado.
        if not _exists_by_metadata_job(db, "iad_training_corrections", job_id):
            db.execute(
                text(
                    """
                    INSERT INTO iad_training_corrections (
                        created_at,
                        usuario,
                        template_name,
                        dictado_original,
                        transcripcion,
                        clinical_json,
                        informe_ia,
                        informe_corregido,
                        diferencias_detectadas,
                        modelo_usado,
                        metadata_json,
                        source,
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
                        :informe_corregido,
                        :diferencias_detectadas,
                        :modelo_usado,
                        :metadata_json,
                        :source,
                        :ot_id
                    )
                    """
                ),
                {
                    "usuario": username,
                    "template_name": template_name,
                    "dictado_original": transcript,
                    "transcripcion": transcript,
                    "clinical_json": _json(clinical_payload),
                    "informe_ia": report,
                    "informe_corregido": "",
                    "diferencias_detectadas": "",
                    "modelo_usado": model,
                    "metadata_json": _json(metadata_payload),
                    "source": source,
                    "ot_id": None,
                },
            )
            ids["training_correction_id"] = _last_id(db)
            inserted.append("iad_training_corrections")
        else:
            skipped.append("iad_training_corrections")

        # 2) Historial limpio / work items.
        if not _exists_by_source_ref(db, "iad_history2_work_items", source, job_id):
            db.execute(
                text(
                    """
                    INSERT INTO iad_history2_work_items (
                        created_at,
                        updated_at,
                        usuario,
                        modalidad,
                        nombre_estudio,
                        paciente,
                        estado,
                        ot_id,
                        training_id,
                        template_name,
                        modelo_ia,
                        version_ia,
                        transcripcion,
                        tags_json,
                        clinical_json,
                        propuesta_ia,
                        puntos_conflictivos_json,
                        version_final_usuario,
                        diff,
                        metadata_json,
                        source,
                        source_ref
                    )
                    VALUES (
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP,
                        :usuario,
                        :modalidad,
                        :nombre_estudio,
                        :paciente,
                        :estado,
                        :ot_id,
                        :training_id,
                        :template_name,
                        :modelo_ia,
                        :version_ia,
                        :transcripcion,
                        :tags_json,
                        :clinical_json,
                        :propuesta_ia,
                        :puntos_conflictivos_json,
                        :version_final_usuario,
                        :diff,
                        :metadata_json,
                        :source,
                        :source_ref
                    )
                    """
                ),
                {
                    "usuario": username,
                    "modalidad": modality,
                    "nombre_estudio": study,
                    "paciente": patient,
                    "estado": estado,
                    "ot_id": None,
                    "training_id": ids.get("training_correction_id"),
                    "template_name": template_name,
                    "modelo_ia": model,
                    "version_ia": "core_v4_auto",
                    "transcripcion": transcript,
                    "tags_json": _json(hallazgos),
                    "clinical_json": _json(clinical_payload),
                    "propuesta_ia": report,
                    "puntos_conflictivos_json": _json(
                        {
                            "advertencias": advertencias,
                            "posibles_omisiones": posibles,
                        }
                    ),
                    "version_final_usuario": "",
                    "diff": "",
                    "metadata_json": _json(metadata_payload),
                    "source": source,
                    "source_ref": job_id,
                },
            )
            ids["history2_work_item_id"] = _last_id(db)
            inserted.append("iad_history2_work_items")
        else:
            skipped.append("iad_history2_work_items")

        # 3) Historial de validación: queda como no validado hasta que el usuario valide.
        if not _exists_by_metadata_job(db, "iad_validation_history", job_id):
            db.execute(
                text(
                    """
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
                    """
                ),
                {
                    "usuario": username,
                    "template_name": template_name,
                    "dictado_original": transcript,
                    "transcripcion": transcript,
                    "clinical_json": _json(clinical_payload),
                    "informe_ia": report,
                    "informe_validado": "",
                    "diferencias_detectadas": "",
                    "modelo_usado": model,
                    "metadata_json": _json(metadata_payload),
                    "source": source,
                    "estado": estado,
                    "ot_id": None,
                },
            )
            ids["validation_history_id"] = _last_id(db)
            inserted.append("iad_validation_history")
        else:
            skipped.append("iad_validation_history")

        db.commit()

        return {
            "ok": True,
            "source": source,
            "source_ref": job_id,
            "estado": estado,
            "inserted": inserted,
            "skipped": skipped,
            "ids": ids,
        }

    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass

        return {
            "ok": False,
            "source": source,
            "source_ref": job_id,
            "estado": estado,
            "error": repr(exc),
            "inserted": inserted,
            "skipped": skipped,
            "ids": ids,
        }
