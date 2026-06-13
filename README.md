# IA Dictador

IA Dictador es un prototipo de dictado radiologico asistido por inteligencia artificial.

El objetivo operativo es transformar audio o texto dictado por el usuario en un informe radiologico final editable, auditable y reutilizable como material de entrenamiento.

El sistema no reemplaza la validacion medica. El informe final siempre debe ser revisado, corregido y guardado por el usuario.

## Flujo operativo actual

Ruta principal:

    /iad/trabajo

Flujo:

    audio o texto
    transcripcion literal
    deteccion de plantilla
    extraccion de hallazgos y tags
    generacion de informe final
    edicion manual
    guardar validacion

## Reconocimiento de texto

El sistema conserva el texto transcrito literal como fuente primaria auditable.

Debe quedar visible para el usuario y guardarse en Historial2 y Training IA.

Campo conceptual:

    texto_transcrito_literal

Uso operativo:

    verificar que dijo realmente el usuario
    detectar errores de transcripcion
    comparar contra el informe generado
    generar ejemplos de entrenamiento

## Procesamiento por inteligencia artificial

El sistema intenta extraer desde el texto:

    tipo de estudio
    plantilla sugerida
    hallazgos importantes
    medidas
    lateralidad
    organo o region
    advertencias
    puntos conflictivos

La salida relevante para auditoria debe incluir:

    texto transcrito literal
    tags especificos reconocidos
    plantilla sugerida
    propuesta de IA
    advertencias
    modelo o proceso responsable

## Producto final

El producto final es un informe radiologico limpio, editable y validable.

Reglas generales:

    no arrastrar placeholders
    no conservar xxxxx
    no incluir alternativas de plantilla
    no inventar hallazgos no dictados
    no mezclar medidas de organos distintos
    no duplicar hallazgos equivalentes
    mantener estructura radiologica limpia
    dejar la impresion diagnostica conceptual

Al guardar validacion, el sistema debe conservar:

    propuesta IA
    version final guardada por el usuario
    diff
    tags
    advertencias
    responsable tecnico

## Historial operativo

Ruta nueva:

    /iad/historial2

Historial2 reemplaza conceptualmente al historial antiguo.

Debe funcionar como tabla de trabajos generados, no como registro escrito simple.

Cada entrada debe mostrar:

    hora
    usuario
    modalidad
    nombre del estudio
    estado
    link para abrir

Cada trabajo se abre como hoja no editable:

    /iad/historial2/w/<id>

La hoja no editable debe mostrar:

    texto transcrito literal
    tags importantes reconocidos
    extraccion IA o JSON clinico
    propuesta IA
    puntos conflictivos detectados
    version final guardada por el usuario
    diff
    responsable tecnico

## Training IA

Ruta nueva:

    /iad/trining-ia

Esta ruta reemplaza conceptualmente al training anterior.

Training IA debe funcionar como dataset seleccionable, exportable y depurable.

Cada entrada debe mostrar en la lista:

    hora
    modelo IA utilizado
    version o proceso IA
    plantilla
    cuantificacion numerica del diff

Cada entrada individual debe mostrar:

    texto transcrito literal
    tags importantes reconocidos
    plantilla a utilizar
    propuesta de la IA
    puntos conflictivos detectados
    version final guardada por el usuario
    diff
    responsable tecnico

La finalidad de Training IA es guardar ejemplos de correccion para alimentar motores futuros.

## Responsable tecnico

Para auditar errores y comparar motores, cada generacion nueva debe guardar una traza publica del proceso.

No se guarda razonamiento interno del modelo.

Si se guarda:

    provider
    modelo
    proceso
    etapas
    prompt y schema IDs publicos
    writer o regla aplicada
    timestamp

Esto permite saber si un error fue responsabilidad de:

    modelo
    prompt
    schema
    writer especifico
    regla editable
    postproceso
    transcripcion
    plantilla

## Donde esta guardada la inteligencia

### Runtime actual

    app/services/ai/tasks/audio_first_flow.py

Contiene actualmente buena parte del flujo real:

    seleccion de plantilla
    puentes audio-first
    postprocesos
    writers especificos
    reglas activas
    metadata de responsabilidad
    resumen de extraccion

Estado: funcional pero demasiado cargado. Debe refactorizarse.

### Prompts

    app/services/ai/prompts/

Aqui deben vivir prompts versionados para:

    extraccion clinica
    seleccion de plantilla
    redaccion sobre plantilla
    revision automatica
    comparacion contra validaciones previas

Ejemplo existente:

    app/services/ai/prompts/audio_first_smart_template_editor.md

### Schemas

    app/services/ai/schemas/

Aqui deben vivir esquemas JSON para salidas estructuradas.

Objetivo futuro:

    obligar al modelo a devolver JSON estable
    separar hallazgos, medidas, negaciones y advertencias
    evitar campos omitidos o ambiguos

Ejemplo existente:

    app/services/ai/schemas/audio_first_smart_template_editor.schema.json

### Reglas editables

    app/services/ai/intelligence_pack/rules_editable/

Aqui deben guardarse reglas clinicas y de estilo que el usuario pueda modificar sin tocar codigo duro.

Ejemplo actual:

    app/services/ai/intelligence_pack/rules_editable/ecografia_abdominal_rules.yaml

### Paquete transferible de inteligencia

    app/services/ai/intelligence_pack/

Debe concentrar progresivamente:

    reglas
    prompts
    schemas
    ejemplos
    documentacion de comportamiento

Objetivo: trasladar el cerebro del sistema a otro servidor o motor.

### Plantillas de informe

    report_templates/

Las plantillas contienen estructura radiologica reutilizable.

Problema actual: algunas plantillas contienen placeholders, marcas o alternativas internas. Eso puede contaminar el informe final.

Regla operativa:

    las plantillas deben ser limpias
    sin xxxxx visibles
    sin alternativas multiples pegadas
    sin bloques de prueba

## Que NO debe guardarse como inteligencia

No debe dependerse de:

    parches puntuales para un solo dictado
    reglas de medida demasiado especificas
    correcciones que solo funcionan para un texto aislado
    logica clinica escondida en JavaScript

JavaScript puede mostrar, depurar o guardar. No debe ser el cerebro clinico.

## Arquitectura deseada

    Interfaz grafica
    API interna IA Dictador
    AI Gateway configurable
    OpenAI / endpoint compatible / modelo local / motor propio

Etapas ideales:

    transcripcion
    extraccion estructurada
    redaccion sobre plantilla
    revision automatica
    validacion humana
    training

## Cambio de motor IA

La interfaz grafica debe seguir funcionando aunque se cambie el motor.

Variables objetivo futuras:

    IAD_AI_PROVIDER
    IAD_AI_BASE_URL
    IAD_AI_MODEL_TRANSCRIPTION
    IAD_AI_MODEL_EXTRACTOR
    IAD_AI_MODEL_REPORT
    IAD_AI_MODEL_REVIEW

## Rutas importantes

    /iad/trabajo
    /iad/historial2
    /iad/historial2/w/<id>
    /iad/trining-ia
    /iad/trining-ia/<id>

Rutas antiguas a reemplazar conceptualmente:

    /iad/historial
    /iad/admin/training
    /iad/training

## Estado actual resumido

El prototipo ya demuestra:

    captura de audio
    transcripcion
    generacion de informe editable
    panel visible de extraccion
    guardado de validaciones
    historial operativo nuevo
    training IA nuevo
    registro de responsable tecnico para registros nuevos
    reglas especificas para ecografia abdominal

Todavia falta un motor inteligente limpio, general y robusto.

El siguiente gran paso es construir un motor IA v2 con prompts, schemas y gateway separados.
