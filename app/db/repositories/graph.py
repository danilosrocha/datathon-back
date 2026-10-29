"""Context graph no Postgres: seed (kg_version 1), carga da versão publicada, rebuild e publish."""

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KgEdgeRow, KgNodeRow, KgVersionRow, LearningEventRow
from app.graph.learning import LearningEvent, apply_learning
from app.graph.store import GraphSnapshot, snapshot_from_rows, snapshot_to_rows

SEED_VERSION = 1
# Versões que servem de base para a retroalimentação (as do rebuild são derivadas delas).
BASE_NOTES = ("seed", "treino")


async def _write(
    session: AsyncSession, snapshot: GraphSnapshot, status: str, note: str, now: datetime
) -> None:
    nodes, edges = snapshot_to_rows(snapshot)
    for n in nodes:
        await session.merge(KgNodeRow(**n))
    session.add(KgVersionRow(version=snapshot.version, status=status, note=note, created_at=now))
    await session.flush()
    session.add_all(KgEdgeRow(kg_version=snapshot.version, **e) for e in edges)


async def seed(session: AsyncSession, snapshot: GraphSnapshot, now: datetime) -> None:
    """Ontologia + priors → kg_version 1 publicada. Idempotente: refaz a versão 1."""
    await session.execute(delete(KgEdgeRow).where(KgEdgeRow.kg_version == SEED_VERSION))
    await session.execute(delete(KgVersionRow).where(KgVersionRow.version == SEED_VERSION))
    seeded = GraphSnapshot(version=SEED_VERSION, graph=snapshot.graph)
    await _write(session, seeded, "publicada", "seed: ontologia + priors", now)


async def publish_trained(
    session: AsyncSession, snapshot: GraphSnapshot, note: str, now: datetime
) -> int:
    """Nova versão publicada com os priors treinados. Não sobrescreve versões anteriores: cada
    decisão registra a kg_version que usou."""
    version = (await session.scalar(select(func.max(KgVersionRow.version))) or 0) + 1
    trained = GraphSnapshot(version=version, graph=snapshot.graph)
    await _write(session, trained, "publicada", f"treino: {note}", now)
    return version


async def latest_base(session: AsyncSession) -> int:
    """Versão de seed ou treino mais recente: base da retroalimentação."""
    versions = (
        await session.scalars(select(KgVersionRow).order_by(KgVersionRow.version.desc()))
    ).all()
    return next(v.version for v in versions if (v.note or "").startswith(BASE_NOTES))


async def latest_published(session: AsyncSession) -> int | None:
    return await session.scalar(
        select(func.max(KgVersionRow.version)).where(KgVersionRow.status == "publicada")
    )


async def load(session: AsyncSession, version: int) -> GraphSnapshot:
    edges = (await session.scalars(select(KgEdgeRow).where(KgEdgeRow.kg_version == version))).all()
    used = {e.src for e in edges} | {e.dst for e in edges}
    nodes = (await session.scalars(select(KgNodeRow).where(KgNodeRow.id.in_(used)))).all()
    return snapshot_from_rows(
        version,
        [{"id": n.id, "type": n.type, "label": n.label, "attrs": n.attrs} for n in nodes],
        [
            {
                "src": e.src,
                "dst": e.dst,
                "type": e.type,
                "alpha": e.alpha,
                "beta": e.beta,
                "weight": e.weight,
            }
            for e in edges
        ],
    )


async def rebuild(session: AsyncSession, now: datetime) -> tuple[int, list[dict]]:
    """Seed/treino mais recente + todos os learning_events → nova versão `rascunho`
    (sempre a partir da base, sem dupla contagem)."""
    base = await load(session, await latest_base(session))
    rows = (await session.scalars(select(LearningEventRow))).all()
    events = [LearningEvent(r.atividade, r.caracteristica, r.valor) for r in rows]
    version = (await session.scalar(select(func.max(KgVersionRow.version)))) + 1
    snapshot, changed = apply_learning(base, events, version)
    await _write(session, snapshot, "rascunho", f"rebuild: {len(events)} learning_events", now)
    return version, changed


async def publish(session: AsyncSession, version: int) -> bool:
    row = await session.get(KgVersionRow, version)
    if row is None:
        return False
    row.status = "publicada"
    return True
