"""DSL de regras com lógica de três valores (Kleene).

Condição: { fato: <chave>, <operador>: <valor> } ou { todos | algum | nenhum: [condições] }.
Operadores: igual, diferente, em, fora_de, maior_que, menor_que, existe.
Fato ausente → DESCONHECIDO. Nunca converter ausência em FALSO.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domain.facts import Fact, FactStatus

OPERATORS = ("igual", "diferente", "em", "fora_de", "maior_que", "menor_que", "existe")
COMBINATORS = ("todos", "algum", "nenhum")


class Tri(StrEnum):
    VERDADEIRO = "VERDADEIRO"
    FALSO = "FALSO"
    DESCONHECIDO = "DESCONHECIDO"


@dataclass(frozen=True)
class Evaluation:
    value: Tri
    fact_keys: frozenset[str]  # todas as chaves citadas pela condição
    unknown: frozenset[str]  # chaves cuja ausência deixou o resultado em aberto


def usable_values(facts: dict[str, Fact], *, include_estimated: bool) -> dict[str, Any]:
    """Valores que as regras enxergam. Para elegibilidade, `estimado` não conta (fica DESCONHECIDO);
    para necessidades, entra como hipótese. Rejeitado nunca tem valor."""
    allowed = {FactStatus.CONFIRMADO, FactStatus.OBSERVADO, FactStatus.DERIVADO}
    if include_estimated:
        allowed.add(FactStatus.ESTIMADO)
    return {k: f.value for k, f in facts.items() if f.status in allowed and f.value is not None}


def condition_keys(cond: dict) -> set[str]:
    if "fato" in cond:
        return {cond["fato"]}
    (name,) = (k for k in cond if k in COMBINATORS)
    return set().union(*(condition_keys(c) for c in cond[name]))


def _compare(op: str, actual: Any, expected: Any) -> bool:
    match op:
        case "igual":
            return actual == expected
        case "diferente":
            return actual != expected
        case "em":
            return actual in expected
        case "fora_de":
            return actual not in expected
        case "maior_que":
            return actual > expected
        case "menor_que":
            return actual < expected
    raise ValueError(f"operador desconhecido: {op}")


def _and(values: list[Tri]) -> Tri:
    if Tri.FALSO in values:
        return Tri.FALSO
    return Tri.DESCONHECIDO if Tri.DESCONHECIDO in values else Tri.VERDADEIRO


def _or(values: list[Tri]) -> Tri:
    if Tri.VERDADEIRO in values:
        return Tri.VERDADEIRO
    return Tri.DESCONHECIDO if Tri.DESCONHECIDO in values else Tri.FALSO


def _not(value: Tri) -> Tri:
    return {Tri.VERDADEIRO: Tri.FALSO, Tri.FALSO: Tri.VERDADEIRO}.get(value, Tri.DESCONHECIDO)


def evaluate(cond: dict, values: dict[str, Any]) -> Evaluation:
    if "fato" in cond:
        key = cond["fato"]
        (op,) = (k for k in cond if k in OPERATORS)
        keys = frozenset({key})
        if op == "existe":
            # Pergunta sobre o próprio conhecimento: aqui a ausência é a resposta.
            present = key in values
            return Evaluation(
                Tri.VERDADEIRO if present == cond[op] else Tri.FALSO, keys, frozenset()
            )
        if key not in values:
            return Evaluation(Tri.DESCONHECIDO, keys, keys)
        value = Tri.VERDADEIRO if _compare(op, values[key], cond[op]) else Tri.FALSO
        return Evaluation(value, keys, frozenset())

    (name,) = (k for k in cond if k in COMBINATORS)
    parts = [evaluate(c, values) for c in cond[name]]
    tris = [p.value for p in parts]
    value = {"todos": _and, "algum": _or}.get(name, lambda v: _not(_or(v)))(tris)
    keys = frozenset().union(*(p.fact_keys for p in parts))
    unknown = (
        frozenset()
        if value is not Tri.DESCONHECIDO
        else frozenset().union(*(p.unknown for p in parts))
    )
    return Evaluation(value, keys, unknown)
