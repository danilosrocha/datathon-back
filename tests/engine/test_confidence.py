"""Confiança geral = média entre a sustentação das faixas e a da escolha do plano."""

from app.domain.facts import FactStatus
from app.engine.decide import decide
from tests.engine.conftest import NO_IMPEDIMENTS, make_facts

FACADE_QUESTION = "A fachada ou vitrine é de vidro?"


def test_upgrade_by_regional_estimate_is_weakly_supported(catalog, graph) -> None:
    facts = make_facts(**NO_IMPEDIMENTS) | make_facts(
        FactStatus.ESTIMADO, risco_roubo_regiao="alto"
    )
    d = decide(facts, catalog, graph)
    assert d.offers[0].plan_code == "PRATICO"
    assert d.confidence.plan == 0.4  # teto de `estimado`


def test_upgrade_by_known_fact_is_well_supported(catalog, graph) -> None:
    d = decide(make_facts(**NO_IMPEDIMENTS, possui_estoque=True), catalog, graph)
    assert d.offers[0].plan_code == "PRATICO"
    assert d.confidence.plan == 0.8  # observado
    assert d.confidence.overall == round((d.confidence.ranges + 0.8) / 2, 2)


def test_essential_with_open_upgrade_rule_has_no_plan_support(catalog, graph) -> None:
    d = decide(make_facts(**NO_IMPEDIMENTS), catalog, graph)
    assert d.offers[0].plan_code == "ESSENCIAL"
    assert d.confidence.plan == 0.0  # nada descarta as regras de subida
    assert FACADE_QUESTION in d.confirmation_questions  # o que falta vira pergunta


def test_essential_with_upgrade_rules_discarded(catalog, graph) -> None:
    known_no = {
        "possui_estoque": False,
        "fachada_vidros": False,
        "num_empregados_faixa": "1_9",
        "risco_vendaval_regiao": "baixo",
        "risco_granizo_regiao": "baixo",
        "risco_roubo_regiao": "baixo",
    }
    d = decide(make_facts(**NO_IMPEDIMENTS, **known_no), catalog, graph)
    assert d.offers[0].plan_code == "ESSENCIAL"
    assert d.confidence.plan == 0.8
    assert FACADE_QUESTION not in d.confirmation_questions


def test_weak_data_quality_lowers_range_confidence(catalog, graph) -> None:
    strong = make_facts(**NO_IMPEDIMENTS, valor_conteudo_faixa="50k_200k", objeto_seguro="conteudo")
    weak = dict(strong)
    weak["valor_conteudo_faixa"] = strong["valor_conteudo_faixa"].model_copy(
        update={"confidence": 0.3}
    )

    def basic(d):
        return next(c for c in d.offers[0].coverages if c.code == "INCENDIO_RAIO_EXPLOSAO_FUMACA")

    assert (
        basic(decide(weak, catalog, graph)).confidence
        < basic(decide(strong, catalog, graph)).confidence
    )
