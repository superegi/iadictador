# Pendientes dIctAdor

Estado: versión experimental funcional, no estable para producción clínica sin revisión humana.

## 1. Calidad clínica / prompts

Prioridad alta.

- Separar definitivamente prompt de sistema, prompt general, reglas radiológicas y reglas de usuario.
- Mejorar contrato plantilla-dictado:
  - la plantilla es esqueleto, no evidencia clínica;
  - el dictado manda sobre frases normales de plantilla;
  - hallazgos positivos anulan negativos contradictorios;
  - no conservar frases incompatibles con técnica, contraste o hallazgos dictados.
- Corregir errores graves observados:
  - estudios con contraste usando frases de “no contrastado”;
  - plantillas SC/CC incompatibles con el dictado;
  - negativos pulmonares conservados cuando se dicta nódulo;
  - negativos renales conservados cuando se dicta lesión sólida;
  - órganos sexo-dependientes de plantilla no reconciliados.
- Implementar validación dura SC/CC después de consolidar prompts.
- Revisar reglas radiológicas compiladas al final.

## 2. GUI / experiencia de usuario

Prioridad alta.

- Corregir barra lateral global.
- Unificar navegación y nombres:
  - “Uso OpenAI” debe pasar a “Uso IA”;
  - “Training IA” debe quedar escrito correctamente;
  - “Historial” debe reemplazar “Historial2” en la UI.
- Mantener estructura de trabajo:
  - Datos administrativos fuera del informe;
  - Informe editable;
  - Advertencias / inconsistencias / omisiones.
- Mantener el informe editable con altura automática según contenido.
- Mejorar Historial con filtros por usuario, centro, fecha, estado, estudio y modelo.
- Optimizar Training IA: no validado / validado, diff útil, evitar duplicados y búsqueda por tags.

## 3. Uso IA, billing y proveedores

Prioridad media-alta.

- Renombrar “Uso OpenAI” a “Uso IA”.
- Convertir el tablero en resumen multi-proveedor:
  - proveedor;
  - modelo;
  - llamadas;
  - tokens;
  - audio tokens;
  - tiempo;
  - costo estimado;
  - usuario;
  - centro.
- Implementar billing por usuario y por centro.
- Implementar reglas de cobro/pago según modalidad, estudio, centro, tags, modelo usado y estado de validación.
- Permitir selección de modelos por usuario:
  - rápido/barato;
  - equilibrado;
  - premium.
- Definir modelos permitidos y precios desde web.

## 4. Gateway de IAs

Prioridad media.

- Crear gateway interno de proveedores IA.
- Abstraer proveedor/modelo: OpenAI, otros proveedores externos y modelos locales futuros.
- Registrar por llamada: provider, model, stage, tokens, costo estimado, latencia y error.
- Permitir fallback entre modelos.
- Permitir configuración desde panel web.

## 5. Repositorio/configuración IA desde web

Prioridad media.

- Crear panel web de setup IA:
  - modelos disponibles;
  - modelo por defecto;
  - proveedor;
  - API keys o referencias seguras;
  - prompts;
  - reglas;
  - límites de uso;
  - permisos por usuario.
- Evitar depender de terminal para configuración habitual.
- Dejar reglas de seguridad en programación:
  - usuarios no admin no editan reglas de aplicación;
  - reglas generales solo admin;
  - reglas de usuario solo del usuario;
  - prioridad fija: aplicación > general > usuario.

## 6. Centros, estudios y operación

Prioridad media.

- Asignar cada estudio a un centro de trabajo.
- Crear catálogo de centros.
- Asociar usuarios a centros.
- Asociar trabajos a centro.
- Crear reglas de pago y cobro por centro.
- Detectar modalidad/estudio/tags desde dictado.
- Preparar exportación administrativa por fecha, usuario, centro, modalidad y modelo IA.

## 7. Publicación

Prioridad media.

- Publicar como `dictador.rix.cl`.
- Integrar con Traefik.
- Revisar variables de entorno, volúmenes, base de datos, logs, backups, TLS, usuarios y política de acceso.
- No publicar como producción clínica hasta cerrar prompts, UI e historial.

## 8. Limpieza del repositorio

No borrar código sin auditoría.

Candidatos a revisar:
- backups locales;
- logs temporales;
- archivos `.bak`;
- carpetas `backup_*`;
- carpetas `backups_*`;
- archivos de auditoría antiguos;
- scripts temporales generados por pruebas;
- assets no usados;
- código legacy de flujos de audio anteriores si V4 queda definitivo.

Acción recomendada:
1. Generar listado.
2. Revisar manualmente.
3. Borrar en commit separado.
