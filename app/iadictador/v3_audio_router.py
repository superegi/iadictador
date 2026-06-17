from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.iadictador.db import get_db


router = APIRouter()


@router.post("/iad/api/v3/audio/procesar-dictado-completo.json")
async def iad_api_v3_audio_procesar_dictado_completo_json(
    request: Request,
    audio_files: list[UploadFile] = File(...),
    segments_metadata_json: str = Form(""),
    extra_context: str = Form(""),
    db: Session = Depends(get_db),
):
    from app.iadictador.router import require_user
    from app.services.ai.v3.pipeline import process_v3_endpoint_response

    user = require_user(request, db)

    return await process_v3_endpoint_response(
        audio_files=audio_files,
        segments_metadata_json=segments_metadata_json,
        extra_context=extra_context,
        username=getattr(user, "username", "") or "",
        db=db,
    )
