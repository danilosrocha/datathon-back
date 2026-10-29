from app.graph.learning import LearningEvent, apply_learning
from app.graph.reasoner import probability
from app.graph.store import load_snapshot, snapshot_from_rows, snapshot_to_rows


def test_rows_roundtrip() -> None:
    snapshot = load_snapshot()
    again = snapshot_from_rows(1, *snapshot_to_rows(snapshot))
    assert snapshot_to_rows(again) == snapshot_to_rows(snapshot)


def test_confirmed_events_update_alpha_beta_in_new_version() -> None:
    base = load_snapshot()
    before = probability(base, "1091-1/02", "possui_estoque")
    events = [LearningEvent("1091-1/02", "possui_estoque", True)] * 10
    new, changed = apply_learning(base, events, version=2)
    assert new.version == 2
    assert changed == [
        {
            "src": "CNAE:1091-1/02",
            "dst": "possui_estoque",
            "before": (1.0, 1.0),
            "after": (11.0, 1.0),
        }
    ]
    assert probability(new, "1091-1/02", "possui_estoque") > (before or 0)
    assert probability(base, "1091-1/02", "possui_estoque") == before  # base intacta


def test_unknown_characteristic_is_ignored() -> None:
    _, changed = apply_learning(
        load_snapshot(), [LearningEvent("1091-1/02", "faturamento_faixa", True)], 2
    )
    assert changed == []
