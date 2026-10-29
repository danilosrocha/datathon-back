from app.domain.facts import FactStatus
from app.engine.questions import MAX_QUESTIONS, impact, next_question
from tests.engine.conftest import NO_IMPEDIMENTS, make_facts


def test_activity_first(catalog, graph) -> None:
    q = next_question({}, catalog, graph)
    assert q.fact_key == "cnae_principal"


def test_open_eligibility_comes_before_anything(catalog, graph) -> None:
    facts = make_facts(cnae_principal="1091-1/02", imovel_em_obra=False)
    q = next_question(facts, catalog, graph)
    eligibility_keys = {
        "atividade_rural",
        "localizacao_restrita",
        "imovel_tombado_desapropriado_condenado",
        "parede_externa_combustivel",
        "objeto_ja_segurado_bb",
    }
    assert q.fact_key in eligibility_keys
    assert q.score >= 1000
    assert q.input.type == "boolean"


def test_highest_impact_times_uncertainty_wins(catalog, graph) -> None:
    facts = make_facts(**NO_IMPEDIMENTS, cnae_principal="1091-1/02")
    q = next_question(facts, catalog, graph)
    # valor_conteudo_faixa: impacto 4 × incerteza 1 − custo 0,2 = 3,8;
    # mercadoria_refrigerada (p = 0,8): impacto 3 × incerteza 0,4 = 1,2.
    assert (q.fact_key, q.score) == ("valor_conteudo_faixa", 3.8)


def test_high_probability_becomes_confirmation(catalog) -> None:
    from app.engine.questions import build_question

    q = build_question("mercadoria_refrigerada", 0.8, None, 1.2, catalog)
    assert q.style == "confirmacao"
    assert q.prompt == "Imagino que vocês usem freezer ou câmara fria, certo?"
    assert build_question("mercadoria_refrigerada", 0.5, None, 1.2, catalog).style == "aberta"


def test_impact_counts_changed_coverages(catalog, graph) -> None:
    facts = make_facts(**NO_IMPEDIMENTS, cnae_principal="4721-1/02")
    assert impact("delivery", facts, catalog, graph) > 0
    assert impact("razao_social", facts, catalog, graph) == 0  # texto: sem contrafactual


def test_select_question_has_labeled_options(catalog, graph) -> None:
    from app.engine.questions import build_question

    q = build_question("valor_estoque_faixa", 0.5, None, 1.0, catalog)
    assert q.input.type == "select"
    assert q.input.options[0].label == "Até R$ 10 mil"


def test_stops_when_ineligible_or_limit(catalog, graph) -> None:
    blocked = make_facts(**{**NO_IMPEDIMENTS, "imovel_em_obra": True}, cnae_principal="4721-1/02")
    assert next_question(blocked, catalog, graph) is None
    facts = make_facts(**NO_IMPEDIMENTS, cnae_principal="4721-1/02")
    assert next_question(facts, catalog, graph, asked=MAX_QUESTIONS) is None


def test_estimated_fact_is_still_asked(catalog, graph) -> None:
    facts = make_facts(**NO_IMPEDIMENTS, cnae_principal="4721-1/02") | make_facts(
        FactStatus.ESTIMADO, delivery=True
    )
    q = next_question(facts, catalog, graph)
    assert q is not None
