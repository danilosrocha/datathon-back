"""Retroalimentação do context graph (ARQUITETURA §4.3). Função pura.

Só fatos `confirmado` viram learning_events (atividade, característica, valor — sem dados
pessoais). Agregação: α += verdadeiros, β += falsos na aresta atividade → característica.
A nova versão nasce `rascunho`; o grafo só muda para os próximos casos quando é publicada,
o que preserva a reprodutibilidade (cada decisão grava a versão usada)."""

from collections import Counter
from dataclasses import dataclass

from app.graph.store import GraphSnapshot, snapshot_from_rows, snapshot_to_rows


@dataclass(frozen=True)
class LearningEvent:
    atividade: str  # CNAE subclasse, ex.: "1091-1/02"
    caracteristica: str  # fact_key
    valor: bool


def apply_learning(
    base: GraphSnapshot, events: list[LearningEvent], version: int
) -> tuple[GraphSnapshot, list[dict]]:
    """Nova versão do grafo com α/β atualizados e a lista de arestas alteradas (antes/depois)."""
    nodes, edges = snapshot_to_rows(base)
    by_key = {(e["src"], e["dst"], e["type"]): e for e in edges}
    known = {n["id"] for n in nodes}
    fact_to_node = {
        n["attrs"].get("fact_key"): n["id"] for n in nodes if n["attrs"].get("fact_key")
    }

    counts = Counter((f"CNAE:{e.atividade}", e.caracteristica, e.valor) for e in events)
    changed = []
    for (activity, fact_key, value), n in sorted(counts.items()):
        target = fact_to_node.get(fact_key)
        if target is None:
            continue
        if activity not in known:
            nodes.append({"id": activity, "type": "atividade", "label": activity, "attrs": {}})
            known.add(activity)
        edge = by_key.setdefault(
            (activity, target, "TIPICAMENTE_TEM"),
            {
                "src": activity,
                "dst": target,
                "type": "TIPICAMENTE_TEM",
                "alpha": 1.0,
                "beta": 1.0,
                "weight": None,
            },
        )
        before = (edge["alpha"], edge["beta"])
        edge["alpha" if value else "beta"] += n
        changed.append(
            {
                "src": activity,
                "dst": target,
                "before": before,
                "after": (edge["alpha"], edge["beta"]),
            }
        )
    return snapshot_from_rows(version, nodes, list(by_key.values())), changed
