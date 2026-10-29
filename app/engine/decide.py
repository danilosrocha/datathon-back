"""decide(fatos, catálogo, grafo) -> Decision. Função pura: sem IO, sem relógio, sem LLM."""

from typing import Any

from app.domain.decision import Decision, Hypothesis, Need, Versions
from app.domain.facts import Fact
from app.engine.cards import build_cards
from app.engine.catalog import Catalog
from app.engine.eligibility import assess_eligibility
from app.engine.estimates import Input, basic_minimum, build_inputs
from app.engine.explain_template import (
    confirmation_questions,
    describe,
    external_sources,
    overall_confidence,
)
from app.engine.needs import assess_needs, graph_hypotheses
from app.engine.prefill import quote_prefill
from app.engine.recommender import plan_confidence, plan_open_keys, recommend
from app.graph.store import GraphSnapshot

# CNAE seção A (agropecuária) = divisões 01 a 03.
AGRO_DIVISIONS = {"01", "02", "03"}


def derive_facts(facts: dict[str, Fact], catalog: Catalog) -> dict[str, Any]:
    """Fatos que o motor calcula a partir de entradas sabidas (nunca de estimativas).
    O fato do caso, se existir, prevalece."""
    known = build_inputs(facts, [], include_estimated=False)
    derived: dict[str, Any] = {}
    # ELG-008: IS básica mínima pelas faixas declaradas.
    if "is_basica_estimada" not in facts and (basic := basic_minimum(known, catalog)) is not None:
        derived["is_basica_estimada"] = basic
    # ELG-007 (L-03) e ELG-001: atividade aceita e não rural = CNAE fora da seção A.
    if "cnae_principal" in known:
        agro = known["cnae_principal"].value[:2] in AGRO_DIVISIONS
        if "atividade_aceita" not in facts:
            derived["atividade_aceita"] = not agro
        if "atividade_rural" not in facts:
            derived["atividade_rural"] = agro
    return derived


def case_context(
    facts: dict[str, Fact], graph: GraphSnapshot
) -> tuple[list[Hypothesis], dict[str, Input], list[Need]]:
    """Hipóteses do grafo, entradas (com estimados e hipóteses) e necessidades do caso."""
    hyps = graph_hypotheses(facts, graph)
    inputs = build_inputs(facts, hyps, include_estimated=True)
    values = {k: i.value for k, i in inputs.items()}
    return hyps, inputs, assess_needs(facts, values, hyps, graph)


def decide(facts: dict[str, Fact], catalog: Catalog, graph: GraphSnapshot) -> Decision:
    derived = derive_facts(facts, catalog)
    eligibility = assess_eligibility(facts, catalog, derived)
    versions = Versions(rules=catalog.version, rules_hash=catalog.content_hash, kg=graph.version)

    if eligibility.status == "inelegivel":
        return Decision(
            status=None,
            eligibility=eligibility,
            derived=derived,
            hypotheses=[],
            needs=[],
            offers=[],
            confidence=None,
            confirmation_questions=[],
            external_sources=external_sources(facts),
            versions=versions,
        )

    # Necessidades, ofertas e faixas enxergam estimados e hipóteses do grafo; a elegibilidade, não.
    hyps, inputs, needs = case_context(facts, graph)
    offers = recommend(inputs, catalog, hyps, needs)
    best = offers[0]
    offers = [
        o.model_copy(
            update={
                **describe(o, best),
                "quote_prefill": quote_prefill(o, inputs, catalog),
                "coverage_cards": build_cards(o, facts, catalog),
            }
        )
        for o in offers
    ]

    return Decision(
        status="conclusiva" if eligibility.status == "elegivel" else "preliminar",
        eligibility=eligibility,
        derived=derived,
        hypotheses=hyps,
        needs=needs,
        offers=offers,
        confidence=overall_confidence(best, plan_confidence(best, inputs, catalog)),
        confirmation_questions=confirmation_questions(
            eligibility, best, catalog, plan_open_keys(best, inputs, catalog)
        ),
        external_sources=external_sources(facts),
        versions=versions,
    )
