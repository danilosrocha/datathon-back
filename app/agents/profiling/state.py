from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

from app.domain.decision import Decision, Question
from app.domain.facts import Fact, merge_facts


class ProfileState(TypedDict, total=False):
    """CONTRATOS_API §4 — campos serão completados conforme o motor for implementado."""

    case_id: str
    messages: Annotated[list, add_messages]
    facts: Annotated[dict[str, Fact], merge_facts]
    hypotheses: dict[str, float]
    decision: Decision | None
    question: Question | None
    questions_asked: int
    kg_version: int
