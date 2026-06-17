from __future__ import annotations

import re
from typing import Any


def validate_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    warnings = payload.get("advertencias")
    if not isinstance(warnings, list):
        warnings = []

    report = str(payload.get("informe_final") or "")
    impression = str(payload.get("impresion_diagnostica") or "")
    findings = payload.get("hallazgos_estructurados")
    if not isinstance(findings, list):
        findings = []

    if not report.strip():
        warnings.append("V3: informe_final vacío.")

    if "xxxxx" in report.lower() or "xxxxxxxx" in report.lower():
        warnings.append("V3: el informe final aún contiene separadores xxxxx.")

    contradictory_pairs = [
        ("hígado", "lesión hepática"),
        ("higado", "lesion hepatica"),
        ("riñones", "litiasis"),
        ("vesícula", "colelitiasis"),
        ("vesicula", "colelitiasis"),
        ("corazón", "cardiomegalia"),
        ("corazon", "cardiomegalia"),
    ]

    low_report = report.lower()
    for normal_region, positive in contradictory_pairs:
        if positive in low_report and re.search(rf"{normal_region}.{{0,120}}sin alteraciones", low_report):
            warnings.append(
                f"V3: posible contradicción: se menciona '{positive}' y también normalidad de {normal_region}."
            )

    for item in findings:
        if not isinstance(item, dict):
            continue
        hallazgo = str(item.get("hallazgo") or "").strip()
        debe_ir = item.get("debe_ir_en_impresion")
        if hallazgo and debe_ir is True:
            token = hallazgo.lower().split()[0]
            if token and token not in impression.lower():
                warnings.append(
                    f"V3: verificar impresión: hallazgo estructurado '{hallazgo}' podría no estar representado."
                )

    payload["advertencias"] = warnings
    return payload
