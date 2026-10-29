"""Modelos do caso na API (CONTRATOS_API §3.5 Recommendation e §3.6 CaseSnapshot)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.domain.decision import Confidence, Decision, Eligibility, Offer, Question, Versions

CaseStatus = Literal[
    "em_perfilamento", "recomendado", "inelegivel", "em_contratacao", "contratado_simulado",
    "abandonado",
]  # fmt: skip
AvatarState = Literal[
    "ouvindo", "pensando", "consultando", "sorrindo", "explicando", "preocupado", "comemorando"
]


class Recommendation(BaseModel):
    recommendation_id: str
    case_id: str
    status: Literal["conclusiva", "preliminar"]
    eligibility: Eligibility
    offers: list[Offer]
    confidence: Confidence
    confirmation_questions: list[str]
    external_sources: list[str]
    versions: Versions
    created_at: datetime

    @classmethod
    def from_decision(
        cls, recommendation_id: str, case_id: str, decision: Decision, created_at: datetime
    ) -> "Recommendation":
        return cls(
            recommendation_id=recommendation_id,
            case_id=case_id,
            status=decision.status,
            eligibility=decision.eligibility,
            offers=decision.offers,
            confidence=decision.confidence,
            confirmation_questions=decision.confirmation_questions,
            external_sources=decision.external_sources,
            versions=decision.versions,
            created_at=created_at,
        )


class ChatMessage(BaseModel):
    message_id: str
    role: Literal["user", "assistant"]
    text: str


class Progress(BaseModel):
    answered: int
    estimated_remaining: int


class CaseSnapshot(BaseModel):
    case_id: str
    status: CaseStatus
    cards: list[dict[str, Any]]
    question: Question | None
    messages: list[ChatMessage]
    eligibility: Eligibility | None
    recommendation: Recommendation | None
    avatar_state: AvatarState
    progress: Progress
