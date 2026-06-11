from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.services.rule_interpreter import interpret_rules
from app.services.template_engine import build_report, load_template


app = FastAPI(title="Reporte IA Prototype")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


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
        },
    )


@app.post("/process", response_class=HTMLResponse)
async def process(request: Request, dictado_bruto: str = Form("")):
    template = load_template("tc_tap_cc")
    interpretation = interpret_rules(dictado_bruto)
    result = build_report(template, interpretation)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "dictado_bruto": dictado_bruto,
            "result": result,
            "actions": interpretation.get("actions", []),
            "processed": True,
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
