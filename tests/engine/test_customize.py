from app.domain.decision import CoverageChange, CustomizeRequest
from app.engine.customize import customize
from app.engine.decide import decide
from tests.engine.conftest import NO_IMPEDIMENTS, make_facts


def setup(catalog, graph, **values):
    facts = make_facts(**NO_IMPEDIMENTS, **values)
    return facts, decide(facts, catalog, graph).offers[0]


def test_reset_returns_base(catalog, graph) -> None:
    facts, base = setup(catalog, graph)
    assert customize(base, CustomizeRequest(reset=True), facts, catalog, graph).offer == base


def test_remove_standard_and_add_optional(catalog, graph) -> None:
    facts, base = setup(catalog, graph, possui_estoque=True)
    request = CustomizeRequest(
        coverages=[
            CoverageChange(code="VENDAVAL_GRANIZO", active=False),
            CoverageChange(code="TUMULTOS_GREVES_LOCAUTES", active=True),
        ]
    )
    result = customize(base, request, facts, catalog, graph)
    assert result.violations == []
    offer = result.offer
    assert offer.kind == "personalizada" and offer.offer_id == "of_1_p"
    assert offer.diff_vs_best == [
        "+ Tumultos, greves e locautes",
        "− Vendaval, furacão, tornado, ciclone e granizo",
    ]
    added = next(c for c in offer.coverages if c.code == "TUMULTOS_GREVES_LOCAUTES")
    assert added.rule_id == "PERSONALIZAR" and added.note  # opcional sem regra EST-*


def test_violations(catalog, graph) -> None:
    facts, base = setup(catalog, graph)  # Essencial
    request = CustomizeRequest(
        coverages=[
            CoverageChange(code="INCENDIO_RAIO_EXPLOSAO_FUMACA", active=False),
            CoverageChange(code="DELIVERY", active=True),
            CoverageChange(code="QUEBRA_VIDROS", active=True),
            CoverageChange(code="XPTO", active=True),
            CoverageChange(code="DANOS_ELETRICOS", active=True, insured_amount=0),
        ],
        vigencia_anos=6,
        premium_benefit="camera_wifi",
    )
    result = customize(base, request, facts, catalog, graph)
    assert result.offer is None
    assert [(v.code, v.coverage_code) for v in result.violations] == [
        ("fixa_nao_removivel", "INCENDIO_RAIO_EXPLOSAO_FUMACA"),
        ("grupo_nao_permitido_no_plano", "DELIVERY"),
        ("grupo_nao_permitido_no_plano", "QUEBRA_VIDROS"),
        ("cobertura_desconhecida", "XPTO"),
        ("is_fora_dos_limites", "DANOS_ELETRICOS"),
        ("vigencia_fora_dos_limites", None),
        ("beneficio_premium_invalido", None),
    ]


def test_basic_is_limits(catalog, graph) -> None:
    facts, base = setup(catalog, graph)
    too_low = CoverageChange(
        code="INCENDIO_RAIO_EXPLOSAO_FUMACA", active=True, insured_amount=50_000
    )
    assert customize(base, CustomizeRequest(coverages=[too_low]), facts, catalog, graph).violations

    ok = CoverageChange(code="INCENDIO_RAIO_EXPLOSAO_FUMACA", active=True, insured_amount=400_000)
    result = customize(
        base, CustomizeRequest(coverages=[ok], vigencia_anos=3), facts, catalog, graph
    )
    prefill = result.offer.quote_prefill
    assert prefill.vigencia_anos == 3
    basic = next(c for c in prefill.coberturas if c.code == "INCENDIO_RAIO_EXPLOSAO_FUMACA")
    assert basic.is_sugerida == 400_000


def test_premium_benefit_on_total(catalog, graph) -> None:
    facts, base = setup(catalog, graph, fachada_vidros=True)
    result = customize(base, CustomizeRequest(premium_benefit="camera_wifi"), facts, catalog, graph)
    assert result.offer.premium_benefit["selected"] == "camera_wifi"
    assert result.offer.quote_prefill.beneficio_premium == "camera_wifi"


def test_offer_has_one_card_per_coverage(catalog, graph) -> None:
    _, base = setup(catalog, graph)  # Essencial
    cards = {c.code: c for c in base.coverage_cards}
    assert set(cards) == set(catalog.coverages)
    fixed = cards["INCENDIO_RAIO_EXPLOSAO_FUMACA"]
    assert fixed.status == "incluida" and fixed.actions == ["ajustar_is"] and fixed.lock_reason
    assert cards["VENDAVAL_GRANIZO"].status == "indisponivel"  # L-01
    assert cards["DELIVERY"].status == "indisponivel"
    assert cards["TUMULTOS_GREVES_LOCAUTES"].actions == ["adicionar"]


def test_cumulative_changes_and_readd_keeps_range(catalog, graph) -> None:
    facts, base = setup(catalog, graph, possui_estoque=True)
    remove = CustomizeRequest(coverages=[CoverageChange(code="VENDAVAL_GRANIZO", active=False)])
    first = customize(base, remove, facts, catalog, graph).offer
    cards = {c.code: c for c in first.coverage_cards}
    assert cards["VENDAVAL_GRANIZO"].suggested and cards["VENDAVAL_GRANIZO"].warning
    off = next(p for p in first.quote_prefill.coberturas if p.code == "VENDAVAL_GRANIZO")
    assert off.ativa is False

    add = CustomizeRequest(coverages=[CoverageChange(code="TUMULTOS_GREVES_LOCAUTES", active=True)])
    second = customize(base, add, facts, catalog, graph, current=first).offer
    assert {"VENDAVAL_GRANIZO", "TUMULTOS_GREVES_LOCAUTES"} & {
        c.code for c in second.coverages
    } == {"TUMULTOS_GREVES_LOCAUTES"}
    assert {c.code: c for c in second.coverage_cards}["TUMULTOS_GREVES_LOCAUTES"].origin == (
        "adicionada_cliente"
    )

    readd = CustomizeRequest(coverages=[CoverageChange(code="VENDAVAL_GRANIZO", active=True)])
    third = customize(base, readd, facts, catalog, graph, current=second).offer
    vendaval = next(c for c in third.coverages if c.code == "VENDAVAL_GRANIZO")
    original = next(c for c in base.coverages if c.code == "VENDAVAL_GRANIZO")
    assert vendaval == original and third.diff_vs_best == ["+ Tumultos, greves e locautes"]


def test_specific_blocked_when_fact_says_no(catalog, graph) -> None:
    facts, base = setup(catalog, graph, possui_estoque=True, delivery=False)
    cards = {c.code: c for c in base.coverage_cards}
    assert cards["DELIVERY"].status == "indisponivel"
    result = customize(
        base,
        CustomizeRequest(coverages=[CoverageChange(code="DELIVERY", active=True)]),
        facts,
        catalog,
        graph,
    )
    assert [(v.code, v.coverage_code) for v in result.violations] == [
        ("incompativel_atividade", "DELIVERY")
    ]
