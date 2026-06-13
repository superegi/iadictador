# Copia transferible extraida desde app/services/ai/tasks/audio_first_flow.py
# Nota: hoy runtime aun usa audio_first_flow.py; esta copia sirve para exportar/auditar/refactorizar.

# IAD_APPLY_STRUCTURED_FINDINGS_TO_REPORT_V5
# Usa hallazgos_estructurados como fuente de verdad y los aplica al cuerpo del informe final.
# No reemplaza la inteligencia: corrige el punto donde el informe final no absorbe el JSON clínico.

try:
    import re as _iad_sfm_re
    import json as _iad_sfm_json
except Exception:
    _iad_sfm_re = None
    _iad_sfm_json = None


def _iad_sfm_text(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return _iad_sfm_json.dumps(v, ensure_ascii=False, default=str)
    except Exception:
        return str(v)


def _iad_sfm_norm(v):
    s = _iad_sfm_text(v).lower()
    repl = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ü": "u", "ñ": "n"
    }
    for a, b in repl.items():
        s = s.replace(a, b)
    if _iad_sfm_re:
        s = _iad_sfm_re.sub(r"\s+", " ", s).strip()
    else:
        s = " ".join(s.split())
    return s


def _iad_sfm_pretty_measure(v):
    s = _iad_sfm_text(v).strip()
    if not s:
        return ""
    s = s.replace("×", "x")
    if _iad_sfm_re:
        s = _iad_sfm_re.sub(r"\s*[xX]\s*", " x ", s)
        s = _iad_sfm_re.sub(r"\s+", " ", s).strip()
        if not _iad_sfm_re.search(r"\bmm\b|mil[ií]metros?", s, flags=_iad_sfm_re.I):
            if _iad_sfm_re.search(r"\d", s):
                s += " mm"
    return s


def _iad_sfm_flatten_findings(value):
    out = []

    if value is None:
        return out

    if isinstance(value, str):
        try:
            parsed = _iad_sfm_json.loads(value)
            return _iad_sfm_flatten_findings(parsed)
        except Exception:
            return out

    if isinstance(value, dict):
        # Si parece hallazgo, conservar.
        keys = set(value.keys())
        relevant = {
            "organo_o_region", "órgano_o_region", "region", "órgano", "organo",
            "hallazgo", "interpretacion", "interpretación", "medida",
            "lateralidad", "localizacion", "localización"
        }
        if keys & relevant:
            out.append(value)

        # Buscar listas/dicts anidados.
        for v in value.values():
            if isinstance(v, (list, dict, str)):
                out.extend(_iad_sfm_flatten_findings(v))

        return out

    if isinstance(value, list):
        for item in value:
            out.extend(_iad_sfm_flatten_findings(item))
        return out

    return out


def _iad_sfm_get(d, *names):
    for name in names:
        if isinstance(d, dict) and name in d and d.get(name) not in (None, ""):
            return _iad_sfm_text(d.get(name)).strip()
    return ""


def _iad_sfm_collect_findings(result):
    if not isinstance(result, dict):
        return []

    raw_candidates = [
        result.get("hallazgos_estructurados"),
        result.get("structured_findings"),
        result.get("analysis", {}).get("hallazgos_estructurados") if isinstance(result.get("analysis"), dict) else None,
        result.get("data", {}).get("hallazgos_estructurados") if isinstance(result.get("data"), dict) else None,
    ]

    findings = []
    for raw in raw_candidates:
        findings.extend(_iad_sfm_flatten_findings(raw))

    # Deduplicar por contenido normalizado.
    seen = set()
    clean = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        key = _iad_sfm_norm(f)
        if not key or key in seen:
            continue
        seen.add(key)
        clean.append(f)

    return clean


def _iad_sfm_build_lines(findings):
    pulmonary = []
    renal = []
    cardiac = []
    other = []

    renal_right = []
    renal_left = []
    renal_unspecified = []

    for f in findings:
        organ = _iad_sfm_get(f, "organo_o_region", "órgano_o_region", "region", "organo", "órgano")
        hall = _iad_sfm_get(f, "hallazgo", "finding")
        interp = _iad_sfm_get(f, "interpretacion", "interpretación", "impression")
        lat = _iad_sfm_get(f, "lateralidad", "side")
        loc = _iad_sfm_get(f, "localizacion", "localización", "ubicacion", "ubicación")
        measure = _iad_sfm_pretty_measure(_iad_sfm_get(f, "medida", "tamaño", "tamano", "size"))

        blob = _iad_sfm_norm(" ".join([organ, hall, interp, lat, loc, measure]))

        if "nodulo" in blob and ("pulmon" in blob or "base" in blob or "torax" in blob):
            side = ""
            if "derech" in blob:
                side = " en la base pulmonar derecha"
            elif "izquierd" in blob:
                side = " en la base pulmonar izquierda"
            elif loc:
                side = f" en {loc}"

            line = "Parénquima pulmonar: nódulo pulmonar"
            line += side
            if measure:
                line += f" de {measure}"
            line += "."
            pulmonary.append(line)
            continue

        if "cardiomegalia" in blob or ("corazon" in blob and "leve" in blob):
            line = "Cardiomediastino: leve cardiomegalia."
            cardiac.append(line)
            continue

        if "litiasis" in blob or "nefrolitiasis" in blob or "renal" in blob or "rinon" in blob or "riñon" in blob:
            side = ""
            if "derech" in blob:
                side = "derecha"
            elif "izquierd" in blob:
                side = "izquierda"

            line = "litiasis renal"
            if side:
                line += f" {side}"
            if "no obstruct" in blob:
                line += " no obstructiva"
            if measure:
                line += f" de {measure}"

            if side == "derecha":
                renal_right.append(line)
            elif side == "izquierda":
                renal_left.append(line)
            else:
                renal_unspecified.append(line)
            continue

        label = interp or hall
        if label:
            other.append(label.rstrip(".") + ".")

    body_lines = []

    if pulmonary:
        body_lines.extend(_iad_sfm_unique_lines(pulmonary))

    if cardiac:
        body_lines.extend(_iad_sfm_unique_lines(cardiac))

    renal_parts = []
    renal_parts.extend(_iad_sfm_unique_lines(renal_right))
    renal_parts.extend(_iad_sfm_unique_lines(renal_left))
    renal_parts.extend(_iad_sfm_unique_lines(renal_unspecified))

    if renal_parts:
        if len(renal_parts) == 1:
            body_lines.append("Riñones y vías urinarias: se observa " + renal_parts[0] + ".")
        else:
            body_lines.append("Riñones y vías urinarias: se observan " + " y ".join(renal_parts) + ".")

    body_lines.extend(_iad_sfm_unique_lines(other))

    impression_lines = []

    if pulmonary:
        # Mantener impresión más concisa.
        for line in _iad_sfm_unique_lines(pulmonary):
            imp = line
            imp = imp.replace("Parénquima pulmonar: ", "")
            impression_lines.append(imp[0].upper() + imp[1:] if imp else imp)

    if renal_parts:
        impression_lines.append("Nefrolitiasis no obstructiva.")

    if cardiac:
        impression_lines.append("Leve cardiomegalia.")

    return _iad_sfm_unique_lines(body_lines), _iad_sfm_unique_lines(impression_lines)


def _iad_sfm_unique_lines(lines):
    out = []
    seen = set()
    for line in lines or []:
        line = _iad_sfm_text(line).strip()
        if not line:
            continue
        line = line.replace("..", ".")
        key = _iad_sfm_norm(line)
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _iad_sfm_find_impression(report):
    if not _iad_sfm_re:
        return -1

    patterns = [
        r"^\s*Impresi[oó]n\s+diagn[oó]stica\s*:",
        r"^\s*Impresi[oó]n\s*:",
        r"^\s*Conclusi[oó]n\s*:",
        r"^\s*Conclusiones\s*:",
    ]

    for pat in patterns:
        m = _iad_sfm_re.search(pat, report, flags=_iad_sfm_re.I | _iad_sfm_re.M)
        if m:
            return m.start()

    return -1


def _iad_sfm_remove_old_block(report):
    if not _iad_sfm_re:
        return report

    # Permite reejecutar sin acumular bloques.
    return _iad_sfm_re.sub(
        r"\n{0,2}Hallazgos positivos estructurados aplicados al informe:\n.*?(?=\n\s*(?:Impresi[oó]n|Conclusi[oó]n)|\Z)",
        "\n",
        report,
        flags=_iad_sfm_re.I | _iad_sfm_re.S,
    ).strip()


def _iad_sfm_has_body_fact(body, line):
    bn = _iad_sfm_norm(body)
    ln = _iad_sfm_norm(line)

    # Evitar duplicar si el cuerpo ya menciona el concepto principal.
    if "nodulo pulmonar" in ln and "nodulo pulmonar" in bn:
        return True
    if "cardiomegalia" in ln and "cardiomegalia" in bn:
        return True
    if ("litiasis renal" in ln or "nefrolitiasis" in ln) and ("litiasis renal" in bn or "nefrolitiasis" in bn):
        return True

    return ln and ln in bn


def _iad_sfm_apply_to_report(report, body_lines, impression_lines):
    report = _iad_sfm_text(report).strip()
    if not report:
        return report, []

    if not body_lines and not impression_lines:
        return report, []

    report = _iad_sfm_remove_old_block(report)

    idx = _iad_sfm_find_impression(report)
    if idx >= 0:
        body = report[:idx].rstrip()
        impression = report[idx:].strip()
    else:
        body = report.rstrip()
        impression = ""

    inserted = []

    missing_body = []
    for line in body_lines:
        if not _iad_sfm_has_body_fact(body, line):
            missing_body.append(line)

    if missing_body:
        block = "Hallazgos positivos estructurados aplicados al informe:\n" + "\n".join(missing_body)
        body = body.rstrip() + "\n\n" + block
        inserted.extend(missing_body)

    if impression_lines:
        if not impression:
            impression = "Impresión diagnóstica:\n"

        imp_norm = _iad_sfm_norm(impression)
        imp_add = []

        for line in impression_lines:
            key = _iad_sfm_norm(line)
            if "nodulo pulmonar" in key and "nodulo pulmonar" in imp_norm:
                continue
            if "nefrolitiasis" in key and ("nefrolitiasis" in imp_norm or "litiasis renal" in imp_norm):
                continue
            if "cardiomegalia" in key and "cardiomegalia" in imp_norm:
                continue
            if key and key not in imp_norm:
                imp_add.append(line)

        if imp_add:
            impression = impression.rstrip() + "\n" + "\n".join(imp_add)
            inserted.extend(imp_add)

    final = (body.rstrip() + "\n\n" + impression.strip()).strip() if impression else body.strip()

    if _iad_sfm_re:
        final = _iad_sfm_re.sub(r"\n{3,}", "\n\n", final).strip()

    return final, inserted


def _iad_sfm_apply_structured_mapper(result, source_label=""):
    if not isinstance(result, dict):
        return result

    report = _iad_sfm_text(
        result.get("informe_final")
        or result.get("final_report")
        or result.get("resultado_revisado")
        or ""
    ).strip()

    findings = _iad_sfm_collect_findings(result)
    body_lines, impression_lines = _iad_sfm_build_lines(findings)

    final, inserted = _iad_sfm_apply_to_report(report, body_lines, impression_lines)

    mapper_info = {
        "ok": bool(final and final != report),
        "source": source_label,
        "findings_count": len(findings),
        "body_lines": body_lines,
        "impression_lines": impression_lines,
        "inserted": inserted,
    }

    result["structured_mapper"] = mapper_info

    if final and final != report:
        result["informe_final_antes_structured_mapper"] = report
        result["informe_final"] = final
        result["final_report"] = final
        result["resultado_revisado"] = final

        warnings = result.get("advertencias")
        if not isinstance(warnings, list):
            warnings = []
        warnings.append("Structured mapper: los hallazgos estructurados fueron aplicados al cuerpo del informe final.")
        result["advertencias"] = warnings

        mapa = result.get("mapa_aplicacion")
        if not isinstance(mapa, list):
            mapa = []
        for line in inserted:
            mapa.append({
                "hallazgo": line,
                "seccion_destino": "cuerpo del informe / impresión",
                "accion": "insertado",
                "motivo": "Hallazgo estructurado detectado en JSON clínico y ausente en el cuerpo del informe."
            })
        result["mapa_aplicacion"] = mapa

    return result


try:
    _iad_sfm_original_v2_apply_template_bridge_force = _iad_v2_apply_template_bridge_force

    def _iad_v2_apply_template_bridge_force(client, parsed, metadata, db=None, composed=None):
        result = _iad_sfm_original_v2_apply_template_bridge_force(
            client=client,
            parsed=parsed,
            metadata=metadata,
            db=db,
            composed=composed,
        )
        return _iad_sfm_apply_structured_mapper(result, "v2_force_structured_mapper")
except Exception:
    pass


try:
    _iad_sfm_original_audio_first_complete_with_template_bridge = _iad_audio_first_complete_with_template_bridge

    def _iad_audio_first_complete_with_template_bridge(client, parsed, metadata, db=None):
        result = _iad_sfm_original_audio_first_complete_with_template_bridge(
            client=client,
            parsed=parsed,
            metadata=metadata,
            db=db,
        )
        return _iad_sfm_apply_structured_mapper(result, "audio_first_structured_mapper")
except Exception:
    pass
