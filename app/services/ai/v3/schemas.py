from __future__ import annotations

from typing import Any


V3_OUTPUT_SCHEMA_EXAMPLE: dict[str, Any] = {
    "ok": True,
    "transcripcion": "",
    "plantilla_sugerida": {
        "id": "",
        "nombre": "",
        "confianza": "alta|media|baja",
        "motivo": ""
    },
    "hallazgos_radiologicos": "",
    "hallazgos_estructurados": [
        {
            "region": "",
            "hallazgo": "",
            "medida": "",
            "lateralidad": "",
            "estado": "positivo|negativo|dudoso|no_mencionado",
            "accion_en_plantilla": "conservar|reemplazar|insertar|eliminar|advertir",
            "debe_ir_en_impresion": True
        }
    ],
    "impresion_diagnostica": "",
    "informe_final": "",
    "advertencias": [],
    "posibles_omisiones": [],
    "metodo": "iad_v3_report_bridge"
}


def required_output_keys() -> list[str]:
    return [
        "ok",
        "transcripcion",
        "plantilla_sugerida",
        "hallazgos_radiologicos",
        "hallazgos_estructurados",
        "impresion_diagnostica",
        "informe_final",
        "advertencias",
        "posibles_omisiones",
        "metodo",
    ]


def normalize_v3_output(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}

    data["ok"] = bool(data.get("ok", True))

    for key in required_output_keys():
        if key not in data:
            if key in {"advertencias", "posibles_omisiones", "hallazgos_estructurados"}:
                data[key] = []
            elif key == "plantilla_sugerida":
                data[key] = {}
            elif key == "metodo":
                data[key] = "iad_v3_report_bridge"
            else:
                data[key] = ""

    if not isinstance(data.get("advertencias"), list):
        data["advertencias"] = [str(data.get("advertencias"))]

    if not isinstance(data.get("posibles_omisiones"), list):
        data["posibles_omisiones"] = [str(data.get("posibles_omisiones"))]

    if not isinstance(data.get("hallazgos_estructurados"), list):
        data["hallazgos_estructurados"] = []

    if not isinstance(data.get("plantilla_sugerida"), dict):
        data["plantilla_sugerida"] = {}

    data["metodo"] = data.get("metodo") or "iad_v3_report_bridge"
    return data
