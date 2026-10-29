"""Hipóteses do context graph e necessidades de proteção (ARQUITETURA §5.3).

Hipótese: característica com p(k | CNAE) ≥ 0,8 ainda sem fato no caso. Fato rejeitado não volta
como hipótese. Hipóteses valem só para necessidades e oferta — nunca para elegibilidade.
"""

from typing import Any

from app.domain.decision import Hypothesis, Need, NeedEvidence
from app.domain.fact_keys import get_fact_key
from app.domain.facts import Fact, FactStatus
from app.graph.reasoner import exposures, hypotheses
from app.graph.store import GraphSnapshot

# Mesmo limiar da pergunta de confirmação (CONTRATOS_API §3.3).
HYPOTHESIS_MIN_P = 0.8
PRIORITY = ((0.7, "alta"), (0.4, "media"), (0.0, "baixa"))


def graph_hypotheses(facts: dict[str, Fact], graph: GraphSnapshot) -> list[Hypothesis]:
    cnae = facts.get("cnae_principal")
    if cnae is None or not cnae.is_known:
        return []
    result = []
    for key, p in hypotheses(graph, cnae.value).items():
        if key in facts or p < HYPOTHESIS_MIN_P or get_fact_key(key).never_estimated:
            continue
        result.append(Hypothesis(fact_key=key, value=True, p=round(p, 4)))
    return sorted(result, key=lambda h: h.fact_key)


def assess_needs(
    facts: dict[str, Fact],
    values: dict[str, Any],
    hyps: list[Hypothesis],
    graph: GraphSnapshot,
) -> list[Need]:
    """Para cada característica presente (fato, estimativa ou hipótese), segue os riscos até as
    dimensões. Força da evidência = p(característica) × peso da exposição; prioridade pela maior."""
    hyp_p = {h.fact_key: h.p for h in hyps}
    by_dim: dict[str, list[NeedEvidence]] = {}
    for key, value in sorted(values.items()):
        if value is not True:
            continue
        if key in hyp_p:
            origin, p = "hipotese", hyp_p[key]
        elif facts[key].status is FactStatus.ESTIMADO:
            origin, p = "estimado", facts[key].confidence
        else:
            origin, p = "fato", 1.0
        for risk, weight, dims in exposures(graph, key):
            for dim in dims:
                by_dim.setdefault(dim, []).append(
                    NeedEvidence(
                        fact_key=key,
                        risk=risk,
                        origin=origin,
                        strength=round(p * weight, 4),
                    )
                )

    needs = []
    for dim, evidence in sorted(by_dim.items()):
        score = max(e.strength for e in evidence)
        priority = next(label for floor, label in PRIORITY if score >= floor)
        evidence = sorted(evidence, key=lambda e: (-e.strength, e.fact_key, e.risk))
        needs.append(Need(dimension=dim, priority=priority, score=score, evidence=evidence))
    return needs
