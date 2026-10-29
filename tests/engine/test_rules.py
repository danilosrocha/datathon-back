import pytest

from app.engine.rules import Tri, evaluate

T, F, U = Tri.VERDADEIRO, Tri.FALSO, Tri.DESCONHECIDO


def test_absence_is_unknown_never_false() -> None:
    ev = evaluate({"fato": "delivery", "igual": False}, {})
    assert ev.value is U
    assert ev.unknown == {"delivery"}


@pytest.mark.parametrize(
    ("cond", "expected"),
    [
        ({"fato": "x", "igual": 1}, T),
        ({"fato": "x", "diferente": 1}, F),
        ({"fato": "x", "em": [1, 2]}, T),
        ({"fato": "x", "fora_de": [1, 2]}, F),
        ({"fato": "x", "maior_que": 0}, T),
        ({"fato": "x", "menor_que": 0}, F),
        ({"fato": "x", "existe": True}, T),
        ({"fato": "y", "existe": True}, F),
        ({"fato": "y", "existe": False}, T),
    ],
)
def test_operators(cond, expected) -> None:
    assert evaluate(cond, {"x": 1}).value is expected


def test_kleene_combinators() -> None:
    known_true = {"fato": "a", "igual": True}
    known_false = {"fato": "b", "igual": True}
    unknown = {"fato": "c", "igual": True}
    values = {"a": True, "b": False}

    assert evaluate({"algum": [known_true, unknown]}, values).value is T
    assert evaluate({"algum": [known_false, unknown]}, values).value is U
    assert evaluate({"todos": [known_false, unknown]}, values).value is F
    assert evaluate({"todos": [known_true, unknown]}, values).value is U
    assert evaluate({"nenhum": [known_false, unknown]}, values).value is U
    assert evaluate({"nenhum": [known_false]}, values).value is T


def test_unknown_only_reported_when_result_is_open() -> None:
    cond = {"algum": [{"fato": "a", "igual": True}, {"fato": "c", "igual": True}]}
    assert evaluate(cond, {"a": True}).unknown == frozenset()
    assert evaluate(cond, {"a": False}).unknown == {"c"}
