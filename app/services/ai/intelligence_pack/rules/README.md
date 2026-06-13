# Rules

Estas reglas representan comportamiento clínico/programático transferible.

Estado actual:
- son copias extraídas desde app/services/ai/tasks/audio_first_flow.py;
- todavía no están importadas por runtime;
- sirven para transferir, auditar y luego refactorizar.

Reglas principales:
1. template_merge_deterministic_v3.py
   Fallback determinístico. Aplica plantilla completa y evita que el informe quede vacío.

2. smart_template_editor_v1.py
   Editor inteligente. Usa prompt, modelo y schema para mejorar el informe preservando plantilla.

3. apply_structured_findings_to_report_v5.py
   Aplica hallazgos estructurados al cuerpo del informe final.
