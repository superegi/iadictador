from app.services.ai.tasks.info_extractor import extract_information_from_text
from app.services.ai.tasks.audio_transcriber import transcribe_audio_upload, AudioTranscriptionError
from fastapi.responses import JSONResponse
from fastapi import UploadFile, File
from datetime import datetime
from starlette.responses import Response as StarletteResponse
import asyncio
import difflib
import os
import zipfile
import io
import base64
import json
import difflib
import json
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

IAD_BODY_REGIONS = [
    "Cabeza, cuello y columna",
    "Torax, abdomen y pelvis",
    "Extremidades y articulaciones",
    "Mamaria y ginecología",
]
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



def clean_form_text(value: str) -> str:
    value = str(value or "").strip()
    if value.lower() == "none":
        return ""
    return value


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



# IAD_TEMPLATE_WORK_HELPERS_START
def report_template_to_text(t: ReportTemplate | None) -> str:
    if not t:
        return ""

    chunks = []

    title = (t.title or t.template_name or "").strip()
    if title:
        chunks.append(title)

    technique = (t.technique or "").strip()
    if technique:
        chunks.append("TÉCNICA:\n" + technique)

    background = (t.background or "").strip()
    if background:
        chunks.append("ANTECEDENTES:\n" + background)

    findings = (t.findings or "").strip()
    if findings:
        chunks.append("HALLAZGOS:\n" + findings)

    impression = (t.impression or "").strip()
    if impression:
        chunks.append("IMPRESIÓN:\n" + impression)

    return "\n\n".join(chunks).strip()


def report_template_payload(t: ReportTemplate) -> dict:
    return {
        "id": str(t.id),
        "radiology_use": t.radiology_use or "",
        "template_name": t.template_name or "",
        "title": t.title or "",
        "technique": t.technique or "",
        "background": t.background or "",
        "findings": t.findings or "",
        "impression": t.impression or "",
        "tags": t.tags or "",
        "specific_rules_json": t.specific_rules_json or "",
        "template_text": report_template_to_text(t),
    }


def templates_payload_json(rows: list[ReportTemplate]) -> str:
    return json.dumps([report_template_payload(t) for t in rows], ensure_ascii=False)


def compose_work_report(
    input_text: str,
    template_working_text: str,
    template_obj: ReportTemplate | None,
    modality: str = "",
    report_type: str = "",
) -> str:
    input_text = (input_text or "").strip()
    template_working_text = (template_working_text or "").strip()

    if not template_working_text and template_obj:
        template_working_text = report_template_to_text(template_obj)

    chunks = []

    meta = []
    if modality:
        meta.append(f"Modalidad: {clean_form_text(modality)}")
    if report_type:
        meta.append(f"Tipo de informe: {clean_form_text(report_type)}")

    if meta:
        chunks.append(" / ".join(meta))

    if template_working_text:
        chunks.append(template_working_text)

    if input_text:
        if template_working_text:
            chunks.append("DATOS DICTADOS / AJUSTES:\n" + input_text)
        else:
            chunks.append(input_text)

    return "\n\n".join(chunks).strip()
# IAD_TEMPLATE_WORK_HELPERS_END


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
    templates_list = db.query(ReportTemplate).order_by(ReportTemplate.radiology_use, ReportTemplate.template_name).all()

    return render(
        request,
        "iadictador/work.html",
        {
            "ot": None,
            "workplaces": workplaces,
            "templates": templates_list,
            "templates_json": templates_payload_json(templates_list),
        },
        db,
    )




@router.post("/iad/audio/transcribir")
async def iad_audio_transcribe_post(
    request: Request,
    audio_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        user = require_user(request, db)
    except PermissionError:
        return JSONResponse(
            {"ok": False, "text": "", "detail": "No autenticado."},
            status_code=401,
        )

    try:
        result = await transcribe_audio_upload(audio_file)

        try:
            audit(
                db,
                request,
                "AUDIO_TRANSCRIBED",
                f"filename={getattr(audio_file, 'filename', '')}; provider={result.get('provider')}; model={result.get('model')}",
                user.id,
            )
        except Exception:
            pass

        return JSONResponse(result)

    except AudioTranscriptionError as exc:
        detail = str(exc)

        try:
            audit(
                db,
                request,
                "AUDIO_TRANSCRIPTION_FAILED",
                f"filename={getattr(audio_file, 'filename', '')}; error={detail}",
                user.id,
            )
        except Exception:
            pass

        return JSONResponse(
            {"ok": False, "text": "", "detail": detail},
            status_code=500,
        )

    except Exception as exc:
        detail = str(exc)

        try:
            audit(
                db,
                request,
                "AUDIO_TRANSCRIPTION_FAILED",
                f"filename={getattr(audio_file, 'filename', '')}; error={detail}",
                user.id,
            )
        except Exception:
            pass

        return JSONResponse(
            {"ok": False, "text": "", "detail": detail},
            status_code=500,
        )

@router.post("/iad/ot/crear")
async def create_ot(
    request: Request,
    input_text_final: str = Form(""),
    clarification_text: str = Form(""),
    workplace_id: str = Form(""),
    template_id: str = Form(""),
    template_working_text: str = Form(""),
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
    audio_files: list[UploadFile] = File([]),
    audio_durations_json: str = Form("[]"),
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

    base_text = clean_form_text(input_text_final)
    clarification = clean_form_text(clarification_text)

    workplace_id_int = int(workplace_id) if workplace_id else None
    template_id_int = int(template_id) if template_id else None
    utc_offset_int = int(utc_offset_minutes) if utc_offset_minutes not in ("", None) else None

    selected_template = None
    if template_id_int:
        selected_template = db.query(ReportTemplate).filter(ReportTemplate.id == template_id_int).first()

    review_report = compose_work_report(
        input_text=base_text,
        template_working_text=template_working_text,
        template_obj=selected_template,
        modality=modality,
        report_type=report_type,
    )

    if clarification:
        review_report = (review_report + "\n\nACLARACIÓN:\n" + clarification).strip()

    final_initial = normalize_report_for_copy(review_report)

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
        patient_first_name=clean_form_text(patient_first_name) or None,
        patient_last_name=clean_form_text(patient_last_name) or None,
        patient_sex=clean_form_text(patient_sex) or None,
        patient_birthdate=clean_form_text(patient_birthdate) or None,
        patient_age=clean_form_text(patient_age) or None,
        hospital_service=clean_form_text(hospital_service) or None,
        report_type=clean_form_text(report_type) or None,
        modality=clean_form_text(modality) or None,
        report_title=clean_form_text(report_title) or None,
        billing_visible=user.billing_visible,
        billing_enabled=user.billing_enabled,
        charge_yes_no=bool(user.billing_enabled),
        charge_value=user.price_per_transcription if user.billing_enabled else None,
    )

    db.add(ot)
    db.commit()
    db.refresh(ot)
# Audio de aclaración deshabilitado por ahora.


    # IAD_AUDIO_MULTI_SAVE_START
    try:
        audio_durations = json.loads(audio_durations_json or "[]")
    except Exception:
        audio_durations = []

    async def _save_one_ot_audio(upload, seq: int):
        if not upload or not getattr(upload, "filename", ""):
            return

        duration_s = 0
        try:
            duration_s = int(float(audio_durations[seq - 1]))
        except Exception:
            duration_s = 0

        mm = duration_s // 60
        ss = duration_s % 60
        duration_txt = f"{mm:02d}:{ss:02d}"

        now_txt = datetime.now().strftime("%H:%M:%S")
        ext = ".webm"
        original_name = getattr(upload, "filename", "") or ""
        if "." in original_name:
            ext = "." + original_name.rsplit(".", 1)[-1].lower()[:8]

        try:
            upload.filename = f"OT#{ot.id} Grabacion{seq} {now_txt} - {duration_txt}{ext}"
        except Exception:
            pass

        await save_audio_file(upload, ot.id, seq, db)

    seq = 1
    for upload in audio_files or []:
        await _save_one_ot_audio(upload, seq)
        seq += 1

    # Compatibilidad con input antiguo audio_file, si quedó en el formulario.
    try:
        if audio_file and getattr(audio_file, "filename", ""):
            await _save_one_ot_audio(audio_file, seq)
            seq += 1
    except NameError:
        pass
    # IAD_AUDIO_MULTI_SAVE_END

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
    templates_list = db.query(ReportTemplate).order_by(ReportTemplate.radiology_use, ReportTemplate.template_name).all()

    return render(
        request,
        "iadictador/work.html",
        {
            "ot": ot,
            "workplaces": workplaces,
            "templates": templates_list,
            "templates_json": templates_payload_json(templates_list),
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




# IAD_EXTRACCION_CONTROLADA_MARKER
def _iad_extraction_current_user(request, db):
    """Compatibilidad con distintas versiones internas de login."""
    for fname in ("current_user_from_request", "get_current_user", "current_user", "require_current_user"):
        fn = globals().get(fname)
        if callable(fn):
            try:
                return fn(request, db)
            except TypeError:
                try:
                    return fn(request)
                except Exception:
                    pass
            except Exception:
                pass

    session = getattr(request, "session", {}) or {}
    user_id = session.get("user_id") or session.get("iad_user_id") or session.get("uid")
    if user_id:
        for obj in globals().values():
            if isinstance(obj, type) and getattr(obj, "__tablename__", "") in {"iad_users", "users", "usuarios"}:
                try:
                    return db.query(obj).filter(obj.id == int(user_id)).first()
                except Exception:
                    return None
    return None


def _iad_extraction_ot_model():
    """Detecta dinámicamente el modelo SQLAlchemy de OT."""
    candidates = []
    for obj in globals().values():
        if not isinstance(obj, type):
            continue
        tablename = getattr(obj, "__tablename__", "")
        attrs = set(dir(obj))
        score = 0
        if tablename in {"iad_ots", "ots", "ordenes_trabajo", "work_orders"}:
            score += 100
        if "audio_transcription_initial" in attrs:
            score += 30
        if "audio_transcription_final" in attrs:
            score += 30
        if "input_text_initial" in attrs or "input_text_final" in attrs:
            score += 20
        if "final_text" in attrs or "report_final" in attrs:
            score += 10
        if "id" in attrs:
            score += 5
        if score:
            candidates.append((score, obj))
    if not candidates:
        raise RuntimeError("No pude detectar el modelo de OT.")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _iad_extraction_get_ot(db, ot_id: int):
    model = _iad_extraction_ot_model()
    return db.query(model).filter(model.id == ot_id).first()


def _iad_extraction_source_text(ot, override_text: str = "") -> str:
    parts = []
    if override_text and override_text.strip():
        parts.append(override_text.strip())

    preferred_attrs = [
        "input_text_final",
        "input_text_initial",
        "audio_transcription_final",
        "audio_transcription_initial",
        "transcription_final",
        "transcription_initial",
        "texto_final",
        "texto_inicial",
        "final_text",
        "initial_text",
        "raw_text",
        "description",
        "descripcion",
    ]

    for attr in preferred_attrs:
        value = getattr(ot, attr, None)
        if value and str(value).strip():
            parts.append(str(value).strip())

    # Quitar duplicados conservando orden.
    seen = set()
    unique = []
    for item in parts:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(key)

    return "\n\n".join(unique).strip()


def _iad_extraction_list_templates(db):
    """Lista plantillas sin depender de nombres exactos de modelos."""
    from sqlalchemy import text as _sa_text

    out = []
    try:
        tables = db.execute(
            _sa_text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ).fetchall()
    except Exception:
        return out

    for row in tables:
        table = row[0]
        table_l = table.lower()
        if not any(key in table_l for key in ("template", "plantilla")):
            continue

        try:
            cols = db.execute(_sa_text(f'PRAGMA table_info("{table}")')).fetchall()
        except Exception:
            continue

        colnames = [c[1] for c in cols]
        id_col = "id" if "id" in colnames else None
        name_col = None
        for candidate in ("name", "nombre", "title", "titulo", "template_name"):
            if candidate in colnames:
                name_col = candidate
                break

        if not id_col or not name_col:
            continue

        try:
            rows = db.execute(
                _sa_text(f'SELECT "{id_col}", "{name_col}" FROM "{table}" ORDER BY "{name_col}" LIMIT 200')
            ).fetchall()
            for r in rows:
                if r[1]:
                    out.append({"id": r[0], "nombre": str(r[1]), "tabla": table})
        except Exception:
            continue

    # Dedupe por nombre.
    seen = set()
    clean = []
    for item in out:
        key = item["nombre"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            clean.append(item)
    return clean


def _iad_extraction_ensure_table(db):
    from sqlalchemy import text as _sa_text

    db.execute(_sa_text("""
        CREATE TABLE IF NOT EXISTS iad_ot_extractions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ot_id INTEGER NOT NULL UNIQUE,
            extraction_json TEXT NOT NULL,
            raw_text TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    db.commit()


def _iad_extraction_get_saved(db, ot_id: int):
    from sqlalchemy import text as _sa_text
    import json as _json

    _iad_extraction_ensure_table(db)
    row = db.execute(
        _sa_text("""
            SELECT extraction_json, raw_text, created_at, updated_at
            FROM iad_ot_extractions
            WHERE ot_id = :ot_id
        """),
        {"ot_id": ot_id},
    ).fetchone()

    if not row:
        return None

    try:
        extraction = _json.loads(row[0] or "{}")
    except Exception:
        extraction = {}

    return {
        "ot_id": ot_id,
        "extraction": extraction,
        "raw_text": row[1] or "",
        "created_at": row[2],
        "updated_at": row[3],
    }


def _iad_extraction_save(db, ot_id: int, extraction: dict, raw_text: str):
    from sqlalchemy import text as _sa_text
    import json as _json

    _iad_extraction_ensure_table(db)
    payload = _json.dumps(extraction, ensure_ascii=False, indent=2)

    db.execute(
        _sa_text("""
            INSERT INTO iad_ot_extractions (ot_id, extraction_json, raw_text, created_at, updated_at)
            VALUES (:ot_id, :extraction_json, :raw_text, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(ot_id) DO UPDATE SET
                extraction_json = excluded.extraction_json,
                raw_text = excluded.raw_text,
                updated_at = CURRENT_TIMESTAMP
        """),
        {
            "ot_id": ot_id,
            "extraction_json": payload,
            "raw_text": raw_text,
        },
    )
    db.commit()


@router.get("/iad/ot/{ot_id}/extraccion.json")
async def iad_ot_extraction_json(request: Request, ot_id: int, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse

    user = _iad_extraction_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "login_required"}, status_code=401)

    ot = _iad_extraction_get_ot(db, ot_id)
    if not ot:
        return JSONResponse({"ok": False, "error": "ot_not_found"}, status_code=404)

    saved = _iad_extraction_get_saved(db, ot_id)
    if not saved:
        return JSONResponse({"ok": True, "has_extraction": False, "ot_id": ot_id, "extraction": {}})

    return JSONResponse({"ok": True, "has_extraction": True, **saved})


@router.post("/iad/ot/{ot_id}/extraer-informacion")
async def iad_ot_extract_information_post(
    request: Request,
    ot_id: int,
    texto_bruto: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _iad_extraction_current_user(request, db)
    if not user:
        return redirect("/iad/login")

    ot = _iad_extraction_get_ot(db, ot_id)
    if not ot:
        return redirect("/iad/trabajo")

    source_text = _iad_extraction_source_text(ot, texto_bruto)
    templates = _iad_extraction_list_templates(db)
    extraction = extract_information_from_text(source_text, templates)

    _iad_extraction_save(db, ot_id, extraction, source_text)

    return redirect(f"/iad/ot/{ot_id}?extraida=1")


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


# IAD_PROFILE_TEMPLATE_USER_ROUTES_START

def template_rows_for_user(db: Session, user: User):
    rows = db.query(ReportTemplate).order_by(ReportTemplate.radiology_use, ReportTemplate.template_name).all()

    # Migración lógica: no existen plantillas sin dueño.
    owner_cache = {u.id: u.username for u in db.query(User).all()}

    visible = []
    for t in rows:
        if t.user_id == user.id or getattr(t, "is_shared", False) or user.role == "admin":
            t.owner_username = owner_cache.get(t.user_id, "")
            visible.append(t)

    return visible


def can_edit_template(user: User, template_obj: ReportTemplate) -> bool:
    return user.role == "admin" or template_obj.user_id == user.id


def can_view_template(user: User, template_obj: ReportTemplate) -> bool:
    return user.role == "admin" or template_obj.user_id == user.id or getattr(template_obj, "is_shared", False)


@router.get("/iad/perfil", response_class=HTMLResponse)
def profile_get(request: Request, db: Session = Depends(get_db)):
    try:
        require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    return render(request, "iadictador/profile.html", {"ok": "", "error": ""}, db)


@router.post("/iad/perfil", response_class=HTMLResponse)
def profile_post(
    request: Request,
    email: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    country: str = Form(""),
    timezone: str = Form(""),
    specialty: str = Form(""),
    subspecialty: str = Form(""),
    birthdate: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    user.email = email.strip() or None
    user.first_name = first_name.strip() or None
    user.last_name = last_name.strip() or None
    user.country = country.strip() or None
    user.timezone = timezone.strip() or None
    user.specialty = specialty.strip() or None
    user.subspecialty = subspecialty.strip() or None
    user.birthdate = birthdate.strip() or None

    db.commit()
    audit(db, request, "PROFILE_UPDATED", f"user_id={user.id}; username={user.username}", user.id)

    return render(request, "iadictador/profile.html", {"ok": "Perfil guardado.", "error": ""}, db)






# IAD_WORKPLACES_REPO_START
IAD_WORKPLACE_MODALITIES = ["US", "TC", "RX", "MR", "MG", "XA", "NM", "PET", "OTRO"]
IAD_WORKPLACE_STUDY_TYPES = ["urgencia", "onco", "ambulatorio"]


def _model_columns(model):
    return {c.name for c in model.__table__.columns}


def _workplace_name_column(cols):
    for candidate in ["name", "workplace_name", "nombre", "label", "title"]:
        if candidate in cols:
            return candidate
    return None


def _workplace_tariffs(w):
    raw = getattr(w, "tariffs_json", "") or ""
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}

    if not isinstance(data, dict):
        data = {}

    data.setdefault("modalities", {})
    data.setdefault("study_types", {})

    for m in IAD_WORKPLACE_MODALITIES:
        data["modalities"].setdefault(m, {"price": "", "credits": ""})

    for t in IAD_WORKPLACE_STUDY_TYPES:
        data["study_types"].setdefault(t, {"price": "", "credits": ""})

    return data


def _workplace_display_dict(w):
    cols = _model_columns(Workplace)
    name_col = _workplace_name_column(cols)

    name = ""
    if name_col:
        value = getattr(w, name_col, "")
        if value not in [None, "None"]:
            name = value

    return {
        "id": getattr(w, "id", None),
        "name": name,
        "tariffs": _workplace_tariffs(w),
    }


def _query_user_workplaces(db: Session, user: User):
    cols = _model_columns(Workplace)
    q = db.query(Workplace)

    if "user_id" in cols:
        q = q.filter(Workplace.user_id == user.id)

    try:
        return q.order_by(Workplace.id.desc()).all()
    except Exception:
        return q.all()


@router.get("/iad/lugares", response_class=HTMLResponse)
def workplaces_repo_get(request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    workplaces = [_workplace_display_dict(w) for w in _query_user_workplaces(db, user)]

    return render(
        request,
        "iadictador/workplaces_repo.html",
        {
            "workplaces_repo": workplaces,
            "modalities": IAD_WORKPLACE_MODALITIES,
            "study_types": IAD_WORKPLACE_STUDY_TYPES,
            "error": "",
            "ok": "",
        },
        db,
    )


@router.post("/iad/lugares/nuevo")
async def workplaces_create_post(request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    form_data = await request.form()
    name = clean_form_text(form_data.get("name", ""))

    if not name:
        workplaces = [_workplace_display_dict(w) for w in _query_user_workplaces(db, user)]
        return render(
            request,
            "iadictador/workplaces_repo.html",
            {
                "workplaces_repo": workplaces,
                "modalities": IAD_WORKPLACE_MODALITIES,
                "study_types": IAD_WORKPLACE_STUDY_TYPES,
                "error": "El nombre del lugar de trabajo es obligatorio.",
                "ok": "",
            },
            db,
        )

    tariffs = {
        "modalities": {},
        "study_types": {},
    }

    for m in IAD_WORKPLACE_MODALITIES:
        tariffs["modalities"][m] = {
            "price": clean_form_text(form_data.get(f"price_{m}", "")),
            "credits": clean_form_text(form_data.get(f"credits_{m}", "")),
        }

    for t in IAD_WORKPLACE_STUDY_TYPES:
        tariffs["study_types"][t] = {
            "price": clean_form_text(form_data.get(f"price_type_{t}", "")),
            "credits": clean_form_text(form_data.get(f"credits_type_{t}", "")),
        }

    cols = _model_columns(Workplace)
    data = {}

    if "user_id" in cols:
        data["user_id"] = user.id

    name_col = _workplace_name_column(cols)
    if name_col:
        data[name_col] = name

    if "tariffs_json" in cols:
        data["tariffs_json"] = json.dumps(tariffs, ensure_ascii=False)

    w = Workplace(**data)
    db.add(w)
    db.commit()
    db.refresh(w)

    audit(db, request, "WORKPLACE_CREATED", f"workplace_id={w.id}; name={name}", user.id)

    return redirect("/iad/lugares")


@router.post("/iad/lugares/{workplace_id}/eliminar")
def workplaces_delete_post(workplace_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    cols = _model_columns(Workplace)
    q = db.query(Workplace).filter(Workplace.id == workplace_id)

    if "user_id" in cols:
        q = q.filter(Workplace.user_id == user.id)

    w = q.first()
    if not w:
        return redirect("/iad/lugares")

    display = _workplace_display_dict(w)

    db.delete(w)
    db.commit()

    audit(db, request, "WORKPLACE_DELETED", f"workplace_id={workplace_id}; name={display.get('name','')}", user.id)

    return redirect("/iad/lugares")
# IAD_WORKPLACES_REPO_END

@router.get("/iad/plantillas", response_class=HTMLResponse)
def templates_repo_get(request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    return render(
        request,
        "iadictador/templates_repo.html",
        {"templates_repo": template_rows_for_user(db, user)},
        db,
    )


@router.get("/iad/plantillas/nueva", response_class=HTMLResponse)
def template_new_get(request: Request, db: Session = Depends(get_db)):
    try:
        require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    return render(
        request,
        "iadictador/template_edit.html",
        {"template_obj": None, "error": ""},
        db,
    )


@router.post("/iad/plantillas/nueva", response_class=HTMLResponse)
def template_new_post(
    request: Request,
    radiology_use: str = Form(""),
    body_region: str = Form(""),
    template_name: str = Form(""),
    title: str = Form(""),
    technique: str = Form(""),
    background: str = Form(""),
    findings: str = Form(""),
    impression: str = Form(""),
    tags: str = Form(""),
    specific_rules_json: str = Form(""),
    is_shared: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    if not template_name.strip() or not radiology_use.strip():
        return render(
            request,
            "iadictador/template_edit.html",
            {"template_obj": None, "error": "Nombre plantilla y uso/modalidad base son obligatorios."},
            db,
        )

    t = ReportTemplate(
        user_id=user.id,
        is_global=False,
        radiology_use=clean_form_text(radiology_use),
        body_region=clean_form_text(body_region) or None,
        template_name=clean_form_text(template_name),
        title=clean_form_text(report_title) or None,
        technique=clean_form_text(technique) or None,
        background=clean_form_text(background) or None,
        findings=clean_form_text(findings) or None,
        impression=clean_form_text(impression) or None,
        tags=clean_form_text(tags) or None,
        specific_rules_json=clean_form_text(specific_rules_json) or None,
    )

    if hasattr(t, "is_shared"):
        t.is_shared = bool(is_shared)

    if hasattr(t, "is_shared"):
        t.is_shared = bool(is_shared)

    if hasattr(t, "is_shared"):
        t.is_shared = bool(is_shared)

    db.add(t)
    db.commit()
    db.refresh(t)

    audit(db, request, "TEMPLATE_CREATED", f"template_id={t.id}; name={t.template_name}", user.id)

    return redirect("/iad/plantillas")




# IAD_TEMPLATE_IMPORTER_ROUTES_START

def _json_b64_encode(obj) -> str:
    raw = json.dumps(obj, ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _json_b64_decode(payload: str):
    raw = base64.urlsafe_b64decode((payload or "").encode("ascii")).decode("utf-8")
    return json.loads(raw)


def _normalize_template_name_for_match(name: str) -> str:
    value = (name or "").lower().strip()
    value = "".join(ch for ch in value if ch.isalnum() or ch.isspace())
    return " ".join(value.split())


def _template_similarity(a: str, b: str) -> float:
    aa = _normalize_template_name_for_match(a)
    bb = _normalize_template_name_for_match(b)

    if not aa or not bb:
        return 0.0

    if aa == bb:
        return 1.0

    ratio = difflib.SequenceMatcher(None, aa, bb).ratio()

    a_words = set(aa.split())
    b_words = set(bb.split())
    jaccard = len(a_words & b_words) / max(1, len(a_words | b_words))

    return max(ratio, jaccard)


def _available_templates_for_similarity(db: Session, user: User):
    rows = db.query(ReportTemplate).order_by(ReportTemplate.radiology_use, ReportTemplate.template_name).all()

    if user.role == "admin":
        return rows

    return [
        t for t in rows
        if t.user_id == user.id or t.is_global
    ]


def _similar_templates(db: Session, user: User, desired_name: str, limit: int = 3):
    NL = chr(10)
    matches = []

    for t in _available_templates_for_similarity(db, user):
        score = _template_similarity(desired_name, t.template_name)
        if score >= 0.72:
            preview_parts = []

            if t.technique:
                preview_parts.append("Técnica:" + NL + t.technique)
            if t.background:
                preview_parts.append("Antecedentes:" + NL + t.background)
            if t.findings:
                preview_parts.append("Hallazgos:" + NL + t.findings)
            if t.impression:
                preview_parts.append("Impresión diagnóstica:" + NL + t.impression)

            preview = (NL + NL).join(preview_parts).strip()

            if len(preview) > 900:
                preview = preview[:900].rstrip() + NL + "..."

            matches.append({
                "id": t.id,
                "template_name": t.template_name,
                "radiology_use": t.radiology_use,
        "body_region": getattr(t, "body_region", "") or "",
                "title": t.title,
                "preview": preview or "(sin cuerpo de plantilla)",
                "score": score,
            })

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches[:limit]


def _template_name_exists_in_user_scope(db: Session, user: User, name: str, is_global: bool = False) -> bool:
    norm = _normalize_template_name_for_match(name)
    rows = db.query(ReportTemplate).all()

    for t in rows:
        same_scope = False

        if is_global:
            same_scope = bool(t.is_global)
        elif user.role == "admin":
            same_scope = bool(t.user_id == user.id or t.is_global)
        else:
            same_scope = bool(t.user_id == user.id or t.is_global)

        if same_scope and _normalize_template_name_for_match(t.template_name) == norm:
            return True

    return False


def _unique_template_name(db: Session, user: User, desired_name: str, is_global: bool = False) -> str:
    base = (desired_name or "Plantilla importada").strip()

    if not _template_name_exists_in_user_scope(db, user, base, is_global=False):
        return base

    n = 2
    while True:
        candidate = f"{base} ({n})"
        if not _template_name_exists_in_user_scope(db, user, candidate, is_global=False):
            return candidate
        n += 1


def _render_importer_empty(
    request: Request,
    db: Session,
    ok: str = "",
    error: str = "",
    warnings: list | None = None,
):
    return render(
        request,
        "iadictador/templates_importer.html",
        {
            "current_candidate": None,
            "current_index": 0,
            "total_candidates": 0,
            "candidates_payload": "",
            "raw_text": "",
            "engine": "",
            "duplicate_matches": [],
            "submitted_fields": {},
            "warnings": warnings or [],
            "import_report": [],
            "error": error,
            "ok": ok,
        },
        db,
    )


def _render_importer_current(
    request: Request,
    db: Session,
    candidates: list,
    current_index: int,
    engine: str,
    raw_text: str = "",
    ok: str = "",
    error: str = "",
    warnings: list | None = None,
    duplicate_matches: list | None = None,
    submitted_fields: dict | None = None,
):
    total = len(candidates)

    imported_report = []
    if isinstance(candidates, dict):
        imported_report = candidates.get("imported_report", [])
        candidates = candidates.get("items", [])

    total = len(candidates)

    if current_index >= total:
        return render(
            request,
            "iadictador/templates_importer.html",
            {
                "current_candidate": None,
                "current_index": 0,
                "total_candidates": 0,
                "candidates_payload": "",
                "raw_text": raw_text,
                "engine": engine,
                "duplicate_matches": [],
                "submitted_fields": {},
                "warnings": warnings or [],
                "import_report": imported_report,
                "error": error,
                "ok": ok or "Importación terminada.",
            },
            db,
        )

    candidate = candidates[current_index]

    if submitted_fields:
        candidate = dict(candidate)
        candidate["template_name"] = submitted_fields.get("template_name", candidate.get("template_name", ""))
        candidate["modality"] = submitted_fields.get("radiology_use", candidate.get("modality", ""))
        candidate["body_region"] = submitted_fields.get("body_region", candidate.get("body_region", ""))
        candidate["title"] = submitted_fields.get("title", candidate.get("title", ""))
        candidate["technique"] = submitted_fields.get("technique", candidate.get("technique", ""))
        candidate["background"] = submitted_fields.get("background", candidate.get("background", ""))
        candidate["findings"] = submitted_fields.get("findings", candidate.get("findings", ""))
        candidate["impression"] = submitted_fields.get("impression", candidate.get("impression", ""))
        candidate["specific_rules_json"] = submitted_fields.get("specific_rules_json", candidate.get("specific_rules_json", ""))

    payload = {
        "candidates": candidates,
        "engine": engine,
        "raw_text": raw_text,
        "imported_report": imported_report if "imported_report" in locals() else [],
    }

    return render(
        request,
        "iadictador/templates_importer.html",
        {
            "current_candidate": candidate,
            "current_index": current_index,
            "total_candidates": total,
            "candidates_payload": _json_b64_encode(payload),
            "raw_text": raw_text,
            "engine": engine,
            "duplicate_matches": duplicate_matches or [],
            "submitted_fields": submitted_fields or {},
            "warnings": warnings or [],
            "import_report": [],
            "error": error,
            "ok": ok,
        },
        db,
    )


async def _read_template_import_files(files) -> str:
    NL = chr(10)
    chunks = []

    for upload in files or []:
        if not upload or not getattr(upload, "filename", ""):
            continue

        filename = upload.filename or "archivo"
        data = await upload.read()

        if not data:
            continue

        text = ""
        for enc in ["utf-8", "latin-1"]:
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                pass

        if text.strip():
            chunk = (NL + NL + "---" + NL + NL + "# Archivo: " + filename + NL + NL + text)
            chunks.append(chunk)

    return (NL.join(chunks)).strip()






@router.post("/iad/plantillas/eliminar_lote")
async def templates_delete_batch_post(request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    form_data = await request.form()
    selected_ids_raw = clean_form_text(form_data.get("selected_ids", ""))

    ids = []
    for part in selected_ids_raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))

    if not ids:
        return redirect("/iad/plantillas")

    rows = db.query(ReportTemplate).filter(ReportTemplate.id.in_(ids)).all()

    deleted = []
    denied = []

    for t in rows:
        if can_edit_template(user, t):
            deleted.append((t.id, t.template_name or f"plantilla #{t.id}"))
            db.delete(t)
        else:
            denied.append(t.id)

    db.commit()

    for template_id, name in deleted:
        audit(db, request, "TEMPLATE_DELETED", f"template_id={template_id}; name={name}", user.id)

    if denied:
        audit(db, request, "TEMPLATE_DELETE_DENIED", f"ids={denied}", user.id)

    return redirect("/iad/plantillas")

@router.post("/iad/plantillas/exportar")
async def templates_export_post(request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    form_data = await request.form()

    selected_ids_raw = str(form_data.get("selected_ids", "") or "").strip()
    file_mode = str(form_data.get("file_mode", "single") or "single")
    export_format = str(form_data.get("export_format", "txt") or "txt")
    fields_mode = str(form_data.get("fields_mode", "nonempty") or "nonempty")
    labels_mode = str(form_data.get("labels_mode", "with_labels") or "with_labels")

    ids = []
    for part in selected_ids_raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))

    query = db.query(ReportTemplate)
    if ids:
        query = query.filter(ReportTemplate.id.in_(ids))

    rows = query.order_by(ReportTemplate.radiology_use, ReportTemplate.template_name).all()

    rows = [
        t for t in rows
        if user.role == "admin" or t.user_id == user.id or getattr(t, "is_shared", False)
    ]

    def clean_value(value):
        if value is None:
            return ""
        if isinstance(value, bool):
            return value
        s = str(value)
        if s.strip().lower() == "none":
            return ""
        return s

    def safe_name(name: str) -> str:
        value = "".join(ch if ch.isalnum() or ch in [" ", "-", "_"] else "_" for ch in (name or "plantilla"))
        value = "_".join(value.strip().split())
        return value[:90] or "plantilla"

    def template_dict(t: ReportTemplate) -> dict:
        data = {
            "nombre_plantilla": clean_value(t.template_name),
            "modalidad": clean_value(t.radiology_use),
            "region_del_cuerpo": clean_value(getattr(t, "body_region", "")),
            "titulo_informe": clean_value(t.title),
            "tecnica": clean_value(t.technique),
            "antecedentes": clean_value(t.background),
            "hallazgos": clean_value(t.findings),
            "impresion_diagnostica": clean_value(t.impression),
            "reglas_especificas_notas_uso": clean_value(t.specific_rules_json),
            "tags": clean_value(t.tags),
            "compartida": bool(getattr(t, "is_shared", False)),
        }

        if fields_mode == "nonempty":
            data = {k: v for k, v in data.items() if v not in ["", None, False]}

        return data

    def template_txt(t: ReportTemplate) -> str:
        data = template_dict(t)
        NL = chr(10)
        parts = []

        if labels_mode == "content_only":
            for value in data.values():
                if isinstance(value, bool):
                    continue
                if value not in ["", None]:
                    parts.append(str(value))
            return (NL + NL).join(parts).strip() + NL

        label_map = {
            "nombre_plantilla": "Nombre plantilla",
            "modalidad": "Modalidad",
            "region_del_cuerpo": "Región del cuerpo",
            "titulo_informe": "Título informe",
            "tecnica": "Técnica",
            "antecedentes": "Antecedentes",
            "hallazgos": "Hallazgos",
            "impresion_diagnostica": "Impresión diagnóstica",
            "reglas_especificas_notas_uso": "Reglas específicas / notas de uso",
            "tags": "Tags",
            "compartida": "Compartida",
        }

        for key, value in data.items():
            if isinstance(value, bool):
                value = "sí" if value else "no"
            elif value in ["", None]:
                value = "(vacío)"
            parts.append(label_map.get(key, key) + ":" + NL + str(value))

        return (NL + NL).join(parts).strip() + NL

    if export_format == "json":
        payload = [template_dict(t) for t in rows]
        content_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        ext = "json"
        media_type = "application/json"
    else:
        sep = chr(10) + chr(10) + "---" + chr(10) + chr(10)
        content_bytes = sep.join(template_txt(t).strip() for t in rows).encode("utf-8")
        ext = "txt"
        media_type = "text/plain; charset=utf-8"

    if file_mode == "separate":
        bio = io.BytesIO()
        used_names = set()

        with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for t in rows:
                base = safe_name(t.template_name)
                filename = base + "." + ext
                n = 2
                while filename in used_names:
                    filename = f"{base}_{n}.{ext}"
                    n += 1
                used_names.add(filename)

                if export_format == "json":
                    data = json.dumps(template_dict(t), ensure_ascii=False, indent=2).encode("utf-8")
                else:
                    data = template_txt(t).encode("utf-8")

                zf.writestr(filename, data)

        content = bio.getvalue()
        headers = {"Content-Disposition": "attachment; filename=plantillas_exportadas.zip"}
        return StarletteResponse(content=content, media_type="application/zip", headers=headers)

    single_name = "plantillas_exportadas"
    if len(rows) == 1:
        one = rows[0]
        base_name = safe_name(f"{clean_value(getattr(one, 'radiology_use', ''))} - {clean_value(getattr(one, 'template_name', ''))}".strip(" -"))
        if base_name:
            single_name = base_name
    headers = {"Content-Disposition": f"attachment; filename={single_name}.{ext}"}
    return StarletteResponse(content=content_bytes, media_type=media_type, headers=headers)


@router.get("/iad/plantillas/importador", response_class=HTMLResponse)
def template_importer_get(request: Request, db: Session = Depends(get_db)):
    try:
        require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    return _render_importer_empty(request, db)


@router.post("/iad/plantillas/importador/analizar", response_class=HTMLResponse)
async def template_importer_analyze(
    request: Request,
    raw_text: str = Form(""),
    use_ai: str = Form("1"),
    template_files: list[UploadFile] = File([]),
    db: Session = Depends(get_db),
):
    try:
        require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    from app.services.ai.tasks.template_importer import import_templates_intelligent

    NL = chr(10)
    file_text = await _read_template_import_files(template_files)
    combined = ((raw_text or "") + NL + NL + (file_text or "")).strip()

    if not combined:
        return _render_importer_empty(
            request,
            db,
            error="Debe pegar texto o subir al menos un archivo con texto.",
        )

    result = import_templates_intelligent(combined, use_ai=(use_ai == "1"))
    candidates = result.get("templates", [])

    if not candidates:
        return _render_importer_empty(
            request,
            db,
            error="No se detectaron plantillas.",
            warnings=result.get("global_warnings", []),
        )

    return _render_importer_current(
        request=request,
        db=db,
        candidates=candidates,
        current_index=0,
        engine=result.get("engine", ""),
        raw_text=combined,
        ok=f"Se detectaron {len(candidates)} posible(s) plantilla(s).",
        warnings=result.get("global_warnings", []),
    )


@router.post("/iad/plantillas/importador/guardar_actual", response_class=HTMLResponse)
async def template_importer_save_current(request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    form_data = await request.form()

    try:
        payload = _json_b64_decode(str(form_data.get("candidates_payload", "")))
        candidates = payload.get("candidates", [])
        imported_report = payload.get("imported_report", [])
        engine = payload.get("engine", "")
        raw_text = payload.get("raw_text", "")
        current_index = int(form_data.get("current_index", "0"))
    except Exception:
        return PlainTextResponse("Payload de importación inválido.", status_code=400)

    submitted = {
        "template_name": clean_form_text(form_data.get("template_name", "")),
        "radiology_use": clean_form_text(form_data.get("radiology_use", "")),
        "body_region": clean_form_text(form_data.get("body_region", "")),
        "title": clean_form_text(form_data.get("title", "")),
        "technique": clean_form_text(form_data.get("technique", "")),
        "background": clean_form_text(form_data.get("background", "")),
        "findings": clean_form_text(form_data.get("findings", "")),
        "impression": clean_form_text(form_data.get("impression", "")),
        "specific_rules_json": clean_form_text(form_data.get("specific_rules_json", "")),
        "tags": clean_form_text(form_data.get("tags", "")),
    }

    if current_index < 0 or current_index >= len(candidates):
        return redirect("/iad/plantillas/importador")

    if not submitted["template_name"] or not submitted["radiology_use"]:
        return _render_importer_current(
            request=request,
            db=db,
            candidates=candidates,
            current_index=current_index,
            engine=engine,
            raw_text=raw_text,
            error="Nombre plantilla y modalidad son obligatorios.",
            submitted_fields=submitted,
        )

    is_shared = bool(form_data.get("is_shared"))
    confirm_similar = bool(form_data.get("confirm_similar"))

    similar = _similar_templates(db, user, submitted["template_name"])

    if similar and not confirm_similar:
        return _render_importer_current(
            request=request,
            db=db,
            candidates=candidates,
            current_index=current_index,
            engine=engine,
            raw_text=raw_text,
            duplicate_matches=similar,
            submitted_fields=submitted,
            error="Se detectó una plantilla con nombre parecido.",
        )

    final_name = _unique_template_name(
        db=db,
        user=user,
        desired_name=submitted["template_name"],
        is_global=False,
    )

    t = ReportTemplate(
        user_id=user.id,
        is_global=False,
        radiology_use=submitted["radiology_use"],
        body_region=submitted.get("body_region") or None,
        template_name=final_name,
        title=submitted["title"] or None,
        technique=submitted["technique"] or None,
        background=submitted["background"] or None,
        findings=submitted["findings"] or None,
        impression=submitted["impression"] or None,
        tags=submitted["tags"] or None,
        specific_rules_json=submitted["specific_rules_json"] or None,
    )

    if hasattr(t, "import_source"):
        t.import_source = "ai"
    if hasattr(t, "imported_at") and getattr(t, "imported_at", None) is None:
        pass

    db.add(t)
    db.commit()
    db.refresh(t)

    audit(
        db,
        request,
        "TEMPLATE_IMPORTED_ONE",
        f"template_id={t.id}; name={t.template_name}; source_index={current_index + 1}",
        user.id,
    )

    imported_report.append({
        "template_name": t.template_name,
        "radiology_use": t.radiology_use,
        "body_region": getattr(t, "body_region", "") or "",
        "title": t.title or "",
        "is_shared": bool(getattr(t, "is_shared", False)),
    })

    return _render_importer_current(
        request=request,
        db=db,
        candidates={
            "items": candidates,
            "imported_report": imported_report,
        },
        current_index=current_index + 1,
        engine=engine,
        raw_text=raw_text,
        ok=f"Plantilla guardada: {t.template_name}",
    )


@router.post("/iad/plantillas/importador/saltar_actual", response_class=HTMLResponse)
async def template_importer_skip_current(request: Request, db: Session = Depends(get_db)):
    try:
        require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    form_data = await request.form()

    try:
        payload = _json_b64_decode(str(form_data.get("candidates_payload", "")))
        candidates = payload.get("candidates", [])
        imported_report = payload.get("imported_report", [])
        engine = payload.get("engine", "")
        raw_text = payload.get("raw_text", "")
        current_index = int(form_data.get("current_index", "0"))
    except Exception:
        return PlainTextResponse("Payload de importación inválido.", status_code=400)

    return _render_importer_current(
        request=request,
        db=db,
        candidates={
            "items": candidates,
            "imported_report": imported_report,
        },
        current_index=current_index + 1,
        engine=engine,
        raw_text=raw_text,
        ok="Plantilla descartada. Pasando a la siguiente.",
    )

# IAD_TEMPLATE_IMPORTER_ROUTES_END






@router.post("/iad/plantillas/{template_id}/eliminar")
def template_delete_post(template_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    t = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
    if not t:
        return PlainTextResponse("Plantilla no encontrada.", status_code=404)

    if not can_edit_template(user, t):
        return PlainTextResponse("No autorizado para eliminar esta plantilla.", status_code=403)

    name = t.template_name or f"plantilla #{template_id}"

    db.delete(t)
    db.commit()

    audit(db, request, "TEMPLATE_DELETED", f"template_id={template_id}; name={name}", user.id)

    return redirect("/iad/plantillas")

@router.get("/iad/plantillas/{template_id}", response_class=HTMLResponse)
def template_edit_get(template_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    t = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
    if not t:
        return PlainTextResponse("Plantilla no encontrada.", status_code=404)

    if not can_view_template(user, t):
        return PlainTextResponse("Sin permiso.", status_code=403)

    return render(
        request,
        "iadictador/template_edit.html",
        {"template_obj": t, "error": ""},
        db,
    )


@router.post("/iad/plantillas/{template_id}/guardar", response_class=HTMLResponse)
def template_edit_post(
    template_id: int,
    request: Request,
    radiology_use: str = Form(""),
    body_region: str = Form(""),
    template_name: str = Form(""),
    title: str = Form(""),
    technique: str = Form(""),
    background: str = Form(""),
    findings: str = Form(""),
    impression: str = Form(""),
    tags: str = Form(""),
    specific_rules_json: str = Form(""),
    is_shared: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    t = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
    if not t:
        return PlainTextResponse("Plantilla no encontrada.", status_code=404)

    if not can_edit_template(user, t):
        return PlainTextResponse("Sin permiso para editar esta plantilla.", status_code=403)

    if not template_name.strip() or not radiology_use.strip():
        return render(
            request,
            "iadictador/template_edit.html",
            {"template_obj": t, "error": "Nombre plantilla y uso/modalidad base son obligatorios."},
            db,
        )

    t.radiology_use = radiology_use.strip()
    t.body_region = body_region.strip() or None
    t.template_name = template_name.strip()
    t.title = clean_form_text(report_title) or None
    t.technique = clean_form_text(technique) or None
    t.background = clean_form_text(background) or None
    t.findings = clean_form_text(findings) or None
    t.impression = clean_form_text(impression) or None
    t.tags = clean_form_text(tags) or None
    t.specific_rules_json = clean_form_text(specific_rules_json) or None
    t.is_global = False
    t.is_shared = bool(is_shared)

    db.commit()

    audit(db, request, "TEMPLATE_UPDATED", f"template_id={t.id}; name={t.template_name}", user.id)

    return redirect("/iad/plantillas")


@router.get("/iad/admin/usuarios/nuevo", response_class=HTMLResponse)
def admin_user_new_get(request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    if user.role != "admin":
        return PlainTextResponse("Solo admin.", status_code=403)

    return render(request, "iadictador/admin_user_new.html", {}, db)


@router.get("/iad/admin/usuarios/{user_id}", response_class=HTMLResponse)
def admin_user_detail_get(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    if user.role != "admin":
        return PlainTextResponse("Solo admin.", status_code=403)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return PlainTextResponse("Usuario no encontrado.", status_code=404)

    return render(
        request,
        "iadictador/admin_user_detail.html",
        {"target_user": target, "error": ""},
        db,
    )


@router.post("/iad/admin/usuarios/{user_id}/guardar", response_class=HTMLResponse)
def admin_user_detail_post(
    user_id: int,
    request: Request,
    username: str = Form(""),
    email: str = Form(""),
    role: str = Form("user"),
    first_name: str = Form(""),
    last_name: str = Form(""),
    country: str = Form(""),
    timezone: str = Form(""),
    specialty: str = Form(""),
    subspecialty: str = Form(""),
    birthdate: str = Form(""),
    is_active: Optional[str] = Form(None),
    must_change_password: Optional[str] = Form(None),
    billing_visible: Optional[str] = Form(None),
    billing_enabled: Optional[str] = Form(None),
    price_per_transcription: str = Form(""),
    new_password: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        admin = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    if admin.role != "admin":
        return PlainTextResponse("Solo admin.", status_code=403)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return PlainTextResponse("Usuario no encontrado.", status_code=404)

    if not username.strip():
        return render(
            request,
            "iadictador/admin_user_detail.html",
            {"target_user": target, "error": "El usuario no puede quedar vacío."},
            db,
        )

    existing = db.query(User).filter(User.username == username.strip(), User.id != target.id).first()
    if existing:
        return render(
            request,
            "iadictador/admin_user_detail.html",
            {"target_user": target, "error": "Ya existe otro usuario con ese nombre."},
            db,
        )

    target.username = username.strip()
    target.email = email.strip() or None
    target.role = role if role in ("user", "admin") else "user"
    target.first_name = first_name.strip() or None
    target.last_name = last_name.strip() or None
    target.country = country.strip() or None
    target.timezone = timezone.strip() or None
    target.specialty = specialty.strip() or None
    target.subspecialty = subspecialty.strip() or None
    target.birthdate = birthdate.strip() or None

    target.is_active = bool(is_active)
    if target.id == admin.id:
        target.is_active = True

    target.must_change_password = bool(must_change_password)
    target.billing_visible = bool(billing_visible)
    target.billing_enabled = bool(billing_enabled)

    if price_per_transcription.strip():
        try:
            target.price_per_transcription = float(price_per_transcription.replace(",", "."))
        except ValueError:
            return render(
                request,
                "iadictador/admin_user_detail.html",
                {"target_user": target, "error": "Valor de cobro inválido."},
                db,
            )
    else:
        target.price_per_transcription = None

    if new_password.strip():
        ok, msg = password_is_valid(new_password.strip())
        if not ok:
            return render(
                request,
                "iadictador/admin_user_detail.html",
                {"target_user": target, "error": msg},
                db,
            )
        target.password_hash = hash_password(new_password.strip())
        target.must_change_password = True

    db.commit()

    audit(db, request, "USER_UPDATED", f"user_id={target.id}; username={target.username}", admin.id)

    return redirect(f"/iad/admin/usuarios/{target.id}")

# IAD_PROFILE_TEMPLATE_USER_ROUTES_END
