import os

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.services.rule_interpreter import interpret_rules
from app.services.template_engine import build_report, load_template


app = FastAPI(title="IA Dictador")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def interpret_dictation(dictado_bruto: str, template: dict):
    provider = os.getenv("AI_PROVIDER", "rules").strip().lower()

    if not dictado_bruto.strip():
        return {
            "dictado_normalizado": "",
            "actions": [],
            "global_warnings": [],
            "provider": provider,
        }

    if provider in ["gpt", "openai"]:
        try:
            from app.services.gpt_interpreter import interpret_gpt
            return interpret_gpt(dictado_bruto, template)
        except Exception as exc:
            fallback = interpret_rules(dictado_bruto)
            fallback.setdefault("global_warnings", [])
            fallback["global_warnings"].insert(
                0,
                f"GPT falló y se usaron reglas locales como fallback: {exc}"
            )
            fallback["provider"] = "rules_fallback"
            return fallback

    result = interpret_rules(dictado_bruto)
    result["provider"] = "rules"
    return result


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    template = load_template("tc_tap_cc")
    result = build_report(template)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "dictado_bruto": "",
            "result": result,
            "actions": [],
            "processed": False,
            "provider": os.getenv("AI_PROVIDER", "rules"),
        },
    )


@app.post("/process", response_class=HTMLResponse)
async def process(request: Request, dictado_bruto: str = Form("")):
    template = load_template("tc_tap_cc")
    interpretation = interpret_dictation(dictado_bruto, template)
    result = build_report(template, interpretation)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "dictado_bruto": dictado_bruto,
            "result": result,
            "actions": interpretation.get("actions", []),
            "processed": True,
            "provider": interpretation.get("provider", os.getenv("AI_PROVIDER", "rules")),
        },
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "ai_provider": os.getenv("AI_PROVIDER", "rules"),
        "openai_model": os.getenv("OPENAI_MODEL", ""),
    }


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

