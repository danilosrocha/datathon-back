"""Leitura do schema `externo` por SQL direto ou pela API REST (PostgREST) do Supabase."""

import datetime as dt
from collections.abc import Sequence
from typing import Any, Protocol

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings
from app.enrichment.externo.access import AccessPlan, key_role, resolve_access_mode
from app.enrichment.externo.tables import SCHEMA

Row = dict[str, Any]

FONTE_COLUMNS = (
    "id,nome,orgao,granularidade,periodo_inicio,periodo_fim,licenca,limitacoes,url,"
    "ultima_carga_em,sha256"
)


class ExternalDataUnavailable(Exception):
    """A fonte externa não pôde ser consultada (rede, permissão, schema ausente)."""


class ExternalDataRepository(Protocol):
    async def desastres_municipio(self, cod_ibge: str) -> list[Row]: ...
    async def cobertura_desastres(self, uf: str) -> list[Row]: ...
    async def crimes_uf(self, uf: str, indicadores: Sequence[str]) -> list[Row]: ...
    async def fontes(self, ids: Sequence[str]) -> dict[str, Row]: ...
    async def aclose(self) -> None: ...


def _jsonable(row: Row) -> Row:
    return {k: v.isoformat() if isinstance(v, dt.datetime | dt.date) else v for k, v in row.items()}


class SqlRepository:
    def __init__(self, database_url: str, *, connect_timeout: float = 5) -> None:
        self._engine: AsyncEngine = create_async_engine(
            database_url,
            connect_args={"connect_timeout": max(1, int(connect_timeout))},
            pool_pre_ping=True,
        )

    async def _fetch(self, sql: str, **params: Any) -> list[Row]:
        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(sa.text(sql), params)
                return [_jsonable(dict(r)) for r in result.mappings()]
        except (sa.exc.SQLAlchemyError, OSError) as exc:
            raise ExternalDataUnavailable(f"consulta SQL falhou: {type(exc).__name__}") from exc

    async def desastres_municipio(self, cod_ibge: str) -> list[Row]:
        return await self._fetch(
            f"SELECT ano, uf, tipo_evento, desastre_original, se_ecp, qa_flags "
            f"FROM {SCHEMA}.desastre_reconhecimento WHERE cod_ibge = :c ORDER BY ano, linha_origem",
            c=cod_ibge,
        )

    async def cobertura_desastres(self, uf: str) -> list[Row]:
        return await self._fetch(
            f"SELECT ano, arquivo_presente, registros_lidos, divergencia_total "
            f"FROM {SCHEMA}.desastre_cobertura WHERE uf = :u ORDER BY ano",
            u=uf,
        )

    async def crimes_uf(self, uf: str, indicadores: Sequence[str]) -> list[Row]:
        return await self._fetch(
            f"SELECT ano, indicador, valor, situacao, ressalva, qa_flags "
            f"FROM {SCHEMA}.crime_uf_indicador "
            f"WHERE uf = :u AND indicador = ANY(:i) ORDER BY ano, indicador",
            u=uf,
            i=list(indicadores),
        )

    async def fontes(self, ids: Sequence[str]) -> dict[str, Row]:
        rows = await self._fetch(
            f"SELECT {FONTE_COLUMNS} FROM {SCHEMA}.fonte WHERE id = ANY(:ids)", ids=list(ids)
        )
        return {r["id"]: r for r in rows}

    async def aclose(self) -> None:
        await self._engine.dispose()


class RestRepository:
    """PostgREST com `Accept-Profile: externo`. A chave de serviço fica só no backend."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        schema: str = SCHEMA,
        timeout: float = 5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base = base_url.rstrip("/") + "/rest/v1"
        self._key = api_key
        self._schema = schema
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def _get(self, table: str, params: dict[str, str]) -> list[Row]:
        if key_role(self._key) != "privileged":
            raise ExternalDataUnavailable(
                "a chave da API não tem privilégio de serviço para ler o schema externo"
            )
        headers = {
            "apikey": self._key,
            "Accept-Profile": self._schema,
            "Accept": "application/json",
        }
        if self._key.count(".") == 2:  # JWT legado; as chaves sb_secret_* não vão em Authorization
            headers["Authorization"] = f"Bearer {self._key}"
        try:
            response = await self._client.get(
                f"{self._base}/{table}", params=params, headers=headers
            )
        except httpx.HTTPError as exc:
            raise ExternalDataUnavailable(f"REST indisponível: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise ExternalDataUnavailable(f"REST respondeu HTTP {response.status_code}")
        data = response.json()
        if not isinstance(data, list):
            raise ExternalDataUnavailable("resposta REST inesperada")
        return data

    async def desastres_municipio(self, cod_ibge: str) -> list[Row]:
        return await self._get(
            "desastre_reconhecimento",
            {
                "select": "ano,uf,tipo_evento,desastre_original,se_ecp,qa_flags",
                "cod_ibge": f"eq.{cod_ibge}",
                "order": "ano.asc,linha_origem.asc",
            },
        )

    async def cobertura_desastres(self, uf: str) -> list[Row]:
        return await self._get(
            "desastre_cobertura",
            {
                "select": "ano,arquivo_presente,registros_lidos,divergencia_total",
                "uf": f"eq.{uf}",
                "order": "ano.asc",
            },
        )

    async def crimes_uf(self, uf: str, indicadores: Sequence[str]) -> list[Row]:
        return await self._get(
            "crime_uf_indicador",
            {
                "select": "ano,indicador,valor,situacao,ressalva,qa_flags",
                "uf": f"eq.{uf}",
                "indicador": f"in.({','.join(indicadores)})",
                "order": "ano.asc,indicador.asc",
            },
        )

    async def fontes(self, ids: Sequence[str]) -> dict[str, Row]:
        rows = await self._get("fonte", {"select": FONTE_COLUMNS, "id": f"in.({','.join(ids)})"})
        return {r["id"]: r for r in rows}

    async def aclose(self) -> None:
        await self._client.aclose()


def build_repository(settings: Settings) -> tuple[ExternalDataRepository, AccessPlan]:
    api_key = settings.supabase_service_role_key or settings.supabase_key
    plan = resolve_access_mode(
        database_url=settings.database_url,
        supabase_url=settings.supabase_url,
        api_key=api_key,
        forced=settings.external_data_mode,
    )
    if plan.mode == "sql":
        repo: ExternalDataRepository = SqlRepository(
            settings.database_url, connect_timeout=settings.enrichment_timeout_s
        )
    else:
        repo = RestRepository(settings.supabase_url, api_key, timeout=settings.enrichment_timeout_s)
    return repo, plan
