"""Registro das chaves de fatos (CONTRATOS_API §5): tipo, grupo e valores aceitos."""

import re
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

FactType = Literal[
    "boolean", "select", "multiselect", "number", "text", "cnpj", "cep", "list", "object"
]

_ALIASES = {
    "money_range": ["ate_10k", "10k_50k", "50k_200k", "200k_1m", "1m_7_5m", "acima_7_5m"],
    "level": ["baixo", "medio", "alto"],
}


class FactKey(BaseModel):
    key: str
    label: str
    group: str
    type: FactType
    options: list[str] = []
    pattern: str | None = None
    min: float | None = None
    max: float | None = None
    extractable: bool = True
    eligibility: bool = False
    never_estimated: bool = False

    def validate_value(self, value: Any) -> Any:
        """Devolve o valor normalizado ou levanta ValueError."""
        match self.type:
            case "boolean":
                ok = isinstance(value, bool)
            case "select":
                ok = value in self.options
            case "multiselect":
                ok = isinstance(value, list) and all(v in self.options for v in value)
                value = sorted(set(value)) if ok else value
            case "number":
                ok = isinstance(value, int | float) and not isinstance(value, bool)
                ok = ok and (self.min is None or value >= self.min)
                ok = ok and (self.max is None or value <= self.max)
            case "cnpj":
                value = re.sub(r"\D", "", value) if isinstance(value, str) else value
                ok = isinstance(value, str) and len(value) in (11, 14)
            case "cep":
                value = re.sub(r"\D", "", value) if isinstance(value, str) else value
                ok = isinstance(value, str) and len(value) == 8
            case "list":
                ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
            case "object":
                ok = isinstance(value, dict)
            case _:
                value = value.strip() if isinstance(value, str) else value
                ok = isinstance(value, str) and bool(value)
        if ok and self.pattern:
            ok = re.fullmatch(self.pattern, value) is not None
        if not ok:
            raise ValueError(f"valor inválido para {self.key} ({self.type}): {value!r}")
        return value


@cache
def fact_keys() -> dict[str, FactKey]:
    raw = yaml.safe_load((Path(__file__).parent / "fact_keys.yaml").read_text(encoding="utf-8"))
    registry = {}
    for group, keys in raw.items():
        for key, spec in keys.items():
            if key in registry:
                raise ValueError(f"chave de fato duplicada: {key}")
            spec = dict(spec)
            if spec["type"] in _ALIASES:
                spec["options"] = _ALIASES[spec.pop("type")]
                spec["type"] = "select"
            registry[key] = FactKey(key=key, group=group, **spec)
    return registry


def get_fact_key(key: str) -> FactKey:
    try:
        return fact_keys()[key]
    except KeyError:
        raise ValueError(f"chave de fato inexistente: {key!r}") from None
