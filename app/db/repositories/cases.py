"""Persistência do caso: cadastro, fatos (upsert por chave), auditoria e recomendações."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CaseEventRow, CaseFactRow, CaseRow, LearningEventRow, RecommendationRow
from app.domain.case import Recommendation
from app.domain.facts import Fact, FactStatus


async def create_case(
    session: AsyncSession, case_id: str, token_hash: str, channel: str, now: datetime
) -> None:
    session.add(
        CaseRow(
            id=case_id,
            status="em_perfilamento",
            channel=channel,
            case_token_hash=token_hash,
            created_at=now,
        )
    )
    await session.flush()  # o caso precisa existir antes do evento (FK de case_events)
    await append_event(session, case_id, "case.created", {"channel": channel}, "sistema", now)


async def get_token_hash(session: AsyncSession, case_id: str) -> str | None:
    row = await session.get(CaseRow, case_id)
    return row.case_token_hash if row else None


async def upsert_facts(session: AsyncSession, case_id: str, facts: list[Fact]) -> None:
    for fact in facts:
        row = await session.get(CaseFactRow, (case_id, fact.key))
        data = fact.model_dump(mode="json", exclude={"key", "updated_at"})
        data["updated_at"] = fact.updated_at
        if row is None:
            session.add(CaseFactRow(case_id=case_id, key=fact.key, **data))
        else:
            for name, value in data.items():
                setattr(row, name, value)


async def load_facts(session: AsyncSession, case_id: str) -> dict[str, Fact]:
    rows = await session.scalars(select(CaseFactRow).where(CaseFactRow.case_id == case_id))
    return {
        r.key: Fact(
            key=r.key,
            value=r.value,
            status=r.status,
            source=r.source,
            confidence=r.confidence,
            evidence=r.evidence,
            rejected_values=r.rejected_values or [],
            updated_at=r.updated_at,
            updated_by=r.updated_by,
        )
        for r in rows
    }


async def append_event(
    session: AsyncSession, case_id: str, type_: str, payload: dict, actor: str, ts: datetime
) -> None:
    """Auditoria append-only: nunca atualiza nem apaga."""
    session.add(CaseEventRow(case_id=case_id, type=type_, payload=payload, actor=actor, ts=ts))


async def list_events(session: AsyncSession, case_id: str) -> list[CaseEventRow]:
    rows = await session.scalars(
        select(CaseEventRow).where(CaseEventRow.case_id == case_id).order_by(CaseEventRow.id)
    )
    return list(rows)


async def save_recommendation(session: AsyncSession, rec: Recommendation, status: str) -> None:
    session.add(
        RecommendationRow(
            id=rec.recommendation_id,
            case_id=rec.case_id,
            status=rec.status,
            eligibility=rec.eligibility.model_dump(mode="json"),
            offers=[o.model_dump(mode="json") for o in rec.offers],
            # Recomendação completa no trace: permite restaurar o caso depois de um restart.
            trace={"recommendation": rec.model_dump(mode="json")},
            rules_version=rec.versions.rules,
            kg_version=rec.versions.kg,
            created_at=rec.created_at,
        )
    )
    case = await session.get(CaseRow, rec.case_id)
    if case is not None:
        case.status, case.rules_version, case.kg_version = (
            status,
            rec.versions.rules,
            rec.versions.kg,
        )


async def latest_recommendation(session: AsyncSession, case_id: str) -> Recommendation | None:
    row = await session.scalar(
        select(RecommendationRow)
        .where(RecommendationRow.case_id == case_id)
        .order_by(RecommendationRow.created_at.desc())
        .limit(1)
    )
    if row is None or "recommendation" not in row.trace:
        return None
    return Recommendation.model_validate(row.trace["recommendation"])


async def record_learning(
    session: AsyncSession,
    case_id: str,
    cnae: str,
    facts: dict[str, Fact],
    keys: set[str],
    now: datetime,
) -> int:
    """Só fatos `confirmado` realimentam o grafo (ARQUITETURA §4.3)."""
    count = 0
    for key in sorted(keys):
        fact = facts.get(key)
        if (
            fact is not None
            and fact.status is FactStatus.CONFIRMADO
            and isinstance(fact.value, bool)
        ):
            session.add(
                LearningEventRow(
                    case_id=case_id, atividade=cnae, caracteristica=key, valor=fact.value, ts=now
                )
            )
            count += 1
    return count
