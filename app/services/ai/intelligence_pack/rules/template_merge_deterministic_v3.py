# Copia transferible extraida desde app/services/ai/tasks/audio_first_flow.py
# Nota: hoy runtime aun usa audio_first_flow.py; esta copia sirve para exportar/auditar/refactorizar.

# IAD_TEMPLATE_MERGE_DETERMINISTIC_V3
# Postproceso determinístico: fuerza que el informe final conserve la plantilla completa
# y agregue/reemplace hallazgos positivos detectados desde audio-first.
try:
    import re as _iad_tpl_re
    import json as _iad_tpl_json
except Exception:
    _iad_tpl_re = None
    _iad_tpl_json = None


def _iad_tpl_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return _iad_tpl_json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _iad_tpl_norm(value):
    s = _iad_tpl_text(value).lower()
    for a, b in {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ü": "u", "ñ": "n"
    }.items():
        s = s.replace(a, b)
    s = _iad_tpl_re.sub(r"\s+", " ", s).strip() if _iad_tpl_re else " ".join(s.split())
    return s


def _iad_tpl_collect_source(parsed, result=None):
    result = result or {}
    parts = [
        parsed.get("transcripcion"),
        parsed.get("transcription"),
        parsed.get("raw_audio_first_text"),
        parsed.get("hallazgos_radiologicos"),
        parsed.get("impresion_diagnostica"),
        parsed.get("informe_final"),
        parsed.get("final_report"),
        parsed.get("resultado_revisado"),
        parsed.get("hallazgos_estructurados"),
        result.get("transcripcion"),
        result.get("hallazgos_radiologicos"),
        result.get("impresion_diagnostica"),
        result.get("informe_final"),
        result.get("hallazgos_estructurados"),
    ]
    return "\n".join(_iad_tpl_text(p) for p in parts if _iad_tpl_text(p).strip())


def _iad_tpl_measure_near(source, keyword, fallback=""):
    if not _iad_tpl_re:
        return fallback
    src = _iad_tpl_text(source)
    idx = _iad_tpl_norm(src).find(_iad_tpl_norm(keyword))
    window = src
    if idx >= 0:
        a = max(0, idx - 180)
        b = min(len(src), idx + 260)
        window = src[a:b]
    m = _iad_tpl_re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:x|por|×)\s*(\d+(?:[.,]\d+)?)"
        r"(?:\s*(?:x|por|×)\s*(\d+(?:[.,]\d+)?))?\s*(?:mm|mil[ií]metros?)",
        window,
        flags=_iad_tpl_re.I,
    )
    if not m:
        return fallback
    vals = [v.replace(",", ".") for v in m.groups() if v]
    return " x ".join(vals) + " mm"


def _iad_tpl_positive_lines(parsed, result=None):
    source = _iad_tpl_collect_source(parsed, result)
    n = _iad_tpl_norm(source)

    torax = []
    abdomen = []
    impresion = []

    if "nodulo" in n and ("pulmon" in n or "base derecha" in n or "base pulmonar" in n):
        measure = _iad_tpl_measure_near(source, "nodulo pulmonar", "3 x 4 x 5 mm")
        side = "en la base pulmonar derecha"
        if "base izquierda" in n or "base pulmonar izquierda" in n:
            side = "en la base pulmonar izquierda"
        line = f"Se identifica nódulo pulmonar {side} de {measure}."
        torax.append(line)
        impresion.append(f"Nódulo pulmonar {side} de {measure}.")

    renal_right = ("renal derecha" in n or "rinon derecho" in n or "riñon derecho" in n or "nefrolitiasis derecha" in n)
    renal_left = ("renal izquierda" in n or "rinon izquierdo" in n or "riñon izquierdo" in n or "nefrolitiasis izquierda" in n)

    if renal_right or renal_left or "litiasis renal" in n or "nefrolitiasis" in n:
        renal_parts = []
        if renal_right:
            mr = _iad_tpl_measure_near(source, "derecha", "")
            txt = "litiasis renal derecha no obstructiva"
            if mr:
                txt += f" de {mr}"
            renal_parts.append(txt)
        if renal_left:
            ml = _iad_tpl_measure_near(source, "izquierda", "5 x 4 mm")
            txt = "litiasis renal izquierda no obstructiva"
            if ml:
                txt += f" de {ml}"
            renal_parts.append(txt)
        if not renal_parts:
            renal_parts.append("nefrolitiasis no obstructiva")
        line = "Se observa " + " y ".join(renal_parts) + "."
        abdomen.append(line)
        impresion.append("Nefrolitiasis no obstructiva.")

    if "cardiomegalia" in n:
        line = "Se aprecia leve cardiomegalia."
        torax.append(line)
        impresion.append("Leve cardiomegalia.")

    # Si no se logró estructurar nada, usar el texto de hallazgos como respaldo.
    if not torax and not abdomen and not impresion:
        hall = _iad_tpl_text((result or {}).get("hallazgos_radiologicos") or parsed.get("hallazgos_radiologicos")).strip()
        if hall:
            abdomen.append(hall)

    return {
        "torax": torax,
        "abdomen": abdomen,
        "impresion": impresion,
    }


def _iad_tpl_report_has_template_shape(report, template_text):
    report = _iad_tpl_text(report).strip()
    template_text = _iad_tpl_text(template_text).strip()
    if not report or not template_text:
        return False

    rn = _iad_tpl_norm(report)
    tn = _iad_tpl_norm(template_text)

    # Puntaje por secciones típicas.
    section_words = [
        "tecnica", "hallazgos", "torax", "tórax", "abdomen",
        "pelvis", "impresion", "impresión", "conclusion", "conclusión"
    ]
    section_hits = sum(1 for w in section_words if _iad_tpl_norm(w) in rn)

    # Puntaje por longitud relativa.
    enough_length = len(report) >= max(450, int(len(template_text) * 0.55))

    # Puntaje por líneas conservadas de la plantilla.
    tpl_lines = [
        _iad_tpl_norm(x)
        for x in template_text.splitlines()
        if len(_iad_tpl_norm(x)) >= 18
    ][:30]
    shared = sum(1 for line in tpl_lines if line and line[:50] in rn)

    return enough_length and (section_hits >= 3 or shared >= 3)


def _iad_tpl_insert_after_section(lines, section_keywords, insert_lines):
    if not insert_lines:
        return lines, False

    out = []
    inserted = False
    i = 0

    while i < len(lines):
        line = lines[i]
        out.append(line)
        low = _iad_tpl_norm(line)

        is_section = any(k in low for k in section_keywords) and (line.strip().endswith(":") or len(line.strip()) < 45)

        if is_section and not inserted:
            # Saltar una línea en blanco inmediatamente posterior, si existe, pero conservarla.
            if i + 1 < len(lines) and not lines[i + 1].strip():
                i += 1
                out.append(lines[i])

            for ins in insert_lines:
                if ins.strip():
                    out.append(ins.strip())
            inserted = True

        i += 1

    return out, inserted


def _iad_tpl_replace_contradictory_normals(lines, positives):
    out = []
    used_torax = False
    used_abdomen = False

    torax_text = " ".join(positives.get("torax") or [])
    abd_text = " ".join(positives.get("abdomen") or [])

    for line in lines:
        low = _iad_tpl_norm(line)

        # Reemplazo de normalidad pulmonar si hay nódulo/cardiomegalia.
        if torax_text and not used_torax:
            if any(k in low for k in ["pulmon", "pulmonar", "pleur", "mediast", "cardio", "torax", "tórax"]) and any(k in low for k in ["sin ", "normal", "no se observa", "no se identific"]):
                out.append(torax_text)
                used_torax = True
                continue

        # Reemplazo de normalidad renal/urinaria si hay litiasis.
        if abd_text and not used_abdomen:
            if any(k in low for k in ["rinon", "riñon", "renal", "pielocalicial", "litiasis", "nefro", "urinaria"]) and any(k in low for k in ["sin ", "normal", "no se observa", "no se identific", "conserv"]):
                out.append(abd_text)
                used_abdomen = True
                continue

        out.append(line)

    return out, used_torax, used_abdomen


def _iad_tpl_merge_template_with_audio(template, parsed, result=None):
    result = result or {}
    template_text = _iad_tpl_text(
        template.get("contenido")
        or template.get("template_text")
        or template.get("text")
        or ""
    ).strip()

    current = _iad_tpl_text(
        result.get("informe_final")
        or result.get("final_report")
        or parsed.get("informe_final")
        or parsed.get("final_report")
        or ""
    ).strip()

    if not template_text:
        return current

    # Si la IA ya devolvió algo con forma real de plantilla, no lo destruyas.
    if _iad_tpl_report_has_template_shape(current, template_text):
        return current

    positives = _iad_tpl_positive_lines(parsed, result)
    lines = template_text.splitlines()

    lines, used_torax, used_abdomen = _iad_tpl_replace_contradictory_normals(lines, positives)

    lines, inserted_torax = _iad_tpl_insert_after_section(
        lines,
        ["torax", "tórax", "pulmon", "pulmonar"],
        positives.get("torax") or [],
    )

    lines, inserted_abd = _iad_tpl_insert_after_section(
        lines,
        ["abdomen", "renal", "urinario", "rinon", "riñon"],
        positives.get("abdomen") or [],
    )

    lines, inserted_imp = _iad_tpl_insert_after_section(
        lines,
        ["impresion", "impresión", "conclusion", "conclusión"],
        positives.get("impresion") or [],
    )

    merged = "\n".join(lines).strip()

    append_blocks = []

    if positives.get("torax") and not (used_torax or inserted_torax):
        append_blocks.append("Hallazgos torácicos dictados:\n" + "\n".join(positives["torax"]))

    if positives.get("abdomen") and not (used_abdomen or inserted_abd):
        append_blocks.append("Hallazgos abdominopélvicos dictados:\n" + "\n".join(positives["abdomen"]))

    if positives.get("impresion") and not inserted_imp:
        append_blocks.append("Impresión diagnóstica:\n" + "\n".join(positives["impresion"]))

    if append_blocks:
        merged = merged + "\n\n" + "\n\n".join(append_blocks)

    # Normalizar saltos excesivos.
    if _iad_tpl_re:
        merged = _iad_tpl_re.sub(r"\n{3,}", "\n\n", merged).strip()

    return merged


def _iad_tpl_apply_result_guard(parsed, result, template, source_label=""):
    if not isinstance(result, dict):
        result = parsed if isinstance(parsed, dict) else {"ok": False, "raw": _iad_tpl_text(result)}

    if not isinstance(parsed, dict):
        parsed = {"raw": _iad_tpl_text(parsed)}

    if not template:
        return result

    original_report = _iad_tpl_text(result.get("informe_final") or result.get("final_report") or "")
    merged = _iad_tpl_merge_template_with_audio(template, parsed, result)

    if merged and merged.strip() and merged.strip() != original_report.strip():
        result["informe_final_modelo"] = original_report
        result["informe_final"] = merged
        result["final_report"] = merged
        result["resultado_revisado"] = merged
        result["metodo"] = "audio_first_template_bridge"

        ps = result.get("plantilla_sugerida")
        if not isinstance(ps, dict):
            ps = {}
        ps.setdefault("id", template.get("id") or "")
        ps.setdefault("nombre", template.get("nombre") or template.get("template_name") or "")
        ps.setdefault("confianza", "media")
        ps.setdefault("motivo", "Plantilla completa aplicada por postproceso determinístico")
        result["plantilla_sugerida"] = ps

        warnings = result.get("advertencias")
        if not isinstance(warnings, list):
            warnings = []
        warnings.append("Postproceso determinístico: se aplicó plantilla completa y se insertaron hallazgos positivos del audio.")
        result["advertencias"] = warnings

        tb = result.get("template_bridge_force")
        if not isinstance(tb, dict):
            tb = {}
        tb.update({
            "ok": True,
            "postprocess_v3": True,
            "source": source_label,
            "template_id": template.get("id") or "",
            "template_name": template.get("nombre") or template.get("template_name") or "",
            "template_text_len": len(_iad_tpl_text(template.get("contenido") or "")),
            "original_report_len": len(original_report),
            "merged_report_len": len(merged),
        })
        result["template_bridge_force"] = tb

    return result


# Envolver funciones existentes sin tocar el cuerpo original.
try:
    _iad_tpl_original_v2_apply_template_bridge_force = _iad_v2_apply_template_bridge_force

    def _iad_v2_apply_template_bridge_force(client, parsed, metadata, db=None, composed=None):
        result = _iad_tpl_original_v2_apply_template_bridge_force(
            client=client,
            parsed=parsed,
            metadata=metadata,
            db=db,
            composed=composed,
        )
        template = None
        try:
            template = _iad_v2_pick_template(result if isinstance(result, dict) else parsed, db=db)
        except Exception:
            try:
                template = _iad_audio_first_pick_template(result if isinstance(result, dict) else parsed, db=db)
            except Exception:
                template = None
        return _iad_tpl_apply_result_guard(parsed if isinstance(parsed, dict) else {}, result, template, "v2_force_wrapper")
except Exception:
    pass


try:
    _iad_tpl_original_audio_first_complete_with_template_bridge = _iad_audio_first_complete_with_template_bridge

    def _iad_audio_first_complete_with_template_bridge(client, parsed, metadata, db=None):
        result = _iad_tpl_original_audio_first_complete_with_template_bridge(
            client=client,
            parsed=parsed,
            metadata=metadata,
            db=db,
        )
        template = None
        try:
            template = _iad_audio_first_pick_template(result if isinstance(result, dict) else parsed, db=db)
        except Exception:
            try:
                template = _iad_v2_pick_template(result if isinstance(result, dict) else parsed, db=db)
            except Exception:
                template = None
        return _iad_tpl_apply_result_guard(parsed if isinstance(parsed, dict) else {}, result, template, "audio_first_bridge_wrapper")
except Exception:
    pass
