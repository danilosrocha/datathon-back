"""Elegibilidade em três valores (ARQUITETURA §5.2): impedimento VERDADEIRO → inelegível;
nenhum verdadeiro e algum DESCONHECIDO → pendente; todos FALSO → elegível."""

from typing import Any

from app.domain.decision import Blocker, Eligibility, Pending
from app.domain.facts import Fact
from app.engine.catalog import Catalog
from app.engine.rules import Tri, evaluate, usable_values


def assess_eligibility(
    facts: dict[str, Fact], catalog: Catalog, derived: dict[str, Any] | None = None
) -> Eligibility:
    """`derived`: fatos calculados pelo motor; o fato do caso, se existir, prevalece."""
    # Estimado não decide elegibilidade: fica DESCONHECIDO até ser confirmado.
    values = (derived or {}) | usable_values(facts, include_estimated=False)
    blockers: list[Blocker] = []
    pending: list[Pending] = []
    redirect_to = None

    for rule in catalog.eligibility:
        ev = evaluate(rule.quando, values)
        if ev.value is Tri.VERDADEIRO:
            blockers.append(
                Blocker(rule_id=rule.id, description=rule.descricao, fact_keys=sorted(ev.fact_keys))
            )
            if rule.tipo == "redirecionamento":
                redirect_to = rule.destino
        elif ev.value is Tri.DESCONHECIDO and rule.tipo == "impedimento":
            # Redirecionamento depende de fato derivado pelo motor, não vira pergunta.
            pending += [
                Pending(fact_key=k, rule_id=rule.id, why=rule.descricao) for k in ev.unknown
            ]

    status = "inelegivel" if blockers else "pendente" if pending else "elegivel"
    return Eligibility(
        status=status,
        blockers=sorted(blockers, key=lambda b: b.rule_id),
        pending=sorted(pending, key=lambda p: (p.rule_id, p.fact_key)),
        rules_version=catalog.version,
        redirect_to=redirect_to,
    )
