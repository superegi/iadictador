# IA Dictador - Intelligence Pack

Este directorio concentra la parte transferible de la inteligencia del flujo de informes.

## Qué contiene

### prompts/
Instrucciones para el modelo.

Archivo principal actual:
- prompts/audio_first_smart_template_editor.md

Ese prompt define, entre otras cosas:
- conservar la plantilla completa;
- no resumir;
- insertar hallazgos positivos;
- reemplazar normalidad solo cuando contradice el dictado;
- devolver JSON válido.

### schemas/
Contratos de salida esperada del modelo.

Archivo principal actual:
- schemas/audio_first_smart_template_editor.schema.json

### rules/
Copias transferibles de reglas actualmente pegadas en:
app/services/ai/tasks/audio_first_flow.py

Archivos esperados:
- rules/template_merge_deterministic_v3.py
- rules/smart_template_editor_v1.py
- rules/apply_structured_findings_to_report_v5.py

Importante:
- hoy estas copias no son importadas por runtime;
- el runtime real todavía vive en audio_first_flow.py;
- estas copias sirven para transferir, auditar y luego refactorizar.

### ui_debug/
Copias transferibles de componentes de visualización/depuración actualmente pegados en:
app/static/iadictador_work_v2.js

No son el cerebro. Sirven para ver:
- informe final editable;
- metadatos de plantilla;
- depuración IA;
- aplicación de hallazgos estructurados.

### examples/
Lugar previsto para few-shots y correcciones exportables.

### config/
Documentación de variables de entorno y modelo.

## Qué es transferible

Para portar la inteligencia a otro proyecto o servidor, copiar al menos:
- app/services/ai/intelligence_pack/
- app/services/ai/prompts/
- app/services/ai/schemas/
- report_templates/

Además, exportar:
- las plantillas guardadas en base de datos;
- la tabla de correcciones si existe.

## Qué falta ordenar

Próximo paso recomendado:
1. mover reglas desde audio_first_flow.py a módulos reales bajo app/services/ai/intelligence/;
2. hacer que audio_first_flow.py solo orqueste;
3. exportar correcciones médicas a examples/*.jsonl;
4. crear tests con dictado esperado -> JSON -> informe final.

## Training IA y aprendizaje por correcciones

Training IA almacena correcciones reales del usuario para reutilizarlas como ejemplos.

Flujo objetivo:
1. dictado original;
2. transcripción;
3. JSON clínico;
4. plantilla detectada;
5. informe IA;
6. informe corregido por médico;
7. diferencia IA vs corrección;
8. reutilización como ejemplo en futuros casos.

Endpoints:
- POST /iad/api/training/corrections/save.json
- GET /iad/api/training/corrections/list.json
- GET /iad/api/training/corrections/export.jsonl

Tabla:
- iad_training_corrections

Esto permite aprendizaje por ejemplos sin fine-tuning inmediato.

## Reglas editables TC Abdomen y Pelvis CC

Archivo:
- app/services/ai/intelligence_pack/rules_editable/tc_abdomen_pelvis_style_rules.yaml

Reglas agregadas:
- impresión diagnóstica sin guiones;
- impresión diagnóstica sin medidas;
- impresión diagnóstica conceptual;
- no concluir órganos solo presentes/ausentes;
- mantener frases estándar de plantilla para vesícula, útero, vesículas seminales y líquido libre.
