import pytest

from app.agents.profiling.validator import validate_explanation
from app.engine.catalog import default_catalog
from app.engine.decide import decide
from tests.engine.conftest import NO_IMPEDIMENTS, make_facts


@pytest.fixture(scope="module")
def offer():
    from app.graph.store import load_snapshot

    facts = make_facts(**NO_IMPEDIMENTS, mercadoria_refrigerada=True, valor_estoque_faixa="10k_50k")
    return decide(facts, default_catalog(), load_snapshot()).offers[0]


def test_accepts_faithful_text(offer) -> None:
    frig = next(c for c in offer.coverages if c.code == "DETERIORACAO_MERCADORIAS_FRIGORIFICADAS")
    value = f"R$ {frig.insured_amount.max:,}".replace(",", ".")
    text = (
        f"A deterioração de mercadorias em ambientes frigorificados entra com até {value}, "
        "conforme as condições gerais."
    )
    assert validate_explanation(text, offer, default_catalog()) == []


def test_rejects_coverage_outside_offer(offer) -> None:
    problems = validate_explanation("Inclui também Quebra de vidros.", offer, default_catalog())
    assert problems == ["cita cobertura fora da oferta: Quebra de vidros"]


def test_rejects_value_not_in_offer(offer) -> None:
    problems = validate_explanation("Cobertura de R$ 123.456.", offer, default_catalog())
    assert problems and "valor não presente" in problems[0]


def test_accepts_value_written_in_thousands(offer) -> None:
    frig = next(c for c in offer.coverages if c.code == "DETERIORACAO_MERCADORIAS_FRIGORIFICADAS")
    text = f"Até R$ {frig.insured_amount.max // 1000} mil."
    assert validate_explanation(text, offer, default_catalog()) == []


@pytest.mark.parametrize(
    "text", ["Garantimos a indenização.", "Você vai receber tudo.", "Esse plano cobre tudo."]
)
def test_rejects_promises(offer, text) -> None:
    assert validate_explanation(text, offer, default_catalog())
