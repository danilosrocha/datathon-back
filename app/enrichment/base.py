"""Tipos comuns dos adaptadores de enriquecimento (STACK_E_SERVICOS §6.6, ARQUITETURA §6.3)."""

import time
from collections.abc import Awaitable, Callable, Hashable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

FactNature = Literal["observado", "derivado"]
EnrichmentStatus = Literal["done", "partial", "failed"]


@dataclass(frozen=True)
class Provenance:
    fonte: str
    fonte_id: str
    granularidade: str
    periodo: list[int] | None
    atualizado_em: str | None
    limitacoes: str
    licenca: str


@dataclass(frozen=True)
class FactPatch:
    """Fato proposto pelo enriquecimento. Só `observado` ou `derivado`: nunca confirmado."""

    key: str
    value: Any
    status: FactNature
    source: str
    confidence: float
    evidence: str
    provenance: Provenance


@dataclass(frozen=True)
class Unavailable:
    """Fato que a fonte não consegue fornecer. Não vira valor (muito menos zero) no perfil."""

    key: str
    reason: str
    detail: str


@dataclass
class EnrichmentResult:
    adapter: str
    status: EnrichmentStatus
    patches: list[FactPatch] = field(default_factory=list)
    unavailable: list[Unavailable] = field(default_factory=list)
    detail: str | None = None


class EnrichmentAdapter(Protocol):
    name: str
    triggers: set[str]
    produces: set[str]

    async def run(self, facts: Mapping[str, Any]) -> EnrichmentResult: ...


class TTLCache:
    """Cache em memória com validade; falhas nunca são guardadas."""

    def __init__(self, ttl_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl, self._clock = ttl_s, clock
        self._items: dict[Hashable, tuple[float, Any]] = {}

    async def get_or_load[T](self, key: Hashable, loader: Callable[[], Awaitable[T]]) -> T:
        hit = self._items.get(key)
        if hit and self._clock() - hit[0] < self._ttl:
            return hit[1]
        value = await loader()
        self._items[key] = (self._clock(), value)
        return value

    def clear(self) -> None:
        self._items.clear()
