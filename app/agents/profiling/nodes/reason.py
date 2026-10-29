"""Motor determinístico: decisão e próxima pergunta. O LLM nunca decide nada aqui."""

from app.agents.profiling.nodes.common import snapshot
from app.agents.profiling.state import ProfileState
from app.engine.catalog import default_catalog
from app.engine.decide import decide
from app.engine.questions import next_question
from app.graph.reasoner import hypotheses


def reason(state: ProfileState) -> dict:
    graph, catalog = snapshot(), default_catalog()
    facts = state.get("facts", {})
    decision = decide(facts, catalog, graph)
    question = next_question(
        facts, catalog, graph, asked=state.get("questions_asked", 0), decision=decision
    )
    cnae_fact = facts.get("cnae_principal")
    cnae = cnae_fact.value if cnae_fact and cnae_fact.is_known else None
    return {
        "decision": decision,
        "question": question,
        "hypotheses": hypotheses(graph, cnae) if cnae else {},
        "kg_version": graph.version,
    }


def route(state: ProfileState) -> str:
    """Perfil pronto (sem pergunta) e com oferta → Explicador; senão, Entrevistador."""
    decision = state.get("decision")
    if state.get("question") is None and decision is not None and decision.offers:
        return "explain"
    return "ask"
