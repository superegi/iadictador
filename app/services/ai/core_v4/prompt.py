from __future__ import annotations

import json
from typing import Any


OUTPUT_SCHEMA = {
    "ok": True,
    "metodo": "core_v4_audio_rules_template",
    "transcripcion": "",
    "plantilla_usada": {
        "id": "",
        "nombre": "",
        "source": ""
    },
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
    "informe_final": "",
    "impresion_diagnostica": "",
    "advertencias": [],
    "posibles_omisiones": []
}


def build_prompt(
    *,
    transcripcion: str,
    reglas: str,
    plantilla: dict[str, Any],
    texto_adicional: str = "",
) -> str:
    template_text = plantilla.get("contenido") or ""

    return f"""
Eres un editor de plantillas radiológicas.

OBJETIVO ÚNICO:
A partir de AUDIO TRANSCRITO + REGLAS + PLANTILLA, debes generar un informe final.

ENTRADAS:
1. TRANSCRIPCIÓN: lo que dijo el médico.
2. TEXTO ADICIONAL: instrucciones escritas opcionales.
3. REGLAS: reglas generales de redacción radiológica.
4. PLANTILLA: texto base del informe.

TAREA:
Editar la PLANTILLA usando lo dictado por el médico.
El resultado NO debe ser un resumen.
El resultado debe ser la PLANTILLA COMPLETA modificada.

REGLAS DE MEZCLA:
- Conserva la estructura y los saltos de línea de la plantilla.
- Conserva encabezados como Técnica, Antecedentes, Hallazgos, Impresión diagnóstica.
- Conserva normalidades de la plantilla si no contradicen el dictado.
- Reemplaza normalidades que contradigan hallazgos positivos dictados.
- Inserta hallazgos positivos dictados en la sección anatómica correspondiente.
- Si el hallazgo no tiene sección clara, agrégalo al final de Hallazgos.
- No omitas hallazgos positivos aunque sean pequeños.
- No omitas lesiones focales de pocos milímetros.
- No omitas litiasis pequeñas.
- No omitas hallazgos incidentales si fueron dictados.
- Si hay autocorrección de lateralidad, usa la última versión clara.
- Si la lateralidad queda dudosa, conserva el hallazgo y agrega advertencia.
- Si la plantilla tiene bloques xxxxx, no copies los xxxxx.
- Si un bloque xxxxx contiene alternativas, elige solo la aplicable.
- No dejes alternativas contradictorias.
- No inventes hallazgos.

FORMATO DEL INFORME:
- Mantén formato multilínea.
- Usa saltos de línea reales.
- No devuelvas un párrafo único salvo que la plantilla original sea un párrafo único.
- El campo informe_final debe contener el informe listo para copiar.

IMPRESIÓN DIAGNÓSTICA:
- Debe incluir los hallazgos positivos relevantes.
- No debe decir normal si hay hallazgos positivos.
- No repitas medidas si no aportan.
- Si el médico dicta una recomendación explícita, inclúyela si corresponde.

REGLAS GENERALES:
{reglas}

PLANTILLA:
ID: {plantilla.get("id") or ""}
NOMBRE: {plantilla.get("nombre") or ""}
FUENTE: {plantilla.get("source") or ""}

--- INICIO PLANTILLA ---
{template_text}
--- FIN PLANTILLA ---

TRANSCRIPCIÓN:
{transcripcion}

TEXTO ADICIONAL:
{texto_adicional}

SALIDA:
Devuelve SOLO JSON válido, sin markdown, con esta estructura:

{json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=2)}

CONTROL FINAL ANTES DE RESPONDER:
1. ¿informe_final conserva estructura de plantilla?
2. ¿informe_final tiene saltos de línea si la plantilla los tenía?
3. ¿todos los hallazgos positivos dictados aparecen en Hallazgos?
4. ¿los hallazgos relevantes aparecen en Impresión diagnóstica?
5. ¿no quedan xxxxx?
6. ¿no hay alternativas contradictorias?
""".strip()
