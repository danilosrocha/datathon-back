"""Alternativas, quote_prefill, textos por template e fatos derivados."""

from app.domain.facts import FactSource
from app.engine.decide import decide
from app.engine.prefill import suggested_is
from tests.engine.conftest import NO_IMPEDIMENTS, make_facts


def kinds(d) -> list[str]:
    return [o.kind for o in d.offers]


def by_kind(d, kind):
    return next(o for o in d.offers if o.kind == kind)


def test_practical_gets_cheaper_and_wider_alternatives(catalog, graph) -> None:
    d = decide(make_facts(**NO_IMPEDIMENTS, possui_estoque=True, delivery=True), catalog, graph)
    assert kinds(d) == ["melhor_ajuste", "custo_beneficio", "protecao_ampliada"]
    assert [o.offer_id for o in d.offers] == ["of_1", "of_2", "of_3"]
    cheaper, wider = by_kind(d, "custo_beneficio"), by_kind(d, "protecao_ampliada")
    assert (cheaper.plan_code, wider.plan_code) == ("ESSENCIAL", "TOTAL")
    # O Essencial perde as padrão e a específica; fixas nunca aparecem como removidas.
    assert "− Delivery" in cheaper.diff_vs_best
    assert not any("Incêndio" in line for line in cheaper.diff_vs_best)
    assert wider.diff_vs_best == ["+ Quebra de vidros", "+ Responsabilidade civil – empregador"]
    assert d.offers[0].diff_vs_best == []


def test_total_has_no_wider_alternative(catalog, graph) -> None:
    d = decide(make_facts(**NO_IMPEDIMENTS, fachada_vidros=True), catalog, graph)
    assert d.offers[0].plan_code == "TOTAL"
    assert "protecao_ampliada" not in kinds(d)


def test_lean_essential_drops_low_priority_optionals(catalog, graph) -> None:
    d = decide(make_facts(**NO_IMPEDIMENTS, letreiro_luminoso=True), catalog, graph)
    assert by_kind(d, "custo_beneficio").diff_vs_best == ["− Letreiros e anúncios luminosos"]


def test_essential_without_optionals_has_no_cheaper_alternative(catalog, graph) -> None:
    d = decide(make_facts(**NO_IMPEDIMENTS), catalog, graph)
    assert kinds(d) == ["melhor_ajuste", "protecao_ampliada"]


def test_quote_prefill(catalog, graph) -> None:
    facts = make_facts(
        **NO_IMPEDIMENTS,
        tipo_pessoa="pj",
        relacao_imovel="inquilino",
        valor_conteudo_faixa="50k_200k",
        municipio_ibge="3550308",
        uf="SP",
        cep="01310-100",  # da base comum: fictício
    )
    prefill = decide(facts, catalog, graph).offers[0].quote_prefill
    assert prefill.tipo_pessoa == "pj"
    assert prefill.objeto_seguro == "conteudo"
    assert prefill.endereco.model_dump() == {"cep": None, "municipio_ibge": "3550308", "uf": "SP"}
    assert prefill.vigencia_anos == 1
    assert prefill.atividade is None  # sem mapeamento oficial (L-10)
    basic = next(c for c in prefill.coberturas if c.code == "INCENDIO_RAIO_EXPLOSAO_FUMACA")
    assert basic.is_sugerida == 150_000  # ponto médio de 100–200 mil


def test_user_cep_is_kept(catalog, graph) -> None:
    facts = make_facts(**NO_IMPEDIMENTS)
    cep = make_facts(cep="70040-010")
    cep["cep"].source = FactSource.USUARIO_TEXTO
    prefill = decide(facts | cep, catalog, graph).offers[0].quote_prefill
    assert prefill.endereco.cep == "70040010"


def test_suggested_is_rounds_down_to_5k(catalog) -> None:
    from app.domain.decision import InsuredAmount

    cov = catalog.coverages["DANOS_ELETRICOS"]
    assert suggested_is(InsuredAmount(min=10_000, max=37_000), cov) == 20_000
    assert suggested_is(InsuredAmount(min=1_000, max=3_000), cov) == 5_000
    assert suggested_is(None, cov) is None


def test_template_texts(catalog, graph) -> None:
    d = decide(make_facts(**NO_IMPEDIMENTS, mercadoria_refrigerada=True), catalog, graph)
    best = d.offers[0]
    assert best.title == "Plano Prático — o que recomendamos para o seu negócio"
    assert best.explanation_source == "template"
    assert "Deterioração de mercadorias" in best.explanation_md and "R$ " in best.explanation_md
    assert [r.coverage_code for r in best.reasons] == ["DETERIORACAO_MERCADORIAS_FRIGORIFICADAS"]
    assert best.limitations


def test_overall_confidence_and_questions(catalog, graph) -> None:
    facts = make_facts(**{k: v for k, v in NO_IMPEDIMENTS.items() if k != "imovel_em_obra"})
    d = decide(facts, catalog, graph)
    assert d.confidence.level in ("alta", "media", "baixa")
    assert d.confirmation_questions[0] == "O imóvel está em construção, reforma ou reconstrução?"


def test_activity_acceptance_is_derived_from_cnae(catalog, graph) -> None:
    base = {k: v for k, v in NO_IMPEDIMENTS.items() if k != "atividade_aceita"}
    commerce = decide(make_facts(**base, cnae_principal="4721-1/02"), catalog, graph)
    farming = decide(make_facts(**base, cnae_principal="0111-3/01"), catalog, graph)
    assert commerce.derived["atividade_aceita"] is True
    assert commerce.eligibility.status == "elegivel"
    assert farming.eligibility.status == "inelegivel"
    assert [b.rule_id for b in farming.eligibility.blockers] == ["ELG-007"]


def test_all_offers_valid_and_complete(catalog, graph) -> None:
    d = decide(make_facts(**NO_IMPEDIMENTS, possui_estoque=True, delivery=True), catalog, graph)
    for offer in d.offers:
        codes = {c.code for c in offer.coverages}
        assert set(catalog.plans["ESSENCIAL"].fixas) <= codes
        assert offer.quote_prefill.plano == offer.plan_code
        assert {c.code for c in offer.quote_prefill.coberturas} == codes
