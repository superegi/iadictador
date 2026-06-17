import os

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.iadictador.router import router as iadictador_router
from app.iadictador.router import init_iadictador
from app.iadictador.models import Workplace
from app.iadictador.db import engine
from sqlalchemy import inspect, text
from app.iad_review import router as iad_review_router




ENABLE_DOCS = os.getenv("IADICTADOR_ENABLE_DOCS", "1").strip().lower() in {"1", "true", "yes", "on"}
DOCS_URL = "/docs" if ENABLE_DOCS else None
REDOC_URL = "/redoc" if ENABLE_DOCS else None
OPENAPI_URL = "/openapi.json" if ENABLE_DOCS else None

def ensure_iad_template_schema():
    inspector = inspect(engine)
    if "iad_report_templates" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("iad_report_templates")}

    with engine.begin() as conn:
        dialect = engine.dialect.name

        if "body_region" not in cols:
            conn.execute(text("ALTER TABLE iad_report_templates ADD COLUMN body_region VARCHAR"))

        if "is_shared" not in cols:
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE iad_report_templates ADD COLUMN is_shared BOOLEAN DEFAULT false"))
            else:
                conn.execute(text("ALTER TABLE iad_report_templates ADD COLUMN is_shared BOOLEAN DEFAULT 0"))

        # Migración semántica: is_global viejo pasa a is_shared, pero cada plantilla mantiene dueño.
        try:
            if dialect == "postgresql":
                conn.execute(text("UPDATE iad_report_templates SET is_shared = true WHERE is_global = true AND is_shared = false"))
            else:
                conn.execute(text("UPDATE iad_report_templates SET is_shared = 1 WHERE is_global = 1 AND is_shared = 0"))
        except Exception:
            pass







# IAD_TEMPLATE_SCHEMA_HELPER_START
def ensure_iad_template_schema():
    inspector = inspect(engine)
    if "iad_report_templates" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("iad_report_templates")}

    with engine.begin() as conn:
        dialect = engine.dialect.name

        if "body_region" not in cols:
            conn.execute(text("ALTER TABLE iad_report_templates ADD COLUMN body_region VARCHAR"))
            cols.add("body_region")

        if "is_shared" not in cols:
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE iad_report_templates ADD COLUMN is_shared BOOLEAN DEFAULT false"))
            else:
                conn.execute(text("ALTER TABLE iad_report_templates ADD COLUMN is_shared BOOLEAN DEFAULT 0"))
            cols.add("is_shared")

        if "imported_at" not in cols:
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE iad_report_templates ADD COLUMN imported_at TIMESTAMP"))
            else:
                conn.execute(text("ALTER TABLE iad_report_templates ADD COLUMN imported_at DATETIME"))
            cols.add("imported_at")

        if "import_source" not in cols:
            conn.execute(text("ALTER TABLE iad_report_templates ADD COLUMN import_source VARCHAR"))
            cols.add("import_source")

        try:
            if "is_global" in cols and "is_shared" in cols:
                if dialect == "postgresql":
                    conn.execute(text("UPDATE iad_report_templates SET is_shared = true WHERE is_global = true AND is_shared = false"))
                else:
                    conn.execute(text("UPDATE iad_report_templates SET is_shared = 1 WHERE is_global = 1 AND is_shared = 0"))
        except Exception:
            pass

        for col in [
            "title",
            "technique",
            "background",
            "findings",
            "impression",
            "specific_rules_json",
            "tags",
            "body_region",
            "import_source",
        ]:
            if col in cols:
                try:
                    conn.execute(text(f"UPDATE iad_report_templates SET {col} = NULL WHERE lower(trim(CAST({col} AS TEXT))) = 'none'"))
                except Exception:
                    pass

        if "imported_at" in cols:
            try:
                conn.execute(text("UPDATE iad_report_templates SET imported_at = CURRENT_TIMESTAMP WHERE imported_at IS NULL"))
            except Exception:
                pass

        if "import_source" in cols:
            try:
                conn.execute(text("UPDATE iad_report_templates SET import_source = 'manual' WHERE import_source IS NULL OR trim(import_source) = ''"))
            except Exception:
                pass
# IAD_TEMPLATE_SCHEMA_HELPER_END



# IAD_WORKPLACE_SCHEMA_HELPER_START
def ensure_iad_workplace_schema():
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    try:
        table = Workplace.__tablename__
    except Exception:
        table = "iad_workplaces"

    if table not in tables:
        return

    cols = {c["name"] for c in inspector.get_columns(table)}

    with engine.begin() as conn:
        if "tariffs_json" not in cols:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN tariffs_json TEXT"))
            cols.add("tariffs_json")

        # Limpieza defensiva de valores literales None.
        if "tariffs_json" in cols:
            try:
                conn.execute(text(f"UPDATE {table} SET tariffs_json = NULL WHERE lower(trim(CAST(tariffs_json AS TEXT))) = 'none'"))
            except Exception:
                pass
# IAD_WORKPLACE_SCHEMA_HELPER_END


app = FastAPI(
    docs_url=DOCS_URL,
    redoc_url=REDOC_URL,
    openapi_url=OPENAPI_URL,title="IA Dictador")

app.mount("/static", StaticFiles(directory="app/static"), name="static")


_session_secret = (
    os.getenv("IADICTADOR_SESSION_SECRET")
    or os.getenv("SESSION_SECRET")
    or os.getenv("ANGIOPACS_SESSION_SECRET")
    or "iadictador_dev_secret_change_me"
)

app.add_middleware(SessionMiddleware, secret_key=_session_secret)


@app.get("/")
async def root():
    return RedirectResponse("/iad/trabajo", status_code=303)


@app.post("/process")
async def legacy_process_disabled():
    return RedirectResponse("/iad/trabajo", status_code=303)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "iadictador",
        "ai_provider": os.getenv("AI_PROVIDER", "rules"),
        "openai_model": os.getenv("OPENAI_MODEL", ""),
    }


ensure_iad_template_schema()
init_iadictador()
app.include_router(iadictador_router)

# IA Dictador - modo revisión demo
app.include_router(iad_review_router)

# IA Dictador V3 - reglas editables y endpoint paralelo limpio
from app.iadictador.rules_router import router as iad_rules_router
from app.iadictador.rules_repo_router import router as iad_rules_repo_router
from app.iadictador.v4_trace_router import router as iad_v4_trace_router
from app.iadictador.v3_audio_router import router as iad_v3_audio_router

app.include_router(iad_rules_router)
app.include_router(iad_rules_repo_router)
app.include_router(iad_v4_trace_router)
app.include_router(iad_v3_audio_router)
