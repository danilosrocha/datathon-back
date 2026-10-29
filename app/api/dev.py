"""Rotas de desenvolvimento (só com ENABLE_DEV_ROUTES=true): retroalimentação do context graph.

rebuild agrega os learning_events numa nova versão `rascunho`; publish troca a versão usada pelos
próximos turnos. Em memória por padrão; com PERSISTENCE=postgres, usa kg_versions/kg_edges."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from app.agents.profiling.nodes.common import set_snapshot
from app.db.repositories import graph as graph_repo
from app.graph.learning import apply_learning

router = APIRouter(prefix="/api/v1/dev/graph", tags=["dev"])


@router.post("/rebuild")
async def rebuild(request: Request) -> dict:
    state = request.app.state
    if state.sessions:
        async with state.sessions() as session, session.begin():
            version, changed = await graph_repo.rebuild(session, datetime.now(UTC))
    else:
        events = [e for per_case in state.learning.values() for e in per_case.values()]
        version = max([state.graph.version, *state.kg_drafts]) + 1
        draft, changed = apply_learning(state.graph_seed, events, version)
        state.kg_drafts[version] = draft
    return {"kg_version": version, "status": "rascunho", "changed_edges": changed}


@router.post("/publish/{kg_version}")
async def publish(request: Request, kg_version: int) -> dict:
    state = request.app.state
    if state.sessions:
        async with state.sessions() as session, session.begin():
            if not await graph_repo.publish(session, kg_version):
                raise HTTPException(404, detail="Versão inexistente.")
            draft = await graph_repo.load(session, kg_version)
    else:
        draft = state.kg_drafts.pop(kg_version, None)
        if draft is None:
            raise HTTPException(404, detail="Versão inexistente.")
    state.graph = draft
    set_snapshot(draft)
    return {"kg_version": kg_version, "status": "publicada"}
