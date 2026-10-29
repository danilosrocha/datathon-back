"""Fatos do caso com natureza e proveniência (CONTRATOS_API §2 e §3.1)."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, model_validator

from app.domain.fact_keys import get_fact_key


class FactStatus(StrEnum):
    OBSERVADO = "observado"
    DERIVADO = "derivado"
    ESTIMADO = "estimado"
    CONFIRMADO = "confirmado"
    REJEITADO = "rejeitado"


class FactSource(StrEnum):
    USUARIO_TEXTO = "usuario_texto"
    USUARIO_RESPOSTA = "usuario_resposta"
    BASE_COMUM = "base_comum"
    RECEITA_CNPJ = "receita_cnpj"
    FORMULA = "formula"
    API_TERRITORIO = "api_territorio"
    API_CLIMA = "api_clima"
    API_DESASTRES = "api_desastres"
    API_SEGURANCA = "api_seguranca"
    GRAFO = "grafo"


class Fact(BaseModel):
    key: str
    value: Any | None
    status: FactStatus
    source: FactSource
    confidence: float
    evidence: str | None = None
    rejected_values: list[Any] = []
    updated_at: datetime
    updated_by: str

    @model_validator(mode="after")
    def _check_key_and_value(self) -> "Fact":
        spec = get_fact_key(self.key)
        if spec.never_estimated and self.status is FactStatus.ESTIMADO:
            raise ValueError(f"{self.key} nunca pode ser estimado")
        if self.value is not None:
            self.value = spec.validate_value(self.value)
        return self

    @property
    def is_known(self) -> bool:
        """Estimado é hipótese e rejeitado não tem valor: nenhum dos dois conta como sabido."""
        return self.status in (FactStatus.CONFIRMADO, FactStatus.OBSERVADO, FactStatus.DERIVADO)


# Prioridade entre naturezas: confirmado > observado > derivado > estimado.
_RANK = {
    FactStatus.ESTIMADO: 0,
    FactStatus.DERIVADO: 1,
    FactStatus.OBSERVADO: 2,
    FactStatus.CONFIRMADO: 3,
    FactStatus.REJEITADO: 3,
}


def merge_fact(current: Fact | None, incoming: Fact) -> Fact:
    """Regras de atualização de um fato:
    - natureza mais fraca não sobrescreve mais forte (estimado do grafo não apaga o declarado);
    - rejeitar zera o valor e guarda o anterior em rejected_values;
    - trocar de valor guarda o anterior em rejected_values, para não voltar a sugeri-lo.
    """
    if current is None:
        return incoming
    if _RANK[incoming.status] < _RANK[current.status]:
        return current

    rejected = list(current.rejected_values)

    if incoming.status is FactStatus.REJEITADO:
        value = incoming.value if incoming.value is not None else current.value
        if value is not None and value not in rejected:
            rejected.append(value)
        return incoming.model_copy(update={"value": None, "rejected_values": rejected})

    if current.value is not None and current.value != incoming.value:
        rejected.append(current.value)
    rejected = [v for v in rejected if v != incoming.value]
    return incoming.model_copy(update={"rejected_values": rejected})


def merge_facts(current: dict[str, Fact] | None, incoming: dict[str, Fact]) -> dict[str, Fact]:
    """Reducer do LangGraph: os nós devolvem só os fatos novos."""
    merged = dict(current or {})
    for key, fact in incoming.items():
        merged[key] = merge_fact(merged.get(key), fact)
    return merged
