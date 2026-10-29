"""Personalizar: aplica as mudanças do cliente sobre uma oferta e devolve a oferta `personalizada`
(com os cards de cobertura) ou as violações. Nenhum preço é calculado."""

from app.domain.decision import (
    CustomizeRequest,
    CustomizeResult,
    Offer,
    OfferCoverage,
    PrefillCoverage,
    Violation,
)
from app.domain.facts import Fact
from app.engine.cards import applicability, build_cards, card_order, lock_reason
from app.engine.catalog import Catalog
from app.engine.decide import case_context
from app.engine.explain_template import describe
from app.engine.prefill import quote_prefill
from app.engine.recommender import offer_violations, size_coverage
from app.engine.rules import Tri
from app.graph.store import GraphSnapshot

CUSTOMIZE_RULE_ID = "PERSONALIZAR"


def customize(
    base: Offer,
    request: CustomizeRequest,
    facts: dict[str, Fact],
    catalog: Catalog,
    graph: GraphSnapshot,
    current: Offer | None = None,
) -> CustomizeResult:
    """`base`: a oferta de origem (de `decide`). `current`: a personalizada atual, para mudanças
    cumulativas (um clique por vez nos cards); sem ela, aplica sobre a base. `reset` devolve a base
    (Oferta padrão). Coberturas sugeridas retiradas voltam com a faixa original."""
    suggested = {c.code for c in base.coverages}
    if request.reset:
        return CustomizeResult(
            offer=base.model_copy(
                update={"coverage_cards": build_cards(base, facts, catalog, suggested)}
            )
        )

    current = current or base
    _, inputs, _ = case_context(facts, graph)
    base_items = {c.code: c for c in base.coverages}
    coverages = {c.code: c for c in current.coverages}
    violations: list[Violation] = []

    def reject(kind: str, coverage: str | None, message: str) -> None:
        violations.append(Violation(code=kind, coverage_code=coverage, message=message))

    for change in request.coverages:
        cov = catalog.coverages.get(change.code)
        if cov is None:
            reject("cobertura_desconhecida", change.code, "Cobertura inexistente no catálogo.")
            continue
        if not change.active:
            if cov.grupo == "fixa":
                reject("fixa_nao_removivel", cov.codigo, "Cobertura fixa: não pode ser desligada.")
            else:
                coverages.pop(cov.codigo, None)
            continue

        if cov.codigo not in coverages:
            if reason := lock_reason(cov, base.plan_code, facts, catalog):
                contradicted = applicability(cov, facts) is Tri.FALSO
                kind = "incompativel_atividade" if contradicted else "grupo_nao_permitido_no_plano"
                reject(kind, cov.codigo, reason)
                continue
            if cov.codigo in base_items:
                coverages[cov.codigo] = base_items[cov.codigo]
            else:
                item = OfferCoverage(
                    code=cov.codigo,
                    name=cov.nome,
                    group=cov.grupo,
                    rule_id=CUSTOMIZE_RULE_ID,
                    fact_keys=[],
                    risk=None,
                    need=cov.dimensao,
                    justification="Incluída por você em Personalizar.",
                    origin="adicionada_cliente",
                )
                coverages[cov.codigo] = size_coverage(item, inputs, catalog)

        if change.insured_amount is not None:
            low = cov.is_min if cov.is_min is not None else 1
            if change.insured_amount < low or (
                cov.is_max is not None and change.insured_amount > cov.is_max
            ):
                upper = f" e {cov.is_max}" if cov.is_max is not None else ""
                message = f"Importância segurada fora dos limites ({low}{upper})."
                reject("is_fora_dos_limites", cov.codigo, message)
            else:
                coverages[cov.codigo] = coverages[cov.codigo].model_copy(
                    update={"is_escolhida": change.insured_amount}
                )

    term = catalog.term
    if request.vigencia_anos is not None and not term.min <= request.vigencia_anos <= term.max:
        message = f"Vigência deve ficar entre {term.min} e {term.max} anos."
        reject("vigencia_fora_dos_limites", None, message)

    premium = current.premium_benefit
    if request.premium_benefit is not None:
        if premium is None:
            reject(
                "beneficio_premium_invalido", None, "Benefício Premium só existe no plano Total."
            )
        elif request.premium_benefit not in premium["options"]:
            reject("beneficio_premium_invalido", None, "Benefício Premium inválido.")

    if violations:
        return CustomizeResult(offer=None, violations=violations)

    if premium is not None:
        premium = {**premium, "selected": request.premium_benefit or premium.get("selected")}
    offer = current.model_copy(
        update={
            "offer_id": f"{base.offer_id}_p",
            "kind": "personalizada",
            "base_offer_id": base.offer_id,
            "coverages": sorted(coverages.values(), key=lambda c: c.code),
            "premium_benefit": premium,
        }
    )
    # Mudança válida para o cliente mas inválida no catálogo é bug de regra.
    problems = offer_violations(offer, catalog)
    if problems:
        # Combinação que o catálogo não admite: recusada como grupo não permitido no plano.
        return CustomizeResult(
            offer=None,
            violations=[
                Violation(code="grupo_nao_permitido_no_plano", message=p) for p in problems
            ],
        )

    vigencia = request.vigencia_anos or (
        current.quote_prefill.vigencia_anos if current.quote_prefill else None
    )
    chosen_is = {c.code: c.is_escolhida for c in offer.coverages if c.is_escolhida is not None}
    prefill = quote_prefill(offer, inputs, catalog, vigencia_anos=vigencia, chosen_is=chosen_is)
    # Sugeridas e retiradas seguem no formulário, desligadas.
    removed = sorted(suggested - coverages.keys(), key=lambda c: card_order(catalog, c))
    prefill.coberturas += [PrefillCoverage(code=c, ativa=False, is_sugerida=None) for c in removed]
    offer = offer.model_copy(update={**describe(offer, base), "quote_prefill": prefill})
    return CustomizeResult(
        offer=offer.model_copy(
            update={"coverage_cards": build_cards(offer, facts, catalog, suggested)}
        )
    )
