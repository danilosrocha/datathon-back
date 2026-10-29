import pytest

from app.domain.facts import FactStatus
from app.engine.decide import decide
from tests.engine.conftest import NO_IMPEDIMENTS, make_facts


def coverage(decision, code):
    return next(c for c in decision.offers[0].coverages if c.code == code)


def run(catalog, graph, status=FactStatus.OBSERVADO, **values):
    return decide(make_facts(**NO_IMPEDIMENTS) | make_facts(status, **values), catalog, graph)


def test_every_coverage_in_offers_has_integer_range(catalog, graph) -> None:
    d = run(
        catalog,
        graph,
        possui_estoque=True,
        fachada_vidros=True,
        delivery=True,
        mercadoria_refrigerada=True,
        letreiro_luminoso=True,
        eletronicos_relevantes=True,
    )
    for c in d.offers[0].coverages:
        amount = c.insured_amount
        assert amount is not None, c.code
        assert isinstance(amount.min, int) and isinstance(amount.max, int)
        assert 0 < amount.min <= amount.max
        assert c.calc_rule and c.calc_rule.startswith("EST-")
        assert 0 < c.confidence <= 1
        assert c.data_used


def test_basic_sums_what_is_protected(catalog, graph) -> None:
    d = run(
        catalog,
        graph,
        objeto_seguro="ambos",
        valor_predio_faixa="200k_1m",
        valor_conteudo_faixa="50k_200k",
    )
    basic = coverage(d, "INCENDIO_RAIO_EXPLOSAO_FUMACA")
    assert (basic.insured_amount.min, basic.insured_amount.max) == (250_000, 1_200_000)
    assert basic.confidence == 0.8  # três entradas observadas
    assert basic.to_confirm == []
    assert d.derived["is_basica_estimada"] == 250_000  # soma dos pisos


def test_basic_respects_floor(catalog, graph) -> None:
    d = run(catalog, graph, objeto_seguro="conteudo", valor_conteudo_faixa="10k_50k")
    basic = coverage(d, "INCENDIO_RAIO_EXPLOSAO_FUMACA")
    assert (basic.insured_amount.min, basic.insured_amount.max) == (100_000, 100_000)


def test_tenant_protects_content_only(catalog, graph) -> None:
    d = run(catalog, graph, relacao_imovel="inquilino", valor_conteudo_faixa="50k_200k")
    basic = coverage(d, "INCENDIO_RAIO_EXPLOSAO_FUMACA")
    assert (basic.insured_amount.min, basic.insured_amount.max) == (100_000, 200_000)
    assert "Confirmar: objeto do seguro?" in basic.to_confirm


def test_missing_inputs_use_team_table_with_low_confidence(catalog, graph) -> None:
    d = run(catalog, graph)
    rent = coverage(d, "PERDA_PAGAMENTO_ALUGUEL")
    assert (rent.insured_amount.min, rent.insured_amount.max) == (15_000, 60_000)
    assert rent.confidence == 0.2  # tabela (0,4) ÷ 2 entradas
    assert rent.data_used == ["tabela da equipe EST-ALUG-01 (estimado)"]
    assert "Confirmar: aluguel mensal?" in rent.to_confirm


def test_confirmed_input_raises_confidence(catalog, graph) -> None:
    observed = coverage(
        run(catalog, graph, aluguel_mensal_faixa="ate_10k"), "PERDA_PAGAMENTO_ALUGUEL"
    )
    confirmed = coverage(
        run(catalog, graph, FactStatus.CONFIRMADO, aluguel_mensal_faixa="ate_10k"),
        "PERDA_PAGAMENTO_ALUGUEL",
    )
    assert (observed.insured_amount.min, observed.insured_amount.max) == (3_000, 60_000)
    assert confirmed.confidence > observed.confidence


def test_fixed_expenses_fall_back_to_revenue(catalog, graph) -> None:
    d = run(catalog, graph, faturamento_faixa="200k_1m")
    df = coverage(d, "DESPESAS_FIXAS")
    # 200k–1m/ano × 1,67% × 3–6
    assert (df.insured_amount.min, df.insured_amount.max) == (10_000, 101_000)
    assert df.data_used == ["faturamento_faixa (observado, base_comum)"]


def test_cyber_by_digital_exposure(catalog, graph) -> None:
    d = run(catalog, graph, armazena_dados_clientes=True, recebe_pagamentos_online=True)
    cyb = coverage(d, "PROTECAO_CIBERNETICA")
    assert (cyb.insured_amount.min, cyb.insured_amount.max) == (100_000, 200_000)
    assert "Confirmar: sistema crítico online?" in cyb.to_confirm


def test_basic_above_limit_redirects_from_ranges(catalog, graph) -> None:
    d = run(
        catalog,
        graph,
        objeto_seguro="ambos",
        valor_predio_faixa="acima_7_5m",
        valor_conteudo_faixa="1m_7_5m",
    )
    assert d.derived["is_basica_estimada"] > 7_500_000
    assert d.eligibility.redirect_to == "Seguro Personalizado Empresarial"
    assert d.offers == []


def test_estimated_values_never_trigger_redirect(catalog, graph) -> None:
    d = run(
        catalog,
        graph,
        FactStatus.ESTIMADO,
        objeto_seguro="ambos",
        valor_predio_faixa="acima_7_5m",
        valor_conteudo_faixa="1m_7_5m",
    )
    assert d.derived == {}
    assert d.eligibility.redirect_to is None
    basic = coverage(d, "INCENDIO_RAIO_EXPLOSAO_FUMACA")
    assert basic.insured_amount.max == 7_500_000  # teto do catálogo


@pytest.mark.parametrize("code", ["DETERIORACAO_MERCADORIAS_FRIGORIFICADAS"])
def test_specific_coverage_range(catalog, graph, code) -> None:
    d = run(catalog, graph, mercadoria_refrigerada=True, valor_estoque_faixa="10k_50k")
    frig = coverage(d, code)
    assert (frig.insured_amount.min, frig.insured_amount.max) == (3_000, 30_000)
    assert frig.calc_rule == "EST-FRIG-01"


# --- confiança por vagas de entrada ---------------------------------------------------------


def test_alternative_inputs_fill_a_single_slot(catalog, graph) -> None:
    # Vendaval usa prédio OU conteúdo: só o conteúdo (derivado 0,7) não pode valer metade.
    # possui_estoque leva ao Prático (PLN-01), que inclui vendaval.
    d = run(
        catalog, graph, FactStatus.DERIVADO, valor_conteudo_faixa="50k_200k", possui_estoque=True
    )
    assert d.offers[0].plan_code == "PRATICO"
    vendaval = coverage(d, "VENDAVAL_GRANIZO")
    de = coverage(d, "DANOS_ELETRICOS")  # equipamentos OU conteúdo
    assert vendaval.confidence == de.confidence == 0.7
    assert "Confirmar: valor dos equipamentos?" not in de.to_confirm
    assert "Confirmar: valor do prédio?" not in vendaval.to_confirm


def test_tenant_basic_ignores_building_value(catalog, graph) -> None:
    d = run(catalog, graph, relacao_imovel="inquilino", valor_conteudo_faixa="50k_200k")
    basic = coverage(d, "INCENDIO_RAIO_EXPLOSAO_FUMACA")
    assert basic.confidence == 0.8  # objeto (pela relação, observado) + conteúdo (observado)
    assert "Confirmar: valor do prédio?" not in basic.to_confirm


def test_pending_eligibility_does_not_lower_confidence(catalog, graph) -> None:
    from app.engine.decide import decide
    from tests.engine.conftest import make_facts

    values = {"valor_conteudo_faixa": "50k_200k", "objeto_seguro": "conteudo"}
    complete = decide(make_facts(**NO_IMPEDIMENTS, **values), catalog, graph)
    partial = {k: v for k, v in NO_IMPEDIMENTS.items() if k != "imovel_em_obra"}
    pending = decide(make_facts(**partial, **values), catalog, graph)
    assert pending.eligibility.status == "pendente"
    assert pending.confidence.overall == complete.confidence.overall


# --- fontes alternativas em ordem (EST-CYB-01, EST-VIDRO-01) ----------------------------------


def test_cyber_uses_exposure_index_first(catalog, graph) -> None:
    d = run(
        catalog,
        graph,
        FactStatus.DERIVADO,
        exposicao_digital_nivel="alto",
        armazena_dados_clientes=False,
    )
    cyb = coverage(d, "PROTECAO_CIBERNETICA")
    assert (cyb.insured_amount.min, cyb.insured_amount.max) == (100_000, 200_000)
    assert cyb.confidence == 0.7  # uma vaga: o índice (derivado)
    assert cyb.data_used == ["exposicao_digital_nivel (derivado, base_comum)"]


def test_glass_falls_back_to_establishment_type(catalog, graph) -> None:
    facts = {"fachada_vidros": True}  # leva ao Total (PLN-02)
    with_facade = run(catalog, graph, **facts)
    glass = coverage(with_facade, "QUEBRA_VIDROS")
    assert (glass.insured_amount.min, glass.insured_amount.max) == (20_000, 60_000)

    d = run(
        catalog,
        graph,
        FactStatus.DERIVADO,
        num_empregados_faixa="10_49",
        tipo_estabelecimento="loja",
    )
    glass = coverage(d, "QUEBRA_VIDROS")
    assert (glass.insured_amount.min, glass.insured_amount.max) == (10_000, 40_000)
    assert glass.confidence == 0.7
    assert "Confirmar: fachada de vidro?" not in glass.to_confirm


def test_without_any_source_uses_team_table(catalog, graph) -> None:
    d = run(catalog, graph, num_empregados_faixa="10_49")
    glass = coverage(d, "QUEBRA_VIDROS")
    assert (glass.insured_amount.min, glass.insured_amount.max) == (10_000, 30_000)
    assert glass.confidence == 0.4
    assert "Confirmar: fachada de vidro?" in glass.to_confirm
