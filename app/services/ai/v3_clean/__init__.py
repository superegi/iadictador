"""
IADictador V3 - Clean Pipeline Architecture

Agnóstico del modelo IA.
Basado en REGLAS radiológicas (no en entrenamiento).
Auditable contra Training IA dataset.
"""

from .config import RadiologyRules, load_rules_from_file, DEFAULT_RULES
from .findings_extractor import FindingsExtractor
from .template_applier import TemplateApplier
from .report_validator import ReportValidator
from .ia_provider import IAProvider, OpenAIProvider

__all__ = [
    "RadiologyRules",
    "load_rules_from_file",
    "DEFAULT_RULES",
    "FindingsExtractor",
    "TemplateApplier",
    "ReportValidator",
    "IAProvider",
    "OpenAIProvider",
]
