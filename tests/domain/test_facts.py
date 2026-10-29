from datetime import UTC, datetime

from app.domain.facts import Fact, FactSource, FactStatus, merge_fact, merge_facts

T0 = datetime(2026, 10, 28, tzinfo=UTC)


def fact(value, status=FactStatus.OBSERVADO, source=FactSource.USUARIO_TEXTO) -> Fact:
    return Fact(
        key="mercadoria_refrigerada",
        value=value,
        status=status,
        source=source,
        confidence=0.8,
        updated_at=T0,
        updated_by="teste",
    )


def test_first_fact_is_stored() -> None:
    assert merge_fact(None, fact(True)).value is True


def test_estimate_does_not_override_declared() -> None:
    declared = fact(True)
    estimate = fact(False, FactStatus.ESTIMADO, FactSource.GRAFO)
    assert merge_fact(declared, estimate) == declared


def test_correction_keeps_previous_value_as_rejected() -> None:
    merged = merge_fact(fact(True), fact(False, FactStatus.CONFIRMADO, FactSource.USUARIO_RESPOSTA))
    assert merged.value is False
    assert merged.status is FactStatus.CONFIRMADO
    assert merged.rejected_values == [True]


def test_free_text_does_not_override_confirmed() -> None:
    confirmed = fact(True, FactStatus.CONFIRMADO, FactSource.USUARIO_RESPOSTA)
    assert merge_fact(confirmed, fact(False)) == confirmed


def test_rejection_clears_value() -> None:
    merged = merge_fact(fact(True), fact(True, FactStatus.REJEITADO, FactSource.USUARIO_RESPOSTA))
    assert merged.value is None
    assert merged.rejected_values == [True]
    assert not merged.is_known


def test_estimated_is_not_known() -> None:
    assert not fact(True, FactStatus.ESTIMADO, FactSource.GRAFO).is_known


def test_merge_facts_keeps_untouched_keys() -> None:
    other = fact(True).model_copy(update={"key": "delivery"})
    merged = merge_facts({"delivery": other}, {"mercadoria_refrigerada": fact(True)})
    assert set(merged) == {"delivery", "mercadoria_refrigerada"}
