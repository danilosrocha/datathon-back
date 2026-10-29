from datetime import UTC, datetime

from langgraph.checkpoint.memory import InMemorySaver

from app.agents.profiling.graph import build_graph
from app.agents.profiling.graph import graph as profiling
from app.agents.profiling.nodes.ask import interviewer_context
from app.agents.profiling.nodes.explain import Explanation
from app.agents.profiling.nodes.extract import Extraction
from app.domain.facts import Fact, FactSource, FactStatus
from app.engine.questions import MAX_QUESTIONS


def _fact(key, value, status=FactStatus.OBSERVADO, source=FactSource.USUARIO_TEXTO) -> Fact:
    return Fact(
        key=key,
        value=value,
        status=status,
        source=source,
        confidence=0.8,
        updated_at=datetime(2026, 10, 28, tzinfo=UTC),
        updated_by="teste",
    )


CNAE = _fact("cnae_principal", "1091-1/02")
NO_IMPEDIMENTS = {
    k: _fact(k, False)
    for k in (
        "localizacao_restrita",
        "imovel_tombado_desapropriado_condenado",
        "imovel_em_obra",
        "parede_externa_combustivel",
        "objeto_ja_segurado_bb",
    )
}


async def test_profiling_extracts_and_asks_engine_question(fake_llm) -> None:
    fake_llm.respond(Extraction, "extraction_padaria")
    result = await profiling.ainvoke({"case_id": "c1", "messages": [("user", "padaria 1091-1/02")]})

    # Descartados: chave inexistente, valor fora do tipo e chave não extraível.
    assert set(result["facts"]) == {"cnae_principal"}
    cnae = result["facts"]["cnae_principal"]
    assert (cnae.value, cnae.status, cnae.source) == ("1091-1/02", "observado", "usuario_texto")
    assert result["hypotheses"]["mercadoria_refrigerada"] == 0.8
    # Motor: impedimentos ainda em aberto → a pergunta é de elegibilidade.
    assert result["decision"].eligibility.status == "pendente"
    assert result["question"].score >= 1000
    assert result["questions_asked"] == 1
    assert result["messages"][-1].content.strip() == "Pergunta de teste?"
    # O Entrevistador recebe a pergunta escolhida pelo motor no fim, como mensagem de sistema.
    context = fake_llm.calls[-1]["messages"][-1]
    assert context["role"] == "system" and result["question"].prompt in context["content"]


async def test_profiling_asks_activity_first(fake_llm) -> None:
    result = await profiling.ainvoke({"case_id": "c1", "messages": [("user", "oi")]})
    assert result["question"].fact_key == "cnae_principal"


async def test_ineligible_case_gets_no_question(fake_llm) -> None:
    facts = {"cnae_principal": CNAE, "imovel_em_obra": _fact("imovel_em_obra", True)}
    result = await profiling.ainvoke({"case_id": "c1", "facts": facts, "messages": []})
    assert result["question"] is None
    assert result["questions_asked"] == 0
    assert "inelegível" in interviewer_context(result)


async def test_profile_reaches_recommendation_with_validated_explanation(fake_llm) -> None:
    fake_llm.respond(Explanation, "explanation_valid")
    facts = {
        "cnae_principal": CNAE,
        **NO_IMPEDIMENTS,
        "mercadoria_refrigerada": _fact("mercadoria_refrigerada", True),
    }
    state = {"case_id": "c1", "facts": facts, "messages": [], "questions_asked": MAX_QUESTIONS}
    result = await profiling.ainvoke(state)

    best = result["decision"].offers[0]
    assert result["question"] is None
    assert best.plan_code == "PRATICO"
    assert best.explanation_source == "llm_validado"
    assert result["messages"][-1].content == best.explanation_md
    assert fake_llm.calls[-1]["effort"] == "medium"


async def test_invalid_explanation_falls_back_to_template(fake_llm) -> None:
    fake_llm.respond(Explanation, "explanation_invalid")
    state = {
        "case_id": "c1",
        "facts": {"cnae_principal": CNAE, **NO_IMPEDIMENTS},
        "messages": [],
        "questions_asked": MAX_QUESTIONS,
    }
    best = (await profiling.ainvoke(state))["decision"].offers[0]
    assert best.explanation_source == "template"
    assert best.explanation_md.startswith("**Plano")


async def test_card_edit_changes_offer(fake_llm) -> None:
    graph = build_graph().compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "profile:c1"}}
    cold = {"mercadoria_refrigerada": _fact("mercadoria_refrigerada", True)}
    first = await graph.ainvoke(
        {"case_id": "c1", "facts": {"cnae_principal": CNAE, **cold}}, config
    )

    # Edição do card: usuário corrige para "não" (confirmado, usuario_resposta).
    edit = _fact(
        "mercadoria_refrigerada", False, FactStatus.CONFIRMADO, FactSource.USUARIO_RESPOSTA
    )
    second = await graph.ainvoke({"facts": {"mercadoria_refrigerada": edit}}, config)

    before = {c.code for c in first["decision"].offers[0].coverages}
    after = {c.code for c in second["decision"].offers[0].coverages}
    assert "DETERIORACAO_MERCADORIAS_FRIGORIFICADAS" in before
    assert "DETERIORACAO_MERCADORIAS_FRIGORIFICADAS" not in after
    assert second["facts"]["mercadoria_refrigerada"].rejected_values == [True]
