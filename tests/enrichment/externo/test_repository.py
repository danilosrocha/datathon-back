import httpx
import pytest

from app.enrichment.externo.repository import (
    ExternalDataUnavailable,
    RestRepository,
    SqlRepository,
)
from app.etl.externo.load import run_etl


@pytest.fixture
def seeded(engine, disasters_zip, crimes_xlsx):
    run_etl(engine, disasters_zip=disasters_zip, crimes_xlsx=crimes_xlsx)
    return engine


@pytest.fixture
async def sql_repo(seeded, pg_url):
    repo = SqlRepository(pg_url)
    yield repo
    await repo.aclose()


async def test_sql_municipal_disasters(sql_repo):
    rows = await sql_repo.desastres_municipio("2700102")
    assert [(r["ano"], r["tipo_evento"], r["se_ecp"]) for r in rows] == [(2003, "estiagem", "SE")]


async def test_sql_unknown_municipality_returns_empty_list_not_error(sql_repo):
    assert await sql_repo.desastres_municipio("3550308") == []


async def test_sql_coverage_by_uf(sql_repo):
    rows = await sql_repo.cobertura_desastres("AL")
    by_year = {r["ano"]: r for r in rows}
    assert by_year[2003]["arquivo_presente"] is True
    assert by_year[2004]["arquivo_presente"] is False
    assert by_year[2004]["registros_lidos"] is None


async def test_sql_crimes_filters_indicators(sql_repo):
    rows = await sql_repo.crimes_uf("AC", ["roubo_total"])
    assert {r["indicador"] for r in rows} == {"roubo_total"}
    assert {(r["ano"], r["valor"]) for r in rows} == {(2022, 4869), (2023, 45789)}


async def test_sql_provenance(sql_repo):
    fontes = await sql_repo.fontes(["defesa_civil_reconhecimentos"])
    assert fontes["defesa_civil_reconhecimentos"]["limitacoes"]


async def test_sql_unreachable_database_raises_unavailable():
    repo = SqlRepository("postgresql+psycopg://x:y@127.0.0.1:1/none", connect_timeout=1)
    with pytest.raises(ExternalDataUnavailable):
        await repo.desastres_municipio("2700102")
    await repo.aclose()


def rest_repo(handler, key="sb_secret_k"):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return RestRepository("https://p.supabase.co", key, client=client)


async def test_rest_sends_schema_profile_and_server_side_filters():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        seen["headers"] = request.headers
        return httpx.Response(200, json=[{"ano": 2003, "tipo_evento": "estiagem"}])

    rows = await rest_repo(handler).desastres_municipio("2700102")

    assert rows == [{"ano": 2003, "tipo_evento": "estiagem"}]
    assert seen["url"].path == "/rest/v1/desastre_reconhecimento"
    assert seen["url"].params["cod_ibge"] == "eq.2700102"
    assert seen["headers"]["accept-profile"] == "externo"
    assert seen["headers"]["apikey"] == "sb_secret_k"


async def test_rest_in_filter_for_crime_indicators():
    seen = {}

    def handler(request):
        seen["params"] = request.url.params
        return httpx.Response(200, json=[])

    await rest_repo(handler).crimes_uf("AC", ["roubo_total", "estupro"])
    assert seen["params"]["uf"] == "eq.AC"
    assert seen["params"]["indicador"] == "in.(roubo_total,estupro)"


@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
async def test_rest_error_status_raises_unavailable(status):
    with pytest.raises(ExternalDataUnavailable):
        await rest_repo(lambda r: httpx.Response(status, json={"message": "x"})).crimes_uf(
            "AC", ["estupro"]
        )


async def test_rest_transport_error_raises_unavailable():
    def handler(request):
        raise httpx.ConnectTimeout("lento", request=request)

    with pytest.raises(ExternalDataUnavailable):
        await rest_repo(handler).cobertura_desastres("AL")


async def test_rest_refuses_public_key_without_calling_the_network():
    def handler(request):
        raise AssertionError("não deveria chamar a rede")

    with pytest.raises(ExternalDataUnavailable, match="privilégio"):
        await rest_repo(handler, key="sb_publishable_k").fontes(["x"])
