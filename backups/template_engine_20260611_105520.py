from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


BASE_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = BASE_DIR / "report_templates"


def load_template(template_id: str = "tc_tap_cc") -> dict[str, Any]:
    path = TEMPLATE_DIR / f"{template_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No existe plantilla: {path}")

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _line_status_class(tags: list[str], requires_review: bool) -> str:
    if "CONFLICTO" in tags:
        return "conflicto"
    if requires_review:
        return "revisar"
    if "ELIMINADO" in tags:
        return "eliminado"
    if "REEMPLAZADO" in tags:
        return "reemplazado"
    if "AGREGADO" in tags:
        return "agregado"
    if "IA" in tags:
        return "ia"
    return "normal"


def build_report(template: dict[str, Any], interpretation: dict[str, Any] | None = None) -> dict[str, Any]:
    interpretation = interpretation or {"actions": [], "global_warnings": []}
    sections = deepcopy(template["sections"])

    # Normalizar líneas
    for section in sections:
        for line in section["lines"]:
            line["tags"] = []
            line["status_class"] = "normal"
            line["requires_review"] = False
            line["note"] = ""
            line["review_reasons"] = []
            line["original_text"] = ""

    actions = interpretation.get("actions", [])

    for action in actions:
        action_type = action.get("type")
        section_key = action.get("section")

        target_section = None
        for section in sections:
            if section["key"] == section_key:
                target_section = section
                break

        if target_section is None:
            continue

        if action_type == "replace":
            for line in target_section["lines"]:
                if line["id"] == action.get("line_id"):
                    line["original_text"] = line["text"]
                    line["text"] = action.get("new_text", line["text"])
                    line["tags"] = action.get("tags", ["REEMPLAZADO"])
                    line["requires_review"] = bool(action.get("requires_review", False))
                    line["note"] = action.get("note", "")
                    line["review_reasons"] = action.get("review_reasons", [])
                    line["status_class"] = _line_status_class(line["tags"], line["requires_review"])
                    break

        elif action_type == "remove":
            for line in target_section["lines"]:
                if line["id"] == action.get("line_id"):
                    line["tags"] = action.get("tags", ["ELIMINADO"])
                    line["requires_review"] = bool(action.get("requires_review", False))
                    line["note"] = action.get("note", "")
                    line["review_reasons"] = action.get("review_reasons", [])
                    line["status_class"] = _line_status_class(line["tags"], line["requires_review"])
                    line["removed"] = True
                    break

        elif action_type == "add_after":
            new_line = {
                "id": action.get("new_id", "linea_agregada"),
                "text": action.get("new_text", ""),
                "tags": action.get("tags", ["AGREGADO"]),
                "requires_review": bool(action.get("requires_review", False)),
                "note": action.get("note", ""),
                "review_reasons": action.get("review_reasons", []),
                "original_text": "",
                "status_class": _line_status_class(action.get("tags", ["AGREGADO"]), bool(action.get("requires_review", False))),
                "added": True,
            }

            after_id = action.get("after_id")
            insert_idx = len(target_section["lines"])

            for idx, line in enumerate(target_section["lines"]):
                if line["id"] == after_id:
                    insert_idx = idx + 1
                    break

            # Evitar duplicados por id si se procesa varias veces
            already_exists = any(line["id"] == new_line["id"] for line in target_section["lines"])
            if not already_exists:
                target_section["lines"].insert(insert_idx, new_line)

    clean_text = render_clean_text(template["nombre"], sections)
    stats = collect_stats(sections, interpretation)

    return {
        "template_name": template["nombre"],
        "sections": sections,
        "clean_text": clean_text,
        "stats": stats,
        "global_warnings": interpretation.get("global_warnings", []),
        "dictado_normalizado": interpretation.get("dictado_normalizado", ""),
    }


def render_clean_text(title: str, sections: list[dict[str, Any]]) -> str:
    chunks = [title, ""]

    for section in sections:
        chunks.append(section["title"] + ":")
        visible_lines = []

        for line in section["lines"]:
            if line.get("removed"):
                continue
            text = (line.get("text") or "").strip()
            if text:
                visible_lines.append(text)

        if visible_lines:
            chunks.extend(visible_lines)
        else:
            chunks.append("")

        chunks.append("")

    return "\n".join(chunks).strip() + "\n"


def collect_stats(sections: list[dict[str, Any]], interpretation: dict[str, Any]) -> dict[str, int]:
    stats = {
        "agregado": 0,
        "reemplazado": 0,
        "ia": 0,
        "revisar": 0,
        "conflicto": 0,
        "eliminado": 0,
    }

    for section in sections:
        for line in section["lines"]:
            tags = line.get("tags", [])
            if "AGREGADO" in tags:
                stats["agregado"] += 1
            if "REEMPLAZADO" in tags:
                stats["reemplazado"] += 1
            if "IA" in tags:
                stats["ia"] += 1
            if line.get("requires_review"):
                stats["revisar"] += 1
            if "CONFLICTO" in tags:
                stats["conflicto"] += 1
            if "ELIMINADO" in tags:
                stats["eliminado"] += 1

    return stats
