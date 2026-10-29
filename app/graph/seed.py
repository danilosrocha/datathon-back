"""Carrega ontologia + priors no Postgres como kg_version 1.

Uso: uv run python -m app.graph.seed   (requer DATABASE_URL e `alembic upgrade head`)"""

import asyncio
from datetime import UTC, datetime

from app.db.repositories import graph as graph_repo
from app.db.session import get_sessionmaker
from app.graph.store import load_snapshot


async def main() -> None:
    async with get_sessionmaker()() as session, session.begin():
        await graph_repo.seed(session, load_snapshot(), datetime.now(UTC))
    print("kg_version 1 publicada")


if __name__ == "__main__":
    asyncio.run(main())
