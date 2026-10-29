from datetime import UTC, datetime

import pytest

from app.domain.facts import Fact, FactSource, FactStatus
from app.engine.catalog import default_catalog
from app.graph.store import load_snapshot

T0 = datetime(2026, 10, 28, tzinfo=UTC)

# Todos os impedimentos respondidos com "não": caso elegível sem pendências.
NO_IMPEDIMENTS = {
    "atividade_rural": False,
    "localizacao_restrita": False,
    "imovel_tombado_desapropriado_condenado": False,
    "imovel_em_obra": False,
    "parede_externa_combustivel": False,
    "objeto_ja_segurado_bb": False,
    "atividade_aceita": True,
}


NATURE_CONFIDENCE = {
    FactStatus.CONFIRMADO: 1.0,
    FactStatus.OBSERVADO: 0.8,
    FactStatus.DERIVADO: 0.7,
    FactStatus.ESTIMADO: 0.4,
    FactStatus.REJEITADO: 1.0,
}


def make_facts(status: FactStatus = FactStatus.OBSERVADO, **values) -> dict[str, Fact]:
    source = FactSource.GRAFO if status is FactStatus.ESTIMADO else FactSource.BASE_COMUM
    return {
        k: Fact(
            key=k,
            value=v,
            status=status,
            source=source,
            confidence=NATURE_CONFIDENCE[status],
            updated_at=T0,
            updated_by="teste",
        )
        for k, v in values.items()
    }


@pytest.fixture(scope="session")
def catalog():
    return default_catalog()


@pytest.fixture(scope="session")
def graph():
    return load_snapshot()
