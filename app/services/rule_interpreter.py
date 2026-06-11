import re
import unicodedata
from typing import Any


NUM_WORDS = {
    "uno": 1, "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
}


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text


def extract_mm(text_norm: str) -> int | None:
    # 3 mm / 3 milimetros / tres mm / tres milimetros
    m = re.search(
        r"\b(\d{1,3}|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince)\s*(mm|milimetros|milimetro)\b",
        text_norm,
    )
    if not m:
        return None

    raw = m.group(1)
    if raw.isdigit():
        return int(raw)
    return NUM_WORDS.get(raw)


def extract_laterality(text_norm: str) -> tuple[str | None, list[str]]:
    matches = []
    for m in re.finditer(r"\b(derecha|derecho|izquierda|izquierdo|bilateral|bilaterales)\b", text_norm):
        val = m.group(1)
        if val in ["derecha", "derecho"]:
            matches.append("derecha")
        elif val in ["izquierda", "izquierdo"]:
            matches.append("izquierda")
        else:
            matches.append("bilateral")

    if not matches:
        return None, []

    return matches[-1], matches


def interpret_rules(dictado_bruto: str) -> dict[str, Any]:
    """
    Interpretador local inicial.
    No usa IA. Solo reglas para validar flujo visual y motor de plantilla.
    """
    text_norm = normalize(dictado_bruto)
    actions: list[dict[str, Any]] = []
    global_warnings: list[str] = []

    abnormal_impressions = []

    # Vesícula ausente / no visualizada
    if any(phrase in text_norm for phrase in [
        "no hay vesicula",
        "vesicula no visualizada",
        "no se visualiza vesicula",
        "colecistectomia",
        "colecistectomizado",
        "colecistectomizada",
    ]):
        actions.append({
            "type": "replace",
            "section": "hallazgos",
            "line_id": "vesicula_estado",
            "new_text": "Vesícula biliar no visualizada.",
            "tags": ["REEMPLAZADO"],
            "note": "El dictado indica ausencia/no visualización de la vesícula biliar.",
            "requires_review": False,
        })

    # Divertículos no complicados
    if "diverticul" in text_norm:
        if any(phrase in text_norm for phrase in [
            "sin signos de complicacion",
            "no complicados",
            "no complicado",
            "sin complicacion",
        ]):
            divert_text = "Divertículos en el colon sin signos de complicación."
        else:
            divert_text = "Divertículos en el colon."
            global_warnings.append("Divertículos mencionados sin aclarar si hay signos de complicación.")

        actions.append({
            "type": "add_after",
            "section": "hallazgos",
            "after_id": "asas",
            "new_id": "diverticulos_agregado",
            "new_text": divert_text,
            "tags": ["AGREGADO"],
            "note": "Hallazgo agregado desde dictado. No reemplaza una frase específica de la plantilla.",
            "requires_review": "sin signos de complicacion" not in text_norm and "no complicado" not in text_norm and "no complicados" not in text_norm,
        })
        abnormal_impressions.append({
            "new_id": "impresion_diverticulos",
            "text": divert_text,
            "tags": ["AGREGADO"],
            "requires_review": "sin signos de complicacion" not in text_norm and "no complicado" not in text_norm and "no complicados" not in text_norm,
        })

    # Litiasis / nefrolitiasis
    if any(word in text_norm for word in ["nefrolitiasis", "litiasis renal", "litiasis", "caliz", "calicial"]):
        mm = extract_mm(text_norm)
        laterality, lateralities_seen = extract_laterality(text_norm)

        if laterality is None:
            laterality = "no especificada"

        location = None
        if "caliz inferior" in text_norm or "calicial inferior" in text_norm or "grupo calicial inferior" in text_norm:
            location = "en cáliz inferior"
        elif "caliz superior" in text_norm or "calicial superior" in text_norm or "grupo calicial superior" in text_norm:
            location = "en cáliz superior"
        elif "caliz medio" in text_norm or "calicial medio" in text_norm or "grupo calicial medio" in text_norm:
            location = "en cáliz medio"

        obstructive = None
        if any(phrase in text_norm for phrase in ["sin dilatacion", "no hay dilatacion", "no obstructiva", "no obstructivo", "sin hidronefrosis"]):
            obstructive = False
        elif any(phrase in text_norm for phrase in ["obstructiva", "obstructivo", "hidronefrosis", "dilatacion pielocalicial"]):
            obstructive = True

        size_text = f" de {mm} mm" if mm is not None else ""
        loc_text = f" {location}" if location else ""
        lat_text = "" if laterality == "no especificada" else f" {laterality}"

        if obstructive is False:
            hallazgo = f"Litiasis no obstructiva{lat_text}{loc_text}{size_text}, sin dilatación pielocalicial."
            impresion = f"Nefrolitiasis no obstructiva{lat_text}."
        elif obstructive is True:
            hallazgo = f"Litiasis{lat_text}{loc_text}{size_text}, asociada a dilatación pielocalicial."
            impresion = f"Nefrolitiasis obstructiva{lat_text}."
        else:
            hallazgo = f"Litiasis renal{lat_text}{loc_text}{size_text}."
            impresion = f"Nefrolitiasis{lat_text}."

        review_reasons = []
        if mm is None:
            review_reasons.append("No se detectó medición en mm.")
        if laterality == "no especificada":
            review_reasons.append("No se detectó lateralidad.")
        if len(set(lateralities_seen)) > 1:
            review_reasons.append(f"Lateralidad corregida o contradictoria durante el dictado: {', '.join(lateralities_seen)}. Se usó la última: {laterality}.")
        if obstructive is None:
            review_reasons.append("No queda claro si la litiasis es obstructiva o no obstructiva.")

        actions.append({
            "type": "replace",
            "section": "hallazgos",
            "line_id": "rinones_litiasis",
            "new_text": f"Riñones de tamaño normal. No se observa hidronefrosis. {hallazgo}",
            "tags": ["REEMPLAZADO", "IA"],
            "note": "La frase normal renal fue reemplazada por hallazgo de litiasis interpretado desde el dictado.",
            "requires_review": bool(review_reasons),
            "review_reasons": review_reasons,
        })

        abnormal_impressions.append({
            "new_id": "impresion_nefrolitiasis",
            "text": impresion,
            "tags": ["AGREGADO", "IA"],
            "requires_review": bool(review_reasons),
            "review_reasons": review_reasons,
        })

    # Si hay impresión patológica, eliminar impresión normal
    if abnormal_impressions:
        actions.append({
            "type": "remove",
            "section": "impresion",
            "line_id": "impresion_normal",
            "tags": ["ELIMINADO"],
            "note": "Se elimina la impresión normal porque se agregaron hallazgos patológicos.",
            "requires_review": False,
        })

        for item in abnormal_impressions:
            actions.append({
                "type": "add_after",
                "section": "impresion",
                "after_id": "impresion_normal",
                "new_id": item["new_id"],
                "new_text": item["text"],
                "tags": item["tags"],
                "note": "Impresión agregada desde hallazgo detectado en el dictado.",
                "requires_review": item.get("requires_review", False),
                "review_reasons": item.get("review_reasons", []),
            })

    return {
        "dictado_normalizado": text_norm,
        "actions": actions,
        "global_warnings": global_warnings,
    }
