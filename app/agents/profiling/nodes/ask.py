"""Entrevistador (LLM): redige a pergunta que o motor escolheu, ou explica a inelegibilidade."""

from langchain_core.messages import AIMessage
from langgraph.config import get_stream_writer

from app.agents import llm
from app.agents.profiling.state import ProfileState
from app.agents.prompts import load_prompt
from app.config import get_settings


def interviewer_context(state: ProfileState) -> str:
    """Estado volátil para o Entrevistador: o que o motor decidiu que deve ser dito."""
    decision, question = state.get("decision"), state.get("question")
    if decision is not None and decision.eligibility.status == "inelegivel":
        reasons = "; ".join(b.description for b in decision.eligibility.blockers)
        redirect = decision.eligibility.redirect_to
        extra = f" Indique o {redirect}." if redirect else ""
        return f"Caso inelegível: {reasons}. Explique com empatia, sem oferecer produto.{extra}"
    if question is None:
        return "Sem pergunta indicada."
    return (
        f"Pergunta indicada ({question.style}): {question.prompt}\n"
        f"Por que perguntamos: {question.reason}"
    )


async def ask(state: ProfileState) -> dict:
    question = state.get("question")
    writer = get_stream_writer()
    chunks = []
    async for text in llm.stream_text(
        model=get_settings().llm_model_main,
        system=load_prompt("profiling", "interviewer"),
        messages=llm.to_api_messages(state.get("messages", []), interviewer_context(state)),
    ):
        chunks.append(text)
        writer({"event": "message.delta", "case_id": state.get("case_id"), "text": text})
    asked = state.get("questions_asked", 0) + (question is not None)
    return {"questions_asked": asked, "messages": [AIMessage("".join(chunks))]}
