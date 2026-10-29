"""Hipóteses p(característica | atividade) com back-off hierárquico CNAE (ARQUITETURA §4.3)."""

from app.graph.store import GraphSnapshot

MIN_EVIDENCE = 5.0


def cnae_ancestors(cnae: str) -> list[str]:
    """'1091-1/02' → ['CNAE:1091-1/02', 'CNAE:1091-1', 'CNAE:109', 'CNAE:10']."""
    digits = cnae.replace("-", "").replace("/", "")
    levels = [cnae, cnae.split("/")[0], digits[:3], digits[:2]]
    return [f"CNAE:{lvl}" for lvl in dict.fromkeys(levels) if lvl]


def probability(snapshot: GraphSnapshot, cnae: str, caracteristica: str) -> float | None:
    """p = α/(α+β) no nível mais específico com α+β ≥ 5; sem evidência alguma → None."""
    g = snapshot.graph
    fallback = None
    for node in cnae_ancestors(cnae):
        edge = g.get_edge_data(node, caracteristica, key="TIPICAMENTE_TEM")
        if edge is None:
            continue
        alpha, beta = edge["alpha"], edge["beta"]
        if alpha + beta >= MIN_EVIDENCE:
            return alpha / (alpha + beta)
        if fallback is None:
            fallback = alpha / (alpha + beta)
    return fallback


def hypotheses(snapshot: GraphSnapshot, cnae: str) -> dict[str, float]:
    """p(k) por fact_key para todas as características com alguma evidência."""
    g = snapshot.graph
    result = {}
    for node, data in sorted(g.nodes(data=True)):
        if data["type"] != "caracteristica":
            continue
        p = probability(snapshot, cnae, node)
        if p is not None:
            result[data["fact_key"]] = p
    return result


def exposures(snapshot: GraphSnapshot, fact_key: str) -> list[tuple[str, float, list[str]]]:
    """Caminhos característica →EXPOE_A→ risco →AFETA→ dimensões: [(risco, peso, dimensões)]."""
    g = snapshot.graph
    nodes = [n for n, d in g.nodes(data=True) if d.get("fact_key") == fact_key]
    result = []
    for node in nodes:
        for _, risk, key, data in g.out_edges(node, keys=True, data=True):
            if key != "EXPOE_A":
                continue
            dims = sorted(d for _, d, k in g.out_edges(risk, keys=True) if k == "AFETA")
            result.append((risk, data["weight"], dims))
    return sorted(result)
