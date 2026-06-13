# Estado del proyecto IA Dictador

Fecha de actualización: 2026-06-13

## Resumen ejecutivo

IA Dictador está en fase de prototipo funcional.

La herramienta gráfica ya permite trabajar con audio o texto, generar un informe editable, revisar la extracción de la IA, guardar validaciones, ver trabajos en Historial2 y consultar ejemplos en Training IA.

El punto más débil actual no es la interfaz gráfica. El punto más débil es el motor de inteligencia artificial, que creció mediante capas y parches sucesivos.

La decisión técnica actual es congelar parcialmente la interfaz funcional y planificar un motor IA v2 más limpio, auditable e intercambiable.

## Qué funciona actualmente

### Pantalla de trabajo

Ruta principal:

/iad/trabajo

Funciona:

* Grabación o carga de audio.
* Transcripción.
* Procesamiento audio-first.
* Detección de plantilla.
* Informe final editable.
* Copia del informe final.
* Selección de texto.
* Guardado de validación.
* Panel de extracción IA para revisar.

El panel de extracción muestra:

* Texto transcrito literal.
* Tags específicos reconocidos.
* Advertencias.

### Informes

Casos que han mejorado:

* Ecografía abdominal.
* TC abdomen y pelvis con contraste.
* TC abdomen y pelvis sin contraste.

Caso especialmente bueno:

* Ecografía abdominal con colelitiasis múltiple y esteatosis hepática.

Regla estable creada:

app/services/ai/intelligence_pack/rules_editable/ecografia_abdominal_rules.yaml

### Historial2

Ruta:

/iad/historial2

Funciona como tabla de trabajos generados.

Debe listar:

* Trabajo.
* Hora.
* Usuario.
* Modalidad.
* Nombre del estudio.
* Estado.
* Informe.
* Revisión.
* Link de apertura.

Detalle:

/iad/historial2/w/<id>

Debe mostrar una hoja no editable del trabajo:

* Texto transcrito literal.
* Tags.
* Extracción IA.
* Propuesta IA.
* Puntos conflictivos.
* Versión final guardada por el usuario.
* Diff.
* Responsable técnico.

### Training IA

Ruta:

/iad/trining-ia

Funciona como dataset de aprendizaje.

Detalle:

/iad/trining-ia/<id>

Debe mostrar:

* Texto transcrito literal.
* Tags importantes reconocidos.
* Plantilla a utilizar.
* Propuesta de la IA.
* Puntos conflictivos detectados.
* Versión final guardada por el usuario.
* Diff.
* Responsable técnico.

### Responsable técnico

Se empezó a guardar para registros nuevos:

* Provider.
* Modelo.
* Proceso.
* Etapas.
* Prompt/schema IDs.

Limitación:

* Los registros antiguos pueden aparecer como modelo_no_registrado.

## Problemas actuales

### 1. Motor IA no suficientemente inteligente

El sistema actual todavía se siente tonto en algunos casos.

Fallas observadas:

* Mezcla de medidas entre órganos.
* Arrastre de placeholders de plantillas.
* Invención de hallazgos no dictados.
* Duplicación de conceptos.
* Selección incorrecta de plantilla.
* Fallas en impresión diagnóstica conceptual.

Conclusión:

* No conviene seguir agregando parches clínicos por cada error aislado.

### 2. Exceso de lógica en audio_first_flow.py

Archivo principal actual:

app/services/ai/tasks/audio_first_flow.py

Problema:

* Contiene demasiadas capas.
* Contiene writers específicos.
* Contiene postprocesos.
* Contiene reglas de extracción.
* Contiene metadata.
* Contiene wrappers sucesivos.

Debe refactorizarse.

### 3. Falta AI Gateway

Todavía falta una capa formal:

app/services/ai/engine_gateway.py

Objetivo:

* Cambiar proveedor o modelo sin tocar la interfaz.
* Centralizar llamadas a IA.
* Registrar latencia.
* Registrar modelo.
* Registrar provider.
* Soportar OpenAI y endpoints compatibles.

### 4. Falta schema estricto central

Todavía falta definir schemas robustos para:

* Extracción clínica.
* Redacción.
* Revisión automática.
* Comparación con Training IA.

Ubicación objetivo:

app/services/ai/schemas/

### 5. Plantillas sucias

Algunas plantillas contienen:

* xxxxx.
* Marcas internas.
* Alternativas múltiples.
* Texto de prueba.

Estas plantillas pueden contaminar informes.

Pendiente:

* Limpiar repositorio de plantillas.
* Separar placeholders internos de texto visible.
* Validar plantillas antes de usarlas.

### 6. Historial y Training todavía necesitan depuración

Aunque ya funcionan mejor, falta confirmar:

* Que cada generación nueva cree entrada en Historial2.
* Que cada validación actualice esa entrada.
* Que cada validación genere entrada útil en Training IA.
* Que modelo/proceso se guarde siempre.
* Que tags se vean legibles y no escapados.

## Pendientes prioritarios

### Prioridad 1: congelar interfaz funcional

Acciones:

* Probar /iad/trabajo.
* Probar /iad/historial2.
* Probar /iad/trining-ia.
* Guardar validación real.
* Verificar responsable técnico.
* Hacer commit de checkpoint estable.

### Prioridad 2: limpiar menú y rutas

Objetivo:

* /iad/historial debe llevar a Historial2.
* /iad/admin/training debe llevar a Trining IA.
* /iad/training debe llevar a Trining IA.

Pendiente de validar en navegador.

### Prioridad 3: mejorar registro de responsable técnico

Para registros nuevos, debe quedar completo:

* Modelo IA utilizado.
* Provider.
* Proceso.
* Etapas.
* Prompt/schema IDs públicos.
* Writer aplicado.
* Latencia.

No guardar razonamiento interno.

### Prioridad 4: refactorizar inteligencia

Mover lógica desde:

app/services/ai/tasks/audio_first_flow.py

hacia:

* app/services/ai/engine_gateway.py
* app/services/ai/pipelines/
* app/services/ai/rules/
* app/services/ai/prompts/
* app/services/ai/schemas/

### Prioridad 5: motor IA v2

Construir motor nuevo con flujo:

* Transcripción.
* Extracción JSON estricta.
* Selección de plantilla.
* Redacción con plantilla.
* Revisión automática.
* Validación humana.
* Training.

## Plan futuro para optimizar la inteligencia artificial

### Fase 1: AI Gateway configurable

Crear:

app/services/ai/engine_gateway.py

Debe exponer funciones internas:

* generate_text
* generate_json
* transcribe_audio
* review_report

Debe soportar configuración:

* IAD_AI_PROVIDER
* IAD_AI_BASE_URL
* IAD_AI_MODEL_TRANSCRIPTION
* IAD_AI_MODEL_EXTRACTOR
* IAD_AI_MODEL_REPORT
* IAD_AI_MODEL_REVIEW

Objetivo:

* Cambiar de motor IA sin cambiar la interfaz.
* Comparar proveedores.
* Probar modelos más potentes.
* Probar endpoints compatibles.

### Fase 2: extracción estructurada estricta

Crear schema:

app/services/ai/schemas/clinical_extraction.schema.json

Salida esperada:

* tipo_estudio
* plantilla_sugerida
* confianza
* hallazgos
* medidas
* negaciones
* advertencias
* puntos_conflictivos

Cada hallazgo debe tener:

* Órgano.
* Región.
* Lateralidad.
* Hallazgo.
* Medida.
* Interpretación.
* Certeza.
* Texto fuente.

### Fase 3: redacción sobre plantilla

Crear prompt:

app/services/ai/prompts/report_writer_from_template.md

Entrada:

* Texto literal.
* JSON clínico.
* Plantilla completa.
* Reglas de estilo.
* Ejemplos similares.

Salida:

* informe_final
* tags_usados
* cambios_sobre_plantilla
* advertencias

### Fase 4: revisión automática

Crear schema:

app/services/ai/schemas/report_review.schema.json

Debe revisar:

* Medidas mal asignadas.
* Hallazgos inventados.
* Contradicciones.
* Placeholders visibles.
* Duplicaciones.
* Impresión diagnóstica inadecuada.

Salida:

* aprobado
* errores
* advertencias
* severidad
* sugerencias

### Fase 5: usar Training IA como ejemplos

Buscar ejemplos similares por:

* Modalidad.
* Plantilla.
* Tags.
* Tipo de estudio.
* Hallazgos.
* Errores previos.

Inyectar al prompt:

* 2 a 5 ejemplos parecidos.
* Propuesta IA anterior.
* Corrección del usuario.
* Diff.
* Reglas aprendidas.

Objetivo:

* Que la IA aprenda estilo y correcciones previas sin hardcodear reglas demasiado particulares.

### Fase 6: evaluación comparativa de motores

Crear una página o endpoint de test:

/iad/admin/motores

O una herramienta interna:

scripts/test_ai_engines.py

Debe permitir comparar:

* Mismo texto.
* Misma plantilla.
* Mismo schema.
* Modelo A.
* Modelo B.
* Modelo C.

Guardar resultado:

* Calidad.
* Latencia.
* Costo aproximado.
* Errores.
* Responsable técnico.

## Reglas generales de diseño

### No seguir agregando parches demasiado particulares

Evitar reglas como:

* Si este dictado exacto dice X, cambiar Y.

Preferir reglas generales:

* Cada medida debe quedar asociada al órgano más cercano semánticamente.
* No se puede mover una medida entre órganos.
* Si hay duda, generar advertencia.
* No inventar hallazgos ausentes del texto literal.

### Separar interfaz de motor

La interfaz debe recibir siempre el mismo contrato.

No debe importar si el motor es:

* OpenAI.
* OpenAI-compatible.
* Local.
* Propio.

### Guardar trazabilidad

Cada resultado debe poder responder:

* Qué texto entró.
* Qué plantilla se eligió.
* Qué tags se detectaron.
* Qué modelo se usó.
* Qué proceso se aplicó.
* Qué informe propuso la IA.
* Qué corrigió el usuario.
* Qué cambió en el diff.

## Commits recomendados próximos

Después de validar la interfaz actual:

* docs estado operativo ia dictador
* checkpoint ui historial2 training responsibility

Después del motor v2:

* add ai gateway configurable
* add structured clinical extraction pipeline
* add report writer schema pipeline
* add report review pipeline

## Criterio de avance

El proyecto debe considerarse más firme cuando se cumpla:

* Puedo cambiar modelo IA sin romper la interfaz.
* Puedo ver responsable técnico en cada entrada.
* Puedo exportar Training IA limpio.
* Puedo detectar si el error fue transcripción, extracción, redacción o revisión.
* Puedo corregir reglas sin tocar código duro.
* Puedo probar el mismo caso en dos motores distintos.

## Criterio de pausa

No seguir agregando reglas clínicas si:

* La regla solo corrige un texto aislado.
* No mejora una clase general de errores.
* Requiere tocar muchas capas.
* No queda registrada como regla editable.
* No queda visible en responsable técnico.

## Próximo capítulo sugerido

Nombre del próximo capítulo:

Motor IA v2 y AI Gateway

Objetivo:

Hacer que el producto gráfico sea estable y que el cerebro sea reemplazable, auditable y más inteligente.

