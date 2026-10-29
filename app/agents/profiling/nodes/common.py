from app.graph.store import GraphSnapshot, load_snapshot

# Versão do grafo em uso pelos próximos turnos; troca só quando uma nova versão é publicada.
_current: GraphSnapshot | None = None


def snapshot() -> GraphSnapshot:
    global _current
    if _current is None:
        _current = load_snapshot()
    return _current


def set_snapshot(graph: GraphSnapshot) -> None:
    global _current
    _current = graph
