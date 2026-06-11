import asyncio
import difflib
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .db import Base, SessionLocal, engine, get_db
from .models import AuditLog, OTAudioFile, ReportTemplate, User, WorkOrder, Workplace
from .security import (
    hash_password,
    normalize_report_for_copy,
    now_utc,
    password_is_valid,
    verify_password,
)

router = APIRouter()
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

UPLOAD_ROOT = Path(os.getenv("IADICTADOR_UPLOAD_DIR", Path(__file__).resolve().parents[2] / "uploads_iadictador"))


def init_iadictador():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        admin_user = os.getenv("IADICTADOR_ADMIN_USER", "admin")
        admin_password = os.getenv("IADICTADOR_ADMIN_PASSWORD", "admin1")

        existing = db.query(User).filter(User.username == admin_user).first()
        if not existing:
            ok, msg = password_is_valid(admin_password)
            if not ok:
                raise RuntimeError(f"IADICTADOR_ADMIN_PASSWORD inválida: {msg}")

            user = User(
                username=admin_user,
                email=os.getenv("IADICTADOR_ADMIN_EMAIL"),
                password_hash=hash_password(admin_password),
                role="admin",
                is_active=True,
                must_change_password=True,
                billing_visible=False,
                billing_enabled=False,
            )
            db.add(user)
            db.commit()
            print(f"IA Dictador: admin inicial creado. Usuario={admin_user}. Debe cambiar clave al ingresar.")
    finally:
        db.close()


def audit(
    db: Session,
    request: Request,
    action: str,
    detail: str = "",
    user_id: Optional[int] = None,
):
    try:
        db.add(
            AuditLog(
                user_id=user_id,
                action=action,
                detail=detail,
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def get_session_user_id(request: Request) -> Optional[int]:
    return request.session.get("iad_user_id")


def current_user_or_none(request: Request, db: Session) -> Optional[User]:
    user_id = get_session_user_id(request)
    if not user_id:
        return None

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        request.session.clear()
        return None

    request.session["iad_request_count"] = int(request.session.get("iad_request_count", 0)) + 1
    return user


def require_user(request: Request, db: Session) -> User:
    user = current_user_or_none(request, db)
    if not user:
        raise PermissionError("login_required")
    return user


def require_admin(request: Request, db: Session) -> User:
    user = require_user(request, db)
    if user.role != "admin":
        raise PermissionError("admin_required")
    return user


def redirect(path: str):
    return RedirectResponse(path, status_code=303)


def next_ot_user_number(db: Session, user_id: int) -> int:
    last = (
        db.query(WorkOrder)
        .filter(WorkOrder.user_id == user_id)
        .order_by(WorkOrder.ot_user_number.desc())
        .first()
    )
    if not last:
        return 1
    return int(last.ot_user_number) + 1


def safe_filename(name: str) -> str:
    name = name or "audio"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name[:180]


async def save_audio_file(upload: Optional[UploadFile], ot_id: int, audio_order: int, db: Session):
    if not upload or not upload.filename:
        return

    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    ot_dir = UPLOAD_ROOT / f"ot_{ot_id}"
    ot_dir.mkdir(parents=True, exist_ok=True)

    filename = safe_filename(upload.filename)
    target = ot_dir / f"{audio_order}_{int(now_utc().timestamp())}_{filename}"

    with target.open("wb") as f:
        shutil.copyfileobj(upload.file, f)

    ext = Path(filename).suffix.lower().lstrip(".") or None

    db.add(
        OTAudioFile(
            ot_id=ot_id,
            audio_order=audio_order,
            original_filename=upload.filename,
            stored_path=str(target),
            mime_type=upload.content_type,
            extension=ext,
        )
    )
    db.commit()


def diff_text(initial: str, accepted: str) -> str:
    initial_lines = (initial or "").splitlines()
    accepted_lines = (accepted or "").splitlines()
    return "\n".join(
        difflib.unified_diff(
            initial_lines,
            accepted_lines,
            fromfile="inicial",
            tofile="validado",
            lineterm="",
        )
    )


def render(request: Request, template: str, context: dict, db: Optional[Session] = None):
    user = None
    if db:
        user = current_user_or_none(request, db)

    base_context = {
        "request": request,
        "app_name": "IA Dictador",
        "current_user": user,
        "request_count": request.session.get("iad_request_count", 0),
    }
    base_context.update(context)
    return templates.TemplateResponse(template, base_context)


@router.get("/iad", response_class=HTMLResponse)
def iad_home(request: Request, db: Session = Depends(get_db)):
    user = current_user_or_none(request, db)
    if not user:
        return redirect("/iad/login")
    return redirect("/iad/trabajo")


@router.get("/iad/login", response_class=HTMLResponse)
@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request, db: Session = Depends(get_db)):
    return render(request, "iadictador/login.html", {"error": ""}, db)


@router.post("/iad/login")
@router.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    await asyncio.sleep(3)

    user = db.query(User).filter(User.username == username.strip()).first()

    if not user or not user.is_active or not verify_password(password, user.password_hash):
        audit(db, request, "LOGIN_FAILED", f"username={username}", None)
        return render(request, "iadictador/login.html", {"error": "Usuario o clave incorrectos."}, db)

    user.last_login_at = now_utc()
    user.last_login_ip = request.client.host if request.client else None
    user.last_login_user_agent = request.headers.get("user-agent")
    db.commit()

    request.session["iad_user_id"] = user.id
    request.session["iad_username"] = user.username
    request.session["iad_role"] = user.role
    request.session["iad_request_count"] = 0

    audit(db, request, "LOGIN_OK", f"username={user.username}", user.id)

    if user.must_change_password:
        return redirect("/iad/cambiar-clave")

    return redirect("/iad/trabajo")


@router.get("/iad/logout")
@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/iad/login")


@router.get("/iad/cambiar-clave", response_class=HTMLResponse)
def change_password_get(request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    return render(request, "iadictador/change_password.html", {"error": "", "ok": ""}, db)


@router.post("/iad/cambiar-clave")
def change_password_post(
    request: Request,
    password1: str = Form(...),
    password2: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    if password1 != password2:
        return render(
            request,
            "iadictador/change_password.html",
            {"error": "Las claves no coinciden.", "ok": ""},
            db,
        )

    ok, msg = password_is_valid(password1)
    if not ok:
        return render(
            request,
            "iadictador/change_password.html",
            {"error": msg, "ok": ""},
            db,
        )

    user.password_hash = hash_password(password1)
    user.must_change_password = False
    db.commit()

    audit(db, request, "PASSWORD_CHANGED", f"username={user.username}", user.id)

    return redirect("/iad/trabajo")


@router.get("/iad/trabajo", response_class=HTMLResponse)
@router.get("/trabajo", response_class=HTMLResponse)
def work_get(request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    if user.must_change_password:
        return redirect("/iad/cambiar-clave")

    workplaces = db.query(Workplace).filter(Workplace.is_active == True).order_by(Workplace.name).all()
    templates_list = db.query(ReportTemplate).order_by(ReportTemplate.template_name).all()

    return render(
        request,
        "iadictador/work.html",
        {
            "ot": None,
            "workplaces": workplaces,
            "templates": templates_list,
        },
        db,
    )


@router.post("/iad/ot/crear")
async def create_ot(
    request: Request,
    input_text_final: str = Form(""),
    clarification_text: str = Form(""),
    workplace_id: str = Form(""),
    template_id: str = Form(""),
    patient_first_name: str = Form(""),
    patient_last_name: str = Form(""),
    patient_sex: str = Form(""),
    patient_birthdate: str = Form(""),
    patient_age: str = Form(""),
    hospital_service: str = Form(""),
    report_type: str = Form(""),
    modality: str = Form(""),
    report_title: str = Form(""),
    timezone: str = Form(""),
    utc_offset_minutes: str = Form(""),
    audio_file: Optional[UploadFile] = File(None),
    clarification_audio_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    if user.must_change_password:
        return redirect("/iad/cambiar-clave")

    ot_number = next_ot_user_number(db, user.id)

    input_type = "text"
    if audio_file and audio_file.filename:
        input_type = "audio"
    if input_text_final and audio_file and audio_file.filename:
        input_type = "mixed"

    base_text = input_text_final.strip()
    clarification = clarification_text.strip()

    review_report = base_text
    if clarification:
        review_report = f"{base_text}\n\nACLARACIÓN:\n{clarification}".strip()

    final_initial = normalize_report_for_copy(review_report)

    workplace_id_int = int(workplace_id) if workplace_id else None
    template_id_int = int(template_id) if template_id else None
    utc_offset_int = int(utc_offset_minutes) if utc_offset_minutes not in ("", None) else None

    ot = WorkOrder(
        ot_user_number=ot_number,
        user_id=user.id,
        workplace_id=workplace_id_int,
        template_id=template_id_int,
        status="processed",
        ip=request.client.host if request.client else None,
        device="",
        user_agent=request.headers.get("user-agent"),
        timezone=timezone or user.timezone,
        utc_offset_minutes=utc_offset_int,
        input_type=input_type,
        input_text_final=base_text,
        clarification_text=clarification,
        review_report=review_report,
        final_report_initial=final_initial,
        final_report_accepted=final_initial,
        patient_first_name=patient_first_name.strip() or None,
        patient_last_name=patient_last_name.strip() or None,
        patient_sex=patient_sex.strip() or None,
        patient_birthdate=patient_birthdate.strip() or None,
        patient_age=patient_age.strip() or None,
        hospital_service=hospital_service.strip() or None,
        report_type=report_type.strip() or None,
        modality=modality.strip() or None,
        report_title=report_title.strip() or None,
        billing_visible=user.billing_visible,
        billing_enabled=user.billing_enabled,
        charge_yes_no=bool(user.billing_enabled),
        charge_value=user.price_per_transcription if user.billing_enabled else None,
    )

    db.add(ot)
    db.commit()
    db.refresh(ot)

    await save_audio_file(audio_file, ot.id, 1, db)
    await save_audio_file(clarification_audio_file, ot.id, 2, db)

    audit(db, request, "OT_CREATED", f"ot_id={ot.id}; ot_user_number={ot.ot_user_number}", user.id)

    return redirect(f"/iad/ot/{ot.id}")


@router.get("/iad/ot/{ot_id}", response_class=HTMLResponse)
def view_ot(ot_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    ot = db.query(WorkOrder).filter(WorkOrder.id == ot_id).first()
    if not ot:
        return PlainTextResponse("OT no encontrada.", status_code=404)

    if user.role != "admin" and ot.user_id != user.id:
        return PlainTextResponse("Sin permiso.", status_code=403)

    workplaces = db.query(Workplace).filter(Workplace.is_active == True).order_by(Workplace.name).all()
    templates_list = db.query(ReportTemplate).order_by(ReportTemplate.template_name).all()

    return render(
        request,
        "iadictador/work.html",
        {
            "ot": ot,
            "workplaces": workplaces,
            "templates": templates_list,
        },
        db,
    )


@router.post("/iad/ot/{ot_id}/guardar-copiar")
def save_and_copy_ot(
    ot_id: int,
    request: Request,
    final_report_accepted: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        user = require_user(request, db)
    except PermissionError:
        return PlainTextResponse("login_required", status_code=401)

    ot = db.query(WorkOrder).filter(WorkOrder.id == ot_id).first()
    if not ot:
        return PlainTextResponse("OT no encontrada.", status_code=404)

    if user.role != "admin" and ot.user_id != user.id:
        return PlainTextResponse("Sin permiso.", status_code=403)

    accepted = normalize_report_for_copy(final_report_accepted)
    initial = ot.final_report_initial or ""

    ot.final_report_accepted = accepted
    ot.final_report_diff = diff_text(initial, accepted)
    ot.status = "validated"
    ot.validated_at = now_utc()
    db.commit()

    audit(db, request, "OT_VALIDATED", f"ot_id={ot.id}; ot_user_number={ot.ot_user_number}", user.id)

    return PlainTextResponse(accepted)


@router.get("/iad/historial", response_class=HTMLResponse)
@router.get("/historial", response_class=HTMLResponse)
def history_get(request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    q = db.query(WorkOrder)
    if user.role != "admin":
        q = q.filter(WorkOrder.user_id == user.id)

    ots = q.order_by(WorkOrder.created_at.desc()).limit(200).all()

    return render(
        request,
        "iadictador/history.html",
        {
            "ots": ots,
            "admin_view": user.role == "admin",
        },
        db,
    )


@router.get("/iad/admin/usuarios", response_class=HTMLResponse)
def admin_users_get(request: Request, db: Session = Depends(get_db)):
    try:
        require_admin(request, db)
    except PermissionError:
        return redirect("/iad/login")

    users = db.query(User).order_by(User.username).all()
    return render(request, "iadictador/admin_users.html", {"users": users, "error": ""}, db)


@router.post("/iad/admin/usuarios/crear")
def admin_users_create(
    request: Request,
    username: str = Form(...),
    email: str = Form(""),
    role: str = Form("user"),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        admin = require_admin(request, db)
    except PermissionError:
        return redirect("/iad/login")

    username = username.strip()
    role = role if role in ("user", "admin") else "user"

    existing = db.query(User).filter(User.username == username).first()
    if existing:
        users = db.query(User).order_by(User.username).all()
        return render(
            request,
            "iadictador/admin_users.html",
            {"users": users, "error": "Ya existe ese usuario."},
            db,
        )

    ok, msg = password_is_valid(password)
    if not ok:
        users = db.query(User).order_by(User.username).all()
        return render(
            request,
            "iadictador/admin_users.html",
            {"users": users, "error": msg},
            db,
        )

    user = User(
        username=username,
        email=email.strip() or None,
        role=role,
        password_hash=hash_password(password),
        is_active=True,
        must_change_password=True,
    )
    db.add(user)
    db.commit()

    audit(db, request, "USER_CREATED", f"username={username}; role={role}", admin.id)

    return redirect("/iad/admin/usuarios")


@router.post("/iad/admin/usuarios/{user_id}/toggle")
def admin_users_toggle(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        admin = require_admin(request, db)
    except PermissionError:
        return redirect("/iad/login")

    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.is_active = not user.is_active
        db.commit()
        audit(db, request, "USER_TOGGLED", f"username={user.username}; active={user.is_active}", admin.id)

    return redirect("/iad/admin/usuarios")


@router.post("/iad/admin/usuarios/{user_id}/reset")
def admin_users_reset(
    user_id: int,
    request: Request,
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        admin = require_admin(request, db)
    except PermissionError:
        return redirect("/iad/login")

    ok, msg = password_is_valid(password)
    if not ok:
        users = db.query(User).order_by(User.username).all()
        return render(
            request,
            "iadictador/admin_users.html",
            {"users": users, "error": msg},
            db,
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.password_hash = hash_password(password)
        user.must_change_password = True
        db.commit()
        audit(db, request, "USER_PASSWORD_RESET", f"username={user.username}", admin.id)

    return redirect("/iad/admin/usuarios")


@router.post("/iad/admin/usuarios/{user_id}/billing")
def admin_users_billing(
    user_id: int,
    request: Request,
    billing_visible: str = Form("off"),
    billing_enabled: str = Form("off"),
    price_per_transcription: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        admin = require_admin(request, db)
    except PermissionError:
        return redirect("/iad/login")

    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.billing_visible = billing_visible == "on"
        user.billing_enabled = billing_enabled == "on"
        user.price_per_transcription = float(price_per_transcription) if price_per_transcription else None
        db.commit()
        audit(
            db,
            request,
            "USER_BILLING_UPDATED",
            f"username={user.username}; visible={user.billing_visible}; enabled={user.billing_enabled}",
            admin.id,
        )

    return redirect("/iad/admin/usuarios")
