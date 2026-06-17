from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.services.ai.core_v4.rules_store import (
    load_effective_rules,
    read_rule_scope,
    safe_username,
    write_rule_scope,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


class RulesUpdatePayload(BaseModel):
    scope: str
    rules_text: str


def _is_admin(user: Any) -> bool:
    username = str(getattr(user, "username", "") or "")
    admin_user = str(os.getenv("IADICTADOR_ADMIN_USER", "admin") or "admin")
    return bool(
        username == "admin"
        or username == admin_user
        or getattr(user, "is_admin", False)
        or getattr(user, "admin", False)
    )


def _current_user(request: Request, db: Session) -> Any:
    from app.iadictador.router import require_user

    return require_user(request, db)


@router.get("/iad/reglas-ia", response_class=HTMLResponse)
async def iad_reglas_ia_page(
    request: Request,
    db: Session = Depends(__import__("app.iadictador.router", fromlist=["get_db"]).get_db),
):
    user = _current_user(request, db)
    username = str(getattr(user, "username", "") or "")
    admin = _is_admin(user)

    return templates.TemplateResponse(
        "iadictador_rules_repo.html",
        {
            "request": request,
            "username": username,
            "is_admin": admin,
        },
    )


@router.get("/iad/api/rules/repo/current.json")
async def iad_rules_repo_current_json(
    request: Request,
    db: Session = Depends(__import__("app.iadictador.router", fromlist=["get_db"]).get_db),
):
    user = _current_user(request, db)
    username = str(getattr(user, "username", "") or "")
    admin = _is_admin(user)

    bundle = load_effective_rules(username=username)

    return {
        "ok": True,
        "username": username,
        "safe_username": safe_username(username),
        "is_admin": admin,
        "permissions": {
            "can_edit_app": admin,
            "can_edit_general": admin,
            "can_edit_user": True,
        },
        "priority_order": ["app", "general", "user"],
        "conflict_policy": "app > general > user",
        "rules": {
            "app": bundle["app_rules"] if admin else "",
            "general": bundle["general_rules"] if admin else "",
            "user": bundle["user_rules"],
            "compiled": bundle["compiled_rules"],
        },
        "manifest": bundle["manifest"],
    }


@router.post("/iad/api/rules/repo/update.json")
async def iad_rules_repo_update_json(
    payload: RulesUpdatePayload,
    request: Request,
    db: Session = Depends(__import__("app.iadictador.router", fromlist=["get_db"]).get_db),
):
    user = _current_user(request, db)
    username = str(getattr(user, "username", "") or "")
    admin = _is_admin(user)

    scope = str(payload.scope or "").strip().lower()

    if scope not in {"app", "general", "user"}:
        raise HTTPException(status_code=400, detail="scope debe ser app, general o user.")

    if scope in {"app", "general"} and not admin:
        raise HTTPException(status_code=403, detail="Solo administrador puede editar estas reglas.")

    target_username = username if scope == "user" else ""

    saved = write_rule_scope(
        scope=scope,
        rules_text=payload.rules_text,
        username=target_username,
    )

    bundle = load_effective_rules(username=username)

    return {
        "ok": True,
        "saved": saved,
        "username": username,
        "is_admin": admin,
        "manifest": bundle["manifest"],
    }


# Alias simple para futuro frontend.
@router.get("/iad/api/rules/repository.json")
async def iad_rules_repository_alias_json(
    request: Request,
    db: Session = Depends(__import__("app.iadictador.router", fromlist=["get_db"]).get_db),
):
    return await iad_rules_repo_current_json(request=request, db=db)


@router.post("/iad/api/rules/repository/update.json")
async def iad_rules_repository_update_alias_json(
    payload: RulesUpdatePayload,
    request: Request,
    db: Session = Depends(__import__("app.iadictador.router", fromlist=["get_db"]).get_db),
):
    return await iad_rules_repo_update_json(payload=payload, request=request, db=db)
