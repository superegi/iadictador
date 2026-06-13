# Copia transferible extraida desde app/services/ai/tasks/audio_first_flow.py
# Nota: hoy runtime aun usa audio_first_flow.py; esta copia sirve para exportar/auditar/refactorizar.

# IAD_SMART_TEMPLATE_EDITOR_V1
# Editor inteligente recuperable/transferible.
# Orden esperado:
#   audio/transcripción -> extracción JSON -> puente IA/determinístico -> editor inteligente final.
# Si el editor inteligente falla, se conserva el resultado anterior.

try:
    import os as _iad_smart_os
    import json as _iad_smart_json
    import re as _iad_smart_re
    from pathlib import Path as _iad_smart_Path
except Exception:
    _iad_smart_os = None
    _iad_smart_json = None
    _iad_smart_re = None
    _iad_smart_Path = None


def _iad_smart_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return _iad_smart_json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _iad_smart_norm(value):
    s = _iad_smart_text(value).lower()
    repl = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ü": "u", "ñ": "n"
    }
    for a, b in repl.items():
        s = s.replace(a, b)
    if _iad_smart_re:
        s = _iad_smart_re.sub(r"\s+", " ", s).strip()
    else:
        s = " ".join(s.split())
    return s


def _iad_smart_read_prompt():
    try:
        p = _iad_smart_Path("app/services/ai/prompts/audio_first_smart_template_editor.md")
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass

    return (
        "Eres editor radiológico. Conserva la plantilla completa, "
        "inserta hallazgos dictados, reemplaza solo contradicciones, "
        "no resumas y responde JSON válido."
    )


def _iad_smart_find_template(parsed, result=None, db=None):
    result = result if isinstance(result, dict) else {}

    candidates = []
    if isinstance(result, dict):
        candidates.append(result)
    if isinstance(parsed, dict):
        candidates.append(parsed)

    for obj in candidates:
        try:
            tpl = _iad_audio_first_pick_template(obj, db=db)
            if tpl and tpl.get("contenido"):
                return tpl
        except Exception:
            pass

        try:
            tpl = _iad_v2_pick_template(obj, db=db)
            if tpl and tpl.get("contenido"):
                return tpl
        except Exception:
            pass

    return {}


def _iad_smart_collect_training_examples(db=None, template_name="", limit=3):
    if db is None:
        return []

    examples = []
    try:
        from sqlalchemy import text as _sa_text

        rows = db.execute(
            _sa_text("""
                SELECT texto_dictado, plantilla_nombre, hallazgos_detectados, resultado_primario, resultado_revisado, metadata_json
                FROM iad_training_samples
                WHERE resultado_revisado IS NOT NULL
                  AND TRIM(resultado_revisado) != ''
                ORDER BY id DESC
                LIMIT :limit
            """),
            {"limit": int(limit)},
        ).fetchall()

        for r in rows:
            d = {
                "texto_dictado": r[0] or "",
                "plantilla_nombre": r[1] or "",
                "hallazgos_detectados": r[2] or "",
                "resultado_primario": r[3] or "",
                "resultado_revisado": r[4] or "",
            }
            if template_name:
                if _iad_smart_norm(template_name) not in _iad_smart_norm(d["plantilla_nombre"]):
                    continue
            examples.append(d)
    except Exception:
        return []

    return examples[:limit]


def _iad_smart_template_shape_score(report, template_text):
    report = _iad_smart_text(report).strip()
    template_text = _iad_smart_text(template_text).strip()

    if not report or not template_text:
        return 0

    rn = _iad_smart_norm(report)
    tn = _iad_smart_norm(template_text)

    score = 0

    # Longitud relativa.
    if len(report) >= len(template_text) * 0.55:
        score += 30
    elif len(report) >= len(template_text) * 0.35:
        score += 15

    # Secciones.
    for token in ["tecnica", "hallazgos", "torax", "tórax", "abdomen", "pelvis", "impresion", "impresión", "conclusion", "conclusión"]:
        if _iad_smart_norm(token) in rn:
            score += 6

    # Líneas conservadas desde plantilla.
    tpl_lines = [
        _iad_smart_norm(x)
        for x in template_text.splitlines()
        if len(_iad_smart_norm(x)) >= 18
    ][:40]

    shared = 0
    for line in tpl_lines:
        fragment = line[:70]
        if fragment and fragment in rn:
            shared += 1

    score += min(shared * 4, 40)

    # Penaliza resumen demasiado corto.
    if len(report) < 350:
        score -= 35

    return max(0, min(score, 100))


def _iad_smart_extract_json(raw):
    if isinstance(raw, dict):
        return raw

    text = _iad_smart_text(raw).strip()
    if not text:
        return {}

    try:
        return _iad_smart_json.loads(text)
    except Exception:
        pass

    if _iad_smart_re:
        m = _iad_smart_re.search(r"\{.*\}", text, flags=_iad_smart_re.S)
        if m:
            try:
                return _iad_smart_json.loads(m.group(0))
            except Exception:
                pass

    return {}


def _iad_smart_build_prompt(parsed, result, template, metadata, examples):
    template_name = template.get("nombre") or template.get("template_name") or ""
    template_text = template.get("contenido") or template.get("template_text") or template.get("text") or ""

    report_model = (
        result.get("informe_final_modelo")
        or result.get("informe_ia_original")
        or ""
    )

    report_deterministic = (
        result.get("informe_final")
        or result.get("final_report")
        or ""
    )

    source = "\n".join(
        x for x in [
            "TRANSCRIPCION:",
            _iad_smart_text(parsed.get("transcripcion") or parsed.get("transcription") or parsed.get("raw_audio_first_text") or ""),
            "",
            "HALLAZGOS RADIOLOGICOS EXTRAIDOS:",
            _iad_smart_text(parsed.get("hallazgos_radiologicos") or result.get("hallazgos_radiologicos") or ""),
            "",
            "JSON PARCIAL AUDIO-FIRST:",
            _iad_smart_text(parsed),
        ]
        if x is not None
    )

    payload = {
        "instrucciones_base": _iad_smart_read_prompt(),
        "plantilla_detectada": {
            "id": template.get("id") or "",
            "nombre": template_name,
            "contenido_completo": template_text,
        },
        "dictado_y_extraccion": source,
        "informe_previo_ia_si_existe": report_model,
        "informe_base_deterministico_fallback": report_deterministic,
        "metadata": metadata or {},
        "ejemplos_correcciones_previas": examples or [],
        "tarea": (
            "Genera un informe final inteligente usando la plantilla completa como molde. "
            "No hagas resumen libre. Usa el informe determinístico solo como respaldo para no perder hallazgos. "
            "Usa el informe IA previo solo si aporta redacción inteligente. "
            "Devuelve JSON válido con informe_final, hallazgos_estructurados, mapa_aplicacion, advertencias y confianza."
        ),
    }

    return _iad_smart_json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _iad_smart_apply_editor(client, parsed, result, metadata=None, db=None, source_label=""):
    if not isinstance(result, dict):
        return result

    if not isinstance(parsed, dict):
        parsed = {"raw": _iad_smart_text(parsed)}

    try:
        enabled = (_iad_smart_os.getenv("IAD_SMART_TEMPLATE_EDITOR", "1") or "1").strip().lower()
        if enabled in {"0", "false", "no", "off"}:
            result["intelligence_editor"] = {"ok": False, "reason": "disabled_env"}
            return result
    except Exception:
        pass

    template = _iad_smart_find_template(parsed, result=result, db=db)
    if not template or not template.get("contenido"):
        result["intelligence_editor"] = {"ok": False, "reason": "no_template"}
        return result

    current_report = _iad_smart_text(result.get("informe_final") or result.get("final_report") or "")
    template_text = _iad_smart_text(template.get("contenido") or "")

    before_score = _iad_smart_template_shape_score(current_report, template_text)

    model = (
        _iad_smart_os.getenv("IAD_AI_MODEL_AUDIO_FIRST_SMART_EDITOR")
        or _iad_smart_os.getenv("IAD_AI_MODEL_AUDIO_FIRST_TEMPLATE_BRIDGE")
        or _iad_smart_os.getenv("IAD_AI_MODEL_TEXT_STRUCTURED")
        or _iad_smart_os.getenv("IAD_AI_MODEL_TEXT")
        or "gpt-4o-mini"
    )

    template_name = template.get("nombre") or template.get("template_name") or ""
    examples = _iad_smart_collect_training_examples(db=db, template_name=template_name, limit=3)

    prompt = _iad_smart_build_prompt(
        parsed=parsed,
        result=result,
        template=template,
        metadata=metadata or {},
        examples=examples,
    )

    try:
        kwargs = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Responde únicamente JSON válido. "
                        "Eres editor radiológico de plantilla. "
                        "Debes conservar la estructura de la plantilla y aplicar hallazgos del dictado."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        try:
            completion = client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("response_format", None)
            completion = client.chat.completions.create(**kwargs)

        raw = ""
        try:
            raw = completion.choices[0].message.content or ""
        except Exception:
            raw = ""

        edited = _iad_smart_extract_json(raw)

        smart_report = _iad_smart_text(edited.get("informe_final") or edited.get("final_report") or "")
        after_score = _iad_smart_template_shape_score(smart_report, template_text)

        if not smart_report:
            result["intelligence_editor"] = {
                "ok": False,
                "reason": "empty_smart_report",
                "model": model,
                "source": source_label,
                "before_score": before_score,
            }
            return result

        # Aceptar el inteligente si conserva mejor o igual la forma de plantilla,
        # o si el actual era claramente fallback pobre.
        accept = after_score >= max(45, before_score - 5)

        if not accept:
            result["intelligence_editor"] = {
                "ok": False,
                "reason": "smart_report_did_not_preserve_template_shape",
                "model": model,
                "source": source_label,
                "before_score": before_score,
                "after_score": after_score,
                "smart_report_preview": smart_report[:900],
            }
            return result

        result["informe_final_deterministico"] = current_report
        result["informe_final_inteligente"] = smart_report
        result["informe_final"] = smart_report
        result["final_report"] = smart_report
        result["resultado_revisado"] = smart_report
        result["metodo"] = "audio_first_smart_template_editor"

        if isinstance(edited.get("hallazgos_estructurados"), list):
            result["hallazgos_estructurados"] = edited.get("hallazgos_estructurados")

        if isinstance(edited.get("mapa_aplicacion"), list):
            result["mapa_aplicacion"] = edited.get("mapa_aplicacion")

        warnings = result.get("advertencias")
        if not isinstance(warnings, list):
            warnings = []

        for w in edited.get("advertencias") or []:
            if _iad_smart_text(w):
                warnings.append(_iad_smart_text(w))

        warnings.append("Editor inteligente: informe final generado sobre plantilla completa; fallback determinístico conservado en metadata.")
        result["advertencias"] = warnings

        ps = result.get("plantilla_sugerida")
        if not isinstance(ps, dict):
            ps = {}

        ps["id"] = ps.get("id") or template.get("id") or ""
        ps["nombre"] = ps.get("nombre") or template_name
        ps["confianza"] = edited.get("confianza") or ps.get("confianza") or "media"
        ps["motivo"] = "Plantilla aplicada por editor inteligente transferible"
        result["plantilla_sugerida"] = ps

        result["intelligence_editor"] = {
            "ok": True,
            "model": model,
            "source": source_label,
            "template_id": template.get("id") or "",
            "template_name": template_name,
            "before_score": before_score,
            "after_score": after_score,
            "examples_used": len(examples),
            "confianza": edited.get("confianza") or "",
        }

        return result

    except Exception as exc:
        result["intelligence_editor"] = {
            "ok": False,
            "reason": "exception",
            "error": repr(exc),
            "source": source_label,
        }
        return result


try:
    _iad_smart_original_v2_apply_template_bridge_force = _iad_v2_apply_template_bridge_force

    def _iad_v2_apply_template_bridge_force(client, parsed, metadata, db=None, composed=None):
        result = _iad_smart_original_v2_apply_template_bridge_force(
            client=client,
            parsed=parsed,
            metadata=metadata,
            db=db,
            composed=composed,
        )
        return _iad_smart_apply_editor(
            client=client,
            parsed=parsed if isinstance(parsed, dict) else {},
            result=result,
            metadata=metadata,
            db=db,
            source_label="v2_force_smart_editor",
        )
except Exception:
    pass


try:
    _iad_smart_original_audio_first_complete_with_template_bridge = _iad_audio_first_complete_with_template_bridge

    def _iad_audio_first_complete_with_template_bridge(client, parsed, metadata, db=None):
        result = _iad_smart_original_audio_first_complete_with_template_bridge(
            client=client,
            parsed=parsed,
            metadata=metadata,
            db=db,
        )
        return _iad_smart_apply_editor(
            client=client,
            parsed=parsed if isinstance(parsed, dict) else {},
            result=result,
            metadata=metadata,
            db=db,
            source_label="audio_first_smart_editor",
        )
except Exception:
    pass
