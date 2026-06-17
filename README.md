# dIctAdor

Sistema web experimental para dictado radiológico asistido por IA.

El objetivo es transformar audio médico en un informe radiológico estructurado, editable, trazable y auditable, usando plantillas, reglas radiológicas y modelos IA configurables.

Estado actual: **versión funcional inestable**.

## Funcionalidades actuales

- Flujo V4 de generación de informes:
  - audio o múltiples segmentos de audio;
  - fusión de audios antes de transcribir;
  - transcripción;
  - selección de plantilla;
  - generación de informe;
  - trazabilidad por trabajo.
- Informe final editable en la web.
- Paneles externos al informe:
  - datos administrativos fuera del informe;
  - informe editable;
  - advertencias / inconsistencias / omisiones.
- Repositorio multinivel de reglas:
  - reglas de aplicación;
  - reglas generales;
  - reglas de usuario;
  - prioridad fija: aplicación > generales > usuario.
- Página web para edición de reglas.
- Historial de trabajos V4.
- Training IA con registros automáticos.
- Persistencia automática de trabajos no validados.
- Validación posterior de informes.
- Diff entre propuesta IA y versión final validada.
- Panel de trazabilidad V4:
  - modelo;
  - job_id;
  - tokens;
  - llamadas IA;
  - reglas usadas;
  - metadata clínica;
  - audio fusionado.
- Tablero inicial de uso IA:
  - llamadas;
  - tokens;
  - modelos;
  - etapas;
  - últimos trabajos.
- Branding `dIctAdor` con logo y animación de carga.

## Arquitectura resumida

El flujo principal es:

```text
audio(s) + texto complementario + reglas + plantillas
→ motor V4
→ informe editable + metadata + advertencias + trazabilidad
```

Componentes principales:

```text
app/services/ai/core_v4/
app/iadictador/
app/templates/
app/static/
```

Persistencia principal:

```text
iad_history2_work_items
iad_training_corrections
iad_validation_history
```

## Variables relevantes

Ejemplo de modo V4:

```env
IAD_AUDIO_FLOW_MODE=v4
IAD_RULES_DIR=/data/rules
IAD_APP_RULES_FILE=/data/rules/app_rules.md
IAD_GENERAL_RULES_FILE=/data/rules/general_rules.md
IAD_USER_RULES_DIR=/data/rules/users
IAD_AI_MODEL_TRANSCRIBE=gpt-4o-mini-transcribe
IAD_AI_MODEL_TEMPLATE_SELECT=gpt-4o-mini
IAD_AI_MODEL_REPORT_V4=gpt-5.4-mini
```

## Uso local

```bash
docker compose up -d --build
```

Entrada local habitual:

```text
http://localhost:8014/iad/trabajo
```

Páginas relevantes:

```text
/iad/trabajo
/iad/plantillas
/iad/reglas-ia
/iad/historial2
/iad/trining-ia
/iad/uso-openai
```

Nota: algunas rutas conservan nombres legacy y deben normalizarse.

## Estado clínico

El sistema genera informes útiles, pero todavía requiere revisión humana.

Errores pendientes conocidos:
- reconciliación imperfecta entre plantilla y dictado;
- frases normales de plantilla que pueden competir con hallazgos positivos;
- manejo SC/CC aún no endurecido;
- órganos sexo-dependientes pendientes de validación más robusta;
- prompts pendientes de consolidación.

## Pendientes

Ver `Pendiente.md`.

## Seguridad

No usar como sistema clínico autónomo.

Todo informe debe ser revisado y validado por un médico responsable.
