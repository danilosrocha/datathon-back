import hashlib

import pytest

from app.domain.facts import FactSource, FactStatus, merge_facts
from app.engine.decide import decide
from app.engine.recommender import ConfigurationError, validate_offer
from tests.engine.conftest import NO_IMPEDIMENTS, make_facts

FIXAS = {
    "INCENDIO_RAIO_EXPLOSAO_FUMACA",
    "DANOS_ELETRICOS",
    "PERDA_PAGAMENTO_ALUGUEL",
    "RC_ESTABELECIMENTO",
    "DESPESAS_FIXAS",
    "PROTECAO_CIBERNETICA",
}


def codes(decision) -> set[str]:
    return {c.code for c in decision.offers[0].coverages}


# --- 5 casos de demonstração ---------------------------------------------------------------


def test_case_eligible_complete(catalog, graph) -> None:
    d = decide(make_facts(**NO_IMPEDIMENTS, cnae_principal="6201-5/01"), catalog, graph)
    assert d.status == "conclusiva"
    assert d.eligibility.status == "elegivel"
    assert d.offers[0].plan_code == "ESSENCIAL"
    assert codes(d) == FIXAS


def test_case_missing_critical_info(catalog, graph) -> None:
    facts = make_facts(**{k: v for k, v in NO_IMPEDIMENTS.items() if k != "imovel_em_obra"})
    d = decide(facts, catalog, graph)
    assert d.status == "preliminar"
    assert d.eligibility.status == "pendente"
    assert [(p.rule_id, p.fact_key) for p in d.eligibility.pending] == [
        ("ELG-004", "imovel_em_obra")
    ]
    assert d.offers  # recomendação preliminar, sujeita a confirmação (L-05)


def test_case_ineligible(catalog, graph) -> None:
    d = decide(make_facts(**{**NO_IMPEDIMENTS, "imovel_em_obra": True}), catalog, graph)
    assert d.eligibility.status == "inelegivel"
    assert [b.rule_id for b in d.eligibility.blockers] == ["ELG-004"]
    assert d.offers == [] and d.status is None


def test_case_same_cnae_different_offers(catalog, graph) -> None:
    base = {**NO_IMPEDIMENTS, "cnae_principal": "1091-1/02"}
    plain = decide(make_facts(**base, mercadoria_refrigerada=False), catalog, graph)
    cold = decide(make_facts(**base, mercadoria_refrigerada=True), catalog, graph)

    assert plain.offers[0].plan_code == "ESSENCIAL"
    assert cold.offers[0].plan_code == "PRATICO"
    frig = next(
        c for c in cold.offers[0].coverages if c.code == "DETERIORACAO_MERCADORIAS_FRIGORIFICADAS"
    )
    assert (frig.rule_id, frig.fact_keys, frig.risk) == (
        "REC-004",
        ["mercadoria_refrigerada"],
        "deterioracao_mercadoria",
    )
    assert cold.offers[0].plan_rule_ids == ["PLN-ESP"]


def test_case_data_correction(catalog, graph) -> None:
    facts = make_facts(**NO_IMPEDIMENTS, mercadoria_refrigerada=True)
    before = decide(facts, catalog, graph)
    correction = make_facts(FactStatus.CONFIRMADO, mercadoria_refrigerada=False)
    correction["mercadoria_refrigerada"].source = FactSource.USUARIO_RESPOSTA
    after = decide(merge_facts(facts, correction), catalog, graph)

    assert before.offers[0].plan_code == "PRATICO"
    assert after.offers[0].plan_code == "ESSENCIAL"
    assert "DETERIORACAO_MERCADORIAS_FRIGORIFICADAS" not in codes(after)


# --- invariantes --------------------------------------------------------------------------


def test_estimated_impediment_stays_pending(catalog, graph) -> None:
    facts = {
        **make_facts(**{k: v for k, v in NO_IMPEDIMENTS.items() if k != "imovel_em_obra"}),
        **make_facts(FactStatus.ESTIMADO, imovel_em_obra=True),
    }
    assert decide(facts, catalog, graph).eligibility.status == "pendente"


def test_redirect_above_basic_limit(catalog, graph) -> None:
    facts = make_facts(**NO_IMPEDIMENTS, is_basica_estimada=8_000_000)
    d = decide(facts, catalog, graph)
    assert d.eligibility.redirect_to == "Seguro Personalizado Empresarial"
    assert d.offers == []


def test_plan_rules_pick_highest_plan(catalog, graph) -> None:
    facts = make_facts(**NO_IMPEDIMENTS, possui_estoque=True, fachada_vidros=True)
    offer = decide(facts, catalog, graph).offers[0]
    assert offer.plan_code == "TOTAL"
    assert offer.plan_rule_ids == ["PLN-01", "PLN-02"]
    assert {"QUEBRA_VIDROS", "RC_EMPREGADOR"} <= {c.code for c in offer.coverages}
    assert offer.premium_benefit["options"] == [
        "detector_fumaca",
        "camera_wifi",
        "plataforma_minu_biz",
    ]


def test_every_coverage_has_trail(catalog, graph) -> None:
    facts = make_facts(**NO_IMPEDIMENTS, possui_estoque=True, delivery=True, letreiro_luminoso=True)
    for c in decide(facts, catalog, graph).offers[0].coverages:
        assert c.rule_id and c.need


def test_reproducible(catalog, graph) -> None:
    facts = make_facts(**NO_IMPEDIMENTS, possui_estoque=True, mercadoria_refrigerada=True)
    a, b = (
        hashlib.sha256(decide(facts, catalog, graph).model_dump_json().encode()).hexdigest()
        for _ in range(2)
    )
    assert a == b


def test_invalid_offer_is_rejected(catalog, graph) -> None:
    offer = decide(make_facts(**NO_IMPEDIMENTS, delivery=True), catalog, graph).offers[0]
    broken = offer.model_copy(update={"plan_code": "ESSENCIAL"})
    with pytest.raises(ConfigurationError, match="não é padrão|específica"):
        validate_offer(broken, catalog)
    without_fixa = offer.model_copy(update={"coverages": offer.coverages[1:]})
    with pytest.raises(ConfigurationError, match="fixas ausentes"):
        validate_offer(without_fixa, catalog)


# --- hipóteses do context graph -----------------------------------------------------------

PADARIA = {**NO_IMPEDIMENTS, "cnae_principal": "1091-1/02"}


def test_graph_hypotheses_feed_offer(catalog, graph) -> None:
    d = decide(make_facts(**PADARIA), catalog, graph)

    # p ≥ 0,8 vira hipótese; possui_estoque (p = 0,6) não.
    assert [(h.fact_key, h.p) for h in d.hypotheses] == [
        ("maquinas_equipamentos", 0.9),
        ("mercadoria_refrigerada", 0.8),
    ]
    frig = next(
        c for c in d.offers[0].coverages if c.code == "DETERIORACAO_MERCADORIAS_FRIGORIFICADAS"
    )
    assert "Confirmar: mercadoria refrigerada?" in frig.to_confirm
    assert d.offers[0].plan_code == "PRATICO"


def test_needs_follow_graph_paths(catalog, graph) -> None:
    d = decide(make_facts(**PADARIA), catalog, graph)
    conteudo = next(n for n in d.needs if n.dimension == "conteudo")
    top = conteudo.evidence[0]
    # 0,8 (hipótese) × 0,9 (refrigerada → deterioração) = 0,72 → alta
    assert (top.fact_key, top.risk, top.origin, top.strength) == (
        "mercadoria_refrigerada",
        "deterioracao_mercadoria",
        "hipotese",
        0.72,
    )
    assert conteudo.priority == "alta"


def test_declared_fact_beats_hypothesis(catalog, graph) -> None:
    d = decide(make_facts(**PADARIA, mercadoria_refrigerada=True), catalog, graph)
    assert "mercadoria_refrigerada" not in {h.fact_key for h in d.hypotheses}
    frig = next(
        c for c in d.offers[0].coverages if c.code == "DETERIORACAO_MERCADORIAS_FRIGORIFICADAS"
    )
    assert "Confirmar: mercadoria refrigerada?" not in frig.to_confirm
    conteudo = next(n for n in d.needs if n.dimension == "conteudo")
    assert conteudo.evidence[0].origin == "fato"


def test_rejected_fact_is_not_hypothesized_again(catalog, graph) -> None:
    facts = make_facts(**PADARIA) | make_facts(FactStatus.REJEITADO, mercadoria_refrigerada=None)
    d = decide(facts, catalog, graph)
    assert "mercadoria_refrigerada" not in {h.fact_key for h in d.hypotheses}
    assert "DETERIORACAO_MERCADORIAS_FRIGORIFICADAS" not in codes(d)


def test_hypotheses_never_decide_eligibility(catalog, graph) -> None:
    facts = make_facts(**{k: v for k, v in PADARIA.items() if k != "imovel_em_obra"})
    d = decide(facts, catalog, graph)
    assert d.eligibility.status == "pendente"
    assert d.hypotheses  # existem, mas não tocam a elegibilidade
