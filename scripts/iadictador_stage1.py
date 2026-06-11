#!/usr/bin/env python3
from pathlib import Path
import os
import re
import shutil
import tarfile
import time
import json
from textwrap import dedent

ROOT = Path.cwd()
SCRIPT_DIR = ROOT / "scripts"
BACKUP_DIR = ROOT / "backups_iadictador"

PROJECT_NAME_OLD = "Reporte IA Prototype"
PROJECT_NAME_NEW = "IA Dictador"

TEST_PHRASES_TO_REMOVE = [
    "Pruebas rápidas",
    "vesícula ausente",
    "lesión hepática hipodensa de bordes bien definidos con realce arterial periférico",
    "hay divertículos no complicados",
    "litiasis puntiforme en cáliz inferior izquierdo de tres mm sin dilatación",
]


def print_header(title: str):
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def make_backup():
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"backup_iadictador_stage1_{stamp}.tar.gz"

    exclude_names = {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        "backups_iadictador",
        ".pytest_cache",
    }

    def should_exclude(path: Path) -> bool:
        parts = set(path.parts)
        return bool(parts & exclude_names)

    with tarfile.open(backup_path, "w:gz") as tar:
        for item in ROOT.iterdir():
            if item.name in exclude_names:
                continue
            if should_exclude(item):
                continue
            tar.add(item, arcname=item.name)

    print(f"Backup creado: {backup_path}")
    return backup_path


def detect_backend_dir() -> Path:
    candidates = [
        ROOT / "backend",
        ROOT / "app",
        ROOT,
    ]

    for c in candidates:
        if (c / "main.py").exists():
            return c

    for p in ROOT.rglob("main.py"):
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "FastAPI(" in txt:
            return p.parent

    raise RuntimeError("No encontré main.py con FastAPI. Ejecuta desde la raíz del proyecto.")


def detect_main_file(backend_dir: Path) -> Path:
    main_file = backend_dir / "main.py"
    if main_file.exists():
        return main_file

    for p in backend_dir.rglob("main.py"):
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if "FastAPI(" in txt:
            return p

    raise RuntimeError("No encontré archivo main.py.")


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = dedent(content).lstrip()
    if path.exists():
        old = path.read_text(encoding="utf-8", errors="ignore")
        if old == content:
            print(f"Sin cambios: {path}")
            return
    path.write_text(content, encoding="utf-8")
    print(f"Escrito: {path}")


def patch_text_replacements():
    print_header("REEMPLAZOS GENERALES DE TEXTO")

    exts = {".py", ".html", ".css", ".js", ".txt", ".md", ".json"}
    roots_to_scan = []

    for candidate in [ROOT / "backend", ROOT / "templates", ROOT / "static", ROOT / "app", ROOT]:
        if candidate.exists() and candidate not in roots_to_scan:
            roots_to_scan.append(candidate)

    changed = 0

    for scan_root in roots_to_scan:
        for path in scan_root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in exts:
                continue
            if "backups_iadictador" in path.parts:
                continue
            if ".git" in path.parts:
                continue
            if path.name == "iadictador_stage1.py":
                continue

            try:
                txt = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            new = txt.replace(PROJECT_NAME_OLD, PROJECT_NAME_NEW)

            for phrase in TEST_PHRASES_TO_REMOVE:
                new = new.replace(phrase, "")

            new = re.sub(r"\n{4,}", "\n\n\n", new)

            if new != txt:
                path.write_text(new, encoding="utf-8")
                changed += 1
                print(f"Actualizado texto: {path}")

    print(f"Archivos con reemplazos: {changed}")


def create_iadictador_module(backend_dir: Path):
    print_header("CREANDO MÓDULO IA DICTADOR")

    iad_dir = backend_dir / "iadictador"
    templates_dir = backend_dir / "templates" / "iadictador"
    rules_dir = backend_dir / "rules"

    write_file(iad_dir / "__init__.py", """
    # IA Dictador stage 1 module
    """)

    write_file(iad_dir / "db.py", r"""
    import os
    from pathlib import Path
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, declarative_base

    BASE_DIR = Path(__file__).resolve().parents[2]
    DEFAULT_SQLITE_PATH = BASE_DIR / "iadictador.sqlite3"

    DATABASE_URL = os.getenv("IADICTADOR_DB_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")

    connect_args = {}
    if DATABASE_URL.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    Base = declarative_base()


    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    """)

    write_file(iad_dir / "security.py", r"""
    import hashlib
    import hmac
    import os
    import re
    from datetime import datetime, timezone


    def now_utc():
        return datetime.now(timezone.utc)


    def password_is_valid(password: str) -> tuple[bool, str]:
        if password is None:
            return False, "La clave es obligatoria."

        if len(password) <= 4:
            return False, "La clave debe tener más de 4 caracteres."

        if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", password):
            return False, "La clave debe tener al menos una letra."

        if not re.search(r"\d", password):
            return False, "La clave debe tener al menos un número."

        return True, ""


    def hash_password(password: str) -> str:
        salt = os.urandom(16)
        iterations = 240_000
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


    def verify_password(password: str, encoded: str) -> bool:
        try:
            scheme, iterations_s, salt_hex, hash_hex = encoded.split("$", 3)
            if scheme != "pbkdf2_sha256":
                return False
            iterations = int(iterations_s)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(hash_hex)
            candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(candidate, expected)
        except Exception:
            return False


    def normalize_report_for_copy(text: str) -> str:
        if not text:
            return ""

        text = text.replace("\r\n", "\n").replace("\r", "\n")
        blocks = re.split(r"\n\s*\n+", text)

        normalized_blocks = []
        for block in blocks:
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            if not lines:
                continue
            normalized_blocks.append(" ".join(lines))

        result = "\n\n".join(normalized_blocks)
        result = re.sub(r"[ \t]+", " ", result)
        return result.strip()
    """)

    write_file(iad_dir / "models.py", r"""
    from sqlalchemy import (
        Boolean,
        Column,
        DateTime,
        Float,
        ForeignKey,
        Integer,
        String,
        Text,
        UniqueConstraint,
    )
    from sqlalchemy.orm import relationship

    from .db import Base
    from .security import now_utc


    class User(Base):
        __tablename__ = "iad_users"

        id = Column(Integer, primary_key=True, index=True)
        username = Column(String(80), unique=True, nullable=False, index=True)
        email = Column(String(255), nullable=True, index=True)
        password_hash = Column(String(255), nullable=False)
        role = Column(String(20), nullable=False, default="user")
        is_active = Column(Boolean, nullable=False, default=True)
        must_change_password = Column(Boolean, nullable=False, default=True)

        first_name = Column(String(120), nullable=True)
        last_name = Column(String(120), nullable=True)
        country = Column(String(120), nullable=True)
        timezone = Column(String(120), nullable=True)
        specialty = Column(String(120), nullable=True)
        subspecialty = Column(String(120), nullable=True)
        birthdate = Column(String(20), nullable=True)

        billing_visible = Column(Boolean, nullable=False, default=False)
        billing_enabled = Column(Boolean, nullable=False, default=False)
        price_per_transcription = Column(Float, nullable=True)

        created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)
        updated_at = Column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
        last_login_at = Column(DateTime(timezone=True), nullable=True)
        last_login_ip = Column(String(80), nullable=True)
        last_login_user_agent = Column(Text, nullable=True)

        work_orders = relationship("WorkOrder", back_populates="user")


    class Workplace(Base):
        __tablename__ = "iad_workplaces"

        id = Column(Integer, primary_key=True, index=True)
        name = Column(String(255), nullable=False, unique=True)
        kind = Column(String(80), nullable=True)
        city = Column(String(120), nullable=True)
        country = Column(String(120), nullable=True)
        is_active = Column(Boolean, nullable=False, default=True)
        created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)


    class ReportTemplate(Base):
        __tablename__ = "iad_report_templates"

        id = Column(Integer, primary_key=True, index=True)
        user_id = Column(Integer, ForeignKey("iad_users.id"), nullable=True)
        is_global = Column(Boolean, nullable=False, default=False)

        radiology_use = Column(String(20), nullable=False)
        template_name = Column(String(255), nullable=False)
        title = Column(String(255), nullable=True)
        technique = Column(Text, nullable=True)
        background = Column(Text, nullable=True)
        findings = Column(Text, nullable=True)
        impression = Column(Text, nullable=True)
        tags = Column(Text, nullable=True)
        specific_rules_json = Column(Text, nullable=True)

        created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)
        updated_at = Column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

        __table_args__ = (
            UniqueConstraint("user_id", "template_name", name="uq_iad_template_user_name"),
        )


    class WorkOrder(Base):
        __tablename__ = "iad_work_orders"

        id = Column(Integer, primary_key=True, index=True)
        ot_user_number = Column(Integer, nullable=False, index=True)

        user_id = Column(Integer, ForeignKey("iad_users.id"), nullable=False, index=True)
        workplace_id = Column(Integer, ForeignKey("iad_workplaces.id"), nullable=True)
        template_id = Column(Integer, ForeignKey("iad_report_templates.id"), nullable=True)

        status = Column(String(40), nullable=False, default="draft")

        ip = Column(String(80), nullable=True)
        device = Column(String(120), nullable=True)
        user_agent = Column(Text, nullable=True)
        timezone = Column(String(120), nullable=True)
        utc_offset_minutes = Column(Integer, nullable=True)

        input_type = Column(String(40), nullable=True)
        input_text_final = Column(Text, nullable=True)
        audio_transcription_initial = Column(Text, nullable=True)
        audio_transcription_final = Column(Text, nullable=True)
        clarification_text = Column(Text, nullable=True)

        review_report = Column(Text, nullable=True)
        final_report_initial = Column(Text, nullable=True)
        final_report_accepted = Column(Text, nullable=True)
        final_report_diff = Column(Text, nullable=True)

        patient_first_name = Column(String(120), nullable=True)
        patient_last_name = Column(String(120), nullable=True)
        patient_sex = Column(String(40), nullable=True)
        patient_birthdate = Column(String(20), nullable=True)
        patient_age = Column(String(20), nullable=True)
        hospital_service = Column(String(255), nullable=True)
        report_type = Column(String(80), nullable=True)
        modality = Column(String(20), nullable=True)
        report_title = Column(String(255), nullable=True)

        billing_visible = Column(Boolean, nullable=False, default=False)
        billing_enabled = Column(Boolean, nullable=False, default=False)
        charge_yes_no = Column(Boolean, nullable=False, default=False)
        charge_value = Column(Float, nullable=True)

        created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)
        updated_at = Column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
        validated_at = Column(DateTime(timezone=True), nullable=True)

        user = relationship("User", back_populates="work_orders")


    class OTAudioFile(Base):
        __tablename__ = "iad_ot_audio_files"

        id = Column(Integer, primary_key=True, index=True)
        ot_id = Column(Integer, ForeignKey("iad_work_orders.id"), nullable=False, index=True)
        audio_order = Column(Integer, nullable=False, default=1)
        original_filename = Column(String(255), nullable=True)
        stored_path = Column(Text, nullable=False)
        mime_type = Column(String(120), nullable=True)
        extension = Column(String(40), nullable=True)
        duration_seconds = Column(Float, nullable=True)
        transcription_raw = Column(Text, nullable=True)
        transcription_edited = Column(Text, nullable=True)
        created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)


    class AuditLog(Base):
        __tablename__ = "iad_audit_logs"

        id = Column(Integer, primary_key=True, index=True)
        user_id = Column(Integer, ForeignKey("iad_users.id"), nullable=True, index=True)
        action = Column(String(120), nullable=False)
        detail = Column(Text, nullable=True)
        ip = Column(String(80), nullable=True)
        user_agent = Column(Text, nullable=True)
        created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)
    """)

    write_file(iad_dir / "router.py", r"""
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
    """)

    write_file(templates_dir / "base.html", r"""
    <!doctype html>
    <html lang="es">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{{ app_name }}</title>
      <style>
        :root {
          --bg: #0f1720;
          --panel: #162231;
          --panel-soft: #1f2f43;
          --text: #edf3f8;
          --muted: #9fb1c1;
          --border: rgba(255,255,255,.12);
          --primary: #2bb3c0;
          --secondary: #5576d1;
          --accent: #7dd3fc;
          --danger: #ef4444;
          --warning: #f59e0b;
          --success: #22c55e;
        }

        * { box-sizing: border-box; }

        body {
          margin: 0;
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background:
            radial-gradient(circle at 20% 0%, rgba(43,179,192,.18), transparent 32rem),
            radial-gradient(circle at 80% 10%, rgba(85,118,209,.18), transparent 28rem),
            var(--bg);
          color: var(--text);
        }

        a { color: var(--accent); text-decoration: none; }

        .layout {
          min-height: 100vh;
          display: grid;
          grid-template-columns: 280px 1fr;
        }

        .sidebar {
          background: rgba(12,20,30,.88);
          border-right: 1px solid var(--border);
          padding: 1rem;
          position: sticky;
          top: 0;
          height: 100vh;
          overflow: auto;
        }

        .brand {
          padding: 1rem;
          border-radius: 18px;
          background: linear-gradient(135deg, rgba(43,179,192,.35), rgba(85,118,209,.28));
          border: 1px solid var(--border);
          margin-bottom: 1rem;
        }

        .brand h1 {
          margin: 0;
          font-size: 1.2rem;
          letter-spacing: .03em;
        }

        .brand small { color: var(--muted); }

        .nav a, .nav .box {
          display: block;
          padding: .75rem .85rem;
          border-radius: 12px;
          margin-bottom: .4rem;
          background: rgba(255,255,255,.035);
          border: 1px solid transparent;
          color: var(--text);
        }

        .nav a:hover {
          border-color: var(--border);
          background: rgba(255,255,255,.07);
        }

        .content {
          padding: 1.25rem;
        }

        .banner {
          border: 1px solid var(--border);
          border-radius: 22px;
          padding: 1rem 1.2rem;
          margin-bottom: 1rem;
          background: linear-gradient(90deg, rgba(43,179,192,.28), rgba(85,118,209,.24), rgba(125,211,252,.13));
        }

        .banner h2 {
          margin: 0;
          font-size: 1.35rem;
        }

        .panel {
          background: rgba(22,34,49,.88);
          border: 1px solid var(--border);
          border-radius: 18px;
          padding: 1rem;
          margin-bottom: 1rem;
          box-shadow: 0 14px 40px rgba(0,0,0,.18);
        }

        .grid-2 {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 1rem;
        }

        .grid-3 {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 1rem;
        }

        label {
          display: block;
          font-size: .9rem;
          color: var(--muted);
          margin-bottom: .3rem;
        }

        input, select, textarea {
          width: 100%;
          border: 1px solid var(--border);
          border-radius: 12px;
          padding: .72rem .8rem;
          color: var(--text);
          background: rgba(0,0,0,.22);
          outline: none;
        }

        textarea {
          min-height: 180px;
          resize: vertical;
          line-height: 1.45;
        }

        button, .button {
          border: 0;
          border-radius: 12px;
          padding: .75rem 1rem;
          background: linear-gradient(135deg, var(--primary), var(--secondary));
          color: white;
          cursor: pointer;
          font-weight: 650;
          display: inline-block;
        }

        button.secondary {
          background: rgba(255,255,255,.08);
          border: 1px solid var(--border);
        }

        button.danger {
          background: var(--danger);
        }

        .muted { color: var(--muted); }
        .error { color: #fecaca; background: rgba(239,68,68,.18); border: 1px solid rgba(239,68,68,.3); padding: .75rem; border-radius: 12px; margin-bottom: 1rem; }
        .ok { color: #bbf7d0; background: rgba(34,197,94,.15); border: 1px solid rgba(34,197,94,.3); padding: .75rem; border-radius: 12px; margin-bottom: 1rem; }

        table {
          width: 100%;
          border-collapse: collapse;
        }

        th, td {
          padding: .7rem;
          border-bottom: 1px solid var(--border);
          text-align: left;
          vertical-align: top;
        }

        th { color: var(--muted); font-weight: 600; }

        .top-actions {
          display: flex;
          gap: .6rem;
          flex-wrap: wrap;
          align-items: center;
        }

        .audio-box {
          border: 1px dashed var(--border);
          border-radius: 14px;
          padding: .8rem;
          background: rgba(255,255,255,.035);
        }

        @media (max-width: 900px) {
          .layout {
            grid-template-columns: 1fr;
          }

          .sidebar {
            position: relative;
            height: auto;
          }

          .grid-2, .grid-3 {
            grid-template-columns: 1fr;
          }

          .content {
            padding: .8rem;
          }
        }
      </style>
    </head>
    <body>
      <div class="layout">
        <aside class="sidebar">
          <div class="brand">
            <h1>{{ app_name }}</h1>
            <small>radiología asistida</small>
          </div>

          {% if current_user %}
          <nav class="nav">
            <a href="/iad/trabajo">Área de trabajo</a>
            <a href="/iad/historial">Historial</a>
            {% if current_user.role == "admin" %}
              <a href="/iad/admin/usuarios">Usuarios</a>
            {% endif %}
            <div class="box">
              <strong>{{ current_user.username }}</strong><br>
              <span class="muted">Rol: {{ current_user.role }}</span><br>
              <span class="muted">Requests sesión: {{ request_count }}</span><br>
              {% if current_user.last_login_at %}
                <span class="muted">Último login: {{ current_user.last_login_at.strftime("%Y-%m-%d %H:%M:%S") }}</span>
              {% endif %}
            </div>
            <a href="/iad/logout">Cerrar sesión</a>
          </nav>
          {% endif %}
        </aside>

        <main class="content">
          <div class="banner">
            <h2>{% block title %}{{ app_name }}{% endblock %}</h2>
          </div>
          {% block content %}{% endblock %}
        </main>
      </div>
    </body>
    </html>
    """)

    write_file(templates_dir / "login.html", r"""
    {% extends "iadictador/base.html" %}
    {% block title %}Ingreso{% endblock %}
    {% block content %}
    <div class="panel" style="max-width: 520px;">
      <h3>Ingreso</h3>
      <p class="muted">El ingreso tiene una pausa breve de seguridad.</p>

      {% if error %}
        <div class="error">{{ error }}</div>
      {% endif %}

      <form method="post" action="/iad/login">
        <div>
          <label>Usuario</label>
          <input name="username" autocomplete="username" required>
        </div>
        <br>
        <div>
          <label>Clave</label>
          <input name="password" type="password" autocomplete="current-password" required>
        </div>
        <br>
        <button type="submit">Ingresar</button>
      </form>
    </div>
    {% endblock %}
    """)

    write_file(templates_dir / "change_password.html", r"""
    {% extends "iadictador/base.html" %}
    {% block title %}Cambiar clave{% endblock %}
    {% block content %}
    <div class="panel" style="max-width: 560px;">
      <h3>Cambio obligatorio de clave</h3>
      <p class="muted">La clave debe tener más de 4 caracteres, al menos una letra y al menos un número.</p>

      {% if error %}
        <div class="error">{{ error }}</div>
      {% endif %}

      <form method="post" action="/iad/cambiar-clave">
        <div>
          <label>Nueva clave</label>
          <input name="password1" type="password" required>
        </div>
        <br>
        <div>
          <label>Repetir clave</label>
          <input name="password2" type="password" required>
        </div>
        <br>
        <button type="submit">Guardar clave</button>
      </form>
    </div>
    {% endblock %}
    """)

    write_file(templates_dir / "work.html", r"""
    {% extends "iadictador/base.html" %}
    {% block title %}
      {% if ot %}OT #{{ ot.ot_user_number }}{% else %}Nueva OT{% endif %}
    {% endblock %}

    {% block content %}

    {% if not ot %}
    <form method="post" action="/iad/ot/crear" enctype="multipart/form-data">
      <input type="hidden" name="timezone" id="timezone">
      <input type="hidden" name="utc_offset_minutes" id="utc_offset_minutes">

      <div class="panel">
        <h3>Ingreso</h3>
        <p class="muted">
          Si quiere solo procesar texto, ingrese información y haga click en “Procesar”.
          Si quiere agregar información adicional, complete la segunda sección y use “Procesar con datos extra”.
        </p>

        <div class="grid-2">
          <div class="audio-box">
            <h4>Audio principal</h4>
            <p class="muted">PC: click para grabar. Celular: tap para grabar. También puede subir archivo de audio.</p>
            <input id="audio_file" name="audio_file" type="file" accept="audio/*">
            <br><br>
            <div class="top-actions">
              <button type="button" class="secondary" id="audio_start">Grabar</button>
              <button type="button" class="secondary" id="audio_stop" disabled>Finalizar audio</button>
            </div>
            <p class="muted" id="audio_status"></p>
          </div>

          <div class="audio-box">
            <h4>Audio de aclaración</h4>
            <p class="muted">Opcional. Se guarda como segundo audio asociado a la OT.</p>
            <input id="clarification_audio_file" name="clarification_audio_file" type="file" accept="audio/*">
            <br><br>
            <div class="top-actions">
              <button type="button" class="secondary" id="clar_start">Grabar aclaración</button>
              <button type="button" class="secondary" id="clar_stop" disabled>Finalizar aclaración</button>
            </div>
            <p class="muted" id="clar_status"></p>
          </div>
        </div>

        <br>

        <label>1) Información principal para el informe</label>
        <textarea name="input_text_final" placeholder="Ingrese o pegue aquí la información principal. La transcripción de audio quedará aquí cuando se conecte el motor de transcripción."></textarea>

        <br><br>

        <label>Aclaración textual opcional</label>
        <textarea name="clarification_text" placeholder="Ingrese aquí una aclaración adicional si corresponde."></textarea>

        <br><br>
        <button type="submit">Procesar</button>
      </div>

      <div class="panel">
        <h3>2) Información extra</h3>
        <p class="muted">Opcional. Si se completa, se guarda junto a la OT y se usará para procesar con contexto.</p>

        <div class="grid-3">
          <div>
            <label>Lugar de trabajo</label>
            <select name="workplace_id">
              <option value="">Sin especificar</option>
              {% for w in workplaces %}
              <option value="{{ w.id }}">{{ w.name }}</option>
              {% endfor %}
            </select>
          </div>

          <div>
            <label>Plantilla</label>
            <select name="template_id">
              <option value="">Sin plantilla</option>
              {% for t in templates %}
              <option value="{{ t.id }}">{{ t.radiology_use }} · {{ t.template_name }}</option>
              {% endfor %}
            </select>
          </div>

          <div>
            <label>Modalidad</label>
            <select name="modality">
              <option value="">Sin especificar</option>
              <option value="TC">TC</option>
              <option value="MR">MR</option>
              <option value="US">US</option>
              <option value="RX">RX</option>
              <option value="XA">XA</option>
            </select>
          </div>
        </div>

        <br>

        <div class="grid-3">
          <div>
            <label>Nombre paciente</label>
            <input name="patient_first_name">
          </div>
          <div>
            <label>Apellido paciente</label>
            <input name="patient_last_name">
          </div>
          <div>
            <label>Sexo</label>
            <select name="patient_sex">
              <option value="">Sin especificar</option>
              <option value="F">F</option>
              <option value="M">M</option>
              <option value="Otro">Otro</option>
            </select>
          </div>
        </div>

        <br>

        <div class="grid-3">
          <div>
            <label>Fecha nacimiento</label>
            <input name="patient_birthdate" placeholder="AAAA-MM-DD">
          </div>
          <div>
            <label>Edad</label>
            <input name="patient_age">
          </div>
          <div>
            <label>Tipo de informe</label>
            <select name="report_type">
              <option value="">Sin especificar</option>
              <option value="ambulatorio">Ambulatorio</option>
              <option value="urgencia">Urgencia</option>
              <option value="oncologico">Oncológico</option>
              <option value="hospitalizado">Hospitalizado</option>
            </select>
          </div>
        </div>

        <br>

        <div class="grid-2">
          <div>
            <label>Hospital, clínica o servicio</label>
            <input name="hospital_service">
          </div>
          <div>
            <label>Título informe</label>
            <input name="report_title">
          </div>
        </div>

        <br>
        <button type="submit">Procesar con datos extra</button>
      </div>
    </form>
    {% else %}

    <div class="panel">
      <h3>OT #{{ ot.ot_user_number }}</h3>
      <p class="muted">
        Estado: {{ ot.status }} · Creada: {{ ot.created_at.strftime("%Y-%m-%d %H:%M:%S") }}
        {% if ot.validated_at %} · Validada: {{ ot.validated_at.strftime("%Y-%m-%d %H:%M:%S") }}{% endif %}
      </p>
    </div>

    <div class="panel">
      <h3>Revisión</h3>
      <textarea readonly>{{ ot.review_report or "" }}</textarea>
    </div>

    <div class="panel">
      <h3>Resultado</h3>
      <form id="save-copy-form" method="post" action="/iad/ot/{{ ot.id }}/guardar-copiar">
        <label>Informe limpio final editable</label>
        <textarea id="final_report_accepted" name="final_report_accepted">{{ ot.final_report_accepted or ot.final_report_initial or "" }}</textarea>
        <br><br>
        <button type="submit">Guardar y copiar informe final</button>
        <a class="button secondary" href="/iad/historial">Volver al historial</a>
      </form>
      <p class="muted" id="copy_status"></p>
    </div>

    <script>
      const form = document.getElementById("save-copy-form");
      const copyStatus = document.getElementById("copy_status");

      form.addEventListener("submit", async function(e) {
        e.preventDefault();
        const fd = new FormData(form);
        const res = await fetch(form.action, { method: "POST", body: fd });
        const text = await res.text();

        if (!res.ok) {
          copyStatus.textContent = "No se pudo guardar la OT.";
          return;
        }

        try {
          await navigator.clipboard.writeText(text);
          copyStatus.textContent = "OT guardada, validada y copiada al portapapeles.";
        } catch (err) {
          copyStatus.textContent = "OT guardada y validada. No se pudo copiar automáticamente; copie manualmente.";
        }
      });

      window.addEventListener("beforeunload", function(e) {
        const otStatus = "{{ ot.status }}";
        if (otStatus !== "validated") {
          e.preventDefault();
          e.returnValue = "";
        }
      });
    </script>

    {% endif %}

    <script>
      try {
        document.getElementById("timezone").value = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
        document.getElementById("utc_offset_minutes").value = String(-new Date().getTimezoneOffset());
      } catch (e) {}

      function setupRecorder(prefix, inputId) {
        const startBtn = document.getElementById(prefix + "_start");
        const stopBtn = document.getElementById(prefix + "_stop");
        const status = document.getElementById(prefix + "_status");
        const input = document.getElementById(inputId);

        if (!startBtn || !stopBtn || !status || !input) return;

        let mediaRecorder = null;
        let chunks = [];

        startBtn.addEventListener("click", async () => {
          if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            status.textContent = "Grabación no disponible en este navegador. Use subida de archivo.";
            return;
          }

          try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            chunks = [];
            mediaRecorder = new MediaRecorder(stream);
            mediaRecorder.ondataavailable = e => chunks.push(e.data);
            mediaRecorder.onstop = () => {
              const blob = new Blob(chunks, { type: "audio/webm" });
              const file = new File([blob], prefix + "_grabacion.webm", { type: "audio/webm" });
              const dt = new DataTransfer();
              dt.items.add(file);
              input.files = dt.files;
              stream.getTracks().forEach(t => t.stop());
              status.textContent = "Audio listo para subir.";
            };

            mediaRecorder.start();
            startBtn.disabled = true;
            stopBtn.disabled = false;
            status.textContent = "Grabando...";
          } catch (err) {
            status.textContent = "No se pudo iniciar la grabación.";
          }
        });

        stopBtn.addEventListener("click", () => {
          if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
          }
          startBtn.disabled = false;
          stopBtn.disabled = true;
        });
      }

      setupRecorder("audio", "audio_file");
      setupRecorder("clar", "clarification_audio_file");
    </script>

    {% endblock %}
    """)

    write_file(templates_dir / "history.html", r"""
    {% extends "iadictador/base.html" %}
    {% block title %}Historial{% endblock %}
    {% block content %}

    <div class="panel">
      <h3>Historial</h3>
      <p class="muted">
        Las OT históricas son trazabilidad. Si necesita modificar una, luego agregaremos botón para duplicar y crear una nueva OT.
      </p>
    </div>

    <div class="panel">
      <table>
        <thead>
          <tr>
            <th># OT</th>
            {% if admin_view %}<th>Usuario</th>{% endif %}
            <th>Timestamp</th>
            <th>Tipo</th>
            <th>Modalidad</th>
            <th>Título</th>
            <th>Paciente</th>
            <th>Edad</th>
            <th>Estado</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {% for ot in ots %}
          <tr>
            <td>{{ ot.ot_user_number }}</td>
            {% if admin_view %}<td>{{ ot.user.username if ot.user else "" }}</td>{% endif %}
            <td>{{ ot.created_at.strftime("%Y-%m-%d %H:%M:%S") }}</td>
            <td>{{ ot.report_type or "" }}</td>
            <td>{{ ot.modality or "" }}</td>
            <td>{{ ot.report_title or "" }}</td>
            <td>{{ (ot.patient_last_name or "") }} {{ (ot.patient_first_name or "") }}</td>
            <td>{{ ot.patient_age or "" }}</td>
            <td>{{ ot.status }}</td>
            <td><a href="/iad/ot/{{ ot.id }}">Abrir</a></td>
          </tr>
          {% else %}
          <tr><td colspan="10">Sin OT guardadas.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    {% endblock %}
    """)

    write_file(templates_dir / "admin_users.html", r"""
    {% extends "iadictador/base.html" %}
    {% block title %}Usuarios{% endblock %}
    {% block content %}

    <div class="panel">
      <h3>Crear usuario</h3>
      {% if error %}
        <div class="error">{{ error }}</div>
      {% endif %}

      <form method="post" action="/iad/admin/usuarios/crear">
        <div class="grid-3">
          <div>
            <label>Usuario</label>
            <input name="username" required>
          </div>
          <div>
            <label>Email</label>
            <input name="email" type="email">
          </div>
          <div>
            <label>Rol</label>
            <select name="role">
              <option value="user">user</option>
              <option value="admin">admin</option>
            </select>
          </div>
        </div>
        <br>
        <div class="grid-2">
          <div>
            <label>Clave temporal</label>
            <input name="password" required>
          </div>
          <div>
            <label>&nbsp;</label>
            <button type="submit">Crear usuario</button>
          </div>
        </div>
        <p class="muted">La clave debe tener más de 4 caracteres, al menos una letra y al menos un número. El usuario deberá cambiarla en el primer ingreso.</p>
      </form>
    </div>

    <div class="panel">
      <h3>Usuarios</h3>
      <table>
        <thead>
          <tr>
            <th>Usuario</th>
            <th>Rol</th>
            <th>Activo</th>
            <th>Cobro visible</th>
            <th>Cobro habilitado</th>
            <th>Valor</th>
            <th>Reset clave</th>
            <th>Acciones</th>
          </tr>
        </thead>
        <tbody>
          {% for u in users %}
          <tr>
            <td>{{ u.username }}</td>
            <td>{{ u.role }}</td>
            <td>{{ "sí" if u.is_active else "no" }}</td>
            <td>{{ "sí" if u.billing_visible else "no" }}</td>
            <td>{{ "sí" if u.billing_enabled else "no" }}</td>
            <td>{{ u.price_per_transcription or "" }}</td>
            <td>
              <form method="post" action="/iad/admin/usuarios/{{ u.id }}/reset">
                <input name="password" placeholder="nueva clave">
                <button type="submit" class="secondary">Reset</button>
              </form>
            </td>
            <td>
              <form method="post" action="/iad/admin/usuarios/{{ u.id }}/toggle" style="margin-bottom:.4rem;">
                <button type="submit" class="secondary">{{ "Deshabilitar" if u.is_active else "Habilitar" }}</button>
              </form>

              <form method="post" action="/iad/admin/usuarios/{{ u.id }}/billing">
                <label><input type="checkbox" name="billing_visible" {% if u.billing_visible %}checked{% endif %}> Ver cobro</label>
                <label><input type="checkbox" name="billing_enabled" {% if u.billing_enabled %}checked{% endif %}> Cobrar</label>
                <input name="price_per_transcription" value="{{ u.price_per_transcription or "" }}" placeholder="valor">
                <button type="submit" class="secondary">Guardar cobro</button>
              </form>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    {% endblock %}
    """)

    write_file(rules_dir / "general_rules.json", json.dumps({
        "name": "general_rules",
        "description": "Reglas generales iniciales de IA Dictador.",
        "rules": [
            {
                "id": "remove_test_phrases",
                "severity": "warning",
                "description": "Evitar que frases de prueba aparezcan en producción.",
                "phrases": TEST_PHRASES_TO_REMOVE,
                "active": True
            }
        ]
    }, ensure_ascii=False, indent=2))

    write_file(rules_dir / "sex_anatomy_rules.json", json.dumps({
        "name": "sex_anatomy_rules",
        "description": "Reglas sexo/anatomía para advertencias futuras.",
        "rules": [
            {
                "id": "female_with_prostate",
                "severity": "critical",
                "patient_sex": "F",
                "forbidden_terms": ["próstata", "prostata", "vesículas seminales", "vesiculas seminales"],
                "message": "Paciente femenino con término anatómico masculino.",
                "active": True
            },
            {
                "id": "male_with_uterus_ovaries",
                "severity": "critical",
                "patient_sex": "M",
                "forbidden_terms": ["útero", "utero", "ovario", "ovarios", "endometrio"],
                "message": "Paciente masculino con término anatómico femenino.",
                "active": True
            }
        ]
    }, ensure_ascii=False, indent=2))


def patch_main_file(main_file: Path):
    print_header("PATCH MAIN.PY")

    txt = main_file.read_text(encoding="utf-8", errors="ignore")

    marker = "# --- IA DICTADOR STAGE 1 INTEGRATION ---"
    if marker in txt:
        print(f"main.py ya tiene integración IA Dictador: {main_file}")
        return

    block = r'''

# --- IA DICTADOR STAGE 1 INTEGRATION ---
try:
    import os as _iad_os
    from starlette.middleware.sessions import SessionMiddleware as _IADSessionMiddleware

    try:
        from iadictador.router import router as _iadictador_router, init_iadictador as _init_iadictador
    except Exception:
        from backend.iadictador.router import router as _iadictador_router, init_iadictador as _init_iadictador

    _iad_secret = (
        _iad_os.getenv("IADICTADOR_SESSION_SECRET")
        or _iad_os.getenv("SESSION_SECRET")
        or _iad_os.getenv("ANGIOPACS_SESSION_SECRET")
        or "iadictador_dev_secret_change_me"
    )

    if not any(getattr(m, "cls", None) is _IADSessionMiddleware for m in getattr(app, "user_middleware", [])):
        app.add_middleware(_IADSessionMiddleware, secret_key=_iad_secret)

    _init_iadictador()

    if not getattr(app.state, "iadictador_router_loaded", False):
        app.include_router(_iadictador_router)
        app.state.iadictador_router_loaded = True

except Exception as _iad_e:
    print("IA Dictador no pudo iniciar:", repr(_iad_e))
# --- END IA DICTADOR STAGE 1 INTEGRATION ---
'''

    main_file.write_text(txt.rstrip() + "\n" + block + "\n", encoding="utf-8")
    print(f"Integración agregada a: {main_file}")


def main():
    print_header("IA DICTADOR STAGE 1")
    print(f"Raíz detectada: {ROOT}")

    backend_dir = detect_backend_dir()
    main_file = detect_main_file(backend_dir)

    print(f"Backend detectado: {backend_dir}")
    print(f"main.py detectado: {main_file}")

    make_backup()
    create_iadictador_module(backend_dir)
    patch_main_file(main_file)
    patch_text_replacements()

    print_header("RESUMEN")
    print("Stage 1 aplicado.")
    print("Rutas nuevas principales:")
    print("  /iad/login")
    print("  /iad/trabajo")
    print("  /iad/historial")
    print("  /iad/admin/usuarios")
    print()
    print("Usuario admin inicial por defecto:")
    print("  usuario: admin")
    print("  clave:   admin1")
    print("Debe cambiar clave en el primer ingreso.")
    print()
    print("Si quieres definir otro admin inicial, usa variables:")
    print("  IADICTADOR_ADMIN_USER")
    print("  IADICTADOR_ADMIN_PASSWORD")
    print()
    print("Regla de clave activa:")
    print("  >4 caracteres, al menos 1 letra, al menos 1 número")
    print()
    print("#######################################")
    print("######    FIN INPUT    ###############")
    print("#######################################")


if __name__ == "__main__":
    main()
