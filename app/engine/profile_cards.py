"""Projeção de cada fato do caso em card para a UI (CONTRATOS_API §3.2). Função pura."""

from typing import Any

from app.domain.fact_keys import get_fact_key
from app.domain.facts import Fact
from app.engine.catalog import Catalog
from app.engine.rules import condition_keys

BOOLEAN_DISPLAY = {True: "Sim", False: "Não"}


def importance(key: str, catalog: Catalog) -> str:
    """alta: decide elegibilidade ou plano; media: dimensiona faixa ou aciona cobertura."""
    decisive: set[str] = set()
    for rule in catalog.eligibility:
        decisive |= condition_keys(rule.quando)
    for rule in catalog.plan_rules:
        decisive |= condition_keys(rule.se)
    if key in decisive:
        return "alta"
    sizing = {k for r in catalog.estimates.rules.values() for k in r.entradas}
    sizing |= {k for c in catalog.coverages.values() if c.quando for k in condition_keys(c.quando)}
    return "media" if key in sizing else "baixa"


def display_value(fact: Fact, catalog: Catalog) -> str:
    value = fact.value
    if value is None:
        return "Removido"
    if isinstance(value, bool):
        return BOOLEAN_DISPLAY[value]
    if isinstance(value, list):
        return ", ".join(catalog.option_labels.get(v, v) for v in value)
    return catalog.option_labels.get(str(value), str(value))


def fact_card(fact: Fact, catalog: Catalog) -> dict[str, Any]:
    spec = get_fact_key(fact.key)
    editable: dict[str, Any] = {"type": spec.type}
    if spec.options:
        editable["options"] = [
            {"value": o, "label": catalog.option_labels.get(o, o)} for o in spec.options
        ]
    if spec.type == "number":
        editable |= {"min": spec.min, "max": spec.max}
    return {
        "key": fact.key,
        "label": spec.label,
        "group": spec.group,
        "value": fact.value,
        "display_value": display_value(fact, catalog),
        "status": fact.status.value,
        "source": fact.source.value,
        "confidence": fact.confidence,
        "evidence": fact.evidence,
        "importance": importance(fact.key, catalog),
        "editable": editable,
        "updated_at": fact.updated_at.isoformat(),
    }


def profile_cards(facts: dict[str, Fact], catalog: Catalog) -> list[dict[str, Any]]:
    return [fact_card(f, catalog) for _, f in sorted(facts.items())]
