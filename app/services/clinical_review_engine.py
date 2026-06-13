from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Callable


def s(value: Any) -> str:
    return "" if value is None else str(value)


def norm(value: Any) -> str:
    text = s(value)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_lines(text: str) -> list[str]:
    return [line.rstrip() for line in s(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", s(text))
    return [p.strip() for p in parts if p.strip()]


def sentence_matching(text: str, pattern: str) -> str:
    rx = re.compile(pattern, re.I)
    for sentence in split_sentences(text):
        if rx.search(sentence):
            return sentence.strip()
    return ""


def measure_from_text(text: str) -> str:
    m = re.search(
        r"(\d+(?:[,.]\d+)?)\s*(mm|mil[ií]metros|cm|cent[ií]metros)",
        s(text),
        flags=re.I,
    )
    if not m:
        return ""
    unit = m.group(2).lower()
    if "mil" in unit:
        unit = "mm"
    elif "cent" in unit:
        unit = "cm"
    return f"{m.group(1)} {unit}"


def remove_measurements(text: str) -> str:
    out = s(text)
    out = re.sub(
        r"\s*,?\s*de hasta\s+\d+(?:[,.]\d+)?\s*(mm|mil[ií]metros|cm|cent[ií]metros)",
        "",
        out,
        flags=re.I,
    )
    out = re.sub(
        r"\s*,?\s*hasta\s+\d+(?:[,.]\d+)?\s*(mm|mil[ií]metros|cm|cent[ií]metros)",
        "",
        out,
        flags=re.I,
    )
    out = re.sub(
        r"\s+\d+(?:[,.]\d+)?\s*(mm|mil[ií]metros|cm|cent[ií]metros)",
        "",
        out,
        flags=re.I,
    )
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+\.", ".", out)
    return out.strip()


def line_key(text: str) -> str:
    return re.sub(r"[.,;:]+$", "", norm(text))


def has_equivalent_line(report: str, line: str) -> bool:
    key = line_key(line)
    if not key:
        return True
    return any(line_key(existing) == key for existing in split_lines(report))


def remove_existing_impression(report: str) -> str:
    kept: list[str] = []
    in_impression = False

    for line in split_lines(report):
        nl = norm(line)

        if (
            nl.startswith("impresion")
            or nl.startswith("impresion diagnostica")
            or nl.startswith("conclusion")
            or nl.startswith("conclusion diagnostica")
        ):
            in_impression = True
            continue

        if in_impression:
            continue

        kept.append(line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


@dataclass(frozen=True)
class ConceptRule:
    id: str
    label: str
    source_mention: Callable[[str], bool]
    source_present: Callable[[str], bool]
    source_absent: Callable[[str], bool]
    line_mention: Callable[[str], bool]
    line_present: Callable[[str], bool]
    line_absent: Callable[[str], bool]
    finding_text: Callable[[str], str]
    impression_text: Callable[[str], str]
    source_text: Callable[[str], str]
    include_in_impression: bool = True


def prostate_finding(raw: str) -> str:
    sentence = sentence_matching(raw, r"pr[oó]stata")
    measure = measure_from_text(sentence)
    return "Próstata aumentada de tamaño" + (f", de hasta {measure}" if measure else "") + "."


def prostate_impression(raw: str) -> str:
    return "Aumento de tamaño prostático."


def adenopathy_finding(raw: str) -> str:
    sentence = sentence_matching(raw, r"adenopat")
    sentence_n = norm(sentence)
    measure = measure_from_text(sentence)
    iliac_left = (
        "iliacos izquierdos" in sentence_n
        or "iliaco izquierdo" in sentence_n
        or "vasos iliacos izquierdos" in sentence_n
    )
    return (
        "Adenopatías retroperitoneales"
        + (" en relación con los vasos ilíacos izquierdos" if iliac_left else "")
        + (f", de hasta {measure}" if measure else "")
        + "."
    )


def adenopathy_impression(raw: str) -> str:
    return "Adenopatías retroperitoneales."


CONCEPT_RULES: list[ConceptRule] = [
    ConceptRule(
        id="gallbladder",
        label="vesícula biliar",
        source_mention=lambda n: "vesicula" in n or "colecistectom" in n,
        source_present=lambda n: (
            "tiene vesicula" in n
            or "vesicula presente" in n
            or "con vesicula" in n
            or (
                "vesicula" in n
                and "sin vesicula" not in n
                and "vesicula ausente" not in n
                and "no se visualiza vesicula" not in n
                and "colecistectom" not in n
            )
        ),
        source_absent=lambda n: (
            "sin vesicula" in n
            or "vesicula ausente" in n
            or "no se visualiza vesicula" in n
            or "colecistectom" in n
        ),
        line_mention=lambda n: "vesicula" in n or "colecistectom" in n,
        line_present=lambda n: (
            "vesicula" in n
            and (
                "replecion" in n
                or "paredes delgadas" in n
                or "presente" in n
                or "normal" in n
            )
        ),
        line_absent=lambda n: (
            "sin vesicula" in n
            or "vesicula ausente" in n
            or "no se visualiza vesicula" in n
            or "colecistectom" in n
        ),
        finding_text=lambda raw: "Vesícula biliar presente.",
        impression_text=lambda raw: "",
        source_text=lambda raw: sentence_matching(raw, r"ves[ií]cula|colecistectom"),
        include_in_impression=False,
    ),
    ConceptRule(
        id="prostate_enlarged",
        label="próstata",
        source_mention=lambda n: "prostata" in n,
        source_present=lambda n: (
            "prostata" in n
            and (
                "aumentada" in n
                or "diametro transverso" in n
                or "diametro transversal" in n
                or "hiperplasia" in n
            )
        ),
        source_absent=lambda n: False,
        line_mention=lambda n: "prostata" in n,
        line_present=lambda n: (
            "prostata" in n
            and (
                "aumentada" in n
                or "hiperplasia" in n
                or "mayor tamano" in n
            )
        ),
        line_absent=lambda n: (
            "prostata" in n
            and (
                "tamano normal" in n
                or "estructura y tamano normal" in n
                or "dimensiones normales" in n
                or "sin alteraciones" in n
            )
        ),
        finding_text=prostate_finding,
        impression_text=prostate_impression,
        source_text=lambda raw: sentence_matching(raw, r"pr[oó]stata"),
    ),
    ConceptRule(
        id="retroperitoneal_adenopathy",
        label="adenopatías retroperitoneales",
        source_mention=lambda n: "adenopatia" in n or "adenopatias" in n,
        source_present=lambda n: "adenopatia" in n or "adenopatias" in n,
        source_absent=lambda n: False,
        line_mention=lambda n: "adenopat" in n,
        line_present=lambda n: "adenopat" in n,
        line_absent=lambda n: False,
        finding_text=adenopathy_finding,
        impression_text=adenopathy_impression,
        source_text=lambda raw: sentence_matching(raw, r"adenopat"),
    ),
    ConceptRule(
        id="aortic_atheromatosis",
        label="ateromatosis aórtica",
        source_mention=lambda n: "ateromatosis" in n,
        source_present=lambda n: "ateromatosis" in n,
        source_absent=lambda n: False,
        line_mention=lambda n: "ateromatosis" in n,
        line_present=lambda n: "ateromatosis" in n,
        line_absent=lambda n: False,
        finding_text=lambda raw: "Ateromatosis calcificada aórtica.",
        impression_text=lambda raw: "Ateromatosis calcificada aórtica.",
        source_text=lambda raw: sentence_matching(raw, r"ateromatosis"),
    ),
    ConceptRule(
        id="uncomplicated_diverticula",
        label="divertículos colónicos",
        source_mention=lambda n: "diverticul" in n,
        source_present=lambda n: "diverticul" in n,
        source_absent=lambda n: False,
        line_mention=lambda n: "diverticul" in n,
        line_present=lambda n: "diverticul" in n,
        line_absent=lambda n: False,
        finding_text=lambda raw: "Divertículos colónicos sin signos de complicación.",
        impression_text=lambda raw: "Diverticulosis colónica no complicada.",
        source_text=lambda raw: sentence_matching(raw, r"divert"),
    ),
]


def active_facts(source_text: str) -> list[dict[str, Any]]:
    source_n = norm(source_text)
    facts: list[dict[str, Any]] = []

    for rule in CONCEPT_RULES:
        if not rule.source_present(source_n):
            continue

        facts.append(
            {
                "id": rule.id,
                "label": rule.label,
                "text": rule.finding_text(source_text),
                "impression": remove_measurements(rule.impression_text(source_text)),
                "source": rule.source_text(source_text),
                "include_in_impression": rule.include_in_impression,
                "rule": rule,
            }
        )

    return facts


def concept_lines(report: str, rule: ConceptRule) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []

    for line in split_lines(report):
        nl = norm(line)
        if nl and rule.line_mention(nl):
            out.append({"line": line, "norm": nl})

    return out


def build_cards(source_text: str, base_text: str) -> list[dict[str, Any]]:
    source_n = norm(source_text)
    facts = active_facts(source_text)
    cards: list[dict[str, Any]] = []

    def add(kind: str, text: str, original: str = "", explanation: str = "", reasons: list[str] | None = None, card_id: str = ""):
        cards.append(
            {
                "kind": kind,
                "tipo": kind,
                "text": text,
                "texto": text,
                "original": original,
                "explanation": explanation,
                "explicacion": explanation,
                "reasons": reasons or [],
                "motivos": reasons or [],
                "requires_review": kind in {"conflicto", "revisar", "reemplazado", "agregado"},
                "requiere_revision": kind in {"conflicto", "revisar", "reemplazado", "agregado"},
                "id": card_id or f"{kind}:{line_key(text)}",
            }
        )

    for fact in facts:
        rule: ConceptRule = fact["rule"]
        lines = concept_lines(base_text, rule)

        contradictory = [
            x for x in lines
            if (
                (rule.source_present(source_n) and rule.line_absent(x["norm"]))
                or (rule.source_absent(source_n) and rule.line_present(x["norm"]))
            )
        ]

        if contradictory:
            add(
                "conflicto",
                f"El texto base/plantilla conserva una frase incompatible con el dictado: {fact['label']}.",
                fact["source"],
                "Debe prevalecer el dato dictado sobre la frase de plantilla.",
                [
                    "La plantilla puede traer frases normales o alternativas no aplicables.",
                    "El dictado contiene un dato explícito que resuelve el conflicto.",
                    "Eliminar la alternativa incompatible antes de firmar.",
                ],
                f"{fact['id']}:source-vs-template",
            )
            add(
                "reemplazado",
                fact["text"],
                fact["source"],
                "Corrección estructurada desde dictado.",
                ["Confirmar redacción final antes de firmar."],
                f"{fact['id']}:replacement",
            )
        else:
            # Evita tarjeta redundante si el texto base ya expresa el mismo concepto compatible.
            if any(rule.line_present(x["norm"]) for x in lines):
                continue

            if fact["id"] == "gallbladder":
                continue

            add(
                "agregado",
                fact["text"],
                fact["source"],
                "Hallazgo positivo estructurado desde dictado.",
                ["Confirmar si corresponde mantenerlo en hallazgos y/o impresión."],
                f"{fact['id']}:added",
            )

    # Revisión transversal de menciones duplicadas/incompatibles en el texto base.
    for rule in CONCEPT_RULES:
        lines = concept_lines(base_text, rule)
        if len(lines) < 2:
            continue

        has_present = any(rule.line_present(x["norm"]) for x in lines)
        has_absent = any(rule.line_absent(x["norm"]) for x in lines)

        if not (has_present and has_absent):
            continue

        source_mentions = rule.source_mention(source_n)
        source_present = rule.source_present(source_n)
        source_absent = rule.source_absent(source_n)

        if source_mentions and (source_present or source_absent):
            add(
                "conflicto",
                f"El texto base/plantilla contiene menciones incompatibles para {rule.label}, pero el dictado orienta la elección.",
                rule.source_text(source_text),
                "Debe prevalecer el dato dictado sobre la contradicción de plantilla.",
                [
                    "Hay menciones duplicadas o discordantes en el texto base.",
                    "El dictado contiene información explícita para resolverlo.",
                    "Eliminar la alternativa incompatible antes de firmar.",
                ],
                f"{rule.id}:base-discordance-resolved",
            )
        else:
            add(
                "revisar",
                f"El texto base/plantilla menciona {rule.label} con características incompatibles. Elegir una alternativa.",
                " / ".join(x["line"] for x in lines),
                "El dictado no resuelve esta discrepancia.",
                [
                    "Hay al menos una mención positiva y una negativa/normal incompatible.",
                    "Se requiere selección manual.",
                ],
                f"{rule.id}:base-discordance-unresolved",
            )

    if not cards:
        add(
            "normal",
            "No se detectaron conflictos conceptuales; revisar informe limpio final.",
            "",
            "No se generaron tarjetas específicas.",
            [],
            "none",
        )

    # Deduplicación por id.
    priority = {"conflicto": 40, "reemplazado": 30, "agregado": 20, "revisar": 15, "normal": 10}
    dedup: dict[str, dict[str, Any]] = {}

    for card in cards:
        key = s(card.get("id")) or f"{card.get('kind')}:{line_key(card.get('text'))}"
        prev = dedup.get(key)
        if not prev or priority.get(s(card.get("kind")), 0) >= priority.get(s(prev.get("kind")), 0):
            dedup[key] = card

    return list(dedup.values())


def clean_report(source_text: str, base_text: str) -> tuple[str, list[str]]:
    source_n = norm(source_text)
    facts = active_facts(source_text)
    warnings: list[str] = []

    has_positive_facts = bool(facts)
    out_lines: list[str] = []
    seen: set[str] = set()

    for line in split_lines(base_text):
        nl = norm(line)

        if not nl:
            out_lines.append("")
            continue

        remove_line = False

        for fact in facts:
            rule: ConceptRule = fact["rule"]

            if not rule.line_mention(nl):
                continue

            line_contradicts_source = (
                (rule.source_present(source_n) and rule.line_absent(nl))
                or (rule.source_absent(source_n) and rule.line_present(nl))
            )

            if line_contradicts_source:
                remove_line = True
                warnings.append(f"Se eliminó una frase de plantilla incompatible con el dictado: {rule.label}.")
                break

        if remove_line:
            continue

        if has_positive_facts and (
            "sin otras alteraciones" in nl
            or "sin otros hallazgos" in nl
            or "no hay otros hallazgos" in nl
            or "no se observan otras alteraciones" in nl
            or "sin otras alteraciones tomograficas agudas" in nl
            or "sin otras alteraciones agudas" in nl
        ):
            warnings.append("Se eliminó una frase global de ausencia de hallazgos por existir hallazgos positivos dictados.")
            continue

        key = line_key(line)
        if key and key in seen and len(key) > 8:
            continue

        if key:
            seen.add(key)

        out_lines.append(line)

    clean = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()

    for fact in facts:
        text = s(fact.get("text")).strip()
        if not text:
            continue

        # No agregar vesícula presente como hallazgo si la plantilla ya la describe compatible.
        if fact["id"] == "gallbladder":
            continue

        if not has_equivalent_line(clean, text):
            clean = (clean.rstrip() + "\n" + text).strip()

    clean = remove_existing_impression(clean)

    impression_lines: list[str] = []
    impression_seen: set[str] = set()

    for fact in facts:
        if not fact.get("include_in_impression"):
            continue

        impression = remove_measurements(s(fact.get("impression")).strip())
        key = line_key(impression)

        if not key or key in impression_seen:
            continue

        impression_seen.add(key)
        impression_lines.append(impression)

    if impression_lines:
        clean = clean.rstrip() + "\n\nImpresión diagnóstica:\n" + "\n".join(impression_lines)

    # Deduplicación final.
    final_lines: list[str] = []
    final_seen: set[str] = set()

    for line in split_lines(clean):
        key = line_key(line)

        if not key:
            if final_lines and final_lines[-1] != "":
                final_lines.append("")
            continue

        if key in final_seen and len(key) > 8:
            continue

        final_seen.add(key)
        final_lines.append(line)

    clean = re.sub(r"\n{3,}", "\n\n", "\n".join(final_lines)).strip()

    return clean, warnings


def review_clinical_report(
    source_text: str,
    base_text: str,
    clinical_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_text = s(source_text)
    base_text = s(base_text)
    clinical_json = clinical_json or {}

    facts = active_facts(source_text)
    cards = build_cards(source_text, base_text)
    clean, clean_warnings = clean_report(source_text, base_text)

    warnings: list[str] = []

    if any(card["kind"] == "conflicto" for card in cards):
        warnings.append("Se detectaron contradicciones entre el dictado y el texto base/plantilla.")

    if any(card["kind"] == "revisar" for card in cards):
        warnings.append("El texto base/plantilla contiene menciones duplicadas o discordantes que requieren elección manual.")

    warnings.extend(clean_warnings)

    # Deduplicar warnings.
    warnings = list(dict.fromkeys(warnings))

    return {
        "ok": True,
        "engine": "clinical_review_engine_v1",
        "source_text": source_text,
        "base_text": base_text,
        "clinical_json": clinical_json,
        "facts": [
            {
                "id": fact["id"],
                "label": fact["label"],
                "text": fact["text"],
                "impression": fact["impression"],
                "source": fact["source"],
            }
            for fact in facts
        ],
        "cards": cards,
        "warnings": warnings,
        "informe_limpio": clean,
        "revision": {
            "titulo": "Informe en modo revisión",
            "advertencias": warnings,
            "secciones": [
                {
                    "titulo": "Revisión clínica",
                    "bloques": [
                        {
                            "tipo": card["kind"],
                            "texto": card["text"],
                            "original": card["original"],
                            "explicacion": card["explanation"],
                            "motivos": card["reasons"],
                            "requiere_revision": card["requires_review"],
                            "fuente": "Motor clínico",
                        }
                        for card in cards
                    ],
                }
            ],
        },
    }
