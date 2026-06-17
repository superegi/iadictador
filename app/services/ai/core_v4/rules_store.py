from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from .engine import write_json, write_text


def _rules_dir() -> Path:
    return Path(os.getenv("IAD_RULES_DIR", "/data/rules"))


def _app_rules_path() -> Path:
    return Path(os.getenv("IAD_APP_RULES_FILE", str(_rules_dir() / "app_rules.md")))


def _general_rules_path() -> Path:
    return Path(os.getenv("IAD_GENERAL_RULES_FILE", str(_rules_dir() / "general_rules.md")))


def _user_rules_dir() -> Path:
    return Path(os.getenv("IAD_USER_RULES_DIR", str(_rules_dir() / "users")))


def _legacy_rules_path() -> Path:
    return Path(os.getenv("IAD_RULES_FILE", "/data/reglas_radiologicas.md"))


def safe_username(username: str) -> str:
    value = str(username or "anon").strip().lower()
    value = re.sub(r"[^a-z0-9_.-]+", "_", value)
    return value or "anon"


def _user_rules_path(username: str) -> Path:
    return _user_rules_dir() / f"{safe_username(username)}.md"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _write_if_missing(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def ensure_rules_repository(username: str = "") -> None:
    _rules_dir().mkdir(parents=True, exist_ok=True)
    _user_rules_dir().mkdir(parents=True, exist_ok=True)

    _write_if_missing(
        _app_rules_path(),
        """# Reglas de aplicación

Estas reglas tienen prioridad máxima sobre las reglas generales y las reglas de usuario.

- Mantener trazabilidad del método, modelo, llamadas a IA, tiempos y archivos usados.
- El informe final debe devolverse como JSON válido con informe_final y metadata_clinica.
- No dejar marcadores internos de plantilla como xxxxx, pendiente, alternativa 1/2 o texto técnico de depuración.
- La plantilla seleccionada debe corresponder al estudio dictado explícitamente.
- Si hay contradicción entre reglas, manda este orden: aplicación > generales > usuario.
""",
    )

    # Migración inicial: el archivo único anterior pasa a reglas generales si aún no existe general_rules.md.
    legacy = _legacy_rules_path()
    general = _general_rules_path()

    if not general.exists():
        if legacy.exists() and legacy.read_text(encoding="utf-8", errors="ignore").strip():
            general.parent.mkdir(parents=True, exist_ok=True)
            general.write_text(legacy.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        else:
            general.parent.mkdir(parents=True, exist_ok=True)
            general.write_text(
                "# Reglas generales\n\n"
                "- Usar lenguaje radiológico formal.\n"
                "- Conservar la estructura de la plantilla correspondiente.\n"
                "- Todo hallazgo positivo en Impresión diagnóstica debe estar descrito en Hallazgos.\n",
                encoding="utf-8",
            )

    if username:
        _write_if_missing(
            _user_rules_path(username),
            "# Reglas de usuario\n\n",
        )


def read_rule_scope(scope: str, username: str = "") -> str:
    ensure_rules_repository(username=username)

    if scope == "app":
        return _read(_app_rules_path())
    if scope == "general":
        return _read(_general_rules_path())
    if scope == "user":
        return _read(_user_rules_path(username))

    raise ValueError(f"Scope de reglas inválido: {scope}")


def write_rule_scope(scope: str, rules_text: str, username: str = "") -> dict[str, Any]:
    ensure_rules_repository(username=username)

    if scope == "app":
        path = _app_rules_path()
    elif scope == "general":
        path = _general_rules_path()
    elif scope == "user":
        path = _user_rules_path(username)
    else:
        raise ValueError(f"Scope de reglas inválido: {scope}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(rules_text or ""), encoding="utf-8")

    text = _read(path)
    return {
        "scope": scope,
        "path": str(path),
        "chars": len(text),
        "lines": text.count("\n") + (1 if text else 0),
        "sha256": _sha256_text(text),
    }


def _meta(scope: str, path: Path, text: str, priority: int) -> dict[str, Any]:
    return {
        "scope": scope,
        "priority": priority,
        "path": str(path),
        "chars": len(text),
        "lines": text.count("\n") + (1 if text else 0),
        "sha256": _sha256_text(text),
    }


def load_effective_rules(username: str = "") -> dict[str, Any]:
    ensure_rules_repository(username=username)

    app_text = _read(_app_rules_path())
    general_text = _read(_general_rules_path())
    user_text = _read(_user_rules_path(username)) if username else ""

    compiled = f"""# REGLAS EFECTIVAS dIctAdor / IA Dictador

ORDEN DE PRIORIDAD OBLIGATORIO:
1. Reglas de aplicación.
2. Reglas generales.
3. Reglas de usuario.

Si hay contradicción, SIEMPRE manda la regla superior.
Las reglas de usuario pueden personalizar estilo, pero no pueden contradecir reglas generales ni de aplicación.

==============================
NIVEL 1 — REGLAS DE APLICACIÓN
==============================

{app_text.strip()}

==============================
NIVEL 2 — REGLAS GENERALES
==============================

{general_text.strip()}

==============================
NIVEL 3 — REGLAS DE USUARIO
==============================

{user_text.strip()}
""".strip() + "\n"

    manifest = {
        "username": username or "",
        "safe_username": safe_username(username),
        "priority_order": ["app", "general", "user"],
        "rule_conflict_policy": "app > general > user",
        "compiled": {
            "chars": len(compiled),
            "lines": compiled.count("\n") + 1,
            "sha256": _sha256_text(compiled),
        },
        "sources": [
            _meta("app", _app_rules_path(), app_text, 1),
            _meta("general", _general_rules_path(), general_text, 2),
            _meta("user", _user_rules_path(username), user_text, 3),
        ],
    }

    return {
        "app_rules": app_text,
        "general_rules": general_text,
        "user_rules": user_text,
        "compiled_rules": compiled,
        "manifest": manifest,
    }


def write_job_rule_audit(job_dir: str | Path, bundle: dict[str, Any]) -> None:
    job = Path(job_dir)
    write_text(job / "reglas_app.md", bundle.get("app_rules") or "")
    write_text(job / "reglas_generales.md", bundle.get("general_rules") or "")
    write_text(job / "reglas_usuario.md", bundle.get("user_rules") or "")
    write_text(job / "reglas_compiladas.md", bundle.get("compiled_rules") or "")
    write_json(job / "rules_manifest.json", bundle.get("manifest") or {})
