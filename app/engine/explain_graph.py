"""Subgrafo da trilha de uma oferta para a UI (`GET /cases/{id}/explain-graph`). Função pura."""

from app.domain.decision import Offer
from app.domain.fact_keys import fact_keys


def trail_graph(offer: Offer) -> dict[str, list[dict]]:
    """fato →USADO_EM→ regra →ACIONA→ cobertura →MITIGA→ risco →AFETA→ necessidade."""
    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str, str]] = set()

    def node(node_id: str, kind: str, label: str) -> str:
        nodes.setdefault(node_id, {"id": node_id, "type": kind, "label": label})
        return node_id

    registry = fact_keys()
    for c in offer.coverages:
        cov = node(f"coverage:{c.code}", "cobertura", c.name)
        rule = node(f"rule:{c.rule_id}", "regra", c.rule_id)
        need = node(f"need:{c.need}", "necessidade", c.need)
        edges |= {(rule, cov, "ACIONA"), (cov, need, "PERTENCE_A")}
        if c.risk:
            risk = node(f"risk:{c.risk}", "risco", c.risk)
            edges |= {(cov, risk, "MITIGA"), (risk, need, "AFETA")}
        for key in c.fact_keys:
            label = registry[key].label if key in registry else key
            edges.add((node(f"fact:{key}", "fato", label), rule, "USADO_EM"))
    return {
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": [
            {"src": s, "dst": d, "type": t, "label": t.replace("_", " ").lower()}
            for s, d, t in sorted(edges)
        ],
    }
