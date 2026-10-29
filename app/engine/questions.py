"""Próxima pergunta ("Pergunta Certa", ARQUITETURA §4.4).

score(k) = 1000 · [k decide uma regra de elegibilidade em aberto]
         + impacto(k) · incerteza(k) − custo(k)

impacto(k)   = nº de coberturas da melhor oferta que mudam (entram, saem ou mudam de faixa)
               entre dois valores de k — contrafactual: roda o motor duas vezes
incerteza(k) = 1 − |2·p(k) − 1|  (p do grafo, da estimativa ou 0,5)
custo(k)     = 0 (sim/não) · 0,2 (seleção) · 0,5 (número/texto)

Parada: caso inelegível, nenhuma elegibilidade em aberto e impacto 0 em todo fato restante, ou
limite de 15 perguntas (a recomendação sai preliminar com as pendências).
"""

from datetime import UTC, datetime

from app.domain.decision import Decision, Question, QuestionInput, QuestionOption
from app.domain.fact_keys import FactKey, fact_keys, get_fact_key
from app.domain.facts import Fact, FactSource, FactStatus
from app.engine.catalog import Catalog
from app.engine.decide import decide
from app.engine.rules import condition_keys
from app.graph.reasoner import hypotheses
from app.graph.store import GraphSnapshot

MAX_QUESTIONS = 15
CONFIRMATION_P = 0.8
COST = {"boolean": 0.0, "select": 0.2, "multiselect": 0.2}
DEFAULT_COST = 0.5
# Data fixa para fatos contrafactuais: o motor não lê relógio.
_COUNTERFACTUAL_TS = datetime(1970, 1, 1, tzinfo=UTC)


def candidate_keys(catalog: Catalog, graph: GraphSnapshot) -> set[str]:
    """Toda chave que alguma regra, faixa ou o grafo usa — e que o usuário consegue responder."""
    keys: set[str] = set()
    for rule in catalog.eligibility:
        keys |= condition_keys(rule.quando)
    for rule in catalog.plan_rules:
        keys |= condition_keys(rule.se)
    for rule in catalog.additionals:
        keys |= condition_keys(rule.se)
    for cov in catalog.coverages.values():
        if cov.quando:
            keys |= condition_keys(cov.quando)
    for rule in catalog.estimates.rules.values():
        keys |= set(rule.entradas)
    keys |= {d["fact_key"] for _, d in graph.graph.nodes(data=True) if d.get("fact_key")}
    return {k for k in keys if fact_keys()[k].extractable}


def _signature(decision: Decision) -> dict[str, tuple[int, int] | None]:
    if not decision.offers:
        return {}
    return {
        c.code: (c.insured_amount.min, c.insured_amount.max) if c.insured_amount else None
        for c in decision.offers[0].coverages
    }


def _variants(spec: FactKey) -> list:
    if spec.type == "boolean":
        return [True, False]
    if spec.type == "select" and len(spec.options) > 1:
        return [spec.options[0], spec.options[-1]]
    return []


def impact(key: str, facts: dict[str, Fact], catalog: Catalog, graph: GraphSnapshot) -> int:
    signatures = []
    for value in _variants(get_fact_key(key)):
        fact = Fact(
            key=key,
            value=value,
            status=FactStatus.CONFIRMADO,
            source=FactSource.USUARIO_RESPOSTA,
            confidence=1.0,
            updated_at=_COUNTERFACTUAL_TS,
            updated_by="motor:contrafactual",
        )
        signatures.append(_signature(decide({**facts, key: fact}, catalog, graph)))
    if len(signatures) < 2:
        return 0
    a, b = signatures
    return sum(a.get(code) != b.get(code) for code in a.keys() | b.keys())


def _probability(key: str, facts: dict[str, Fact], graph_p: dict[str, float]) -> float:
    fact = facts.get(key)
    if fact is not None and fact.status is FactStatus.ESTIMADO and fact.value is True:
        return fact.confidence
    return graph_p.get(key, 0.5)


def build_question(
    key: str, p: float, reason: str | None, score: float, catalog: Catalog
) -> Question:
    spec = get_fact_key(key)
    text = catalog.questions.get(key)
    confirm = p >= CONFIRMATION_P and text is not None and text.confirmacao is not None
    prompt = (
        text.confirmacao
        if confirm
        else text.texto
        if text
        else f"Pode me contar: {spec.label.lower()}?"
    )
    options = [QuestionOption(value=o, label=catalog.option_labels.get(o, o)) for o in spec.options]
    return Question(
        question_id=f"q_{key}",
        fact_key=key,
        prompt=prompt,
        style="confirmacao" if p >= CONFIRMATION_P else "aberta",
        input=QuestionInput(type=spec.type, options=options, min=spec.min, max=spec.max),
        reason=reason or (text.motivo if text else "Ajuda a ajustar a oferta e as faixas."),
        score=round(score, 4),
    )


def next_question(
    facts: dict[str, Fact],
    catalog: Catalog,
    graph: GraphSnapshot,
    asked: int = 0,
    decision: Decision | None = None,
) -> Question | None:
    """`decision`: a de `decide(facts, ...)`, se o chamador já tiver (evita recalcular)."""
    if asked >= MAX_QUESTIONS:
        return None
    decision = decision or decide(facts, catalog, graph)
    if decision.eligibility.status == "inelegivel":
        return None

    known = {k for k, f in facts.items() if f.is_known}
    # Sem atividade não há hipóteses nem regra de aceitação: identificação vem antes de tudo.
    if "cnae_principal" not in known:
        return build_question("cnae_principal", 0.5, None, 0.0, catalog)

    graph_p = hypotheses(graph, facts["cnae_principal"].value)
    pending = {p.fact_key: p.why for p in decision.eligibility.pending}
    scored = []
    for key in sorted(candidate_keys(catalog, graph) - known):
        p = _probability(key, facts, graph_p)
        uncertainty = 1 - abs(2 * p - 1)
        gain = impact(key, facts, catalog, graph)
        cost = COST.get(get_fact_key(key).type, DEFAULT_COST)
        score = 1000 * (key in pending) + gain * uncertainty - cost
        if key in pending or gain > 0:
            scored.append((score, key, p))
    if not scored:
        return None
    score, key, p = min(scored, key=lambda s: (-s[0], s[1]))
    return build_question(key, p, pending.get(key), score, catalog)
