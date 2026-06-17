from __future__ import annotations

import json
from typing import Any

from .schemas import V3_OUTPUT_SCHEMA_EXAMPLE


def build_report_bridge_prompt(
    *,
    transcripcion: str,
    texto_adicional: str,
    plantilla: dict[str, Any],
    reglas_generales: str,
    audio_first_raw: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    template_id = plantilla.get("id") or ""
    template_name = plantilla.get("nombre") or plantilla.get("template_name") or ""
    template_source = plantilla.get("source") or ""
    template_content = plantilla.get("contenido") or plantilla.get("content") or ""

    return f"""
Eres un sistema de edición de plantillas radiológicas.

TAREA PRINCIPAL:
Debes producir un informe final que sea una versión EDITADA DE LA PLANTILLA COMPLETA.
NO debes producir un resumen narrativo del dictado.
NO debes devolver solo lo que el médico dijo.
Debes combinar:
1. Transcripción literal del médico.
2. Texto adicional escrito por el médico.
3. Plantilla completa seleccionada.
4. Reglas radiológicas generales.

JERARQUÍA:
- La transcripción literal y el texto adicional contienen las instrucciones clínicas.
- La plantilla completa define la estructura y las frases normales base.
- Las reglas generales definen estilo, omisiones permitidas, advertencias y decisiones.
- La salida audio-first cruda es solo apoyo. Si audio-first omitió algo, usa la transcripción literal.

REGLA ABSOLUTA SOBRE PLANTILLA:
El campo informe_final debe conservar la estructura de la plantilla.
Si la plantilla tiene encabezados como Técnica, Antecedentes, Hallazgos, Impresión diagnóstica o Conclusión, deben mantenerse.
Si la plantilla tiene múltiples líneas normales, conserva las que no contradigan el dictado.
Si una línea normal contradice el dictado, reemplázala.
Si el dictado agrega un hallazgo que no tiene una línea exacta en la plantilla, insértalo en la sección anatómica correspondiente.
Si no hay sección anatómica clara, insértalo al final de Hallazgos como hallazgo adicional/incidental.
No conviertas una plantilla larga en un párrafo único.

BLOQUES XXXXX:
- Los bloques con xxxxx son separadores visuales o zonas de atención.
- Nunca deben aparecer en el informe_final.
- Si dentro del bloque hay alternativas, elige solo una.
- Si dentro del bloque hay recordatorios, úsalos para decidir, pero no los copies.
- Nunca dejes alternativas contradictorias simultáneas.

HALLAZGOS:
- No omitas hallazgos positivos dictados, aunque sean pequeños.
- Lesiones focales de pocos mm deben reportarse.
- Litiasis pequeñas deben reportarse.
- Nódulos pequeños deben reportarse.
- Hallazgos incidentales dictados deben reportarse.
- Si hay autocorrección de lateralidad, usa la última versión clara.
- Si la lateralidad queda dudosa, conserva el hallazgo y agrega advertencia.

IMPRESIÓN DIAGNÓSTICA:
- Debe incluir los hallazgos positivos clínicamente relevantes.
- No repitas medidas si no aportan.
- No pongas una impresión normal si hay hallazgos positivos relevantes.
- Si el médico dicta explícitamente una sugerencia, inclúyela si corresponde.

PROHIBIDO:
- Prohibido devolver solo un resumen del dictado.
- Prohibido omitir la plantilla.
- Prohibido dejar xxxxx.
- Prohibido inventar hallazgos.
- Prohibido mezclar alternativas incompatibles.
- Prohibido eliminar hallazgos positivos por ser pequeños.

REGLAS RADIOLÓGICAS GENERALES:
{reglas_generales}

PLANTILLA COMPLETA SELECCIONADA:
ID: {template_id}
NOMBRE: {template_name}
FUENTE: {template_source}

--- INICIO PLANTILLA ---
{template_content}
--- FIN PLANTILLA ---

TRANSCRIPCIÓN LITERAL:
{transcripcion}

TEXTO ADICIONAL ESCRITO POR EL MÉDICO:
{texto_adicional}

SALIDA AUDIO-FIRST CRUDA:
{json.dumps(audio_first_raw, ensure_ascii=False, indent=2, default=str)}

METADATA:
{json.dumps(metadata, ensure_ascii=False, indent=2, default=str)}

SALIDA OBLIGATORIA:
Devuelve SOLO JSON válido, sin markdown.

Estructura obligatoria:
{json.dumps(V3_OUTPUT_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)}

ANTES DE RESPONDER, VERIFICA:
1. informe_final conserva la estructura de la plantilla.
2. informe_final no es un párrafo resumen.
3. todos los hallazgos positivos de la transcripción están en Hallazgos.
4. los hallazgos relevantes están en Impresión diagnóstica.
5. no quedan xxxxx.
6. no quedan alternativas contradictorias.
7. si hubo duda de lateralidad, aparece en advertencias.
""".strip()
