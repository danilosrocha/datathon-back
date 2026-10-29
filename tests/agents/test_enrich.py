from datetime import UTC, datetime

import pytest

from app.agents.profiling.nodes import enrich as enrich_node
from app.domain.facts import Fact, FactSource, FactStatus
from app.enrichment import territory
from app.enrichment.regional import regional_risk


def _cep(source: FactSource) -> Fact:
    return Fact(
        key="cep",
        value="70040-010",
        status=FactStatus.OBSERVADO,
        source=source,
        confidence=0.8,
        updated_at=datetime(2026, 10, 28, tzinfo=UTC),
        updated_by="teste",
    )


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    """Respostas gravadas (DEMO_MODE): nenhum teste chama API pública."""
    monkeypatch.setattr(territory, "_cache", {})
    monkeypatch.setattr(territory.get_settings(), "demo_mode", True)
    monkeypatch.setattr(enrich_node, "get_stream_writer", lambda: lambda event: None)


async def test_user_cep_becomes_municipality_and_regional_risk() -> None:
    result = await enrich_node.enrich({"facts": {"cep": _cep(FactSource.USUARIO_TEXTO)}})
    facts = result["facts"]
    assert facts["municipio_ibge"].value == "5300108"
    assert (facts["uf"].source, facts["uf"].status) == ("api_territorio", "observado")
    assert facts["risco_roubo_regiao"].status == "estimado"
    assert all(f.evidence for f in facts.values())  # proveniência obrigatória


async def test_base_cep_is_never_used() -> None:
    assert await enrich_node.enrich({"facts": {"cep": _cep(FactSource.BASE_COMUM)}}) == {}


async def test_unknown_cep_without_fixture() -> None:
    assert await territory.lookup_cep("00000-000") is None


def test_regional_risk_table() -> None:
    risks = regional_risk("2927408", "BA")  # Salvador
    assert risks["risco_alagamento_regiao"] == "alto"
    assert regional_risk("9999999", "SP") == {"risco_roubo_regiao": "medio"}  # só a UF
