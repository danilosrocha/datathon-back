"""Plano recomendado e as três ofertas: melhor_ajuste, custo_beneficio e protecao_ampliada
(ARQUITETURA §5.3)."""

from typing import Any

from app.domain.decision import Hypothesis, Need, Offer, OfferCoverage, OfferKind, PlanCode
from app.domain.fact_keys import get_fact_key
from app.engine.catalog import PLAN_ORDER, Catalog, Coverage
from app.engine.estimates import Input, estimate, input_factor
from app.engine.rules import COMBINATORS, Tri, evaluate

# Premissa da equipe (análoga à L-01): específicas da atividade só existem no Prático/Total;
# se alguma se aplica, o plano mínimo sobe para o Prático.
SPECIFIC_RULE_ID = "PLN-ESP"
CHEAPER_RULE_ID = "ALT-CUSTO"
WIDER_RULE_ID = "ALT-AMPLIADA"

NO_RULE_NOTE = (
    "Sem regra de dimensionamento: valor definido na cotação, conforme condições gerais (L-02)."
)


class ConfigurationError(ValueError):
    """Oferta inválida no catálogo: é bug de regra, não erro do usuário."""


def _known_keys(keys, values: dict[str, Any]) -> list[str]:
    return sorted(k for k in keys if k in values)


def _applicable_extras(values: dict[str, Any], catalog: Catalog) -> dict[str, OfferCoverage]:
    """Específicas e opcionais acionadas por fatos (estimado entra como hipótese)."""
    extras: dict[str, OfferCoverage] = {}

    def add(cov: Coverage, rule_id: str, keys, risk: str | None, text: str) -> None:
        extras[cov.codigo] = OfferCoverage(
            code=cov.codigo,
            name=cov.nome,
            group=cov.grupo,
            rule_id=rule_id,
            fact_keys=_known_keys(keys, values),
            risk=risk,
            need=cov.dimensao,
            justification=text,
        )

    for cov in catalog.coverages.values():
        if cov.grupo in ("especifica_atividade", "opcional") and cov.quando:
            ev = evaluate(cov.quando, values)
            if ev.value is Tri.VERDADEIRO:
                text = "Compatível com a atividade informada."
                add(cov, f"CAT:{cov.codigo}", ev.fact_keys, None, text)

    # Regras REC-* têm prioridade: trazem risco, necessidade e texto próprios.
    for rule in catalog.additionals:
        ev = evaluate(rule.se, values)
        if ev.value is Tri.VERDADEIRO:
            cov = catalog.coverages[rule.cobertura]
            add(cov, rule.id, ev.fact_keys, rule.risco, rule.texto)
    return extras


def select_plan(
    values: dict[str, Any], catalog: Catalog, needs_specific: bool
) -> tuple[PlanCode, list[str], list[str]]:
    """Vence o plano mínimo mais alto acionado. Devolve (plano, regras, fatos que o justificam)."""
    plan: PlanCode = "ESSENCIAL"
    rule_ids: list[str] = []
    keys: set[str] = set()
    for rule in catalog.plan_rules:
        ev = evaluate(rule.se, values)
        if ev.value is not Tri.VERDADEIRO:
            continue
        rule_ids.append(rule.id)
        keys |= ev.fact_keys
        if PLAN_ORDER.index(rule.plano_minimo) > PLAN_ORDER.index(plan):
            plan = rule.plano_minimo
    if needs_specific and plan == "ESSENCIAL":
        plan = "PRATICO"
        rule_ids.append(SPECIFIC_RULE_ID)
    return plan, sorted(rule_ids), _known_keys(keys, values)


def _annotate(cov: OfferCoverage, hyp_keys: set[str], needs: list[Need]) -> OfferCoverage:
    """Completa a trilha com o grafo: risco pela necessidade da mesma dimensão e, se a cobertura
    depende de hipótese, o que confirmar."""
    risk = cov.risk
    if risk is None:
        need = next((n for n in needs if n.dimension == cov.need), None)
        evidence = [e for e in need.evidence if e.fact_key in cov.fact_keys] if need else []
        risk = evidence[0].risk if evidence else None
    guessed = sorted(set(cov.fact_keys) & hyp_keys)
    to_confirm = [f"Confirmar: {get_fact_key(k).label.lower()}?" for k in guessed]
    justification = cov.justification
    if guessed:
        justification += " Sugerida pelo perfil típico da atividade."
    return cov.model_copy(
        update={"risk": risk, "to_confirm": to_confirm, "justification": justification}
    )


def size_coverage(cov: OfferCoverage, inputs: dict[str, Input], catalog: Catalog) -> OfferCoverage:
    est = estimate(cov.code, inputs, catalog)
    if est is None:
        return cov.model_copy(update={"note": NO_RULE_NOTE})
    return cov.model_copy(
        update={
            "insured_amount": est.amount,
            "confidence": est.confidence,
            "data_used": est.data_used,
            "calc_rule": est.calc_rule,
            "to_confirm": sorted(set(cov.to_confirm) | set(est.to_confirm)),
        }
    )


def _compose(
    offer_id: str,
    kind: OfferKind,
    plan_code: PlanCode,
    plan_rules: list[str],
    plan_keys: list[str],
    extras: list[OfferCoverage],
    inputs: dict[str, Input],
    hyps: list[Hypothesis],
    needs: list[Need],
    catalog: Catalog,
) -> Offer:
    plan = catalog.plans[plan_code]

    def plan_item(code: str, rule_id: str, keys: list[str], text: str) -> OfferCoverage:
        cov = catalog.coverages[code]
        return OfferCoverage(
            code=code,
            name=cov.nome,
            group=cov.grupo,
            rule_id=rule_id,
            fact_keys=keys,
            risk=None,
            need=cov.dimensao,
            justification=text,
        )

    fixed_text = "Cobertura fixa: obrigatória em todos os planos."
    coverages = [plan_item(c, f"PLANO:{plan_code}", [], fixed_text) for c in plan.fixas]
    padrao_rule = plan_rules[-1] if plan_rules else f"PLANO:{plan_code}"
    padrao_text = f"Incluída no plano {plan_code}."
    coverages += [plan_item(c, padrao_rule, plan_keys, padrao_text) for c in plan.padrao]
    coverages += [c for c in extras if c.group == "opcional" or plan.permite_especificas]

    hyp_keys = {h.fact_key for h in hyps}
    coverages = [size_coverage(_annotate(c, hyp_keys, needs), inputs, catalog) for c in coverages]
    offer = Offer(
        offer_id=offer_id,
        kind=kind,
        plan_code=plan_code,
        plan_rule_ids=plan_rules,
        coverages=sorted(coverages, key=lambda c: c.code),
        assistance_packages=plan.assistencias,
        premium_benefit=(
            {"options": plan.beneficio_premium["escolha_uma"], "selected": None}
            if plan.beneficio_premium
            else None
        ),
    )
    validate_offer(offer, catalog)
    return offer


def _priority(dimension: str, needs: list[Need]) -> str:
    return next((n.priority for n in needs if n.dimension == dimension), "baixa")


def recommend(
    inputs: dict[str, Input], catalog: Catalog, hyps: list[Hypothesis], needs: list[Need]
) -> list[Offer]:
    """melhor_ajuste + alternativas. Alternativa idêntica à melhor não é oferecida.

    - custo_beneficio: plano abaixo; no Essencial, o mesmo plano sem opcionais de prioridade
      média/baixa. Comparação de coberturas, não de preço (L-12).
    - protecao_ampliada: plano acima, com as padrão e as específicas que ele libera.
    """
    values = {k: i.value for k, i in inputs.items()}
    extras = list(_applicable_extras(values, catalog).values())
    needs_specific = any(c.group == "especifica_atividade" for c in extras)
    plan_code, plan_rules, plan_keys = select_plan(values, catalog, needs_specific)

    def compose(offer_id, kind, plan, rules, keys, items):
        return _compose(offer_id, kind, plan, rules, keys, items, inputs, hyps, needs, catalog)

    best = compose("of_1", "melhor_ajuste", plan_code, plan_rules, plan_keys, extras)
    offers = [best]

    idx = PLAN_ORDER.index(plan_code)
    if idx > 0:
        cheaper = compose(
            "of_2", "custo_beneficio", PLAN_ORDER[idx - 1], [CHEAPER_RULE_ID], [], extras
        )
    else:
        lean = [c for c in extras if c.group != "opcional" or _priority(c.need, needs) == "alta"]
        cheaper = compose("of_2", "custo_beneficio", plan_code, [CHEAPER_RULE_ID], [], lean)
    if {c.code for c in cheaper.coverages} != {c.code for c in best.coverages}:
        offers.append(cheaper)

    if idx < len(PLAN_ORDER) - 1:
        wider_plan = PLAN_ORDER[idx + 1]
        offers.append(compose("of_3", "protecao_ampliada", wider_plan, [WIDER_RULE_ID], [], extras))
    return offers


def _leaves(cond: dict) -> list[dict]:
    if "fato" in cond:
        return [cond]
    (name,) = (k for k in cond if k in COMBINATORS)
    return [leaf for c in cond[name] for leaf in _leaves(c)]


def plan_confidence(offer: Offer, inputs: dict[str, Input], catalog: Catalog) -> float:
    """Quão sustentada pelos dados está a escolha do plano (0–1).

    - Plano acima do Essencial: a evidência mais forte entre as condições verdadeiras das regras
      que levaram a este plano (um risco regional estimado sustenta pouco; um fato da base, mais).
    - Essencial: cada regra de subida precisa estar descartada por fatos sabidos; vale o descarte
      mais fraco (condição desconhecida = 0, ausência não é "não").
    """
    factors = catalog.estimates.status_factors
    values = {k: i.value for k, i in inputs.items()}

    def strength(key: str) -> float:
        item = inputs.get(key)
        return input_factor(item, factors) if item is not None else 0.0

    if offer.plan_code != "ESSENCIAL":
        best = 0.0
        for rule in catalog.plan_rules:
            if rule.id in offer.plan_rule_ids and rule.plano_minimo == offer.plan_code:
                for leaf in _leaves(rule.se):
                    if evaluate(leaf, values).value is Tri.VERDADEIRO:
                        best = max(best, strength(leaf["fato"]))
        if SPECIFIC_RULE_ID in offer.plan_rule_ids:
            specific = [c for c in offer.coverages if c.group == "especifica_atividade"]
            best = max([best, *(strength(k) for c in specific for k in c.fact_keys)])
        return round(best, 2)

    weakest = 1.0
    for rule in catalog.plan_rules:
        discarded = [
            strength(leaf["fato"])
            for leaf in _leaves(rule.se)
            if evaluate(leaf, values).value is Tri.FALSO
        ]
        unknown = len(_leaves(rule.se)) - len(discarded)
        weakest = min(weakest, 0.0 if unknown else min(discarded))
    return round(weakest, 2)


def plan_open_keys(offer: Offer, inputs: dict[str, Input], catalog: Catalog) -> list[str]:
    """Fatos desconhecidos (e perguntáveis) que ainda podem subir o plano: viram perguntas de
    confirmação. Ex.: Essencial sem saber se a fachada é de vidro (PLN-02 → Total)."""
    values = {k: i.value for k, i in inputs.items()}
    current = PLAN_ORDER.index(offer.plan_code)
    keys = set()
    for rule in catalog.plan_rules:
        if PLAN_ORDER.index(rule.plano_minimo) > current:
            for leaf in _leaves(rule.se):
                key = leaf["fato"]
                if (
                    evaluate(leaf, values).value is Tri.DESCONHECIDO
                    and get_fact_key(key).extractable
                ):
                    keys.add(key)
    return sorted(keys)


def validate_offer(offer: Offer, catalog: Catalog) -> None:
    """Configuração válida no catálogo; falhou → exceção (bug de regra)."""
    for message in offer_violations(offer, catalog):
        raise ConfigurationError(message)


def offer_violations(offer: Offer, catalog: Catalog) -> list[str]:
    plan = catalog.plans[offer.plan_code]
    codes = [c.code for c in offer.coverages]
    problems = []
    if len(codes) != len(set(codes)):
        problems.append(f"cobertura repetida na oferta {offer.kind}")
    missing = set(plan.fixas) - set(codes)
    if missing:
        problems.append(f"fixas ausentes: {sorted(missing)}")
    for c in offer.coverages:
        cov = catalog.coverages.get(c.code)
        if cov is None:
            problems.append(f"cobertura inexistente: {c.code}")
            continue
        if c.group != cov.grupo:
            problems.append(f"{c.code}: grupo {c.group} diverge do catálogo")
        if cov.grupo == "padrao_plano" and c.code not in plan.padrao:
            problems.append(f"{c.code} não é padrão do plano {offer.plan_code} (L-01)")
        if cov.grupo == "especifica_atividade" and not plan.permite_especificas:
            problems.append(f"{c.code}: específica não permitida no {offer.plan_code}")
        if not c.rule_id:
            problems.append(f"{c.code}: cobertura sem trilha")
        amount = c.insured_amount
        if amount is None and (c.code in catalog.estimates.rules or not c.note):
            problems.append(f"{c.code}: sem faixa (só com regra ausente e nota)")
        if amount and not (
            amount.min <= amount.max
            and (cov.is_min is None or amount.min >= cov.is_min)
            and (cov.is_max is None or amount.max <= cov.is_max)
        ):
            problems.append(f"{c.code}: faixa fora dos limites {amount}")
    return problems
