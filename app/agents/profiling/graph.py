"""Sistema 1 — perfilamento: extrai fatos, roda o motor e pergunta ou explica a recomendação.

extract (LLM rápido) → enrich (CEP, risco regional) → reason (motor)
    → ask (LLM, pergunta escolhida pelo motor)
    ↘ explain (LLM + validador, quando não há mais perguntas)
"""

from langgraph.graph import END, START, StateGraph

from app.agents.profiling.nodes.ask import ask
from app.agents.profiling.nodes.enrich import enrich
from app.agents.profiling.nodes.explain import explain
from app.agents.profiling.nodes.extract import extract
from app.agents.profiling.nodes.reason import reason, route
from app.agents.profiling.state import ProfileState


def build_graph() -> StateGraph:
    builder = StateGraph(ProfileState)
    builder.add_node("extract", extract)
    builder.add_node("enrich", enrich)
    builder.add_node("reason", reason)
    builder.add_node("ask", ask)
    builder.add_node("explain", explain)
    builder.add_edge(START, "extract")
    builder.add_edge("extract", "enrich")
    builder.add_edge("enrich", "reason")
    builder.add_conditional_edges("reason", route, ["ask", "explain"])
    builder.add_edge("ask", END)
    builder.add_edge("explain", END)
    return builder


# Sem checkpointer para o LangGraph Studio; a API compila com AsyncPostgresSaver.
graph = build_graph().compile()
