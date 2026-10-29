"""Explicador (LLM, effort medium): reescreve a explicação da melhor oferta em linguagem natural.
O validador confere; reprovou ou recusou → fica o texto de template do motor."""

from langchain_core.messages import AIMessage
from langgraph.config import get_stream_writer
from pydantic import BaseModel

from app.agents import llm
from app.agents.profiling.state import ProfileState
from app.agents.profiling.validator import validate_explanation
from app.agents.prompts import load_prompt
from app.config import get_settings
from app.domain.decision import Offer
from app.engine.catalog import default_catalog
from app.engine.explain_template import brl


class Explanation(BaseModel):
    texto: str


def offer_context(offer: Offer) -> str:
    """Recomendação estruturada para o Explicador (vai no fim, como mensagem de sistema)."""
    lines = [f"Recomendação: {offer.title}", "Coberturas:"]
    for c in offer.coverages:
        amount = c.insured_amount
        value = f"{brl(amount.min)} a {brl(amount.max)}" if amount else "valor na cotação"
        lines.append(f"- {c.name}: {value}. Motivo: {c.justification}")
    to_confirm = sorted({q for c in offer.coverages for q in c.to_confirm})
    if to_confirm:
        lines.append("A confirmar: " + "; ".join(to_confirm))
    lines.append("Assistências do plano: " + ", ".join(offer.assistance_packages))
    return "\n".join(lines)


async def explain(state: ProfileState) -> dict:
    decision = state["decision"]
    best = decision.offers[0]
    result = await llm.parse(
        model=get_settings().llm_model_main,
        system=load_prompt("profiling", "explainer"),
        messages=llm.to_api_messages(state.get("messages", []), offer_context(best)),
        output_format=Explanation,
        effort="medium",
    )
    problems = validate_explanation(result.texto, best, default_catalog()) if result else ["recusa"]
    if problems:
        text, source = best.explanation_md, "template"
    else:
        text, source = result.texto, "llm_validado"

    explained = best.model_copy(update={"explanation_md": text, "explanation_source": source})
    decision = decision.model_copy(update={"offers": [explained, *decision.offers[1:]]})
    get_stream_writer()({"event": "message.delta", "case_id": state.get("case_id"), "text": text})
    return {"decision": decision, "messages": [AIMessage(text)]}
