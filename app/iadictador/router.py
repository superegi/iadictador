from app.services.ai.tasks.audio_transcriber import transcribe_audio_upload, AudioTranscriptionError
from fastapi.responses import JSONResponse
from fastapi import UploadFile, File, Depends, Request
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

# IAD_FIX_EXTRACT_INFORMATION_COMPAT_V1
def extract_information_from_text(source_text, templates=None):
    """
    Compatibilidad para endpoint legacy /iad/ot/{id}/extraer-informacion.
    Evita NameError si el flujo viejo llama extract_information_from_text().
    """
    try:
        from app.services.ai.tasks.info_extractor_v2 import extract_information_from_text_v2
        return extract_information_from_text_v2(source_text)
    except Exception:
        try:
            from app.services.ai.tasks.info_extractor import extract_information_from_text as _old_extract
            return _old_extract(source_text)
        except Exception as exc:
            return {
                "ok": False,
                "error": f"No se pudo ejecutar extractor legacy: {exc}",
                "raw_text": source_text,
                "plantilla_sugerida": None,
                "informacion_secundaria": {},
                "hallazgos_radiologicos": source_text or "",
                "advertencias": ["Extractor legacy no disponible; se devolvió texto fuente como hallazgo bruto."],
                "necesita_revision": True,
                "metodo": "compat_fallback",
            }

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
def iad_work_page_unified(request: Request, db = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    if getattr(user, "must_change_password", False):
        return redirect("/iad/cambiar-clave")

    return render(
        request,
        "iadictador/work_v2.html",
        {
            "page": "trabajo",
        },
        db,
    )

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

    # IAD_FIX_CREATE_OT_REPORT_TITLE_VALUE_V1
    # Compatibilidad: algunos parches dejaron create_ot usando report_title_value
    # sin definirlo. Lo resolvemos desde campos posibles del formulario.
    try:
        report_title_value
    except NameError:
        report_title_value = (
            locals().get("report_title")
            or locals().get("title")
            or locals().get("titulo")
            or locals().get("template_title")
            or locals().get("plantilla_nombre")
            or locals().get("template_name")
            or locals().get("report_name")
            or ""
        )
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
        report_title=clean_form_text(locals().get("report_title_value", locals().get("title", ""))) or None,
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
        title=clean_form_text(locals().get("report_title_value", locals().get("title", ""))) or None,
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
    report_title: str = Form(""),
):

    # IAD_FIX_REPORT_TITLE_TEMPLATE_EDIT_POST_V1
    # Compatibilidad: versiones previas usaban report_title en el cuerpo
    # pero no siempre lo declaraban como campo Form.
    try:
        report_title_value = report_title
    except NameError:
        report_title_value = (
            locals().get("title")
            or locals().get("titulo")
            or locals().get("nombre")
            or locals().get("template_title")
            or locals().get("report_name")
            or ""
        )
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
    t.title = clean_form_text(report_title_value) or None
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



# IAD_FLUJO_2RIA_ENDPOINT_V1
try:
    from fastapi import Form as _IAD2_Form
    from fastapi import Request as _IAD2_Request
    from fastapi.responses import JSONResponse as _IAD2_JSONResponse
except Exception:
    _IAD2_Form = None
    _IAD2_Request = None
    _IAD2_JSONResponse = None


@router.post("/iad/extraer-informacion-2ria.json")
async def iad_extraer_informacion_2ria_json(
    request: _IAD2_Request,
    texto_bruto: str = _IAD2_Form(""),
):
    """
    Extrae plantilla sugerida, información secundaria y hallazgos.
    No genera informe final.
    """
    from app.services.ai.tasks.info_extractor import (
        collect_template_candidates,
        extract_information_from_text,
    )

    templates = collect_template_candidates()
    extraction = extract_information_from_text(texto_bruto or "", templates)

    return _IAD2_JSONResponse(
        {
            "ok": True,
            "extraction": extraction,
        }
    )



# IAD_FLUJO_2RIA_ENDPOINT_V2
from fastapi import Depends as _IAD_V2_Depends
from fastapi import Form as _IAD_V2_Form
from fastapi import Request as _IAD_V2_Request
from fastapi.responses import JSONResponse as _IAD_V2_JSONResponse

try:
    from app.iadictador.db import get_db as _IAD_V2_get_db
except Exception:
    _IAD_V2_get_db = globals().get("get_db")


@router.post("/iad/extraer-informacion-2ria-v2.json")
async def iad_extraer_informacion_2ria_v2_json(
    request: _IAD_V2_Request,
    texto_bruto: str = _IAD_V2_Form(""),
    db = _IAD_V2_Depends(_IAD_V2_get_db),
):
    from app.services.ai.tasks.info_extractor_v2 import extract_information_from_text_v2

    extraction = extract_information_from_text_v2(texto_bruto or "", db=db)

    return _IAD_V2_JSONResponse(
        {
            "ok": True,
            "extraction": extraction,
        }
    )



# IAD_RADIOLOGY_FLOW_ENDPOINTS_V1
from fastapi import Depends as _IAD_RAD_Depends
from fastapi import Form as _IAD_RAD_Form
from fastapi import Request as _IAD_RAD_Request
from fastapi.responses import JSONResponse as _IAD_RAD_JSONResponse

try:
    from app.iadictador.db import get_db as _IAD_RAD_get_db
except Exception:
    _IAD_RAD_get_db = globals().get("get_db")


@router.post("/iad/analizar-radiologia.json")
async def iad_analizar_radiologia_json(
    request: _IAD_RAD_Request,
    texto_bruto: str = _IAD_RAD_Form(""),
    db = _IAD_RAD_Depends(_IAD_RAD_get_db),
):
    from app.services.ai.tasks.radiology_flow import analyze_radiology

    result = analyze_radiology(texto_bruto or "", db=db)
    return _IAD_RAD_JSONResponse(result)


@router.post("/iad/generar-informe-radiologico.json")
async def iad_generar_informe_radiologico_json(
    request: _IAD_RAD_Request,
    hallazgos: str = _IAD_RAD_Form(""),
    plantilla_nombre: str = _IAD_RAD_Form(""),
    plantilla_id: str = _IAD_RAD_Form(""),
    db = _IAD_RAD_Depends(_IAD_RAD_get_db),
):
    from app.services.ai.tasks.radiology_flow import generate_report_from_template

    result = generate_report_from_template(
        hallazgos=hallazgos or "",
        template_name=plantilla_nombre or "",
        template_id=plantilla_id or "",
        db=db,
    )
    return _IAD_RAD_JSONResponse(result)



# IAD_TRAINING_SAMPLES_ENDPOINTS_V1
from fastapi import Depends as _IAD_TS_Depends
from fastapi import Form as _IAD_TS_Form
from fastapi import Request as _IAD_TS_Request
from fastapi.responses import JSONResponse as _IAD_TS_JSONResponse

try:
    from app.iadictador.db import get_db as _IAD_TS_get_db
except Exception:
    _IAD_TS_get_db = globals().get("get_db")


def _iad_ts_ensure_table(db):
    from sqlalchemy import text as _sa_text

    db.execute(_sa_text("""
        CREATE TABLE IF NOT EXISTS iad_training_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ot_id INTEGER,
            texto_dictado TEXT,
            plantilla_nombre TEXT,
            plantilla_id TEXT,
            hallazgos_detectados TEXT,
            resultado_primario TEXT,
            resultado_revisado TEXT,
            modelo TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))

    db.execute(_sa_text("""
        CREATE INDEX IF NOT EXISTS idx_iad_training_samples_ot_id
        ON iad_training_samples(ot_id)
    """))

    db.commit()


@router.post("/iad/guardar-revision-modelo.json")
async def iad_guardar_revision_modelo_json(
    request: _IAD_TS_Request,
    ot_id: str = _IAD_TS_Form(""),
    texto_dictado: str = _IAD_TS_Form(""),
    plantilla_nombre: str = _IAD_TS_Form(""),
    plantilla_id: str = _IAD_TS_Form(""),
    hallazgos_detectados: str = _IAD_TS_Form(""),
    resultado_primario: str = _IAD_TS_Form(""),
    resultado_revisado: str = _IAD_TS_Form(""),
    modelo: str = _IAD_TS_Form(""),
    metadata_json: str = _IAD_TS_Form("{}"),
    db = _IAD_TS_Depends(_IAD_TS_get_db),
):
    from sqlalchemy import text as _sa_text
    import json as _json

    _iad_ts_ensure_table(db)

    try:
        ot_id_int = int(ot_id) if str(ot_id).strip() else None
    except Exception:
        ot_id_int = None

    try:
        parsed_meta = _json.loads(metadata_json or "{}")
        metadata_clean = _json.dumps(parsed_meta, ensure_ascii=False, indent=2)
    except Exception:
        metadata_clean = "{}"

    # Si hay OT, actualiza último registro de esa OT; si no, crea registro nuevo.
    existing_id = None
    if ot_id_int is not None:
        row = db.execute(
            _sa_text("""
                SELECT id
                FROM iad_training_samples
                WHERE ot_id = :ot_id
                ORDER BY id DESC
                LIMIT 1
            """),
            {"ot_id": ot_id_int},
        ).fetchone()
        if row:
            existing_id = row[0]

    if existing_id:
        db.execute(
            _sa_text("""
                UPDATE iad_training_samples
                SET
                    texto_dictado = :texto_dictado,
                    plantilla_nombre = :plantilla_nombre,
                    plantilla_id = :plantilla_id,
                    hallazgos_detectados = :hallazgos_detectados,
                    resultado_primario = :resultado_primario,
                    resultado_revisado = :resultado_revisado,
                    modelo = :modelo,
                    metadata_json = :metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {
                "id": existing_id,
                "texto_dictado": texto_dictado,
                "plantilla_nombre": plantilla_nombre,
                "plantilla_id": plantilla_id,
                "hallazgos_detectados": hallazgos_detectados,
                "resultado_primario": resultado_primario,
                "resultado_revisado": resultado_revisado,
                "modelo": modelo,
                "metadata_json": metadata_clean,
            },
        )
        sample_id = existing_id
    else:
        result = db.execute(
            _sa_text("""
                INSERT INTO iad_training_samples (
                    ot_id,
                    texto_dictado,
                    plantilla_nombre,
                    plantilla_id,
                    hallazgos_detectados,
                    resultado_primario,
                    resultado_revisado,
                    modelo,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (
                    :ot_id,
                    :texto_dictado,
                    :plantilla_nombre,
                    :plantilla_id,
                    :hallazgos_detectados,
                    :resultado_primario,
                    :resultado_revisado,
                    :modelo,
                    :metadata_json,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
            """),
            {
                "ot_id": ot_id_int,
                "texto_dictado": texto_dictado,
                "plantilla_nombre": plantilla_nombre,
                "plantilla_id": plantilla_id,
                "hallazgos_detectados": hallazgos_detectados,
                "resultado_primario": resultado_primario,
                "resultado_revisado": resultado_revisado,
                "modelo": modelo,
                "metadata_json": metadata_clean,
            },
        )
        sample_id = result.lastrowid

    db.commit()

    return _IAD_TS_JSONResponse({
        "ok": True,
        "sample_id": sample_id,
        "ot_id": ot_id_int,
    })


@router.get("/iad/exportar-revisiones-modelo.json")
async def iad_exportar_revisiones_modelo_json(
    request: _IAD_TS_Request,
    db = _IAD_TS_Depends(_IAD_TS_get_db),
):
    from sqlalchemy import text as _sa_text
    import json as _json

    _iad_ts_ensure_table(db)

    rows = db.execute(_sa_text("""
        SELECT
            id,
            ot_id,
            texto_dictado,
            plantilla_nombre,
            plantilla_id,
            hallazgos_detectados,
            resultado_primario,
            resultado_revisado,
            modelo,
            metadata_json,
            created_at,
            updated_at
        FROM iad_training_samples
        ORDER BY id ASC
    """)).fetchall()

    items = []
    for r in rows:
        try:
            meta = _json.loads(r[9] or "{}")
        except Exception:
            meta = {}

        items.append({
            "id": r[0],
            "ot_id": r[1],
            "texto_dictado": r[2] or "",
            "plantilla_nombre": r[3] or "",
            "plantilla_id": r[4] or "",
            "hallazgos_detectados": r[5] or "",
            "resultado_primario": r[6] or "",
            "resultado_revisado": r[7] or "",
            "modelo": r[8] or "",
            "metadata": meta,
            "created_at": r[10],
            "updated_at": r[11],
        })

    return _IAD_TS_JSONResponse({
        "ok": True,
        "count": len(items),
        "items": items,
    })



# IAD_ADMIN_TRAINING_PAGE_ENDPOINTS_V1
from fastapi import Depends as _IAD_AT_Depends
from fastapi import Form as _IAD_AT_Form
from fastapi import Request as _IAD_AT_Request
from fastapi.responses import JSONResponse as _IAD_AT_JSONResponse
from fastapi.responses import RedirectResponse as _IAD_AT_RedirectResponse
from fastapi.responses import Response as _IAD_AT_Response

try:
    from app.iadictador.db import get_db as _IAD_AT_get_db
except Exception:
    _IAD_AT_get_db = globals().get("get_db")


def _iad_at_templates():
    obj = globals().get("templates")
    if obj is not None:
        return obj

    from fastapi.templating import Jinja2Templates
    return Jinja2Templates(directory="app/templates")


def _iad_at_ensure_table(db):
    from sqlalchemy import text as _sa_text

    db.execute(_sa_text("""
        CREATE TABLE IF NOT EXISTS iad_training_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ot_id INTEGER,
            texto_dictado TEXT,
            plantilla_nombre TEXT,
            plantilla_id TEXT,
            hallazgos_detectados TEXT,
            resultado_primario TEXT,
            resultado_revisado TEXT,
            modelo TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))

    db.execute(_sa_text("""
        CREATE INDEX IF NOT EXISTS idx_iad_training_samples_ot_id
        ON iad_training_samples(ot_id)
    """))

    db.commit()


def _iad_at_session_user(request):
    try:
        return request.session or {}
    except Exception:
        return {}


def _iad_at_is_logged(request):
    session = _iad_at_session_user(request)
    if not session:
        return False

    keys = [
        "user_id",
        "iad_user_id",
        "uid",
        "username",
        "user",
        "email",
        "role",
        "is_admin",
    ]

    return any(k in session and session.get(k) for k in keys)


def _iad_at_is_admin(request, db=None):
    session = _iad_at_session_user(request)

    # Admin explícito en sesión.
    for key in ("is_admin", "admin"):
        val = session.get(key)
        if val is True or str(val).lower() in {"1", "true", "yes", "admin"}:
            return True

    role = str(session.get("role") or session.get("rol") or "").lower()
    if role in {"admin", "administrator", "superadmin"}:
        return True

    username = str(session.get("username") or session.get("user") or "").lower()
    if username in {"admin", "egidio"}:
        return True

    # Intento DB tolerante si hay user_id.
    user_id = session.get("user_id") or session.get("iad_user_id") or session.get("uid")
    if db is not None and user_id:
        try:
            from sqlalchemy import text as _sa_text

            tables = db.execute(
                _sa_text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            ).fetchall()

            for row in tables:
                table = row[0]
                if not any(x in table.lower() for x in ("user", "usuario")):
                    continue

                cols = db.execute(_sa_text(f'PRAGMA table_info("{table}")')).fetchall()
                colnames = [c[1] for c in cols]

                if "id" not in colnames:
                    continue

                possible_cols = [
                    c for c in colnames
                    if c.lower() in {"role", "rol", "is_admin", "admin", "username", "user", "nombre"}
                ]

                if not possible_cols:
                    continue

                select_cols = ", ".join(f'"{c}"' for c in possible_cols)
                found = db.execute(
                    _sa_text(f'SELECT {select_cols} FROM "{table}" WHERE id = :id LIMIT 1'),
                    {"id": user_id},
                ).fetchone()

                if not found:
                    continue

                values = [str(v).lower() for v in found if v is not None]
                if any(v in {"admin", "administrator", "superadmin", "1", "true"} for v in values):
                    return True
        except Exception:
            pass

    return False


def _iad_at_require_admin(request, db=None):
    # Si hay login pero no logramos detectar admin, por seguridad no mostramos página.
    if not _iad_at_is_logged(request):
        return _IAD_AT_RedirectResponse("/iad/login", status_code=303)

    if not _iad_at_is_admin(request, db=db):
        return _IAD_AT_Response("Forbidden: admin required", status_code=403)

    return None


def _iad_at_diff_html(a, b):
    import difflib
    import html

    a_lines = str(a or "").splitlines()
    b_lines = str(b or "").splitlines()

    sm = difflib.SequenceMatcher(None, a_lines, b_lines)
    parts = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for line in a_lines[i1:i2]:
                parts.append(f'<div class="iad-diff-line iad-diff-eq"><span class="iad-diff-prefix"> </span>{html.escape(line)}</div>')
        elif tag == "delete":
            for line in a_lines[i1:i2]:
                parts.append(f'<div class="iad-diff-line iad-diff-del"><span class="iad-diff-prefix">−</span>{html.escape(line)}</div>')
        elif tag == "insert":
            for line in b_lines[j1:j2]:
                parts.append(f'<div class="iad-diff-line iad-diff-ins"><span class="iad-diff-prefix">+</span>{html.escape(line)}</div>')
        elif tag == "replace":
            for line in a_lines[i1:i2]:
                parts.append(f'<div class="iad-diff-line iad-diff-del"><span class="iad-diff-prefix">−</span>{html.escape(line)}</div>')
            for line in b_lines[j1:j2]:
                parts.append(f'<div class="iad-diff-line iad-diff-ins"><span class="iad-diff-prefix">+</span>{html.escape(line)}</div>')

    return "\n".join(parts)


def _iad_at_rows(db, ids=None):
    from sqlalchemy import text as _sa_text
    import json as _json

    _iad_at_ensure_table(db)

    where = ""
    params = {}

    if ids:
        clean_ids = []
        for x in ids:
            try:
                clean_ids.append(int(x))
            except Exception:
                pass

        if clean_ids:
            placeholders = []
            for i, value in enumerate(clean_ids):
                key = f"id_{i}"
                placeholders.append(f":{key}")
                params[key] = value
            where = "WHERE id IN (" + ",".join(placeholders) + ")"

    rows = db.execute(
        _sa_text(f"""
            SELECT
                id,
                ot_id,
                texto_dictado,
                plantilla_nombre,
                plantilla_id,
                hallazgos_detectados,
                resultado_primario,
                resultado_revisado,
                modelo,
                metadata_json,
                created_at,
                updated_at
            FROM iad_training_samples
            {where}
            ORDER BY id DESC
        """),
        params,
    ).fetchall()

    items = []
    for r in rows:
        try:
            meta = _json.loads(r[9] or "{}")
        except Exception:
            meta = {}

        item = {
            "id": r[0],
            "ot_id": r[1],
            "texto_dictado": r[2] or "",
            "plantilla_nombre": r[3] or "",
            "plantilla_id": r[4] or "",
            "hallazgos_detectados": r[5] or "",
            "resultado_primario": r[6] or "",
            "resultado_revisado": r[7] or "",
            "modelo": r[8] or "",
            "metadata": meta,
            "created_at": r[10],
            "updated_at": r[11],
        }
        item["diff_html"] = _iad_at_diff_html(item["resultado_primario"], item["resultado_revisado"])
        items.append(item)

    return items


@router.get("/iad/admin/training")
async def iad_admin_training_page(
    request: _IAD_AT_Request,
    db = _IAD_AT_Depends(_IAD_AT_get_db),
):
    denied = _iad_at_require_admin(request, db=db)
    if denied:
        return denied

    items = _iad_at_rows(db)

    return _iad_at_templates().TemplateResponse(
        "iadictador/admin_training.html",
        {
            "request": request,
            "items": items,
            "count": len(items),
        },
    )


@router.get("/iad/admin/training/export.json")
async def iad_admin_training_export_all(
    request: _IAD_AT_Request,
    db = _IAD_AT_Depends(_IAD_AT_get_db),
):
    denied = _iad_at_require_admin(request, db=db)
    if denied:
        return denied

    items = _iad_at_rows(db)

    # No mandar diff_html en export principal.
    for item in items:
        item.pop("diff_html", None)

    return _IAD_AT_JSONResponse({
        "ok": True,
        "count": len(items),
        "items": items,
    })


@router.post("/iad/admin/training/export-selected.json")
async def iad_admin_training_export_selected(
    request: _IAD_AT_Request,
    ids: list[str] = _IAD_AT_Form([]),
    db = _IAD_AT_Depends(_IAD_AT_get_db),
):
    denied = _iad_at_require_admin(request, db=db)
    if denied:
        return denied

    items = _iad_at_rows(db, ids=ids)

    for item in items:
        item.pop("diff_html", None)

    return _IAD_AT_JSONResponse({
        "ok": True,
        "count": len(items),
        "selected_ids": ids,
        "items": items,
    })


@router.get("/iad/admin/training/{sample_id}.json")
async def iad_admin_training_one_json(
    request: _IAD_AT_Request,
    sample_id: int,
    db = _IAD_AT_Depends(_IAD_AT_get_db),
):
    denied = _iad_at_require_admin(request, db=db)
    if denied:
        return denied

    items = _iad_at_rows(db, ids=[sample_id])

    if not items:
        return _IAD_AT_JSONResponse({"ok": False, "error": "not_found"}, status_code=404)

    item = items[0]
    item.pop("diff_html", None)

    return _IAD_AT_JSONResponse({
        "ok": True,
        "item": item,
    })



# IAD_TRAINING_DELETE_AND_HISTORY_SYNC_V2
from fastapi import Depends as _IAD_TDH2_Depends
from fastapi import Form as _IAD_TDH2_Form
from fastapi import Request as _IAD_TDH2_Request
from fastapi.responses import JSONResponse as _IAD_TDH2_JSONResponse
from fastapi.responses import RedirectResponse as _IAD_TDH2_RedirectResponse
from fastapi.responses import Response as _IAD_TDH2_Response

try:
    from app.iadictador.db import get_db as _IAD_TDH2_get_db
except Exception:
    _IAD_TDH2_get_db = globals().get("get_db")


def _iad_tdh2_ensure_tables(db):
    from sqlalchemy import text as _sa_text

    db.execute(_sa_text("""
        CREATE TABLE IF NOT EXISTS iad_training_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ot_id INTEGER,
            texto_dictado TEXT,
            plantilla_nombre TEXT,
            plantilla_id TEXT,
            hallazgos_detectados TEXT,
            resultado_primario TEXT,
            resultado_revisado TEXT,
            modelo TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))

    db.execute(_sa_text("""
        CREATE INDEX IF NOT EXISTS idx_iad_training_samples_ot_id
        ON iad_training_samples(ot_id)
    """))

    db.execute(_sa_text("""
        CREATE TABLE IF NOT EXISTS iad_training_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id INTEGER,
            ot_id INTEGER,
            accion TEXT,
            detalle TEXT,
            resultado_revisado TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))

    db.commit()


def _iad_tdh2_session(request):
    try:
        return request.session or {}
    except Exception:
        return {}


def _iad_tdh2_logged(request):
    sess = _iad_tdh2_session(request)
    return any(sess.get(k) for k in ["user_id", "iad_user_id", "uid", "username", "user", "email", "role", "is_admin"])


def _iad_tdh2_admin(request):
    sess = _iad_tdh2_session(request)

    for key in ("is_admin", "admin"):
        value = sess.get(key)
        if value is True or str(value).lower() in {"1", "true", "yes", "admin"}:
            return True

    role = str(sess.get("role") or sess.get("rol") or "").lower()
    if role in {"admin", "administrator", "superadmin"}:
        return True

    username = str(sess.get("username") or sess.get("user") or "").lower()
    if username in {"admin", "egidio"}:
        return True

    return False


def _iad_tdh2_require_admin(request):
    if not _iad_tdh2_logged(request):
        return _IAD_TDH2_RedirectResponse("/iad/login", status_code=303)

    if not _iad_tdh2_admin(request):
        return _IAD_TDH2_Response("Forbidden: admin required", status_code=403)

    return None


def _iad_tdh2_int_or_none(value):
    try:
        if str(value).strip() == "":
            return None
        return int(value)
    except Exception:
        return None


def _iad_tdh2_clean_json(raw):
    import json as _json

    try:
        parsed = _json.loads(raw or "{}")
        return _json.dumps(parsed, ensure_ascii=False, indent=2)
    except Exception:
        return "{}"


def _iad_tdh2_columns(db, table_name):
    from sqlalchemy import text as _sa_text

    try:
        rows = db.execute(_sa_text('PRAGMA table_info("' + table_name + '")')).fetchall()
        return [r[1] for r in rows]
    except Exception:
        return []


def _iad_tdh2_insert_or_update_sample(
    db,
    ot_id,
    texto_dictado,
    plantilla_nombre,
    plantilla_id,
    hallazgos_detectados,
    resultado_primario,
    resultado_revisado,
    modelo,
    metadata_json,
):
    from sqlalchemy import text as _sa_text

    _iad_tdh2_ensure_tables(db)

    existing_id = None

    if ot_id is not None:
        row = db.execute(
            _sa_text("""
                SELECT id
                FROM iad_training_samples
                WHERE ot_id = :ot_id
                ORDER BY id DESC
                LIMIT 1
            """),
            {"ot_id": ot_id},
        ).fetchone()

        if row:
            existing_id = row[0]

    params = {
        "ot_id": ot_id,
        "texto_dictado": texto_dictado or "",
        "plantilla_nombre": plantilla_nombre or "",
        "plantilla_id": plantilla_id or "",
        "hallazgos_detectados": hallazgos_detectados or "",
        "resultado_primario": resultado_primario or "",
        "resultado_revisado": resultado_revisado or "",
        "modelo": modelo or "",
        "metadata_json": _iad_tdh2_clean_json(metadata_json),
    }

    if existing_id:
        params["id"] = existing_id

        db.execute(
            _sa_text("""
                UPDATE iad_training_samples
                SET
                    texto_dictado = :texto_dictado,
                    plantilla_nombre = :plantilla_nombre,
                    plantilla_id = :plantilla_id,
                    hallazgos_detectados = :hallazgos_detectados,
                    resultado_primario = :resultado_primario,
                    resultado_revisado = :resultado_revisado,
                    modelo = :modelo,
                    metadata_json = :metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            params,
        )

        db.commit()
        return existing_id

    result = db.execute(
        _sa_text("""
            INSERT INTO iad_training_samples (
                ot_id,
                texto_dictado,
                plantilla_nombre,
                plantilla_id,
                hallazgos_detectados,
                resultado_primario,
                resultado_revisado,
                modelo,
                metadata_json,
                created_at,
                updated_at
            )
            VALUES (
                :ot_id,
                :texto_dictado,
                :plantilla_nombre,
                :plantilla_id,
                :hallazgos_detectados,
                :resultado_primario,
                :resultado_revisado,
                :modelo,
                :metadata_json,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
        """),
        params,
    )

    sample_id = getattr(result, "lastrowid", None)

    if not sample_id:
        row = db.execute(_sa_text("SELECT last_insert_rowid()")).fetchone()
        sample_id = row[0] if row else None

    db.commit()
    return sample_id


def _iad_tdh2_sync_history(db, sample_id, ot_id, texto_dictado, plantilla_nombre, hallazgos_detectados, resultado_revisado):
    from sqlalchemy import text as _sa_text

    _iad_tdh2_ensure_tables(db)

    detail = {
        "ok": False,
        "sample_id": sample_id,
        "ot_id": ot_id,
        "updated_table": "",
        "updated_columns": [],
        "reason": "",
    }

    db.execute(
        _sa_text("""
            INSERT INTO iad_training_history (
                sample_id,
                ot_id,
                accion,
                detalle,
                resultado_revisado,
                created_at
            )
            VALUES (
                :sample_id,
                :ot_id,
                'guardar_revision',
                :detalle,
                :resultado_revisado,
                CURRENT_TIMESTAMP
            )
        """),
        {
            "sample_id": sample_id,
            "ot_id": ot_id,
            "detalle": "plantilla=" + (plantilla_nombre or "") + "; hallazgos_len=" + str(len(hallazgos_detectados or "")),
            "resultado_revisado": resultado_revisado or "",
        },
    )

    if ot_id is None:
        detail["reason"] = "sin_ot_id"
        db.commit()
        return detail

    # Sincronización best-effort con una tabla principal si existe.
    tables = db.execute(
        _sa_text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    ).fetchall()

    candidate_tables = []

    for row in tables:
        table = row[0]
        tl = table.lower()

        if table in {"iad_training_samples", "iad_training_history"}:
            continue

        if not any(k in tl for k in ["ot", "orden", "trabajo", "historial", "history", "job"]):
            continue

        cols = _iad_tdh2_columns(db, table)

        if "id" not in cols:
            continue

        try:
            exists = db.execute(
                _sa_text('SELECT id FROM "' + table + '" WHERE id = :id LIMIT 1'),
                {"id": ot_id},
            ).fetchone()
        except Exception:
            exists = None

        if exists:
            candidate_tables.append((table, cols))

    if not candidate_tables:
        detail["reason"] = "no_encontre_tabla_ot_con_ese_id"
        db.commit()
        return detail

    def table_score(item):
        table, cols = item
        tl = table.lower()
        score = 0
        if "ot" in tl:
            score += 50
        if "orden" in tl:
            score += 40
        if "trabajo" in tl:
            score += 40
        if "historial" in tl or "history" in tl:
            score -= 10
        return score

    candidate_tables.sort(key=table_score, reverse=True)
    target_table, cols = candidate_tables[0]

    params = {"id": ot_id}
    assignments = []

    def add_col(possible_names, value, param_name):
        for col in possible_names:
            if col in cols:
                assignments.append('"' + col + '" = :' + param_name)
                params[param_name] = value or ""
                detail["updated_columns"].append(col)
                return True
        return False

    add_col(
        ["resultado_revisado", "resultado_final", "informe_final", "texto_final", "final_text", "resultado", "informe", "output", "salida", "texto_resultado", "contenido_final"],
        resultado_revisado,
        "resultado_revisado",
    )

    add_col(
        ["texto_dictado", "transcripcion", "texto_transcrito", "input_text", "entrada", "texto_entrada"],
        texto_dictado,
        "texto_dictado",
    )

    add_col(
        ["plantilla_nombre", "plantilla", "template_name", "template"],
        plantilla_nombre,
        "plantilla_nombre",
    )

    add_col(
        ["hallazgos_detectados", "hallazgos", "findings"],
        hallazgos_detectados,
        "hallazgos_detectados",
    )

    for col in ["updated_at", "actualizado_en", "modified_at"]:
        if col in cols:
            assignments.append('"' + col + '" = CURRENT_TIMESTAMP')
            detail["updated_columns"].append(col)
            break

    if not assignments:
        detail["reason"] = "tabla_" + target_table + "_sin_columnas_actualizables"
        db.commit()
        return detail

    sql = 'UPDATE "' + target_table + '" SET ' + ", ".join(assignments) + " WHERE id = :id"

    try:
        db.execute(_sa_text(sql), params)
        db.commit()
        detail["ok"] = True
        detail["updated_table"] = target_table
        detail["reason"] = "sincronizado"
        return detail
    except Exception as exc:
        db.rollback()
        detail["reason"] = "error_update_" + target_table + ": " + str(exc)
        return detail


@router.post("/iad/guardar-revision-y-historial.json")
async def iad_guardar_revision_y_historial_json(
    request: _IAD_TDH2_Request,
    ot_id: str = _IAD_TDH2_Form(""),
    texto_dictado: str = _IAD_TDH2_Form(""),
    plantilla_nombre: str = _IAD_TDH2_Form(""),
    plantilla_id: str = _IAD_TDH2_Form(""),
    hallazgos_detectados: str = _IAD_TDH2_Form(""),
    resultado_primario: str = _IAD_TDH2_Form(""),
    resultado_revisado: str = _IAD_TDH2_Form(""),
    modelo: str = _IAD_TDH2_Form(""),
    metadata_json: str = _IAD_TDH2_Form("{}"),
    db = _IAD_TDH2_Depends(_IAD_TDH2_get_db),
):
    ot_id_int = _iad_tdh2_int_or_none(ot_id)

    sample_id = _iad_tdh2_insert_or_update_sample(
        db,
        ot_id_int,
        texto_dictado,
        plantilla_nombre,
        plantilla_id,
        hallazgos_detectados,
        resultado_primario,
        resultado_revisado,
        modelo,
        metadata_json,
    )

    history_sync = _iad_tdh2_sync_history(
        db,
        sample_id,
        ot_id_int,
        texto_dictado,
        plantilla_nombre,
        hallazgos_detectados,
        resultado_revisado,
    )

    return _IAD_TDH2_JSONResponse({
        "ok": True,
        "sample_id": sample_id,
        "ot_id": ot_id_int,
        "historial_sync": history_sync,
    })


@router.post("/iad/admin/training/delete_selected")
async def iad_admin_training_delete_selected_v2(
    request: _IAD_TDH2_Request,
    ids: list[str] = _IAD_TDH2_Form([]),
    db = _IAD_TDH2_Depends(_IAD_TDH2_get_db),
):
    from sqlalchemy import text as _sa_text

    denied = _iad_tdh2_require_admin(request)
    if denied:
        return denied

    _iad_tdh2_ensure_tables(db)

    clean_ids = []

    for value in ids:
        parsed = _iad_tdh2_int_or_none(value)
        if parsed is not None:
            clean_ids.append(parsed)

    clean_ids = sorted(set(clean_ids))

    if not clean_ids:
        return _IAD_TDH2_JSONResponse({
            "ok": False,
            "error": "sin_ids",
            "deleted": 0,
        }, status_code=400)

    placeholders = []
    params = {}

    for i, sample_id in enumerate(clean_ids):
        key = "id_" + str(i)
        placeholders.append(":" + key)
        params[key] = sample_id

    in_sql = ", ".join(placeholders)

    before = db.execute(
        _sa_text("SELECT COUNT(*) FROM iad_training_samples WHERE id IN (" + in_sql + ")"),
        params,
    ).fetchone()[0]

    db.execute(
        _sa_text("DELETE FROM iad_training_samples WHERE id IN (" + in_sql + ")"),
        params,
    )

    db.execute(
        _sa_text("DELETE FROM iad_training_history WHERE sample_id IN (" + in_sql + ")"),
        params,
    )

    db.commit()

    return _IAD_TDH2_JSONResponse({
        "ok": True,
        "deleted": before,
        "ids": clean_ids,
    })


@router.post("/iad/admin/training/delete_one")
async def iad_admin_training_delete_one_v2(
    request: _IAD_TDH2_Request,
    id: str = _IAD_TDH2_Form(""),
    db = _IAD_TDH2_Depends(_IAD_TDH2_get_db),
):
    return await iad_admin_training_delete_selected_v2(
        request=request,
        ids=[id],
        db=db,
    )


# IAD_SAVE_REVIEW_HISTORY_REAL_V3
from fastapi import Depends as _IAD_HR3_Depends
from fastapi import Form as _IAD_HR3_Form
from fastapi import Request as _IAD_HR3_Request
from fastapi.responses import JSONResponse as _IAD_HR3_JSONResponse
from fastapi.responses import RedirectResponse as _IAD_HR3_RedirectResponse
from fastapi.responses import Response as _IAD_HR3_Response

try:
    from app.iadictador.db import get_db as _IAD_HR3_get_db
except Exception:
    _IAD_HR3_get_db = globals().get("get_db")


def _iad_hr3_ensure_training_tables(db):
    from sqlalchemy import text as _sa_text

    db.execute(_sa_text("""
        CREATE TABLE IF NOT EXISTS iad_training_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ot_id INTEGER,
            texto_dictado TEXT,
            plantilla_nombre TEXT,
            plantilla_id TEXT,
            hallazgos_detectados TEXT,
            resultado_primario TEXT,
            resultado_revisado TEXT,
            modelo TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))

    db.execute(_sa_text("""
        CREATE INDEX IF NOT EXISTS idx_iad_training_samples_ot_id
        ON iad_training_samples(ot_id)
    """))

    db.execute(_sa_text("""
        CREATE TABLE IF NOT EXISTS iad_training_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id INTEGER,
            ot_id INTEGER,
            accion TEXT,
            detalle TEXT,
            resultado_revisado TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))

    db.commit()


def _iad_hr3_now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _iad_hr3_session(request):
    try:
        return request.session or {}
    except Exception:
        return {}


def _iad_hr3_username(request):
    sess = _iad_hr3_session(request)
    return (
        sess.get("username")
        or sess.get("user")
        or sess.get("email")
        or sess.get("login")
        or "admin"
    )


def _iad_hr3_logged(request):
    sess = _iad_hr3_session(request)
    return any(sess.get(k) for k in ["user_id", "iad_user_id", "uid", "username", "user", "email", "role", "is_admin"])


def _iad_hr3_admin(request):
    sess = _iad_hr3_session(request)

    for key in ("is_admin", "admin"):
        value = sess.get(key)
        if value is True or str(value).lower() in {"1", "true", "yes", "admin"}:
            return True

    role = str(sess.get("role") or sess.get("rol") or "").lower()
    if role in {"admin", "administrator", "superadmin"}:
        return True

    username = str(sess.get("username") or sess.get("user") or "").lower()
    if username in {"admin", "egidio"}:
        return True

    return False


def _iad_hr3_require_admin(request):
    if not _iad_hr3_logged(request):
        return _IAD_HR3_RedirectResponse("/iad/login", status_code=303)

    if not _iad_hr3_admin(request):
        return _IAD_HR3_Response("Forbidden: admin required", status_code=403)

    return None


def _iad_hr3_int_or_none(value):
    try:
        if str(value).strip() == "":
            return None
        return int(value)
    except Exception:
        return None


def _iad_hr3_clean_json(raw):
    import json as _json

    try:
        parsed = _json.loads(raw or "{}")
        return _json.dumps(parsed, ensure_ascii=False, indent=2)
    except Exception:
        return "{}"


def _iad_hr3_cols_info(db, table_name):
    from sqlalchemy import text as _sa_text

    try:
        rows = db.execute(_sa_text('PRAGMA table_info("' + table_name + '")')).fetchall()
        out = []
        for r in rows:
            out.append({
                "cid": r[0],
                "name": r[1],
                "type": r[2] or "",
                "notnull": bool(r[3]),
                "default": r[4],
                "pk": bool(r[5]),
            })
        return out
    except Exception:
        return []


def _iad_hr3_cols(db, table_name):
    return [c["name"] for c in _iad_hr3_cols_info(db, table_name)]


def _iad_hr3_table_count(db, table_name):
    from sqlalchemy import text as _sa_text

    try:
        row = db.execute(_sa_text('SELECT COUNT(*) FROM "' + table_name + '"')).fetchone()
        return int(row[0] or 0)
    except Exception:
        return 0


def _iad_hr3_find_history_table(db):
    from sqlalchemy import text as _sa_text

    rows = db.execute(_sa_text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")).fetchall()
    candidates = []

    for row in rows:
        table = row[0]
        tl = table.lower()

        if any(x in tl for x in ["training", "template", "plantilla", "user", "usuario", "session", "alembic", "place", "lugar"]):
            continue

        info = _iad_hr3_cols_info(db, table)
        cols = [c["name"] for c in info]
        cl = [c.lower() for c in cols]

        if "id" not in cols:
            continue

        score = 0

        if any(x in tl for x in ["ot", "orden", "trabajo", "work", "job", "request", "historial", "history"]):
            score += 35

        if any(c in cl for c in ["estado", "status"]):
            score += 40

        if any(c in cl for c in ["timestamp", "created_at", "creado_en", "fecha", "fecha_creacion"]):
            score += 35

        if any(c in cl for c in ["usuario", "user", "username"]):
            score += 25

        if any(c in cl for c in ["tipo", "tipo_informe", "report_type"]):
            score += 15

        if any(c in cl for c in ["modalidad", "modality"]):
            score += 15

        if any(c in cl for c in ["titulo", "title", "report_title"]):
            score += 15

        if any(c in cl for c in ["paciente", "patient", "patient_name", "nombre_paciente"]):
            score += 10

        if any(c in cl for c in ["edad", "age"]):
            score += 10

        if any(c in cl for c in ["resultado", "resultado_final", "informe_final", "texto_final", "informe", "output"]):
            score += 20

        count = _iad_hr3_table_count(db, table)
        if count > 0:
            score += 10

        # Evitar tablas demasiado pobres.
        if score >= 60:
            candidates.append({
                "table": table,
                "score": score,
                "count": count,
                "columns": cols,
                "info": info,
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    if not candidates:
        return None

    return candidates[0]


def _iad_hr3_first_col(cols, possible):
    for name in possible:
        if name in cols:
            return name
    return None


def _iad_hr3_infer_modalidad(plantilla_nombre, modalidad):
    raw = ((modalidad or "") + " " + (plantilla_nombre or "")).strip().lower()

    if raw.startswith("tc") or "tomografia" in raw or "tac" in raw:
        return "TC"
    if raw.startswith("rm") or "resonancia" in raw:
        return "RM"
    if raw.startswith("rx") or "radiografia" in raw:
        return "RX"
    if raw.startswith("us") or "ecografia" in raw or "ultrasonido" in raw or raw.startswith("eco"):
        return "US"
    if raw.startswith("mg") or "mamografia" in raw:
        return "MG"

    return modalidad or ""


def _iad_hr3_insert_training_sample(
    db,
    ot_id,
    texto_dictado,
    plantilla_nombre,
    plantilla_id,
    hallazgos_detectados,
    resultado_primario,
    resultado_revisado,
    modelo,
    metadata_json,
):
    from sqlalchemy import text as _sa_text

    _iad_hr3_ensure_training_tables(db)

    result = db.execute(
        _sa_text("""
            INSERT INTO iad_training_samples (
                ot_id,
                texto_dictado,
                plantilla_nombre,
                plantilla_id,
                hallazgos_detectados,
                resultado_primario,
                resultado_revisado,
                modelo,
                metadata_json,
                created_at,
                updated_at
            )
            VALUES (
                :ot_id,
                :texto_dictado,
                :plantilla_nombre,
                :plantilla_id,
                :hallazgos_detectados,
                :resultado_primario,
                :resultado_revisado,
                :modelo,
                :metadata_json,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
        """),
        {
            "ot_id": ot_id,
            "texto_dictado": texto_dictado or "",
            "plantilla_nombre": plantilla_nombre or "",
            "plantilla_id": plantilla_id or "",
            "hallazgos_detectados": hallazgos_detectados or "",
            "resultado_primario": resultado_primario or "",
            "resultado_revisado": resultado_revisado or "",
            "modelo": modelo or "",
            "metadata_json": _iad_hr3_clean_json(metadata_json),
        },
    )

    sample_id = getattr(result, "lastrowid", None)

    if not sample_id:
        row = db.execute(_sa_text("SELECT last_insert_rowid()")).fetchone()
        sample_id = row[0] if row else None

    db.commit()
    return sample_id


def _iad_hr3_insert_training_audit(db, sample_id, ot_id, plantilla_nombre, hallazgos_detectados, resultado_revisado):
    from sqlalchemy import text as _sa_text

    _iad_hr3_ensure_training_tables(db)

    db.execute(
        _sa_text("""
            INSERT INTO iad_training_history (
                sample_id,
                ot_id,
                accion,
                detalle,
                resultado_revisado,
                created_at
            )
            VALUES (
                :sample_id,
                :ot_id,
                'guardar_revision',
                :detalle,
                :resultado_revisado,
                CURRENT_TIMESTAMP
            )
        """),
        {
            "sample_id": sample_id,
            "ot_id": ot_id,
            "detalle": "plantilla=" + (plantilla_nombre or "") + "; hallazgos_len=" + str(len(hallazgos_detectados or "")),
            "resultado_revisado": resultado_revisado or "",
        },
    )

    db.commit()


def _iad_hr3_save_real_history(
    db,
    request,
    ot_id,
    texto_dictado,
    plantilla_nombre,
    plantilla_id,
    hallazgos_detectados,
    resultado_primario,
    resultado_revisado,
    modelo,
    metadata_json,
    tipo,
    modalidad,
    titulo,
    paciente,
    edad,
    dry_run,
):
    from sqlalchemy import text as _sa_text

    chosen = _iad_hr3_find_history_table(db)

    detail = {
        "ok": False,
        "reason": "",
        "table": "",
        "mode": "",
        "ot_id": ot_id,
        "columns_written": [],
        "candidate": chosen,
    }

    if not chosen:
        detail["reason"] = "no_encontre_tabla_real_de_historial"
        return detail

    table = chosen["table"]
    cols = chosen["columns"]
    info = chosen["info"]

    detail["table"] = table

    now = _iad_hr3_now()
    username = _iad_hr3_username(request)

    modalidad_final = _iad_hr3_infer_modalidad(plantilla_nombre, modalidad)
    titulo_final = titulo or plantilla_nombre or ""
    tipo_final = tipo or plantilla_nombre or ""

    # Mapeo de datos a columnas reales.
    mapping = {}

    def set_first(possible, value):
        col = _iad_hr3_first_col(cols, possible)
        if col:
            mapping[col] = value if value is not None else ""
            return col
        return None

    set_first(["usuario", "user", "username"], username)
    set_first(["timestamp", "created_at", "creado_en", "fecha", "fecha_creacion"], now)
    set_first(["updated_at", "actualizado_en", "modified_at"], now)
    set_first(["estado", "status"], "validated")

    set_first(["tipo", "tipo_informe", "report_type"], tipo_final)
    set_first(["modalidad", "modality"], modalidad_final)
    set_first(["titulo", "title", "report_title"], titulo_final)

    set_first(["paciente", "patient", "patient_name", "nombre_paciente"], paciente or "")
    set_first(["edad", "age"], edad or "")

    set_first(["texto_dictado", "transcripcion", "texto_transcrito", "input_text", "entrada", "texto_entrada"], texto_dictado or "")
    set_first(["hallazgos_detectados", "hallazgos", "findings"], hallazgos_detectados or "")
    set_first(["resultado_primario", "resultado_ai", "resultado_ia", "draft", "borrador"], resultado_primario or "")
    set_first(
        ["resultado_revisado", "resultado_final", "informe_final", "texto_final", "final_text", "resultado", "informe", "output", "salida", "texto_resultado", "contenido_final"],
        resultado_revisado or "",
    )

    set_first(["plantilla_nombre", "plantilla", "template_name", "template"], plantilla_nombre or "")
    set_first(["plantilla_id", "template_id"], plantilla_id or "")
    set_first(["modelo", "model"], modelo or "")

    if dry_run:
        detail["ok"] = True
        detail["reason"] = "dry_run"
        detail["planned_mapping"] = mapping
        return detail

    # Si viene ot_id y existe, actualizar. Si no, insertar fila nueva.
    exists = None

    if ot_id is not None:
        try:
            exists = db.execute(
                _sa_text('SELECT id FROM "' + table + '" WHERE id = :id LIMIT 1'),
                {"id": ot_id},
            ).fetchone()
        except Exception:
            exists = None

    if exists:
        assignments = []
        params = {"id": ot_id}

        for col, value in mapping.items():
            if col == "id":
                continue
            assignments.append('"' + col + '" = :' + col)
            params[col] = value

        if not assignments:
            detail["reason"] = "sin_columnas_actualizables"
            return detail

        sql = 'UPDATE "' + table + '" SET ' + ", ".join(assignments) + " WHERE id = :id"
        db.execute(_sa_text(sql), params)
        db.commit()

        detail["ok"] = True
        detail["mode"] = "update"
        detail["reason"] = "historial_actualizado"
        detail["ot_id"] = ot_id
        detail["columns_written"] = list(mapping.keys())
        return detail

    # Insertar nueva OT/historial.
    insert_cols = []
    params = {}

    for col, value in mapping.items():
        if col == "id":
            continue
        insert_cols.append(col)
        params[col] = value

    # Completar columnas NOT NULL sin default que no estén cubiertas.
    for c in info:
        col = c["name"]
        ctype = str(c["type"] or "").upper()

        if c["pk"]:
            continue

        if not c["notnull"]:
            continue

        if c["default"] is not None:
            continue

        if col in params:
            continue

        if "INT" in ctype:
            params[col] = 0
        else:
            params[col] = ""

        insert_cols.append(col)

    if not insert_cols:
        detail["reason"] = "sin_columnas_insertables"
        return detail

    quoted_cols = ['"' + c + '"' for c in insert_cols]
    placeholders = [":" + c for c in insert_cols]

    sql = 'INSERT INTO "' + table + '" (' + ", ".join(quoted_cols) + ') VALUES (' + ", ".join(placeholders) + ')'

    db.execute(_sa_text(sql), params)

    row = db.execute(_sa_text("SELECT last_insert_rowid()")).fetchone()
    new_ot_id = row[0] if row else None

    db.commit()

    detail["ok"] = True
    detail["mode"] = "insert"
    detail["reason"] = "historial_creado"
    detail["ot_id"] = new_ot_id
    detail["columns_written"] = insert_cols
    return detail


@router.post("/iad/guardar-revision-y-historial-v3.json")
async def iad_guardar_revision_y_historial_v3_json(
    request: _IAD_HR3_Request,
    ot_id: str = _IAD_HR3_Form(""),
    texto_dictado: str = _IAD_HR3_Form(""),
    plantilla_nombre: str = _IAD_HR3_Form(""),
    plantilla_id: str = _IAD_HR3_Form(""),
    hallazgos_detectados: str = _IAD_HR3_Form(""),
    resultado_primario: str = _IAD_HR3_Form(""),
    resultado_revisado: str = _IAD_HR3_Form(""),
    modelo: str = _IAD_HR3_Form(""),
    metadata_json: str = _IAD_HR3_Form("{}"),
    tipo: str = _IAD_HR3_Form(""),
    modalidad: str = _IAD_HR3_Form(""),
    titulo: str = _IAD_HR3_Form(""),
    paciente: str = _IAD_HR3_Form(""),
    edad: str = _IAD_HR3_Form(""),
    dry_run: str = _IAD_HR3_Form("0"),
    db = _IAD_HR3_Depends(_IAD_HR3_get_db),
):
    dry = str(dry_run).lower() in {"1", "true", "yes", "si", "sí"}

    ot_id_int = _iad_hr3_int_or_none(ot_id)

    history_sync = _iad_hr3_save_real_history(
        db=db,
        request=request,
        ot_id=ot_id_int,
        texto_dictado=texto_dictado,
        plantilla_nombre=plantilla_nombre,
        plantilla_id=plantilla_id,
        hallazgos_detectados=hallazgos_detectados,
        resultado_primario=resultado_primario,
        resultado_revisado=resultado_revisado,
        modelo=modelo,
        metadata_json=metadata_json,
        tipo=tipo,
        modalidad=modalidad,
        titulo=titulo,
        paciente=paciente,
        edad=edad,
        dry_run=dry,
    )

    if dry:
        return _IAD_HR3_JSONResponse({
            "ok": True,
            "dry_run": True,
            "historial_sync": history_sync,
        })

    sample_id = _iad_hr3_insert_training_sample(
        db=db,
        ot_id=history_sync.get("ot_id") or ot_id_int,
        texto_dictado=texto_dictado,
        plantilla_nombre=plantilla_nombre,
        plantilla_id=plantilla_id,
        hallazgos_detectados=hallazgos_detectados,
        resultado_primario=resultado_primario,
        resultado_revisado=resultado_revisado,
        modelo=modelo,
        metadata_json=metadata_json,
    )

    _iad_hr3_insert_training_audit(
        db=db,
        sample_id=sample_id,
        ot_id=history_sync.get("ot_id") or ot_id_int,
        plantilla_nombre=plantilla_nombre,
        hallazgos_detectados=hallazgos_detectados,
        resultado_revisado=resultado_revisado,
    )

    return _IAD_HR3_JSONResponse({
        "ok": True,
        "sample_id": sample_id,
        "ot_id": history_sync.get("ot_id") or ot_id_int,
        "historial_sync": history_sync,
    })


@router.post("/iad/admin/training/delete-selected-v3.json")
async def iad_admin_training_delete_selected_v3_json(
    request: _IAD_HR3_Request,
    ids: list[str] = _IAD_HR3_Form([]),
    db = _IAD_HR3_Depends(_IAD_HR3_get_db),
):
    from sqlalchemy import text as _sa_text

    denied = _iad_hr3_require_admin(request)
    if denied:
        return denied

    _iad_hr3_ensure_training_tables(db)

    clean_ids = []
    for value in ids:
        parsed = _iad_hr3_int_or_none(value)
        if parsed is not None:
            clean_ids.append(parsed)

    clean_ids = sorted(set(clean_ids))

    if not clean_ids:
        return _IAD_HR3_JSONResponse({"ok": False, "error": "sin_ids", "deleted": 0}, status_code=400)

    placeholders = []
    params = {}

    for idx, sample_id in enumerate(clean_ids):
        key = "id_" + str(idx)
        placeholders.append(":" + key)
        params[key] = sample_id

    in_sql = ", ".join(placeholders)

    before = db.execute(
        _sa_text("SELECT COUNT(*) FROM iad_training_samples WHERE id IN (" + in_sql + ")"),
        params,
    ).fetchone()[0]

    db.execute(
        _sa_text("DELETE FROM iad_training_samples WHERE id IN (" + in_sql + ")"),
        params,
    )

    db.execute(
        _sa_text("DELETE FROM iad_training_history WHERE sample_id IN (" + in_sql + ")"),
        params,
    )

    db.commit()

    return _IAD_HR3_JSONResponse({
        "ok": True,
        "deleted": before,
        "ids": clean_ids,
    })


# IAD_CLINICAL_JSON_ENDPOINTS_V1
@router.post("/iad/analizar-radiologia-estructurada.json")
async def analizar_radiologia_estructurada_json(
    request: Request,
    texto_bruto: str = Form(""),
    db: Session = Depends(get_db),
):
    from fastapi.responses import JSONResponse
    from app.services.ai.tasks.radiology_flow import analyze_radiology
    from app.services.ai.tasks.clinical_json import extract_clinical_json, clinical_json_to_hallazgos_text

    try:
        require_user(request, db)
    except PermissionError:
        return JSONResponse({"ok": False, "error": "login_required"}, status_code=401)

    analysis = analyze_radiology(texto_bruto, db=db)

    try:
        clinical = extract_clinical_json(texto_bruto, analysis=analysis)
    except Exception as exc:
        clinical = {
            "ok": False,
            "version": "clinical_json_v1",
            "dictado_original": texto_bruto,
            "hallazgos": [],
            "impresion_solicitada": [],
            "conflictos": [],
            "advertencias": [f"Falló clinical_json en endpoint estructurado: {exc}"],
            "necesita_revision": True,
            "metodo": "router_fallback_clinical_json_error",
        }

    try:
        structured_text = clinical_json_to_hallazgos_text(clinical)
    except Exception as exc:
        structured_text = ""
        clinical.setdefault("advertencias", []).append(f"No se pudo convertir clinical_json a texto estructurado: {exc}")

    warnings = []
    warnings.extend(analysis.get("advertencias") or [])
    warnings.extend(clinical.get("advertencias") or [])

    conflicts = clinical.get("conflictos") or []
    if conflicts:
        warnings.append("JSON clínico intermedio contiene conflictos que requieren revisión.")

    out = dict(analysis)
    out["clinical_json"] = clinical
    out["hallazgos_radiologicos_originales"] = out.get("hallazgos_radiologicos", "")
    out["hallazgos_radiologicos"] = structured_text or out.get("hallazgos_radiologicos", "")
    out["advertencias"] = list(dict.fromkeys([str(x) for x in warnings if str(x).strip()]))
    out["necesita_revision"] = bool(out.get("necesita_revision") or clinical.get("necesita_revision") or conflicts)
    out["metodo"] = "analisis_estructurado_clinical_json_v1"

    return JSONResponse(out)


@router.post("/iad/generar-informe-radiologico-estructurado.json")
async def generar_informe_radiologico_estructurado_json(
    request: Request,
    plantilla_nombre: str = Form(""),
    plantilla_id: str = Form(""),
    hallazgos: str = Form(""),
    clinical_json: str = Form(""),
    db: Session = Depends(get_db),
):
    from fastapi.responses import JSONResponse
    import json as _json
    from app.services.ai.tasks.radiology_flow import generate_report_from_template
    from app.services.ai.tasks.clinical_json import clinical_json_to_hallazgos_text

    try:
        require_user(request, db)
    except PermissionError:
        return JSONResponse({"ok": False, "error": "login_required"}, status_code=401)

    parsed = {}
    if clinical_json:
        try:
            parsed = _json.loads(clinical_json)
        except Exception as exc:
            parsed = {
                "ok": False,
                "advertencias": [f"clinical_json no era JSON válido: {exc}"],
                "conflictos": [],
            }

    structured_hallazgos = ""
    if parsed:
        try:
            structured_hallazgos = clinical_json_to_hallazgos_text(parsed)
        except Exception as exc:
            structured_hallazgos = ""
            parsed.setdefault("advertencias", []).append(f"No se pudo convertir clinical_json a hallazgos: {exc}")

    final_hallazgos = structured_hallazgos or hallazgos

    result = generate_report_from_template(
        final_hallazgos,
        template_name=plantilla_nombre,
        template_id=plantilla_id,
        db=db,
    )

    warnings = []
    warnings.extend(result.get("advertencias") or [])
    warnings.extend(parsed.get("advertencias") or [])

    if parsed.get("conflictos"):
        warnings.append("El informe fue generado desde JSON clínico con conflictos pendientes. Revisar antes de firmar.")

    out = dict(result)
    out["clinical_json"] = parsed
    out["hallazgos_estructurados_usados"] = final_hallazgos
    out["advertencias"] = list(dict.fromkeys([str(x) for x in warnings if str(x).strip()]))
    out["metodo"] = "generacion_desde_clinical_json_v1"

    return JSONResponse(out)


# IAD_WORK_V2_ROUTE
@router.get("/iad/trabajo2")
def iad_work_v2_alias():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/iad/trabajo", status_code=303)
@router.post("/iad/api/revision-clinica-v2.json")
async def iad_api_revision_clinica_v2(request: Request):
    import json
    from app.services.clinical_review_engine import review_clinical_report

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    source_text = (
        payload.get("source_text")
        or payload.get("dictado_original")
        or payload.get("texto_bruto")
        or ""
    )

    base_text = (
        payload.get("base_text")
        or payload.get("generated_text")
        or payload.get("informe_generado")
        or payload.get("informe_final")
        or ""
    )

    clinical_json = payload.get("clinical_json") or {}

    if isinstance(clinical_json, str):
        try:
            clinical_json = json.loads(clinical_json)
        except Exception:
            clinical_json = {"raw": clinical_json}

    return review_clinical_report(
        source_text=source_text,
        base_text=base_text,
        clinical_json=clinical_json,
    )

# IAD_WORK_LEGACY_ROUTE_V1

@router.get("/iad/trabajo_legacy")
def iad_work_legacy_page(request: Request, db = Depends(get_db)):
    from fastapi.responses import RedirectResponse
    from fastapi.templating import Jinja2Templates

    try:
        user = require_user(request, db)
    except PermissionError:
        return RedirectResponse("/iad/login", status_code=303)

    tmpl = globals().get("templates")
    if tmpl is None:
        tmpl = Jinja2Templates(directory="app/templates")

    return tmpl.TemplateResponse(
        "iadictador/work.html",
        {
            "request": request,
            "user": user,
            "current_user": user,
            "page": "trabajo_legacy",
        },
    )


# IAD_WORK_STORE_ENDPOINTS_V1
def _iad_username_from_user(user):
    try:
        if isinstance(user, dict):
            return str(user.get("username") or user.get("nombre") or user.get("email") or "usuario")
        return str(
            getattr(user, "username", None)
            or getattr(user, "nombre", None)
            or getattr(user, "email", None)
            or "usuario"
        )
    except Exception:
        return "usuario"


def _iad_is_admin_user(user):
    try:
        if isinstance(user, dict):
            role = str(user.get("role") or user.get("rol") or "")
        else:
            role = str(getattr(user, "role", None) or getattr(user, "rol", None) or "")
        return role.lower() == "admin"
    except Exception:
        return False


# IAD_CANONICAL_SAVE_TRABAJO_V1
@router.post("/iad/api/trabajo/guardar_revision.json")
async def iad_api_trabajo_guardar_revision_json(request: Request, db: Session = Depends(get_db)):
    """
    Guardado canónico desde Área de trabajo.

    Objetivo:
    - Guardar una OT visible en /iad/historial.
    - Guardar una muestra visible en /iad/admin/training.
    - Evitar stores paralelos que devuelven 200 OK pero no aparecen en la UI principal.
    """
    from datetime import datetime
    import json
    import traceback
    from sqlalchemy import text as sa_text
    from fastapi.responses import JSONResponse

    def _now_text():
        return datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")

    def _safe_str(value):
        if value is None:
            return ""
        if isinstance(value, (dict, list, tuple)):
            try:
                return json.dumps(value, ensure_ascii=False, default=str)
            except Exception:
                return str(value)
        return str(value)

    def _jsonable(value):
        if value is None:
            return None
        if isinstance(value, str):
            v = value.strip()
            if not v:
                return None
            try:
                return json.loads(v)
            except Exception:
                return value
        return value

    def _json_text(value):
        try:
            return json.dumps(value, ensure_ascii=False, default=str, indent=2)
        except Exception:
            return json.dumps({"raw": str(value)}, ensure_ascii=False, indent=2)

    def _pick(payload: dict, *keys: str):
        lower = {str(k).lower(): k for k in payload.keys()}
        for key in keys:
            if key in payload:
                v = payload.get(key)
            elif key.lower() in lower:
                v = payload.get(lower[key.lower()])
            else:
                continue

            if isinstance(v, list):
                v = "\n".join(_safe_str(x) for x in v if _safe_str(x).strip())
            if v is not None and _safe_str(v).strip():
                return v
        return ""

    def _table_info(table: str):
        rows = db.execute(sa_text(f'PRAGMA table_info("{table}")')).fetchall()
        out = []
        for r in rows:
            # cid, name, type, notnull, dflt_value, pk
            out.append({
                "cid": r[0],
                "name": r[1],
                "type": r[2] or "",
                "notnull": bool(r[3]),
                "default": r[4],
                "pk": bool(r[5]),
            })
        return out

    def _table_exists(table: str) -> bool:
        row = db.execute(
            sa_text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table},
        ).fetchone()
        return bool(row)

    def _default_for_col(name: str, coltype: str):
        n = name.lower()
        t = (coltype or "").lower()

        if n.endswith("_at") or n in {"created_at", "updated_at", "fecha", "fecha_creacion"}:
            return _now_text()
        if n in {"status", "estado"}:
            return "guardada"
        if n in {"source", "origen"}:
            return "trabajo_v2"
        if n in {"modelo", "model"}:
            return "gpt"
        if "json" in n:
            return "{}"
        if "bool" in t:
            return 0
        if "int" in t:
            return 0
        if "float" in t or "real" in t:
            return 0.0
        return ""

    def _insert_dynamic(table: str, base_values: dict, required_ok: bool = True):
        if not _table_exists(table):
            if required_ok:
                raise RuntimeError(f"No existe tabla requerida: {table}")
            return None

        info = _table_info(table)
        cols = []
        vals = {}

        for col in info:
            name = col["name"]
            if col["pk"]:
                continue

            if name in base_values and base_values[name] is not None:
                cols.append(name)
                vals[name] = base_values[name]
                continue

            # matching case-insensitive
            found = None
            for k, v in base_values.items():
                if str(k).lower() == name.lower() and v is not None:
                    found = v
                    break

            if found is not None:
                cols.append(name)
                vals[name] = found
                continue

            if col["notnull"] and col["default"] is None:
                cols.append(name)
                vals[name] = _default_for_col(name, col["type"])

        if not cols:
            raise RuntimeError(f"No hay columnas insertables para {table}")

        quoted_cols = ", ".join(f'"{c}"' for c in cols)
        params = ", ".join(f":{c}" for c in cols)
        sql = f'INSERT INTO "{table}" ({quoted_cols}) VALUES ({params})'
        db.execute(sa_text(sql), vals)
        new_id = db.execute(sa_text("SELECT last_insert_rowid()")).scalar()
        return int(new_id)

    def _next_ot_user_number(user_id: int) -> int:
        if not _table_exists("iad_work_orders"):
            return 1

        cols = [c["name"] for c in _table_info("iad_work_orders")]
        if "ot_user_number" not in cols:
            return 1

        try:
            if "user_id" in cols:
                row = db.execute(
                    sa_text('SELECT MAX(ot_user_number) FROM iad_work_orders WHERE user_id=:uid'),
                    {"uid": user_id},
                ).fetchone()
            else:
                row = db.execute(sa_text('SELECT MAX(ot_user_number) FROM iad_work_orders')).fetchone()
            last = row[0] if row and row[0] is not None else 0
            return int(last) + 1
        except Exception:
            return 1

    def _insert_audit(user_id: int, detail: str):
        if not _table_exists("iad_audit_logs"):
            return
        try:
            base = {
                "user_id": user_id,
                "action": "guardar_revision_canonica",
                "detail": detail,
                "ip": request.client.host if request.client else "",
                "user_agent": request.headers.get("user-agent", ""),
                "created_at": _now_text(),
            }
            _insert_dynamic("iad_audit_logs", base, required_ok=False)
        except Exception:
            # Auditoría no debe romper guardado clínico.
            pass

    try:
        user = require_user(request, db)

        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {"raw_payload": payload}
        else:
            form = await request.form()
            payload = {}
            for key in form.keys():
                vals = form.getlist(key)
                payload[key] = vals if len(vals) > 1 else form.get(key)

        analysis_raw = _pick(
            payload,
            "analysis",
            "analysis_json",
            "analisis",
            "analisis_json",
            "clinical_analysis",
            "revision_json",
        )
        generated_raw = _pick(
            payload,
            "generated",
            "generated_json",
            "generation",
            "generation_json",
            "informe_generado_json",
        )

        analysis = _jsonable(analysis_raw) or {}
        generated = _jsonable(generated_raw) or {}

        if not isinstance(analysis, dict):
            analysis = {"raw": analysis}
        if not isinstance(generated, dict):
            generated = {"raw": generated}

        plantilla_obj = analysis.get("plantilla_sugerida") if isinstance(analysis.get("plantilla_sugerida"), dict) else {}

        texto_dictado = _safe_str(_pick(
            payload,
            "texto_dictado",
            "dictated_text",
            "dictado_original",
            "source_text",
            "raw_text",
            "texto_fuente",
            "input_text",
            "inputText",
            "informacion_principal",
            "main_text",
            "transcription",
            "transcripcion",
            "audio_transcription",
            "audio_transcription_final",
        ))

        plantilla_nombre = _safe_str(_pick(
            payload,
            "plantilla_nombre",
            "template_name",
            "selected_template_name",
            "plantilla",
        ) or plantilla_obj.get("nombre") or generated.get("plantilla_usada", {}).get("nombre") if isinstance(generated.get("plantilla_usada"), dict) else "")

        plantilla_id = _safe_str(_pick(
            payload,
            "plantilla_id",
            "template_id",
            "selected_template_id",
        ) or plantilla_obj.get("id") or generated.get("plantilla_usada", {}).get("id") if isinstance(generated.get("plantilla_usada"), dict) else "")

        hallazgos = _safe_str(_pick(
            payload,
            "hallazgos_detectados",
            "hallazgos_radiologicos",
            "findings",
            "hallazgos",
        ) or analysis.get("hallazgos_radiologicos") or analysis.get("hallazgos_detectados") or "")

        resultado_primario = _safe_str(_pick(
            payload,
            "resultado_primario",
            "primary_result",
            "generated_report",
            "informe_generado",
            "informe_primario",
        ) or generated.get("informe_final") or generated.get("resultado_primario") or "")

        resultado_revisado = _safe_str(_pick(
            payload,
            "resultado_revisado",
            "reviewed_result",
            "final_report",
            "finalReport",
            "informe_final",
            "informe_limpio",
            "clean_report",
            "report",
        ) or resultado_primario)

        modelo = _safe_str(_pick(payload, "modelo", "model", "ai_model") or "gpt")

        if not texto_dictado.strip() and not resultado_revisado.strip():
            return JSONResponse(
                {
                    "ok": False,
                    "error": "No llegó texto dictado ni informe final al endpoint de guardado.",
                    "payload_keys": sorted(list(payload.keys())),
                },
                status_code=422,
            )

        user_id = int(getattr(user, "id", 0) or 0)
        username = _safe_str(getattr(user, "username", ""))

        ot_user_number = _next_ot_user_number(user_id)

        metadata = {
            "payload": payload,
            "analysis": analysis,
            "generated": generated,
            "username": username,
            "user_id": user_id,
            "saved_by_endpoint": "/iad/api/trabajo/guardar_revision.json",
            "saved_by_fix": "IAD_CANONICAL_SAVE_TRABAJO_V1",
            "user_agent": request.headers.get("user-agent", ""),
        }

        now = _now_text()

        work_base = {
            "user_id": user_id,
            "username": username,
            "ot_user_number": ot_user_number,
            "status": "guardada",
            "estado": "guardada",
            "created_at": now,
            "updated_at": now,
            "template_name": plantilla_nombre,
            "plantilla_nombre": plantilla_nombre,
            "selected_template_name": plantilla_nombre,
            "template_id": plantilla_id,
            "plantilla_id": plantilla_id,
            "selected_template_id": plantilla_id,
            "modality": _safe_str(_pick(payload, "modality", "modalidad")),
            "modalidad": _safe_str(_pick(payload, "modality", "modalidad")),
            "input_text": texto_dictado,
            "input_text_initial": texto_dictado,
            "input_text_final": texto_dictado,
            "source_text": texto_dictado,
            "raw_text": texto_dictado,
            "texto_dictado": texto_dictado,
            "dictado_original": texto_dictado,
            "audio_transcription_final": texto_dictado,
            "hallazgos": hallazgos,
            "hallazgos_radiologicos": hallazgos,
            "findings": hallazgos,
            "resultado_primario": resultado_primario,
            "resultado_revisado": resultado_revisado,
            "final_report": resultado_revisado,
            "informe_final": resultado_revisado,
            "report": resultado_revisado,
            "report_text": resultado_revisado,
            "analysis_json": _json_text(analysis),
            "generated_json": _json_text(generated),
            "metadata_json": _json_text(metadata),
            "saved_to_history": 1,
            "saved_to_training": 1,
        }

        ot_id = _insert_dynamic("iad_work_orders", work_base, required_ok=True)

        training_base = {
            "ot_id": ot_id,
            "texto_dictado": texto_dictado,
            "plantilla_nombre": plantilla_nombre,
            "plantilla_id": plantilla_id,
            "hallazgos_detectados": hallazgos,
            "resultado_primario": resultado_primario,
            "resultado_revisado": resultado_revisado,
            "modelo": modelo,
            "metadata_json": _json_text(metadata),
            "created_at": now,
            "updated_at": now,
        }

        sample_id = _insert_dynamic("iad_training_samples", training_base, required_ok=True)

        _insert_audit(
            user_id,
            f"guardado_canonico; ot_id={ot_id}; sample_id={sample_id}; plantilla={plantilla_nombre}; dictado_len={len(texto_dictado)}; resultado_len={len(resultado_revisado)}",
        )

        db.commit()

        return {
            "ok": True,
            "id": sample_id,
            "sample_id": sample_id,
            "training_sample_id": sample_id,
            "ot_id": ot_id,
            "ot_user_number": ot_user_number,
            "historial_sync": {
                "ok": True,
                "ot_id": ot_id,
                "ot_user_number": ot_user_number,
            },
            "saved_to_history": True,
            "saved_to_training": True,
            "message": "Guardado canónico en Historial y Training IA.",
        }

    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass

        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "traceback": traceback.format_exc()[-4000:],
                "saved_by_fix": "IAD_CANONICAL_SAVE_TRABAJO_V1",
            },
            status_code=500,
        )

@router.get("/iad/api/trabajo/historial.json")
def iad_api_trabajo_historial(request: Request, db = Depends(get_db), limit: int = 50):
    from app.services.iad_work_store import list_work_records

    try:
        user = require_user(request, db)
    except PermissionError:
        return {"ok": False, "error": "No autenticado", "items": []}

    username = _iad_username_from_user(user)
    all_users = _iad_is_admin_user(user)

    return {
        "ok": True,
        "items": list_work_records(limit=limit, username=username, all_users=all_users),
    }


@router.get("/iad/api/training/samples.json")
def iad_api_training_samples(request: Request, db = Depends(get_db), limit: int = 50):
    from app.services.iad_work_store import list_training_samples

    try:
        user = require_user(request, db)
    except PermissionError:
        return {"ok": False, "error": "No autenticado", "items": []}

    username = _iad_username_from_user(user)
    all_users = _iad_is_admin_user(user)

    return {
        "ok": True,
        "items": list_training_samples(limit=limit, username=username, all_users=all_users),
    }


# IAD_TRAINING_PAGE_ROUTE_V1
@router.get("/iad/training", response_class=HTMLResponse)
def iad_training_page(request: Request, db = Depends(get_db)):
    try:
        user = require_user(request, db)
    except PermissionError:
        return redirect("/iad/login")

    if getattr(user, "must_change_password", False):
        return redirect("/iad/cambiar-clave")

    return render(
        request,
        "iadictador/training.html",
        {
            "page": "training",
        },
        db,
    )



# IAD_AUDIO_FIRST_ENDPOINTS_V1
from fastapi import File as IAD_AUDIO_File
from fastapi import Form as IAD_AUDIO_Form
from fastapi import UploadFile as IAD_AUDIO_UploadFile


@router.post("/iad/api/audio/componer.json")
async def iad_api_audio_componer_json(
    request: Request,
    audio_files: list[IAD_AUDIO_UploadFile] = IAD_AUDIO_File(...),
    segments_metadata_json: str = IAD_AUDIO_Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    from app.services.ai.tasks.audio_first_flow import compose_endpoint_response

    return await compose_endpoint_response(
        audio_files=audio_files,
        segments_metadata_json=segments_metadata_json,
        username=getattr(user, "username", "") or "",
    )


@router.post("/iad/api/audio/procesar-dictado-completo.json")
async def iad_api_audio_procesar_dictado_completo_json(
    request: Request,
    audio_files: list[IAD_AUDIO_UploadFile] = IAD_AUDIO_File(...),
    segments_metadata_json: str = IAD_AUDIO_Form(""),
    extra_context: str = IAD_AUDIO_Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)

    import os as _iad_audio_os

    flow_mode = (
        _iad_audio_os.getenv("IAD_AUDIO_FLOW_MODE", "v4")
        .strip()
        .lower()
    )

    if flow_mode in {"v4", "core_v4", "clean", "clean_v4"}:
        from app.services.ai.core_v4.web_pipeline import process_web_endpoint_response as process_endpoint_response
    elif flow_mode in {"v3", "clean_v3", "iad_v3"}:
        from app.services.ai.v3.pipeline import process_v3_endpoint_response as process_endpoint_response
    else:
        from app.services.ai.tasks.audio_first_flow import process_endpoint_response

    result = await process_endpoint_response(
        audio_files=audio_files,
        segments_metadata_json=segments_metadata_json,
        extra_context=extra_context,
        username=getattr(user, "username", "") or "",
        db=db,
    )

    if isinstance(result, dict):
        result.setdefault("iad_audio_flow_mode", flow_mode)

        # Trazabilidad explícita para evitar que la UI muestre campos heredados.
        if flow_mode in {"v4", "core_v4", "clean", "clean_v4"}:
            result["metodo"] = "core_v4_audio_rules_template"
            result["iad_audio_flow_mode"] = "v4"
            result["metodo_visible"] = "core_v4_audio_rules_template"

        elif flow_mode in {"v3", "clean_v3", "iad_v3"}:
            result.setdefault("metodo_visible", result.get("metodo") or "iad_v3_clean_parallel")
        else:
            result.setdefault("metodo_visible", result.get("metodo") or "legacy")

    return result

    if flow_mode in {"v3", "clean", "v3_clean", "iad_v3"}:
        from app.services.ai.v3.pipeline import process_v3_endpoint_response as process_endpoint_response
    else:
        from app.services.ai.tasks.audio_first_flow import process_endpoint_response

    result = await process_endpoint_response(
        audio_files=audio_files,
        segments_metadata_json=segments_metadata_json,
        extra_context=extra_context,
        username=getattr(user, "username", "") or "",
        db=db,
    )

    if isinstance(result, dict):
        result.setdefault("iad_audio_flow_mode", flow_mode)

    return result


# IAD_TRAINING_CORRECTIONS_ENDPOINTS_V2
# Endpoints para aprendizaje por correcciones médico-IA.
# Crea tabla bajo demanda: iad_training_corrections.

def _iad_training_v2_username(request):
    try:
        sess = getattr(request, "session", None)
        if isinstance(sess, dict):
            return (
                sess.get("username")
                or sess.get("user")
                or sess.get("usuario")
                or sess.get("email")
                or "unknown"
            )
    except Exception:
        pass
    return "unknown"


def _iad_training_v2_json_dumps(value):
    import json
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _iad_training_v2_dialect(db):
    try:
        return db.bind.dialect.name
    except Exception:
        try:
            return db.get_bind().dialect.name
        except Exception:
            return "unknown"


def _iad_training_v2_ensure_table(db):
    from sqlalchemy import text

    dialect = _iad_training_v2_dialect(db)

    if dialect == "postgresql":
        ddl = """
        CREATE TABLE IF NOT EXISTS iad_training_corrections (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            usuario TEXT,
            template_name TEXT,
            dictado_original TEXT,
            transcripcion TEXT,
            clinical_json TEXT,
            informe_ia TEXT,
            informe_corregido TEXT,
            diferencias_detectadas TEXT,
            modelo_usado TEXT,
            metadata_json TEXT,
            source TEXT
        )
        """
    else:
        ddl = """
        CREATE TABLE IF NOT EXISTS iad_training_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            usuario TEXT,
            template_name TEXT,
            dictado_original TEXT,
            transcripcion TEXT,
            clinical_json TEXT,
            informe_ia TEXT,
            informe_corregido TEXT,
            diferencias_detectadas TEXT,
            modelo_usado TEXT,
            metadata_json TEXT,
            source TEXT
        )
        """

    db.execute(text(ddl))
    try:
        db.commit()
    except Exception:
        pass


def _iad_training_v2_diff(informe_ia, informe_corregido):
    import difflib

    a = (informe_ia or "").splitlines()
    b = (informe_corregido or "").splitlines()

    diff = difflib.unified_diff(
        a,
        b,
        fromfile="informe_ia",
        tofile="informe_corregido",
        lineterm=""
    )

    return "\n".join(list(diff)[:500])


@router.post("/iad/api/training/corrections/save.json")
async def iad_training_corrections_save_v2(request: Request, db = Depends(get_db)):
    from sqlalchemy import text

    _iad_training_v2_ensure_table(db)

    payload = await request.json()

    usuario = _iad_training_v2_username(request)
    template_name = payload.get("template_name") or payload.get("plantilla_nombre") or ""
    dictado_original = payload.get("dictado_original") or payload.get("source_text") or ""
    transcripcion = payload.get("transcripcion") or payload.get("transcription") or ""
    clinical_json = payload.get("clinical_json") or payload.get("hallazgos_estructurados") or {}
    informe_ia = payload.get("informe_ia") or payload.get("model_report") or ""
    informe_corregido = payload.get("informe_corregido") or payload.get("corrected_report") or ""
    modelo_usado = payload.get("modelo_usado") or payload.get("model") or ""
    source = payload.get("source") or "work_v2_final_report_button"

    if not str(informe_corregido or "").strip():
        return {"ok": False, "error": "informe_corregido vacío"}

    diferencias_detectadas = _iad_training_v2_diff(informe_ia, informe_corregido)

    metadata = dict(payload)
    metadata.pop("informe_corregido", None)
    metadata.pop("corrected_report", None)

    sql = text("""
        INSERT INTO iad_training_corrections (
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
            source
        )
        VALUES (
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
            :source
        )
    """)

    db.execute(sql, {
        "usuario": usuario,
        "template_name": template_name,
        "dictado_original": dictado_original,
        "transcripcion": transcripcion,
        "clinical_json": _iad_training_v2_json_dumps(clinical_json),
        "informe_ia": informe_ia,
        "informe_corregido": informe_corregido,
        "diferencias_detectadas": diferencias_detectadas,
        "modelo_usado": modelo_usado,
        "metadata_json": _iad_training_v2_json_dumps(metadata),
        "source": source,
    })

    db.commit()

    return {
        "ok": True,
        "message": "Corrección guardada para Training IA",
        "template_name": template_name,
        "diff_lines": len(diferencias_detectadas.splitlines()) if diferencias_detectadas else 0
    }


@router.get("/iad/api/training/corrections/list.json")
def iad_training_corrections_list_v2(limit: int = 50, db = Depends(get_db)):
    from sqlalchemy import text

    _iad_training_v2_ensure_table(db)

    limit = max(1, min(int(limit or 50), 200))

    rows = db.execute(text("""
        SELECT
            id,
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
            source
        FROM iad_training_corrections
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()

    items = []
    for r in rows:
        items.append({
            "id": r[0],
            "created_at": str(r[1]),
            "usuario": r[2],
            "template_name": r[3],
            "dictado_original": r[4],
            "transcripcion": r[5],
            "clinical_json": r[6],
            "informe_ia": r[7],
            "informe_corregido": r[8],
            "diferencias_detectadas": r[9],
            "modelo_usado": r[10],
            "metadata_json": r[11],
            "source": r[12],
        })

    return {"ok": True, "count": len(items), "items": items}


@router.get("/iad/api/training/corrections/export.jsonl")
def iad_training_corrections_export_v2(db = Depends(get_db)):
    from sqlalchemy import text
    from fastapi.responses import Response
    import json

    _iad_training_v2_ensure_table(db)

    rows = db.execute(text("""
        SELECT
            id,
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
            source
        FROM iad_training_corrections
        ORDER BY id ASC
    """)).fetchall()

    lines = []
    for r in rows:
        obj = {
            "id": r[0],
            "created_at": str(r[1]),
            "usuario": r[2],
            "template_name": r[3],
            "dictado_original": r[4],
            "transcripcion": r[5],
            "clinical_json": r[6],
            "informe_ia": r[7],
            "informe_corregido": r[8],
            "diferencias_detectadas": r[9],
            "modelo_usado": r[10],
            "metadata_json": r[11],
            "source": r[12],
        }
        lines.append(json.dumps(obj, ensure_ascii=False, default=str))

    body = "\n".join(lines) + ("\n" if lines else "")

    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=iad_training_corrections.jsonl"}
    )


# IAD_VALIDATION_SAVE_HISTORY_TRAINING_V3
# Restaura circuito operacional:
# Guardar validación -> historial + Training IA.

def _iad_validation_v3_username(request):
    try:
        sess = getattr(request, "session", None)
        if isinstance(sess, dict):
            return (
                sess.get("username")
                or sess.get("user")
                or sess.get("usuario")
                or sess.get("email")
                or "unknown"
            )
    except Exception:
        pass
    return "unknown"


def _iad_validation_v3_json_dumps(value):
    import json
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _iad_validation_v3_dialect(db):
    try:
        return db.bind.dialect.name
    except Exception:
        try:
            return db.get_bind().dialect.name
        except Exception:
            return "unknown"


def _iad_validation_v3_ensure_tables(db):
    from sqlalchemy import text

    dialect = _iad_validation_v3_dialect(db)

    if dialect == "postgresql":
        training_ddl = """
        CREATE TABLE IF NOT EXISTS iad_training_corrections (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            usuario TEXT,
            template_name TEXT,
            dictado_original TEXT,
            transcripcion TEXT,
            clinical_json TEXT,
            informe_ia TEXT,
            informe_corregido TEXT,
            diferencias_detectadas TEXT,
            modelo_usado TEXT,
            metadata_json TEXT,
            source TEXT
        )
        """

        validation_ddl = """
        CREATE TABLE IF NOT EXISTS iad_validation_history (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            usuario TEXT,
            template_name TEXT,
            dictado_original TEXT,
            transcripcion TEXT,
            clinical_json TEXT,
            informe_ia TEXT,
            informe_validado TEXT,
            diferencias_detectadas TEXT,
            modelo_usado TEXT,
            metadata_json TEXT,
            source TEXT,
            estado TEXT
        )
        """
    else:
        training_ddl = """
        CREATE TABLE IF NOT EXISTS iad_training_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            usuario TEXT,
            template_name TEXT,
            dictado_original TEXT,
            transcripcion TEXT,
            clinical_json TEXT,
            informe_ia TEXT,
            informe_corregido TEXT,
            diferencias_detectadas TEXT,
            modelo_usado TEXT,
            metadata_json TEXT,
            source TEXT
        )
        """

        validation_ddl = """
        CREATE TABLE IF NOT EXISTS iad_validation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            usuario TEXT,
            template_name TEXT,
            dictado_original TEXT,
            transcripcion TEXT,
            clinical_json TEXT,
            informe_ia TEXT,
            informe_validado TEXT,
            diferencias_detectadas TEXT,
            modelo_usado TEXT,
            metadata_json TEXT,
            source TEXT,
            estado TEXT
        )
        """

    db.execute(text(training_ddl))
    db.execute(text(validation_ddl))
    try:
        db.commit()
    except Exception:
        pass


def _iad_validation_v3_diff(informe_ia, informe_validado):
    import difflib

    a = (informe_ia or "").splitlines()
    b = (informe_validado or "").splitlines()

    diff = difflib.unified_diff(
        a,
        b,
        fromfile="informe_ia",
        tofile="informe_validado",
        lineterm=""
    )

    return "\n".join(list(diff)[:700])


@router.post("/iad/api/validacion/guardar.json")
async def iad_validacion_guardar_v3(request: Request, db = Depends(get_db)):
    from sqlalchemy import text

    _iad_validation_v3_ensure_tables(db)

    payload = await request.json()

    usuario = _iad_validation_v3_username(request)
    template_name = payload.get("template_name") or payload.get("plantilla_nombre") or ""
    dictado_original = payload.get("dictado_original") or payload.get("source_text") or ""
    transcripcion = payload.get("transcripcion") or payload.get("transcription") or ""
    clinical_json = payload.get("clinical_json") or payload.get("hallazgos_estructurados") or {}
    informe_ia = payload.get("informe_ia") or payload.get("model_report") or ""
    informe_validado = (
        payload.get("informe_validado")
        or payload.get("informe_corregido")
        or payload.get("corrected_report")
        or payload.get("final_report")
        or ""
    )
    modelo_usado = payload.get("modelo_usado") or payload.get("model") or ""
    source = payload.get("source") or "work_v2_guardar_validacion_v3"
    estado = payload.get("estado") or "validado"

    if not str(informe_validado or "").strip():
        return {"ok": False, "error": "informe_validado vacío"}

    diferencias_detectadas = _iad_validation_v3_diff(informe_ia, informe_validado)

    metadata = dict(payload)
    for k in ["informe_validado", "informe_corregido", "corrected_report", "final_report"]:
        metadata.pop(k, None)

    # 1) Guardar en Training IA.
    db.execute(text("""
        INSERT INTO iad_training_corrections (
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
            source
        )
        VALUES (
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
            :source
        )
    """), {
        "usuario": usuario,
        "template_name": template_name,
        "dictado_original": dictado_original,
        "transcripcion": transcripcion,
        "clinical_json": _iad_validation_v3_json_dumps(clinical_json),
        "informe_ia": informe_ia,
        "informe_corregido": informe_validado,
        "diferencias_detectadas": diferencias_detectadas,
        "modelo_usado": modelo_usado,
        "metadata_json": _iad_validation_v3_json_dumps(metadata),
        "source": source,
    })

    # 2) Guardar en historial de validaciones.
    db.execute(text("""
        INSERT INTO iad_validation_history (
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
            estado
        )
        VALUES (
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
            :estado
        )
    """), {
        "usuario": usuario,
        "template_name": template_name,
        "dictado_original": dictado_original,
        "transcripcion": transcripcion,
        "clinical_json": _iad_validation_v3_json_dumps(clinical_json),
        "informe_ia": informe_ia,
        "informe_validado": informe_validado,
        "diferencias_detectadas": diferencias_detectadas,
        "modelo_usado": modelo_usado,
        "metadata_json": _iad_validation_v3_json_dumps(metadata),
        "source": source,
        "estado": estado,
    })

    db.commit()

    return {
        "ok": True,
        "message": "Validación guardada en historial y Training IA",
        "saved_training": True,
        "saved_history": True,
        "template_name": template_name,
        "estado": estado,
        "diff_lines": len(diferencias_detectadas.splitlines()) if diferencias_detectadas else 0
    }


@router.get("/iad/api/validacion/historial.json")
def iad_validacion_historial_v3(limit: int = 50, db = Depends(get_db)):
    from sqlalchemy import text

    _iad_validation_v3_ensure_tables(db)

    limit = max(1, min(int(limit or 50), 200))

    rows = db.execute(text("""
        SELECT
            id,
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
            estado
        FROM iad_validation_history
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()

    items = []
    for r in rows:
        items.append({
            "id": r[0],
            "created_at": str(r[1]),
            "usuario": r[2],
            "template_name": r[3],
            "dictado_original": r[4],
            "transcripcion": r[5],
            "clinical_json": r[6],
            "informe_ia": r[7],
            "informe_validado": r[8],
            "diferencias_detectadas": r[9],
            "modelo_usado": r[10],
            "metadata_json": r[11],
            "source": r[12],
            "estado": r[13],
        })

    return {"ok": True, "count": len(items), "items": items}


@router.get("/iad/api/validacion/historial/export.jsonl")
def iad_validacion_historial_export_v3(db = Depends(get_db)):
    from sqlalchemy import text
    from fastapi.responses import Response
    import json

    _iad_validation_v3_ensure_tables(db)

    rows = db.execute(text("""
        SELECT
            id,
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
            estado
        FROM iad_validation_history
        ORDER BY id ASC
    """)).fetchall()

    lines = []
    for r in rows:
        obj = {
            "id": r[0],
            "created_at": str(r[1]),
            "usuario": r[2],
            "template_name": r[3],
            "dictado_original": r[4],
            "transcripcion": r[5],
            "clinical_json": r[6],
            "informe_ia": r[7],
            "informe_validado": r[8],
            "diferencias_detectadas": r[9],
            "modelo_usado": r[10],
            "metadata_json": r[11],
            "source": r[12],
            "estado": r[13],
        }
        lines.append(json.dumps(obj, ensure_ascii=False, default=str))

    body = "\n".join(lines) + ("\n" if lines else "")

    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=iad_validation_history.jsonl"}
    )


# IAD_VALIDATION_OT_SYNC_V4
# Integra validaciones nuevas con OT antigua.
# - Agrega columna ot_id si falta en tablas nuevas.
# - Guarda validación vinculada a OT.
# - Expone último informe validado por OT para rellenar /iad/ot/{id}.
# - Actualiza WorkOrder de forma defensiva si existen campos compatibles.

def _iad_v4_json_dumps(value):
    import json
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _iad_v4_username(request):
    try:
        sess = getattr(request, "session", None)
        if isinstance(sess, dict):
            return sess.get("username") or sess.get("user") or sess.get("usuario") or sess.get("email") or "unknown"
    except Exception:
        pass
    return "unknown"


def _iad_v4_diff(a, b):
    import difflib
    a = (a or "").splitlines()
    b = (b or "").splitlines()
    return "\n".join(list(difflib.unified_diff(a, b, fromfile="informe_ia", tofile="informe_validado", lineterm=""))[:700])


def _iad_v4_table_columns(db, table_name):
    from sqlalchemy import text

    try:
        dialect = db.bind.dialect.name
    except Exception:
        dialect = "unknown"

    cols = []

    try:
        if dialect == "postgresql":
            rows = db.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :t
                ORDER BY ordinal_position
            """), {"t": table_name}).fetchall()
            cols = [r[0] for r in rows]
        else:
            rows = db.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            cols = [r[1] for r in rows]
    except Exception:
        cols = []

    return cols


def _iad_v4_ensure_tables_and_ot_id(db):
    from sqlalchemy import text

    # Asegurar tablas base si existe la función V3.
    try:
        _iad_validation_v3_ensure_tables(db)
    except Exception:
        # Fallback mínimo SQLite/Postgres.
        try:
            dialect = db.bind.dialect.name
        except Exception:
            dialect = "unknown"

        pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"

        db.execute(text(f"""
            CREATE TABLE IF NOT EXISTS iad_training_corrections (
                id {pk},
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                usuario TEXT,
                template_name TEXT,
                dictado_original TEXT,
                transcripcion TEXT,
                clinical_json TEXT,
                informe_ia TEXT,
                informe_corregido TEXT,
                diferencias_detectadas TEXT,
                modelo_usado TEXT,
                metadata_json TEXT,
                source TEXT
            )
        """))

        db.execute(text(f"""
            CREATE TABLE IF NOT EXISTS iad_validation_history (
                id {pk},
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                usuario TEXT,
                template_name TEXT,
                dictado_original TEXT,
                transcripcion TEXT,
                clinical_json TEXT,
                informe_ia TEXT,
                informe_validado TEXT,
                diferencias_detectadas TEXT,
                modelo_usado TEXT,
                metadata_json TEXT,
                source TEXT,
                estado TEXT
            )
        """))

    for table in ["iad_training_corrections", "iad_validation_history"]:
        cols = _iad_v4_table_columns(db, table)
        if "ot_id" not in cols:
            try:
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN ot_id INTEGER"))
            except Exception:
                pass

    try:
        db.commit()
    except Exception:
        pass


def _iad_v4_int_or_none(value):
    try:
        if value in (None, "", "null", "undefined"):
            return None
        return int(value)
    except Exception:
        return None


def _iad_v4_update_workorder_if_possible(db, ot_id, informe_validado, informe_ia="", metadata=None):
    if not ot_id or not str(informe_validado or "").strip():
        return {"updated": False, "reason": "sin ot_id o informe"}

    try:
        ot = db.query(WorkOrder).filter(WorkOrder.id == int(ot_id)).first()
    except Exception as e:
        return {"updated": False, "reason": "no query WorkOrder", "error": str(e)}

    if not ot:
        return {"updated": False, "reason": "OT no encontrada"}

    mapper_cols = set()
    try:
        mapper_cols = {c.key for c in WorkOrder.__mapper__.columns}
    except Exception:
        mapper_cols = set()

    updated_fields = []

    # Campos candidatos para resultado/informe final.
    result_candidates = [
        "resultado",
        "resultado_final",
        "informe_final",
        "final_report",
        "report",
        "output_text",
        "resultado_revisado",
        "texto_resultado",
    ]

    # Campos candidatos para revisión.
    review_candidates = [
        "revision",
        "revisión",
        "revision_text",
        "texto_revision",
        "review",
        "review_text",
    ]

    for name in result_candidates:
        if name in mapper_cols and hasattr(ot, name):
            try:
                setattr(ot, name, informe_validado)
                updated_fields.append(name)
            except Exception:
                pass

    # Si hay revisión separada, guardar diff o IA original.
    review_text = ""
    if informe_ia and informe_ia != informe_validado:
        review_text = _iad_v4_diff(informe_ia, informe_validado)
    elif metadata:
        review_text = _iad_v4_json_dumps(metadata)

    if review_text:
        for name in review_candidates:
            if name in mapper_cols and hasattr(ot, name):
                try:
                    setattr(ot, name, review_text)
                    updated_fields.append(name)
                except Exception:
                    pass

    # Estado.
    for name in ["estado", "status", "state"]:
        if name in mapper_cols and hasattr(ot, name):
            try:
                setattr(ot, name, "validada")
                updated_fields.append(name)
                break
            except Exception:
                pass

    # Timestamps posibles.
    import datetime
    now = datetime.datetime.utcnow()

    for name in ["updated_at", "actualizado_en", "validated_at", "validado_en"]:
        if name in mapper_cols and hasattr(ot, name):
            try:
                setattr(ot, name, now)
                updated_fields.append(name)
            except Exception:
                pass

    try:
        db.add(ot)
        db.commit()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return {"updated": False, "reason": "commit falló", "error": str(e), "fields": updated_fields}

    return {
        "updated": bool(updated_fields),
        "fields": updated_fields,
        "mapper_cols": sorted(list(mapper_cols)),
    }


def _iad_v4_insert_validation_and_training(db, request, payload):
    from sqlalchemy import text

    _iad_v4_ensure_tables_and_ot_id(db)

    usuario = _iad_v4_username(request)
    ot_id = _iad_v4_int_or_none(payload.get("ot_id") or payload.get("work_order_id") or payload.get("orden_id"))

    template_name = payload.get("template_name") or payload.get("plantilla_nombre") or ""
    dictado_original = payload.get("dictado_original") or payload.get("source_text") or ""
    transcripcion = payload.get("transcripcion") or payload.get("transcription") or ""
    clinical_json = payload.get("clinical_json") or payload.get("hallazgos_estructurados") or {}
    informe_ia = payload.get("informe_ia") or payload.get("model_report") or ""
    informe_validado = (
        payload.get("informe_validado")
        or payload.get("informe_corregido")
        or payload.get("corrected_report")
        or payload.get("final_report")
        or ""
    )
    modelo_usado = payload.get("modelo_usado") or payload.get("model") or ""
    source = payload.get("source") or "work_v2_guardar_validacion_v4"
    estado = payload.get("estado") or "validado"

    if not str(informe_validado or "").strip():
        return {"ok": False, "error": "informe_validado vacío"}

    diff = _iad_v4_diff(informe_ia, informe_validado)

    metadata = dict(payload)
    for k in ["informe_validado", "informe_corregido", "corrected_report", "final_report"]:
        metadata.pop(k, None)

    # INSERT dinámico compatible con tablas que acaban de recibir ot_id.
    db.execute(text("""
        INSERT INTO iad_training_corrections (
            ot_id,
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
            source
        )
        VALUES (
            :ot_id,
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
            :source
        )
    """), {
        "ot_id": ot_id,
        "usuario": usuario,
        "template_name": template_name,
        "dictado_original": dictado_original,
        "transcripcion": transcripcion,
        "clinical_json": _iad_v4_json_dumps(clinical_json),
        "informe_ia": informe_ia,
        "informe_corregido": informe_validado,
        "diferencias_detectadas": diff,
        "modelo_usado": modelo_usado,
        "metadata_json": _iad_v4_json_dumps(metadata),
        "source": source,
    })

    db.execute(text("""
        INSERT INTO iad_validation_history (
            ot_id,
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
            estado
        )
        VALUES (
            :ot_id,
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
            :estado
        )
    """), {
        "ot_id": ot_id,
        "usuario": usuario,
        "template_name": template_name,
        "dictado_original": dictado_original,
        "transcripcion": transcripcion,
        "clinical_json": _iad_v4_json_dumps(clinical_json),
        "informe_ia": informe_ia,
        "informe_validado": informe_validado,
        "diferencias_detectadas": diff,
        "modelo_usado": modelo_usado,
        "metadata_json": _iad_v4_json_dumps(metadata),
        "source": source,
        "estado": estado,
    })

    db.commit()

    ot_sync = _iad_v4_update_workorder_if_possible(
        db,
        ot_id,
        informe_validado,
        informe_ia=informe_ia,
        metadata=metadata,
    )

    return {
        "ok": True,
        "message": "Validación guardada en historial, Training IA y OT si corresponde",
        "saved_training": True,
        "saved_history": True,
        "ot_id": ot_id,
        "ot_sync": ot_sync,
        "template_name": template_name,
        "estado": estado,
        "diff_lines": len(diff.splitlines()) if diff else 0,
    }


@router.post("/iad/api/validacion/guardar-v4.json")
async def iad_validacion_guardar_v4(request: Request, db = Depends(get_db)):
    payload = await request.json()
    return _iad_v4_insert_validation_and_training(db, request, payload)


@router.get("/iad/api/validacion/ot/{ot_id}/latest.json")
def iad_validacion_ot_latest_v4(ot_id: int, db = Depends(get_db)):
    from sqlalchemy import text

    _iad_v4_ensure_tables_and_ot_id(db)

    rows = db.execute(text("""
        SELECT
            id,
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
        FROM iad_validation_history
        WHERE ot_id = :ot_id
        ORDER BY id DESC
        LIMIT 1
    """), {"ot_id": ot_id}).fetchall()

    if not rows:
        return {"ok": True, "found": False, "ot_id": ot_id}

    r = rows[0]
    return {
        "ok": True,
        "found": True,
        "item": {
            "id": r[0],
            "created_at": str(r[1]),
            "usuario": r[2],
            "template_name": r[3],
            "dictado_original": r[4],
            "transcripcion": r[5],
            "clinical_json": r[6],
            "informe_ia": r[7],
            "informe_validado": r[8],
            "diferencias_detectadas": r[9],
            "modelo_usado": r[10],
            "metadata_json": r[11],
            "source": r[12],
            "estado": r[13],
            "ot_id": r[14],
        },
    }


@router.get("/iad/api/validacion/historial-v4.json")
def iad_validacion_historial_v4(limit: int = 50, db = Depends(get_db)):
    from sqlalchemy import text

    _iad_v4_ensure_tables_and_ot_id(db)

    limit = max(1, min(int(limit or 50), 200))

    rows = db.execute(text("""
        SELECT
            id,
            created_at,
            usuario,
            template_name,
            informe_validado,
            modelo_usado,
            source,
            estado,
            ot_id
        FROM iad_validation_history
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()

    items = []
    for r in rows:
        items.append({
            "id": r[0],
            "created_at": str(r[1]),
            "usuario": r[2],
            "template_name": r[3],
            "informe_validado": r[4],
            "modelo_usado": r[5],
            "source": r[6],
            "estado": r[7],
            "ot_id": r[8],
        })

    return {"ok": True, "count": len(items), "items": items}


# IAD_VALIDATION_OT_SYNC_V5
# Versión corregida: escribe campos reales de WorkOrder:
# review_report, final_report_initial, final_report_accepted, final_report_diff, status, validated_at.

def _iad_v5_json_dumps(value):
    import json
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _iad_v5_username(request):
    try:
        sess = getattr(request, "session", None)
        if isinstance(sess, dict):
            return sess.get("username") or sess.get("user") or sess.get("usuario") or sess.get("email") or "unknown"
    except Exception:
        pass
    return "unknown"


def _iad_v5_int(value):
    try:
        if value in (None, "", "null", "undefined"):
            return None
        return int(value)
    except Exception:
        return None


def _iad_v5_diff(a, b):
    import difflib
    a = (a or "").splitlines()
    b = (b or "").splitlines()
    return "\n".join(list(difflib.unified_diff(a, b, fromfile="informe_ia", tofile="informe_validado", lineterm=""))[:700])


def _iad_v5_ensure_tables(db):
    from sqlalchemy import text

    try:
        _iad_v4_ensure_tables_and_ot_id(db)
        return
    except Exception:
        pass

    try:
        dialect = db.bind.dialect.name
    except Exception:
        dialect = "unknown"

    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"

    db.execute(text(f"""
        CREATE TABLE IF NOT EXISTS iad_training_corrections (
            id {pk},
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ot_id INTEGER,
            usuario TEXT,
            template_name TEXT,
            dictado_original TEXT,
            transcripcion TEXT,
            clinical_json TEXT,
            informe_ia TEXT,
            informe_corregido TEXT,
            diferencias_detectadas TEXT,
            modelo_usado TEXT,
            metadata_json TEXT,
            source TEXT
        )
    """))

    db.execute(text(f"""
        CREATE TABLE IF NOT EXISTS iad_validation_history (
            id {pk},
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ot_id INTEGER,
            usuario TEXT,
            template_name TEXT,
            dictado_original TEXT,
            transcripcion TEXT,
            clinical_json TEXT,
            informe_ia TEXT,
            informe_validado TEXT,
            diferencias_detectadas TEXT,
            modelo_usado TEXT,
            metadata_json TEXT,
            source TEXT,
            estado TEXT
        )
    """))

    try:
        db.commit()
    except Exception:
        pass


def _iad_v5_update_workorder(db, ot_id, informe_validado, informe_ia, diff):
    if not ot_id:
        return {"updated": False, "reason": "sin ot_id"}

    try:
        ot = db.query(WorkOrder).filter(WorkOrder.id == int(ot_id)).first()
    except Exception as e:
        return {"updated": False, "reason": "query WorkOrder falló", "error": str(e)}

    if not ot:
        return {"updated": False, "reason": "OT no encontrada"}

    import datetime
    now = datetime.datetime.utcnow()
    fields = []

    try:
        ot.final_report_accepted = informe_validado
        fields.append("final_report_accepted")
    except Exception:
        pass

    try:
        if not getattr(ot, "final_report_initial", None):
            ot.final_report_initial = informe_ia or informe_validado
            fields.append("final_report_initial")
    except Exception:
        pass

    try:
        ot.final_report_diff = diff or ""
        fields.append("final_report_diff")
    except Exception:
        pass

    try:
        ot.review_report = diff or ""
        fields.append("review_report")
    except Exception:
        pass

    try:
        ot.status = "guardada"
        fields.append("status")
    except Exception:
        pass

    try:
        ot.validated_at = now
        fields.append("validated_at")
    except Exception:
        pass

    try:
        ot.updated_at = now
        fields.append("updated_at")
    except Exception:
        pass

    try:
        db.add(ot)
        db.commit()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return {"updated": False, "reason": "commit WorkOrder falló", "error": str(e), "fields": fields}

    return {"updated": True, "fields": fields, "ot_id": ot_id}


def _iad_v5_insert_history_training(db, request, payload):
    from sqlalchemy import text

    _iad_v5_ensure_tables(db)

    usuario = _iad_v5_username(request)
    ot_id = _iad_v5_int(payload.get("ot_id") or payload.get("work_order_id") or payload.get("orden_id"))

    template_name = payload.get("template_name") or payload.get("plantilla_nombre") or ""
    dictado_original = payload.get("dictado_original") or payload.get("source_text") or ""
    transcripcion = payload.get("transcripcion") or payload.get("transcription") or ""
    clinical_json = payload.get("clinical_json") or payload.get("hallazgos_estructurados") or {}
    informe_ia = payload.get("informe_ia") or payload.get("model_report") or ""
    informe_validado = (
        payload.get("informe_validado")
        or payload.get("informe_corregido")
        or payload.get("corrected_report")
        or payload.get("final_report")
        or ""
    )
    modelo_usado = payload.get("modelo_usado") or payload.get("model") or ""
    source = payload.get("source") or "work_or_ot_guardar_validacion_v5"
    estado = payload.get("estado") or "validado"

    if not str(informe_validado or "").strip():
        return {"ok": False, "error": "informe_validado vacío"}

    diff = _iad_v5_diff(informe_ia, informe_validado)

    metadata = dict(payload)
    for k in ["informe_validado", "informe_corregido", "corrected_report", "final_report"]:
        metadata.pop(k, None)

    db.execute(text("""
        INSERT INTO iad_training_corrections (
            ot_id,
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
            source
        )
        VALUES (
            :ot_id,
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
            :source
        )
    """), {
        "ot_id": ot_id,
        "usuario": usuario,
        "template_name": template_name,
        "dictado_original": dictado_original,
        "transcripcion": transcripcion,
        "clinical_json": _iad_v5_json_dumps(clinical_json),
        "informe_ia": informe_ia,
        "informe_corregido": informe_validado,
        "diferencias_detectadas": diff,
        "modelo_usado": modelo_usado,
        "metadata_json": _iad_v5_json_dumps(metadata),
        "source": source,
    })

    db.execute(text("""
        INSERT INTO iad_validation_history (
            ot_id,
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
            estado
        )
        VALUES (
            :ot_id,
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
            :estado
        )
    """), {
        "ot_id": ot_id,
        "usuario": usuario,
        "template_name": template_name,
        "dictado_original": dictado_original,
        "transcripcion": transcripcion,
        "clinical_json": _iad_v5_json_dumps(clinical_json),
        "informe_ia": informe_ia,
        "informe_validado": informe_validado,
        "diferencias_detectadas": diff,
        "modelo_usado": modelo_usado,
        "metadata_json": _iad_v5_json_dumps(metadata),
        "source": source,
        "estado": estado,
    })

    db.commit()

    ot_sync = _iad_v5_update_workorder(db, ot_id, informe_validado, informe_ia, diff)

    return {
        "ok": True,
        "message": "Validación guardada",
        "saved_training": True,
        "saved_history": True,
        "saved_workorder": bool(ot_sync.get("updated")),
        "ot_id": ot_id,
        "ot_sync": ot_sync,
        "template_name": template_name,
        "estado": estado,
        "diff_lines": len(diff.splitlines()) if diff else 0,
    }


@router.post("/iad/api/validacion/guardar-v5.json")
async def iad_validacion_guardar_v5(request: Request, db = Depends(get_db)):
    payload = await request.json()
    return _iad_v5_insert_history_training(db, request, payload)


@router.get("/iad/api/validacion/ot/{ot_id}/latest-v5.json")
def iad_validacion_ot_latest_v5(ot_id: int, db = Depends(get_db)):
    from sqlalchemy import text

    _iad_v5_ensure_tables(db)

    row = db.execute(text("""
        SELECT
            id,
            created_at,
            usuario,
            template_name,
            informe_ia,
            informe_validado,
            diferencias_detectadas,
            modelo_usado,
            source,
            estado,
            ot_id
        FROM iad_validation_history
        WHERE ot_id = :ot_id
        ORDER BY id DESC
        LIMIT 1
    """), {"ot_id": ot_id}).fetchone()

    if not row:
        # Fallback: leer WorkOrder directo.
        try:
            ot = db.query(WorkOrder).filter(WorkOrder.id == int(ot_id)).first()
            if ot and (ot.final_report_accepted or ot.review_report):
                return {
                    "ok": True,
                    "found": True,
                    "source": "workorder",
                    "item": {
                        "ot_id": ot_id,
                        "informe_ia": ot.final_report_initial or "",
                        "informe_validado": ot.final_report_accepted or "",
                        "diferencias_detectadas": ot.final_report_diff or ot.review_report or "",
                        "template_name": "",
                        "estado": getattr(ot, "status", "") or "",
                    },
                }
        except Exception:
            pass

        return {"ok": True, "found": False, "ot_id": ot_id}

    return {
        "ok": True,
        "found": True,
        "source": "validation_history",
        "item": {
            "id": row[0],
            "created_at": str(row[1]),
            "usuario": row[2],
            "template_name": row[3],
            "informe_ia": row[4],
            "informe_validado": row[5],
            "diferencias_detectadas": row[6],
            "modelo_usado": row[7],
            "source": row[8],
            "estado": row[9],
            "ot_id": row[10],
        },
    }


# IAD_CLEAN_HISTORY_TRAINING_ENDPOINTS_V1
# Endpoints limpios para reconstruir Historial y Training IA sin paneles contaminantes.

def _iad_clean_json_loads_v1(value, fallback=None):
    import json
    if fallback is None:
        fallback = {}
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _iad_clean_text_v1(value):
    if value is None:
        return ""
    return str(value)


def _iad_clean_dt_v1(value):
    if value is None:
        return ""
    try:
        return value.isoformat(sep=" ", timespec="seconds")
    except Exception:
        return str(value)


def _iad_clean_getattr_v1(obj, names, default=""):
    for name in names:
        try:
            if hasattr(obj, name):
                v = getattr(obj, name)
                if v not in (None, ""):
                    return v
        except Exception:
            pass
    return default


def _iad_clean_workorder_item_v1(ot):
    oid = _iad_clean_getattr_v1(ot, ["id"], "")
    created = _iad_clean_getattr_v1(ot, ["created_at", "timestamp", "created", "fecha", "fecha_creacion"], "")
    updated = _iad_clean_getattr_v1(ot, ["updated_at", "validated_at", "validado_en", "actualizado_en"], "")

    initial = _iad_clean_getattr_v1(ot, ["final_report_initial", "informe_ia", "resultado_inicial", "resultado_ia"], "")
    accepted = _iad_clean_getattr_v1(ot, ["final_report_accepted", "final_report", "resultado_final", "resultado", "informe_final"], "")
    review = _iad_clean_getattr_v1(ot, ["review_report", "final_report_diff", "revision", "revisión", "review"], "")

    return {
        "id": oid,
        "ot_id": oid,
        "usuario": _iad_clean_text_v1(_iad_clean_getattr_v1(ot, ["username", "usuario", "user", "created_by", "user_id"], "")),
        "created_at": _iad_clean_dt_v1(created),
        "updated_at": _iad_clean_dt_v1(updated),
        "tipo": _iad_clean_text_v1(_iad_clean_getattr_v1(ot, ["tipo", "type", "study_type", "exam_type"], "")),
        "modalidad": _iad_clean_text_v1(_iad_clean_getattr_v1(ot, ["modalidad", "modality"], "")),
        "titulo": _iad_clean_text_v1(_iad_clean_getattr_v1(ot, ["titulo", "title", "study_title"], "")),
        "paciente": _iad_clean_text_v1(_iad_clean_getattr_v1(ot, ["paciente", "patient", "patient_name", "nombre_paciente"], "")),
        "edad": _iad_clean_text_v1(_iad_clean_getattr_v1(ot, ["edad", "age", "patient_age"], "")),
        "estado": _iad_clean_text_v1(_iad_clean_getattr_v1(ot, ["status", "estado", "state"], "")),
        "plantilla": _iad_clean_text_v1(_iad_clean_getattr_v1(ot, ["template_name", "plantilla_nombre", "template", "plantilla"], "")),
        "has_initial_report": bool(str(initial or "").strip()),
        "has_final_report": bool(str(accepted or "").strip()),
        "has_review": bool(str(review or "").strip()),
        "open_url": f"/iad/ot/{oid}",
    }


@router.get("/iad/api/history/ots-clean.json")
def iad_history_ots_clean_v1(limit: int = 300, db = Depends(get_db)):
    limit = max(1, min(int(limit or 300), 1000))

    try:
        rows = db.query(WorkOrder).order_by(WorkOrder.id.desc()).limit(limit).all()
    except Exception as e:
        return {"ok": False, "error": str(e), "items": [], "count": 0}

    items = [_iad_clean_workorder_item_v1(ot) for ot in rows]

    return {
        "ok": True,
        "count": len(items),
        "items": items,
    }


@router.get("/iad/api/history/ot/{ot_id}/clean.json")
def iad_history_ot_clean_v1(ot_id: int, db = Depends(get_db)):
    try:
        ot = db.query(WorkOrder).filter(WorkOrder.id == int(ot_id)).first()
    except Exception as e:
        return {"ok": False, "error": str(e), "found": False}

    if not ot:
        return {"ok": True, "found": False, "ot_id": ot_id}

    item = _iad_clean_workorder_item_v1(ot)

    item["final_report_initial"] = _iad_clean_text_v1(_iad_clean_getattr_v1(ot, ["final_report_initial", "informe_ia", "resultado_inicial", "resultado_ia"], ""))
    item["final_report_accepted"] = _iad_clean_text_v1(_iad_clean_getattr_v1(ot, ["final_report_accepted", "final_report", "resultado_final", "resultado", "informe_final"], ""))
    item["review_report"] = _iad_clean_text_v1(_iad_clean_getattr_v1(ot, ["review_report", "final_report_diff", "revision", "revisión", "review"], ""))

    return {"ok": True, "found": True, "item": item}


def _iad_clean_db_cols_v1(db, table_name):
    from sqlalchemy import text
    try:
        dialect = db.bind.dialect.name
    except Exception:
        dialect = "unknown"

    try:
        if dialect == "postgresql":
            rows = db.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :t
                ORDER BY ordinal_position
            """), {"t": table_name}).fetchall()
            return [r[0] for r in rows]
        rows = db.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        return [r[1] for r in rows]
    except Exception:
        return []


def _iad_clean_ensure_training_tables_v1(db):
    try:
        _iad_v5_ensure_tables(db)
        return
    except Exception:
        pass
    try:
        _iad_v4_ensure_tables_and_ot_id(db)
        return
    except Exception:
        pass
    try:
        _iad_validation_v3_ensure_tables(db)
        return
    except Exception:
        pass


@router.get("/iad/api/training/dataset-clean.json")
def iad_training_dataset_clean_v1(limit: int = 200, db = Depends(get_db)):
    from sqlalchemy import text

    _iad_clean_ensure_training_tables_v1(db)

    limit = max(1, min(int(limit or 200), 1000))
    cols = _iad_clean_db_cols_v1(db, "iad_training_corrections")

    if not cols:
        return {"ok": True, "count": 0, "items": [], "columns": []}

    wanted = [
        "id",
        "created_at",
        "ot_id",
        "usuario",
        "template_name",
        "dictado_original",
        "transcripcion",
        "clinical_json",
        "informe_ia",
        "informe_corregido",
        "diferencias_detectadas",
        "modelo_usado",
        "metadata_json",
        "source",
    ]

    select_cols = [c for c in wanted if c in cols]
    if "id" not in select_cols:
        select_cols.insert(0, "id")

    sql = "SELECT " + ", ".join(select_cols) + " FROM iad_training_corrections ORDER BY id DESC LIMIT :limit"
    rows = db.execute(text(sql), {"limit": limit}).fetchall()

    items = []
    for row in rows:
        raw = dict(zip(select_cols, row))

        clinical = _iad_clean_json_loads_v1(raw.get("clinical_json"), fallback={})
        metadata = _iad_clean_json_loads_v1(raw.get("metadata_json"), fallback={})

        tags = []
        conflict_points = []

        if isinstance(clinical, dict):
            for key in ["tags", "hallazgos", "findings", "hallazgos_estructurados"]:
                val = clinical.get(key)
                if isinstance(val, list):
                    tags.extend(val)

        if isinstance(metadata, dict):
            for key in ["advertencias", "warnings", "posibles_omisiones", "conflictos", "conflict_points"]:
                val = metadata.get(key)
                if isinstance(val, list):
                    conflict_points.extend([str(x) for x in val if str(x).strip()])

        items.append({
            "id": raw.get("id"),
            "created_at": _iad_clean_dt_v1(raw.get("created_at")),
            "ot_id": raw.get("ot_id"),
            "usuario": raw.get("usuario") or "",
            "texto_transcrito_literal": raw.get("transcripcion") or raw.get("dictado_original") or "",
            "tags_importantes_reconocidos": tags,
            "plantilla_a_utilizar": raw.get("template_name") or "",
            "propuesta_ia": raw.get("informe_ia") or "",
            "puntos_conflictivos_detectados": conflict_points,
            "version_final_usuario": raw.get("informe_corregido") or "",
            "diff": raw.get("diferencias_detectadas") or "",
            "modelo": raw.get("modelo_usado") or "",
            "source": raw.get("source") or "",
            "metadata": metadata,
            "clinical_json": clinical,
        })

    return {
        "ok": True,
        "count": len(items),
        "items": items,
        "columns": select_cols,
    }


# IAD_HISTORY2_TRININGIA_ROUTES_V2
# Historial2 corregido:
# - usuario legible, no objeto User;
# - hora ajustada +3 h por defecto para coincidir con hora local visible;
# - detalle OT con fallback desde WorkOrder + última validación + campos crudos;
# - mantiene Trining IA endpoints.

def _iad_h2v2_text(value):
    if value is None:
        return ""
    return str(value)


def _iad_h2v2_json(value, fallback=None):
    import json
    if fallback is None:
        fallback = {}
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _iad_h2v2_dt(value):
    if value is None:
        return ""

    import os
    import datetime

    offset_hours = int(os.environ.get("IAD_HISTORY_TIME_OFFSET_HOURS", "3"))

    dt = None

    if isinstance(value, datetime.datetime):
        dt = value
    else:
        raw = str(value).strip()
        for fmt in [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ]:
            try:
                dt = datetime.datetime.strptime(raw.replace("Z", ""), fmt)
                break
            except Exception:
                pass

    if dt is None:
        return str(value)

    try:
        dt = dt + datetime.timedelta(hours=offset_hours)
    except Exception:
        pass

    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _iad_h2v2_column_dict(obj):
    out = {}
    try:
        for col in obj.__mapper__.columns:
            key = col.key
            try:
                val = getattr(obj, key)
            except Exception:
                val = None
            out[key] = val
    except Exception:
        pass
    return out


def _iad_h2v2_relationship_username(obj):
    # Evita mostrar "<User object at ...>".
    candidates = []

    for attr in ["user", "usuario", "owner", "created_by_user"]:
        try:
            rel = getattr(obj, attr, None)
            if rel is not None and not isinstance(rel, (str, int, float)):
                candidates.append(rel)
        except Exception:
            pass

    for rel in candidates:
        for name in ["username", "usuario", "email", "name", "nombre", "login"]:
            try:
                v = getattr(rel, name, None)
                if v not in (None, ""):
                    return str(v)
            except Exception:
                pass

    # Fallback a columnas simples.
    cols = _iad_h2v2_column_dict(obj)
    for k in ["username", "usuario", "user_name", "created_by", "user_id", "owner_id"]:
        v = cols.get(k)
        if v not in (None, ""):
            return str(v)

    return ""


def _iad_h2v2_pick(cols, names, default=""):
    for name in names:
        v = cols.get(name)
        if v not in (None, ""):
            return v
    return default


def _iad_h2v2_pick_text(cols, names, default=""):
    return _iad_h2v2_text(_iad_h2v2_pick(cols, names, default))


def _iad_h2v2_derive_modality(cols, template="", title=""):
    direct = _iad_h2v2_pick_text(cols, [
        "modalidad", "modality", "tipo_modalidad", "study_modality"
    ], "")
    if direct:
        return direct

    hay = f"{template} {title}".lower()
    if "tc" in hay or "tac" in hay:
        return "TC"
    if "rx" in hay or "radiograf" in hay:
        return "RX"
    if "us" in hay or "eco" in hay or "ultrason" in hay:
        return "US"
    if "rm" in hay or "resonancia" in hay:
        return "RM"
    return ""


def _iad_h2v2_latest_validation(db, ot_id):
    from sqlalchemy import text

    try:
        rows = db.execute(text("""
            SELECT
                id,
                created_at,
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
            FROM iad_validation_history
            WHERE ot_id = :ot_id
            ORDER BY id DESC
            LIMIT 1
        """), {"ot_id": int(ot_id)}).fetchall()
    except Exception:
        return None

    if not rows:
        return None

    r = rows[0]
    return {
        "id": r[0],
        "created_at": r[1],
        "template_name": r[2],
        "dictado_original": r[3],
        "transcripcion": r[4],
        "clinical_json": r[5],
        "informe_ia": r[6],
        "informe_validado": r[7],
        "diferencias_detectadas": r[8],
        "modelo_usado": r[9],
        "metadata_json": r[10],
        "source": r[11],
        "estado": r[12],
        "ot_id": r[13],
    }


def _iad_h2v2_workorder_row(ot, db=None):
    cols = _iad_h2v2_column_dict(ot)
    oid = cols.get("id")

    latest = None
    if db is not None and oid:
        latest = _iad_h2v2_latest_validation(db, oid)

    created = _iad_h2v2_pick(cols, [
        "created_at", "timestamp", "created", "created_on", "fecha", "fecha_creacion"
    ], "")

    template = ""
    if latest and latest.get("template_name"):
        template = latest.get("template_name")
    else:
        template = _iad_h2v2_pick_text(cols, [
            "template_name", "plantilla_nombre", "template", "plantilla"
        ], "")

    title = _iad_h2v2_pick_text(cols, [
        "titulo", "title", "study_title", "nombre_estudio", "exam_name", "study_name", "description", "tipo", "study_type", "exam_type"
    ], "")

    if not title:
        title = template or f"OT #{oid}"

    modality = _iad_h2v2_derive_modality(cols, template=template, title=title)

    final_report = ""
    review_report = ""

    if latest:
        final_report = latest.get("informe_validado") or ""
        review_report = latest.get("diferencias_detectadas") or ""

    if not final_report:
        final_report = _iad_h2v2_pick_text(cols, [
            "final_report_accepted", "final_report", "resultado_final", "resultado", "informe_final"
        ], "")

    if not review_report:
        review_report = _iad_h2v2_pick_text(cols, [
            "review_report", "final_report_diff", "revision", "revisión", "review"
        ], "")

    return {
        "id": oid,
        "ot_id": oid,
        "hora": _iad_h2v2_dt(created),
        "hora_raw": _iad_h2v2_text(created),
        "usuario": _iad_h2v2_relationship_username(ot),
        "modalidad": modality,
        "nombre_estudio": title,
        "paciente": _iad_h2v2_pick_text(cols, [
            "paciente", "patient", "patient_name", "nombre_paciente"
        ], ""),
        "estado": _iad_h2v2_pick_text(cols, ["status", "estado", "state"], ""),
        "plantilla": template,
        "tiene_informe": bool(str(final_report or "").strip()),
        "tiene_revision": bool(str(review_report or "").strip()),
        "link": f"/iad/historial2/ot/{oid}",
    }


def _iad_h2v2_raw_fields(cols):
    out = []
    skip = set(["password", "hashed_password", "token", "secret"])
    for k, v in cols.items():
        if k.lower() in skip:
            continue
        if v in (None, ""):
            continue
        sv = str(v)
        if len(sv) > 5000:
            sv = sv[:5000] + "\n...[truncado]"
        out.append({"campo": k, "valor": sv})
    return out


def _iad_h2v2_workorder_detail(ot, db):
    cols = _iad_h2v2_column_dict(ot)
    row = _iad_h2v2_workorder_row(ot, db=db)
    latest = _iad_h2v2_latest_validation(db, row.get("ot_id")) if row.get("ot_id") else None

    metadata = _iad_h2v2_json(latest.get("metadata_json") if latest else None, fallback={})
    clinical = _iad_h2v2_json(latest.get("clinical_json") if latest else None, fallback={})

    texto_origen = ""
    extraccion_ia = ""
    propuesta_ia = ""
    revision = ""
    resultado_final = ""

    if latest:
        texto_origen = latest.get("transcripcion") or latest.get("dictado_original") or ""
        extraccion_ia = latest.get("clinical_json") or ""
        propuesta_ia = latest.get("informe_ia") or ""
        revision = latest.get("diferencias_detectadas") or ""
        resultado_final = latest.get("informe_validado") or ""

    if not texto_origen:
        texto_origen = _iad_h2v2_pick_text(cols, [
            "transcripcion", "transcription", "dictado_original", "source_text", "texto_origen", "input_text", "audio_text", "raw_text"
        ], "")

    if not extraccion_ia:
        extraccion_ia = _iad_h2v2_pick_text(cols, [
            "extraction_json", "structured_json", "clinical_json", "json_ia", "ai_json", "metadata_json"
        ], "")

    if not propuesta_ia:
        propuesta_ia = _iad_h2v2_pick_text(cols, [
            "final_report_initial", "informe_ia", "resultado_inicial", "resultado_ia", "model_report"
        ], "")

    if not revision:
        revision = _iad_h2v2_pick_text(cols, [
            "review_report", "final_report_diff", "revision", "revisión", "review"
        ], "")

    if not resultado_final:
        resultado_final = _iad_h2v2_pick_text(cols, [
            "final_report_accepted", "final_report", "resultado_final", "resultado", "informe_final"
        ], "")

    row.update({
        "tipo": _iad_h2v2_pick_text(cols, ["tipo", "type", "study_type", "exam_type"], ""),
        "titulo": _iad_h2v2_pick_text(cols, ["titulo", "title", "study_title", "nombre_estudio"], ""),
        "edad": _iad_h2v2_pick_text(cols, ["edad", "age", "patient_age"], ""),
        "texto_origen": texto_origen,
        "extraccion_ia": extraccion_ia,
        "propuesta_ia": propuesta_ia,
        "revision": revision,
        "resultado_final": resultado_final,
        "latest_validation": latest or {},
        "metadata": metadata,
        "clinical": clinical,
        "raw_fields": _iad_h2v2_raw_fields(cols),
    })

    return row


def _iad_h2v2_db_cols(db, table_name):
    from sqlalchemy import text
    try:
        dialect = db.bind.dialect.name
    except Exception:
        dialect = "unknown"

    try:
        if dialect == "postgresql":
            rows = db.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :t
                ORDER BY ordinal_position
            """), {"t": table_name}).fetchall()
            return [r[0] for r in rows]
        rows = db.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        return [r[1] for r in rows]
    except Exception:
        return []


def _iad_h2v2_ensure_training_tables(db):
    try:
        _iad_v5_ensure_tables(db)
        return
    except Exception:
        pass
    try:
        _iad_v4_ensure_tables_and_ot_id(db)
        return
    except Exception:
        pass
    try:
        _iad_validation_v3_ensure_tables(db)
        return
    except Exception:
        pass


def _iad_h2v2_diff_metrics(diff_text):
    diff_text = _iad_h2v2_text(diff_text)
    lines = [ln for ln in diff_text.splitlines() if ln.strip()]
    changed = [
        ln for ln in lines
        if (ln.startswith("+") or ln.startswith("-"))
        and not ln.startswith("+++")
        and not ln.startswith("---")
    ]
    added = [ln for ln in changed if ln.startswith("+")]
    removed = [ln for ln in changed if ln.startswith("-")]
    return {"lineas_diff": len(lines), "cambios": len(changed), "agregadas": len(added), "eliminadas": len(removed)}


def _iad_h2v2_extract_tags(clinical, metadata):
    tags = []

    def add(x):
        if x is None:
            return
        if isinstance(x, dict):
            parts = []
            for k in ["organo_o_region", "region", "organo", "lateralidad", "side", "hallazgo", "finding", "medida", "size", "interpretacion"]:
                v = x.get(k)
                if v not in (None, ""):
                    parts.append(str(v))
            tags.append(" · ".join(parts) if parts else str(x))
        else:
            sx = str(x).strip()
            if sx:
                tags.append(sx)

    for src in [clinical, metadata]:
        if isinstance(src, list):
            for x in src:
                add(x)
        elif isinstance(src, dict):
            for key in ["tags", "hallazgos", "findings", "hallazgos_estructurados", "structured_findings", "mapa_aplicacion"]:
                val = src.get(key)
                if isinstance(val, list):
                    for x in val:
                        add(x)

    out, seen = [], set()
    for t in tags:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def _iad_h2v2_extract_conflicts(metadata):
    conflicts = []
    if isinstance(metadata, dict):
        for key in ["advertencias", "warnings", "posibles_omisiones", "conflictos", "conflict_points", "puntos_conflictivos"]:
            val = metadata.get(key)
            if isinstance(val, list):
                conflicts.extend([str(x) for x in val if str(x).strip()])
            elif isinstance(val, str) and val.strip():
                conflicts.append(val.strip())

        for key in ["exam_type_guard", "clean_writer", "stable_writer_v2", "ap_safe_impression_v2", "ap_style_rules"]:
            val = metadata.get(key)
            if isinstance(val, dict) and val:
                conflicts.append(f"{key}: {val}")

    out, seen = [], set()
    for c in conflicts:
        k = c.lower()
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def _iad_h2v2_ai_version(metadata, source, model):
    if isinstance(metadata, dict):
        for key in ["version_ia", "ai_version", "metodo", "method"]:
            val = metadata.get(key)
            if val:
                return str(val)
        markers = []
        for key in ["stable_writer_v2", "clean_writer", "exam_type_guard", "ap_style_rules", "ap_safe_impression_v2"]:
            val = metadata.get(key)
            if isinstance(val, dict) and val.get("active"):
                markers.append(key)
        if markers:
            return "+".join(markers)
    return str(source or model or "")


def _iad_h2v2_training_row(raw):
    clinical = _iad_h2v2_json(raw.get("clinical_json"), fallback={})
    metadata = _iad_h2v2_json(raw.get("metadata_json"), fallback={})
    diff = raw.get("diferencias_detectadas") or ""
    metrics = _iad_h2v2_diff_metrics(diff)
    model = raw.get("modelo_usado") or ""
    source = raw.get("source") or ""

    return {
        "id": raw.get("id"),
        "hora": _iad_h2v2_dt(raw.get("created_at")),
        "hora_raw": _iad_h2v2_text(raw.get("created_at")),
        "ot_id": raw.get("ot_id"),
        "modelo_ia_utilizado": model,
        "version_ia": _iad_h2v2_ai_version(metadata, source, model),
        "plantilla": raw.get("template_name") or "",
        "diff_numerico": metrics,
        "diff_cambios": metrics["cambios"],
        "texto_transcrito_literal": raw.get("transcripcion") or raw.get("dictado_original") or "",
        "tags_importantes_reconocidos": _iad_h2v2_extract_tags(clinical, metadata),
        "plantilla_a_utilizar": raw.get("template_name") or "",
        "propuesta_ia": raw.get("informe_ia") or "",
        "puntos_conflictivos_detectados": _iad_h2v2_extract_conflicts(metadata),
        "version_final_guardada_usuario": raw.get("informe_corregido") or "",
        "diff": diff,
        "metadata": metadata,
        "clinical_json": clinical,
    }


def _iad_h2v2_training_select(db, limit=500, ids=None):
    from sqlalchemy import text
    _iad_h2v2_ensure_training_tables(db)

    cols = _iad_h2v2_db_cols(db, "iad_training_corrections")
    if not cols:
        return []

    wanted = ["id", "created_at", "ot_id", "usuario", "template_name", "dictado_original", "transcripcion", "clinical_json", "informe_ia", "informe_corregido", "diferencias_detectadas", "modelo_usado", "metadata_json", "source"]
    select_cols = [c for c in wanted if c in cols]
    if "id" not in select_cols:
        return []

    if ids:
        ids = [int(x) for x in ids]
        placeholders = ", ".join([f":id{i}" for i in range(len(ids))])
        sql = f"SELECT {', '.join(select_cols)} FROM iad_training_corrections WHERE id IN ({placeholders}) ORDER BY id DESC"
        params = {f"id{i}": v for i, v in enumerate(ids)}
    else:
        limit = max(1, min(int(limit or 500), 2000))
        sql = f"SELECT {', '.join(select_cols)} FROM iad_training_corrections ORDER BY id DESC LIMIT :limit"
        params = {"limit": limit}

    rows = db.execute(text(sql), params).fetchall()
    raw_items = [dict(zip(select_cols, row)) for row in rows]
    return [_iad_h2v2_training_row(raw) for raw in raw_items]


@router.get("/iad/historial2")
def iad_historial2_page_v2(request: Request):
    return templates.TemplateResponse("iadictador/historial2.html", {"request": request})


@router.get("/iad/historial2/ot/{ot_id}")
def iad_historial2_ot_page_v2(request: Request, ot_id: int, db = Depends(get_db)):
    try:
        ot = db.query(WorkOrder).filter(WorkOrder.id == int(ot_id)).first()
    except Exception:
        ot = None
    item = _iad_h2v2_workorder_detail(ot, db) if ot else None
    return templates.TemplateResponse("iadictador/historial2_ot.html", {"request": request, "ot_id": ot_id, "item": item})


@router.get("/iad/api/historial2/ots.json")
def iad_api_historial2_ots_v2(limit: int = 500, db = Depends(get_db)):
    limit = max(1, min(int(limit or 500), 2000))
    try:
        rows = db.query(WorkOrder).order_by(WorkOrder.id.desc()).limit(limit).all()
    except Exception as e:
        return {"ok": False, "error": str(e), "items": [], "count": 0}
    items = [_iad_h2v2_workorder_row(ot, db=db) for ot in rows]
    return {"ok": True, "count": len(items), "items": items}


@router.get("/iad/api/historial2/ot/{ot_id}.json")
def iad_api_historial2_ot_v2(ot_id: int, db = Depends(get_db)):
    try:
        ot = db.query(WorkOrder).filter(WorkOrder.id == int(ot_id)).first()
    except Exception as e:
        return {"ok": False, "found": False, "error": str(e)}
    if not ot:
        return {"ok": True, "found": False, "ot_id": ot_id}
    return {"ok": True, "found": True, "item": _iad_h2v2_workorder_detail(ot, db)}


@router.get("/iad/trining-ia")
def iad_trining_ia_page_v2(request: Request):
    return templates.TemplateResponse("iadictador/trining_ia.html", {"request": request})


@router.get("/iad/trining-ia/{training_id}")
def iad_trining_ia_detail_page_v2(request: Request, training_id: int, db = Depends(get_db)):
    items = _iad_h2v2_training_select(db, ids=[training_id])
    item = items[0] if items else None
    return templates.TemplateResponse("iadictador/trining_ia_detail.html", {"request": request, "training_id": training_id, "item": item})


@router.get("/iad/api/trining-ia/items.json")
def iad_api_trining_ia_items_v2(limit: int = 500, db = Depends(get_db)):
    items = _iad_h2v2_training_select(db, limit=limit)
    return {"ok": True, "count": len(items), "items": items}


@router.get("/iad/api/trining-ia/item/{training_id}.json")
def iad_api_trining_ia_item_v2(training_id: int, db = Depends(get_db)):
    items = _iad_h2v2_training_select(db, ids=[training_id])
    if not items:
        return {"ok": True, "found": False, "id": training_id}
    return {"ok": True, "found": True, "item": items[0]}


@router.post("/iad/api/trining-ia/delete.json")
async def iad_api_trining_ia_delete_v2(request: Request, db = Depends(get_db)):
    from sqlalchemy import text
    payload = await request.json()
    ids = payload.get("ids") or []
    clean_ids = []
    for x in ids:
        try:
            clean_ids.append(int(x))
        except Exception:
            pass
    if not clean_ids:
        return {"ok": False, "error": "Sin IDs válidos"}
    placeholders = ", ".join([f":id{i}" for i in range(len(clean_ids))])
    params = {f"id{i}": v for i, v in enumerate(clean_ids)}
    try:
        db.execute(text(f"DELETE FROM iad_training_corrections WHERE id IN ({placeholders})"), params)
        db.commit()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}
    return {"ok": True, "deleted": len(clean_ids), "ids": clean_ids}


# IAD_HISTORY2_WORKITEMS_ROUTES_V1
# Historial2 ahora usa tabla propia de trabajos generados:
# iad_history2_work_items
# Esto no depende de que el flujo cree una OT antigua.

def _iad_h2wi_json_dumps(value):
    import json
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _iad_h2wi_json_loads(value, fallback=None):
    import json
    if fallback is None:
        fallback = {}
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _iad_h2wi_username(request):
    try:
        sess = getattr(request, "session", None)
        if isinstance(sess, dict):
            return sess.get("username") or sess.get("user") or sess.get("usuario") or sess.get("email") or "unknown"
    except Exception:
        pass
    return "unknown"


def _iad_h2wi_dt(value):
    if value is None:
        return ""

    import os
    import datetime

    # La BD actual está 3 h adelantada respecto al login visible.
    offset_hours = int(os.environ.get("IAD_HISTORY2_TIME_OFFSET_HOURS", "-3"))

    dt = None

    if isinstance(value, datetime.datetime):
        dt = value
    else:
        raw = str(value).strip().replace("Z", "")
        for fmt in [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ]:
            try:
                dt = datetime.datetime.strptime(raw, fmt)
                break
            except Exception:
                pass

    if dt is None:
        return str(value)

    try:
        dt = dt + datetime.timedelta(hours=offset_hours)
    except Exception:
        pass

    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _iad_h2wi_table_cols(db, table):
    from sqlalchemy import text

    try:
        dialect = db.bind.dialect.name
    except Exception:
        dialect = "unknown"

    try:
        if dialect == "postgresql":
            rows = db.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :t
                ORDER BY ordinal_position
            """), {"t": table}).fetchall()
            return [r[0] for r in rows]

        rows = db.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return [r[1] for r in rows]
    except Exception:
        return []


def _iad_h2wi_ensure_table(db):
    from sqlalchemy import text

    try:
        dialect = db.bind.dialect.name
    except Exception:
        dialect = "unknown"

    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"

    db.execute(text(f"""
        CREATE TABLE IF NOT EXISTS iad_history2_work_items (
            id {pk},
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            usuario TEXT,
            modalidad TEXT,
            nombre_estudio TEXT,
            paciente TEXT,
            estado TEXT,
            ot_id INTEGER,
            training_id INTEGER,
            template_name TEXT,
            modelo_ia TEXT,
            version_ia TEXT,
            transcripcion TEXT,
            tags_json TEXT,
            clinical_json TEXT,
            propuesta_ia TEXT,
            puntos_conflictivos_json TEXT,
            version_final_usuario TEXT,
            diff TEXT,
            metadata_json TEXT,
            source TEXT,
            source_ref TEXT
        )
    """))

    try:
        db.commit()
    except Exception:
        pass


def _iad_h2wi_int(value):
    try:
        if value in (None, "", "null", "undefined"):
            return None
        return int(value)
    except Exception:
        return None


def _iad_h2wi_text(value):
    if value is None:
        return ""
    return str(value)


def _iad_h2wi_extract_tags(payload):
    tags = []

    def add(x):
        if x is None:
            return
        if isinstance(x, dict):
            parts = []
            for k in [
                "organo_o_region", "region", "organo", "lateralidad", "side",
                "hallazgo", "finding", "medida", "size", "interpretacion"
            ]:
                v = x.get(k)
                if v not in (None, ""):
                    parts.append(str(v))
            if parts:
                tags.append(" · ".join(parts))
            else:
                tags.append(str(x))
        else:
            sx = str(x).strip()
            if sx:
                tags.append(sx)

    if isinstance(payload, dict):
        for key in ["tags", "hallazgos_estructurados", "structured_findings", "mapa_aplicacion"]:
            val = payload.get(key)
            if isinstance(val, list):
                for x in val:
                    add(x)

        meta = payload.get("metadata_json")
        if isinstance(meta, dict):
            for key in ["tags", "hallazgos_estructurados", "structured_findings"]:
                val = meta.get(key)
                if isinstance(val, list):
                    for x in val:
                        add(x)

    out = []
    seen = set()
    for t in tags:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def _iad_h2wi_extract_conflicts(payload):
    conflicts = []
    if isinstance(payload, dict):
        for key in [
            "advertencias", "warnings", "posibles_omisiones", "conflictos",
            "puntos_conflictivos", "conflict_points"
        ]:
            val = payload.get(key)
            if isinstance(val, list):
                conflicts.extend([str(x) for x in val if str(x).strip()])
            elif isinstance(val, str) and val.strip():
                conflicts.append(val.strip())

        meta = payload.get("metadata_json")
        if isinstance(meta, dict):
            for key in ["advertencias", "warnings", "posibles_omisiones", "conflictos"]:
                val = meta.get(key)
                if isinstance(val, list):
                    conflicts.extend([str(x) for x in val if str(x).strip()])
                elif isinstance(val, str) and val.strip():
                    conflicts.append(val.strip())

    out = []
    seen = set()
    for c in conflicts:
        k = c.lower()
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def _iad_h2wi_diff_metrics(diff_text):
    diff_text = _iad_h2wi_text(diff_text)
    lines = [ln for ln in diff_text.splitlines() if ln.strip()]
    changed = [
        ln for ln in lines
        if (ln.startswith("+") or ln.startswith("-"))
        and not ln.startswith("+++")
        and not ln.startswith("---")
    ]
    added = [ln for ln in changed if ln.startswith("+")]
    removed = [ln for ln in changed if ln.startswith("-")]
    return {
        "lineas_diff": len(lines),
        "cambios": len(changed),
        "agregadas": len(added),
        "eliminadas": len(removed),
    }


def _iad_h2wi_row_to_item(row):
    # row es tuple con orden fijo de SELECT.
    (
        id_, created_at, updated_at, usuario, modalidad, nombre_estudio, paciente,
        estado, ot_id, training_id, template_name, modelo_ia, version_ia,
        transcripcion, tags_json, clinical_json, propuesta_ia,
        puntos_conflictivos_json, version_final_usuario, diff,
        metadata_json, source, source_ref
    ) = row

    tags = _iad_h2wi_json_loads(tags_json, fallback=[])
    conflicts = _iad_h2wi_json_loads(puntos_conflictivos_json, fallback=[])
    clinical = _iad_h2wi_json_loads(clinical_json, fallback={})
    metadata = _iad_h2wi_json_loads(metadata_json, fallback={})

    return {
        "id": id_,
        "hora": _iad_h2wi_dt(created_at),
        "hora_raw": _iad_h2wi_text(created_at),
        "updated_at": _iad_h2wi_dt(updated_at),
        "usuario": usuario or "",
        "modalidad": modalidad or "",
        "nombre_estudio": nombre_estudio or template_name or f"Trabajo #{id_}",
        "paciente": paciente or "",
        "estado": estado or "",
        "ot_id": ot_id,
        "training_id": training_id,
        "template_name": template_name or "",
        "modelo_ia": modelo_ia or "",
        "version_ia": version_ia or "",
        "transcripcion": transcripcion or "",
        "tags": tags,
        "clinical_json": clinical,
        "propuesta_ia": propuesta_ia or "",
        "puntos_conflictivos": conflicts,
        "version_final_usuario": version_final_usuario or "",
        "diff": diff or "",
        "diff_numerico": _iad_h2wi_diff_metrics(diff or ""),
        "metadata": metadata,
        "source": source or "",
        "source_ref": source_ref or "",
        "tiene_informe": bool(str(version_final_usuario or propuesta_ia or "").strip()),
        "tiene_revision": bool(str(diff or "").strip()),
        "link": f"/iad/historial2/w/{id_}",
    }


def _iad_h2wi_select_all(db, limit=1000):
    from sqlalchemy import text

    _iad_h2wi_ensure_table(db)

    limit = max(1, min(int(limit or 1000), 3000))

    rows = db.execute(text("""
        SELECT
            id, created_at, updated_at, usuario, modalidad, nombre_estudio, paciente,
            estado, ot_id, training_id, template_name, modelo_ia, version_ia,
            transcripcion, tags_json, clinical_json, propuesta_ia,
            puntos_conflictivos_json, version_final_usuario, diff,
            metadata_json, source, source_ref
        FROM iad_history2_work_items
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()

    return [_iad_h2wi_row_to_item(r) for r in rows]


def _iad_h2wi_select_one(db, item_id):
    from sqlalchemy import text

    _iad_h2wi_ensure_table(db)

    row = db.execute(text("""
        SELECT
            id, created_at, updated_at, usuario, modalidad, nombre_estudio, paciente,
            estado, ot_id, training_id, template_name, modelo_ia, version_ia,
            transcripcion, tags_json, clinical_json, propuesta_ia,
            puntos_conflictivos_json, version_final_usuario, diff,
            metadata_json, source, source_ref
        FROM iad_history2_work_items
        WHERE id = :id
        LIMIT 1
    """), {"id": int(item_id)}).fetchone()

    if not row:
        return None
    return _iad_h2wi_row_to_item(row)


def _iad_h2wi_save_payload(db, request, payload):
    from sqlalchemy import text
    import datetime

    _iad_h2wi_ensure_table(db)

    item_id = _iad_h2wi_int(payload.get("work_item_id") or payload.get("id"))
    usuario = payload.get("usuario") or _iad_h2wi_username(request)

    template_name = (
        payload.get("template_name")
        or payload.get("plantilla_nombre")
        or payload.get("plantilla")
        or ""
    )

    modalidad = payload.get("modalidad") or payload.get("modality") or ""
    if not modalidad:
        hay = f"{template_name} {payload.get('nombre_estudio') or ''}".lower()
        if "tc" in hay or "tac" in hay:
            modalidad = "TC"
        elif "rx" in hay:
            modalidad = "RX"
        elif "us" in hay or "eco" in hay:
            modalidad = "US"
        elif "rm" in hay:
            modalidad = "RM"

    nombre_estudio = (
        payload.get("nombre_estudio")
        or payload.get("study_name")
        or template_name
        or "Trabajo IA"
    )

    estado = payload.get("estado") or "generada"
    ot_id = _iad_h2wi_int(payload.get("ot_id"))
    training_id = _iad_h2wi_int(payload.get("training_id"))

    modelo_ia = payload.get("modelo_ia") or payload.get("modelo_usado") or payload.get("model") or ""
    version_ia = payload.get("version_ia") or payload.get("metodo") or payload.get("method") or ""

    transcripcion = payload.get("transcripcion") or payload.get("transcription") or payload.get("dictado_original") or ""
    propuesta_ia = payload.get("propuesta_ia") or payload.get("informe_ia") or payload.get("informe_final") or payload.get("final_report") or ""
    final_usuario = payload.get("version_final_usuario") or payload.get("informe_validado") or payload.get("informe_corregido") or ""
    diff = payload.get("diff") or payload.get("diferencias_detectadas") or ""

    clinical = payload.get("clinical_json") or payload.get("hallazgos_estructurados") or {}
    metadata = payload.get("metadata_json") or payload

    tags = payload.get("tags_importantes_reconocidos")
    if not isinstance(tags, list):
        tags = _iad_h2wi_extract_tags(payload)

    conflicts = payload.get("puntos_conflictivos_detectados")
    if not isinstance(conflicts, list):
        conflicts = _iad_h2wi_extract_conflicts(payload)

    source = payload.get("source") or "frontend_audio_first"
    source_ref = payload.get("source_ref") or ""

    now = datetime.datetime.utcnow()

    if item_id:
        db.execute(text("""
            UPDATE iad_history2_work_items
            SET
                updated_at = :updated_at,
                usuario = COALESCE(NULLIF(:usuario, ''), usuario),
                modalidad = COALESCE(NULLIF(:modalidad, ''), modalidad),
                nombre_estudio = COALESCE(NULLIF(:nombre_estudio, ''), nombre_estudio),
                paciente = COALESCE(NULLIF(:paciente, ''), paciente),
                estado = COALESCE(NULLIF(:estado, ''), estado),
                ot_id = COALESCE(:ot_id, ot_id),
                training_id = COALESCE(:training_id, training_id),
                template_name = COALESCE(NULLIF(:template_name, ''), template_name),
                modelo_ia = COALESCE(NULLIF(:modelo_ia, ''), modelo_ia),
                version_ia = COALESCE(NULLIF(:version_ia, ''), version_ia),
                transcripcion = COALESCE(NULLIF(:transcripcion, ''), transcripcion),
                tags_json = COALESCE(NULLIF(:tags_json, ''), tags_json),
                clinical_json = COALESCE(NULLIF(:clinical_json, ''), clinical_json),
                propuesta_ia = COALESCE(NULLIF(:propuesta_ia, ''), propuesta_ia),
                puntos_conflictivos_json = COALESCE(NULLIF(:puntos_conflictivos_json, ''), puntos_conflictivos_json),
                version_final_usuario = COALESCE(NULLIF(:version_final_usuario, ''), version_final_usuario),
                diff = COALESCE(NULLIF(:diff, ''), diff),
                metadata_json = COALESCE(NULLIF(:metadata_json, ''), metadata_json),
                source = COALESCE(NULLIF(:source, ''), source),
                source_ref = COALESCE(NULLIF(:source_ref, ''), source_ref)
            WHERE id = :id
        """), {
            "id": item_id,
            "updated_at": now,
            "usuario": usuario,
            "modalidad": modalidad,
            "nombre_estudio": nombre_estudio,
            "paciente": payload.get("paciente") or "",
            "estado": estado,
            "ot_id": ot_id,
            "training_id": training_id,
            "template_name": template_name,
            "modelo_ia": modelo_ia,
            "version_ia": version_ia,
            "transcripcion": transcripcion,
            "tags_json": _iad_h2wi_json_dumps(tags),
            "clinical_json": _iad_h2wi_json_dumps(clinical),
            "propuesta_ia": propuesta_ia,
            "puntos_conflictivos_json": _iad_h2wi_json_dumps(conflicts),
            "version_final_usuario": final_usuario,
            "diff": diff,
            "metadata_json": _iad_h2wi_json_dumps(metadata),
            "source": source,
            "source_ref": source_ref,
        })
        db.commit()
        return _iad_h2wi_select_one(db, item_id)

    db.execute(text("""
        INSERT INTO iad_history2_work_items (
            usuario, modalidad, nombre_estudio, paciente, estado,
            ot_id, training_id, template_name, modelo_ia, version_ia,
            transcripcion, tags_json, clinical_json, propuesta_ia,
            puntos_conflictivos_json, version_final_usuario, diff,
            metadata_json, source, source_ref
        )
        VALUES (
            :usuario, :modalidad, :nombre_estudio, :paciente, :estado,
            :ot_id, :training_id, :template_name, :modelo_ia, :version_ia,
            :transcripcion, :tags_json, :clinical_json, :propuesta_ia,
            :puntos_conflictivos_json, :version_final_usuario, :diff,
            :metadata_json, :source, :source_ref
        )
    """), {
        "usuario": usuario,
        "modalidad": modalidad,
        "nombre_estudio": nombre_estudio,
        "paciente": payload.get("paciente") or "",
        "estado": estado,
        "ot_id": ot_id,
        "training_id": training_id,
        "template_name": template_name,
        "modelo_ia": modelo_ia,
        "version_ia": version_ia,
        "transcripcion": transcripcion,
        "tags_json": _iad_h2wi_json_dumps(tags),
        "clinical_json": _iad_h2wi_json_dumps(clinical),
        "propuesta_ia": propuesta_ia,
        "puntos_conflictivos_json": _iad_h2wi_json_dumps(conflicts),
        "version_final_usuario": final_usuario,
        "diff": diff,
        "metadata_json": _iad_h2wi_json_dumps(metadata),
        "source": source,
        "source_ref": source_ref,
    })
    db.commit()

    # Último ID portable SQLite/Postgres: basta listar último del usuario/source.
    rows = _iad_h2wi_select_all(db, limit=1)
    return rows[0] if rows else None


def _iad_h2wi_backfill_from_training(db, limit=200):
    from sqlalchemy import text

    _iad_h2wi_ensure_table(db)

    try:
        _iad_h2v2_ensure_training_tables(db)
        rows = db.execute(text("""
            SELECT
                id, created_at, ot_id, usuario, template_name,
                dictado_original, transcripcion, clinical_json, informe_ia,
                informe_corregido, diferencias_detectadas, modelo_usado,
                metadata_json, source
            FROM iad_training_corrections
            ORDER BY id DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()
    except Exception:
        return {"created": 0, "error": "no training table"}

    created = 0

    for r in rows:
        source_ref = f"training:{r[0]}"

        exists = db.execute(text("""
            SELECT id FROM iad_history2_work_items
            WHERE source_ref = :source_ref
            LIMIT 1
        """), {"source_ref": source_ref}).fetchone()

        if exists:
            continue

        clinical = _iad_h2wi_json_loads(r[7], fallback={})
        metadata = _iad_h2wi_json_loads(r[12], fallback={})

        payload = {
            "usuario": r[3],
            "template_name": r[4],
            "nombre_estudio": r[4] or f"Training #{r[0]}",
            "estado": "validada" if r[9] else "generada",
            "ot_id": r[2],
            "training_id": r[0],
            "modelo_ia": r[11],
            "version_ia": r[13],
            "transcripcion": r[6] or r[5],
            "clinical_json": clinical,
            "informe_ia": r[8],
            "informe_validado": r[9],
            "diff": r[10],
            "metadata_json": metadata,
            "source": "backfill_training",
            "source_ref": source_ref,
        }
        item = _iad_h2wi_save_payload(db, type("Req", (), {"session": {}})(), payload)
        if item:
            created += 1

    return {"created": created}


@router.get("/iad/historial2")
def iad_historial2_page_workitems_v1(request: Request):
    return templates.TemplateResponse("iadictador/historial2.html", {"request": request})


@router.get("/iad/historial2/w/{item_id}")
def iad_historial2_workitem_page_v1(request: Request, item_id: int, db = Depends(get_db)):
    item = _iad_h2wi_select_one(db, item_id)
    return templates.TemplateResponse("iadictador/historial2_workitem.html", {
        "request": request,
        "item_id": item_id,
        "item": item,
    })


@router.get("/iad/api/historial2/workitems.json")
def iad_api_historial2_workitems_v1(limit: int = 1000, db = Depends(get_db)):
    _iad_h2wi_backfill_from_training(db, limit=300)
    items = _iad_h2wi_select_all(db, limit=limit)
    return {"ok": True, "count": len(items), "items": items}


@router.get("/iad/api/historial2/workitem/{item_id}.json")
def iad_api_historial2_workitem_v1(item_id: int, db = Depends(get_db)):
    item = _iad_h2wi_select_one(db, item_id)
    if not item:
        return {"ok": True, "found": False, "id": item_id}
    return {"ok": True, "found": True, "item": item}


@router.post("/iad/api/historial2/workitems/save.json")
async def iad_api_historial2_workitems_save_v1(request: Request, db = Depends(get_db)):
    payload = await request.json()
    item = _iad_h2wi_save_payload(db, request, payload)
    if not item:
        return {"ok": False, "error": "No se pudo guardar work item"}
    return {"ok": True, "item": item}


# IAD_RESPONSIBILITY_SAVE_ENRICH_V2
# Enriquecimiento seguro de guardados con responsable técnico.
# Evita depender de parches complejos en JS.
# No guarda razonamiento interno; solo traza pública: provider, modelo, proceso, etapas, prompt/schema IDs.

def _iad_respsave_json_loads_v2(value, fallback=None):
    import json
    if fallback is None:
        fallback = {}
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _iad_respsave_first_v2(*values):
    for v in values:
        if v not in (None, ""):
            return v
    return ""


def _iad_respsave_from_payload_v2(payload):
    if not isinstance(payload, dict):
        return payload

    meta = payload.get("metadata_json")
    meta = _iad_respsave_json_loads_v2(meta, fallback={}) if not isinstance(meta, dict) else meta

    # Si no hay metadata_json, a veces el payload completo ES la metadata.
    search = [payload, meta]

    resp = {}
    for src in search:
        if isinstance(src, dict) and isinstance(src.get("responsable_ia"), dict):
            resp = src.get("responsable_ia")
            break

    modelo = _iad_respsave_first_v2(
        payload.get("modelo_ia"),
        payload.get("modelo_usado"),
        payload.get("model"),
        resp.get("modelo"),
        resp.get("model"),
        "modelo_no_registrado"
    )

    proceso = _iad_respsave_first_v2(
        payload.get("version_ia"),
        payload.get("proceso_responsable"),
        payload.get("metodo"),
        payload.get("method"),
        resp.get("proceso"),
        payload.get("source"),
        "proceso_no_registrado"
    )

    provider = _iad_respsave_first_v2(
        payload.get("provider"),
        resp.get("provider"),
        "provider_no_registrado"
    )

    # Completar campos que usan Historial2 y Training.
    payload["modelo_ia"] = modelo
    payload["modelo_usado"] = modelo
    payload["model"] = modelo

    payload["version_ia"] = proceso
    payload["proceso_responsable"] = proceso
    payload["metodo"] = payload.get("metodo") or proceso

    if not isinstance(resp, dict) or not resp:
        resp = {
            "provider": provider,
            "modelo": modelo,
            "proceso": proceso,
            "prompt_schema_ids": payload.get("prompt_trace_publico") or [],
            "etapas": payload.get("etapas_responsables") or [],
            "nota": "Traza pública reconstruida al guardar. No contiene razonamiento interno."
        }

    payload["responsable_ia"] = resp

    if isinstance(meta, dict):
        meta["responsable_ia"] = resp
        payload["metadata_json"] = meta

    return payload


# Historial2 workitems.
try:
    _iad_respsave_orig_h2wi_save_v2 = _iad_h2wi_save_payload

    def _iad_h2wi_save_payload(db, request, payload):
        payload = _iad_respsave_from_payload_v2(payload)
        return _iad_respsave_orig_h2wi_save_v2(db, request, payload)

except Exception:
    pass


# Validación / Training V5.
try:
    _iad_respsave_orig_v5_insert_v2 = _iad_v5_insert_history_training

    def _iad_v5_insert_history_training(db, request, payload):
        payload = _iad_respsave_from_payload_v2(payload)
        return _iad_respsave_orig_v5_insert_v2(db, request, payload)

except Exception:
    pass


# Validación / Training V4.
try:
    _iad_respsave_orig_v4_insert_v2 = _iad_v4_insert_validation_and_training

    def _iad_v4_insert_validation_and_training(db, request, payload):
        payload = _iad_respsave_from_payload_v2(payload)
        return _iad_respsave_orig_v4_insert_v2(db, request, payload)

except Exception:
    pass


# ---------------------------------------------------------------------
# dIctAdor V4: evita duplicados visibles en Historial.
# Algunos registros V4 ya se persisten directamente como core_v4_auto.
# El backfill desde Training IA puede reinsertarlos como backfill_training.
# Este wrapper limpia esos duplicados cada vez que se consulta Historial.
# ---------------------------------------------------------------------
try:
    _dictador_orig_h2wi_backfill_from_training_v4_cleanup = _iad_h2wi_backfill_from_training

    def _iad_h2wi_backfill_from_training(db, limit=200):
        result = _dictador_orig_h2wi_backfill_from_training_v4_cleanup(db, limit=limit)

        deleted = 0
        try:
            db.execute(text("""
                DELETE FROM iad_history2_work_items
                WHERE source = 'backfill_training'
                  AND (
                    version_ia LIKE 'core_v4%'
                    OR source_ref LIKE '%core_v4_%'
                    OR metadata_json LIKE '%core_v4_%'
                    OR metadata_json LIKE '%core_v4_auto%'
                  )
            """))
            try:
                deleted = int(db.execute(text("SELECT changes()")).scalar() or 0)
            except Exception:
                deleted = 0
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

        if isinstance(result, dict):
            result["core_v4_backfill_duplicates_deleted"] = deleted

        return result

except Exception:
    pass
