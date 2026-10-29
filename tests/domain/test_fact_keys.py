from datetime import UTC, datetime

import pytest

from app.domain.fact_keys import fact_keys, get_fact_key
from app.domain.facts import Fact, FactSource, FactStatus


def make(key, value, status=FactStatus.OBSERVADO) -> Fact:
    return Fact(
        key=key,
        value=value,
        status=status,
        source=FactSource.BASE_COMUM,
        confidence=1.0,
        updated_at=datetime(2026, 10, 28, tzinfo=UTC),
        updated_by="teste",
    )


def test_registry_loads_contract_keys() -> None:
    keys = fact_keys()
    assert {"cnae_principal", "mercadoria_refrigerada", "risco_roubo_regiao"} <= set(keys)
    assert keys["faturamento_faixa"].options[0] == "ate_10k"  # alias money_range
    assert keys["risco_roubo_regiao"].options == ["baixo", "medio", "alto"]  # alias level
    assert keys["localizacao_restrita"].eligibility


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="inexistente"):
        make("inventado", True)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("delivery", True, True),
        ("faturamento_faixa", "50k_200k", "50k_200k"),
        ("seguranca_local", ["cameras", "alarme", "cameras"], ["alarme", "cameras"]),
        ("vigencia_anos", 3, 3),
        ("cnpj_cpf", "12.345.678/0001-90", "12345678000190"),
        ("cep", "70040-010", "70040010"),
        ("cnae_principal", " 1091-1/02 ", "1091-1/02"),
    ],
)
def test_valid_values_are_normalized(key, value, expected) -> None:
    assert make(key, value).value == expected


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("delivery", "sim"),
        ("faturamento_faixa", "muito"),
        ("seguranca_local", ["laser"]),
        ("vigencia_anos", 6),
        ("vigencia_anos", True),
        ("cnae_principal", "1091102"),
        ("uf", "df"),
    ],
)
def test_invalid_values_are_rejected(key, value) -> None:
    with pytest.raises(ValueError):
        make(key, value)


def test_never_estimated_guardrail() -> None:
    with pytest.raises(ValueError, match="nunca pode ser estimado"):
        make("localizacao_restrita", True, FactStatus.ESTIMADO)


def test_rejected_fact_has_no_value_to_validate() -> None:
    assert make("delivery", None, FactStatus.REJEITADO).value is None


def test_get_fact_key_error() -> None:
    with pytest.raises(ValueError):
        get_fact_key("x")
