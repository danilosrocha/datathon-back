from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import make_url, text

from app.agents.profiling.checkpoint import serializer
from app.agents.profiling.graph import build_graph
from app.agents.profiling.nodes.common import set_snapshot
from app.api import cases, dev, offers
from app.api.sse import EventBus
from app.config import get_settings
from app.engine.catalog import default_catalog
from app.graph.store import load_snapshot


def psycopg_conninfo(database_url: str) -> str:
    """URL do SQLAlchemy → conninfo do psycopg, com a senha codificada (senhas com %, £ etc.
    passam no SQLAlchemy mas quebram o parser do psycopg)."""
    url = make_url(database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """PERSISTENCE=postgres: checkpointer, casos e grafo publicado no Postgres (Supabase)."""
    settings = get_settings()
    if settings.persistence != "postgres":
        yield
        return

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from app.db.repositories import graph as graph_repo
    from app.db.session import get_sessionmaker

    conninfo = psycopg_conninfo(settings.database_url)
    async with AsyncPostgresSaver.from_conn_string(conninfo, serde=serializer()) as saver:
        await saver.setup()
        sessions = get_sessionmaker()
        app.state.sessions = sessions
        app.state.cases.attach(sessions)
        async with sessions() as session:
            version = await graph_repo.latest_published(session)
            if version is not None:
                app.state.graph = await graph_repo.load(session, version)
                set_snapshot(app.state.graph)
        app.state.profile_graph = build_graph().compile(checkpointer=saver)
        app.state.runner = cases.build_runner(app)
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Negócio de Pé API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    state = app.state
    state.catalog = default_catalog()
    state.graph_seed = state.graph = load_snapshot()
    set_snapshot(state.graph)
    state.characteristic_keys = {
        d["fact_key"] for _, d in state.graph.graph.nodes(data=True) if d.get("fact_key")
    }
    state.offers = offers.OfferRepository()
    state.cases = cases.CaseStore(
        on_restore=lambda case_id, token_hash, rec, facts: state.offers.save_hashed(
            case_id, token_hash, rec.offers, facts
        )
    )
    state.bus = EventBus()
    state.sessions = None
    state.learning = {}  # case_id → {característica: LearningEvent} (só confirmados)
    state.kg_drafts = {}  # versões rascunho em memória
    # Em memória por padrão; o lifespan troca por AsyncPostgresSaver com PERSISTENCE=postgres.
    state.profile_graph = build_graph().compile(checkpointer=InMemorySaver(serde=serializer()))
    state.runner = cases.build_runner(app)
    state.limiter = cases.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(cases.router)
    app.include_router(offers.router)
    if settings.enable_dev_routes:
        app.include_router(dev.router)

    @app.get("/health")
    async def health(deep: bool = False) -> dict:
        if not deep:
            return {"status": "ok"}
        result = {
            "status": "ok",
            "kg_version": state.graph.version,
            "kg_edges": state.graph.graph.number_of_edges(),
        }
        if state.sessions:
            try:
                async with state.sessions() as session:
                    await session.execute(text("SELECT 1"))
                result["database"] = "ok"
            except Exception as error:
                result |= {"status": "degraded", "database": str(error)}
        return result

    return app


app = create_app()
