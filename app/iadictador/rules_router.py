from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.ai.v3.rules_store import read_rules_text, write_rules_text


router = APIRouter()


@router.get("/api/rules/current")
async def iad_api_rules_current():
    return {
        "ok": True,
        "rules_text": read_rules_text(),
    }


@router.post("/api/rules/update")
async def iad_api_rules_update(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "JSON inválido",
            },
        )

    rules_text = payload.get("rules_text", "")
    if not isinstance(rules_text, str):
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "rules_text debe ser texto",
            },
        )

    byte_count = write_rules_text(rules_text)

    return {
        "ok": True,
        "bytes": byte_count,
    }
