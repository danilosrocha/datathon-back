"""Repositórios contra SQLite em memória (mesmos modelos; JSONB vira JSON). A migração do
Postgres é validada à parte em modo offline."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.repositories import cases as case_repo
from app.db.repositories import graph as graph_repo
from app.domain.case import Recommendation
from app.engine.catalog import default_catalog
from app.engine.decide import decide
from app.graph.store import load_snapshot
from tests.engine.conftest import NO_IMPEDIMENTS, make_facts

NOW = datetime(2026, 10, 28, tzinfo=UTC)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Como no Postgres: chaves estrangeiras valem (o SQLite não as aplica por padrão).
    event.listen(
        engine.sync_engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON")
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def test_case_facts_events_and_recommendation(session) -> None:
    await case_repo.create_case(session, "c1", "hash", "web", NOW)
    facts = make_facts(**NO_IMPEDIMENTS, cnae_principal="1091-1/02", mercadoria_refrigerada=True)
    await case_repo.upsert_facts(session, "c1", list(facts.values()))
    await session.flush()
    edited = make_facts(mercadoria_refrigerada=False)
    await case_repo.upsert_facts(session, "c1", list(edited.values()))  # PK (case_id, key)
    await session.commit()

    loaded = await case_repo.load_facts(session, "c1")
    assert set(loaded) == set(facts)
    assert loaded["mercadoria_refrigerada"].value is False
    assert await case_repo.get_token_hash(session, "c1") == "hash"

    decision = decide(loaded, default_catalog(), load_snapshot())
    rec = Recommendation.from_decision("rec_1", "c1", decision, NOW)
    await case_repo.save_recommendation(session, rec, "recomendado")
    await case_repo.append_event(session, "c1", "review_requested", {"reason": "x"}, "usuario", NOW)
    await session.commit()
    restored = await case_repo.latest_recommendation(session, "c1")
    assert restored == rec
    assert [e.type for e in await case_repo.list_events(session, "c1")] == [
        "case.created",
        "review_requested",
    ]


async def test_only_confirmed_facts_feed_learning(session) -> None:
    from app.domain.facts import FactStatus

    await case_repo.create_case(session, "c1", "hash", "web", NOW)
    facts = make_facts(mercadoria_refrigerada=True) | make_facts(
        FactStatus.CONFIRMADO, possui_estoque=False
    )
    n = await case_repo.record_learning(
        session, "c1", "1091-1/02", facts, {"mercadoria_refrigerada", "possui_estoque"}, NOW
    )
    assert n == 1


async def test_graph_seed_rebuild_publish(session) -> None:
    from app.db.models import LearningEventRow

    snapshot = load_snapshot()
    await graph_repo.seed(session, snapshot, NOW)
    await session.commit()
    assert await graph_repo.latest_published(session) == 1
    loaded = await graph_repo.load(session, 1)
    assert loaded.graph.number_of_edges() == snapshot.graph.number_of_edges()

    await case_repo.create_case(session, "c1", "hash", "web", NOW)
    session.add_all(
        LearningEventRow(
            case_id="c1", atividade="1091-1/02", caracteristica="possui_estoque", valor=True, ts=NOW
        )
        for _ in range(3)
    )
    await session.commit()
    version, changed = await graph_repo.rebuild(session, NOW)
    await session.commit()
    assert version == 2 and changed[0]["after"][0] == changed[0]["before"][0] + 3
    assert await graph_repo.latest_published(session) == 1  # rascunho não muda nada
    assert await graph_repo.publish(session, 2)
    await session.commit()
    assert await graph_repo.latest_published(session) == 2
