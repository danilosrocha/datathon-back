import asyncio

import pytest

from app.enrichment.externo.adapter import ExternalContextAdapter
from app.enrichment.externo.repository import ExternalDataUnavailable, SqlRepository
from app.etl.externo.load import run_etl

FONTES = {
    "defesa_civil_reconhecimentos": {
        "id": "defesa_civil_reconhecimentos", "nome": "Reconhecimentos SE/ECP",
        "orgao": "Defesa Civil", "granularidade": "Município", "periodo_inicio": 2003,
        "periodo_fim": 2016, "licenca": "n/v", "limitacoes": "Ausência de registro não é zero.",
        "url": None, "ultima_carga_em": "2026-10-28T12:00:00+00:00", "sha256": "x" * 64,
    },
    "crimes_uf_compilacao": {
        "id": "crimes_uf_compilacao", "nome": "Crimes por UF", "orgao": "Compilação",
        "granularidade": "UF × ano", "periodo_inicio": 2005, "periodo_fim": 2023, "licenca": "n/v",
        "limitacoes": "Nível UF.", "url": None, "ultima_carga_em": "2026-10-28T12:00:00+00:00",
        "sha256": "y" * 64,
    },
}  # fmt: skip


def d(ano, tipo, se="SE"):
    return {"ano": ano, "uf": "AL", "tipo_evento": tipo, "desastre_original": tipo.upper(),
            "se_ecp": se, "qa_flags": []}  # fmt: skip


def c(ano, ind, valor, situacao="informado", ressalva=None):
    return {
        "ano": ano,
        "indicador": ind,
        "valor": valor,
        "situacao": situacao,
        "ressalva": ressalva,
    }


class FakeRepo:
    def __init__(self, desastres=(), cobertura=(), crimes=(), fail=None, delay=0.0):
        self.desastres, self.cobertura, self.crimes = list(desastres), list(cobertura), list(crimes)
        self.fail, self.delay = fail or set(), delay
        self.calls: list[str] = []

    async def _do(self, name, value):
        self.calls.append(name)
        if self.delay:
            await asyncio.sleep(self.delay)
        if name in self.fail:
            raise ExternalDataUnavailable(f"{name} fora do ar")
        return value

    async def desastres_municipio(self, cod_ibge):
        return await self._do("desastres", self.desastres)

    async def cobertura_desastres(self, uf):
        return await self._do("cobertura", self.cobertura)

    async def crimes_uf(self, uf, indicadores):
        return await self._do("crimes", [r for r in self.crimes if r["indicador"] in indicadores])

    async def fontes(self, ids):
        return await self._do("fontes", {i: FONTES[i] for i in ids})

    async def aclose(self): ...


COBERTURA = [
    {"ano": 2003, "arquivo_presente": True, "registros_lidos": 3, "divergencia_total": False},
    {"ano": 2004, "arquivo_presente": False, "registros_lidos": None, "divergencia_total": None},
]
FACTS = {"municipio_ibge": "2700102", "uf": "AL"}


def adapter(repo, **kw):
    kw.setdefault("timeout", 1.0)
    return ExternalContextAdapter(repo, **kw)


def patch(result, key):
    return next(p for p in result.patches if p.key == key)


def unavailable(result, key):
    return next(u for u in result.unavailable if u.key == key)


async def test_municipal_disasters_are_an_observed_historical_context():
    repo = FakeRepo(
        desastres=[d(2003, "estiagem"), d(2003, "estiagem", "ECP"), d(2010, "vendaval")],
        cobertura=COBERTURA,
    )
    result = await adapter(repo).run(FACTS)

    fact = patch(result, "historico_desastres_municipio")
    assert fact.status == "observado"
    assert fact.source == "api_desastres"
    assert fact.value["total_reconhecimentos"] == 3
    assert fact.value["por_tipo"]["estiagem"] == {
        "reconhecimentos": 2, "anos": [2003], "se": 1, "ecp": 1,
    }  # fmt: skip
    assert fact.value["por_tipo"]["vendaval"]["anos"] == [2010]
    assert fact.value["periodo_fonte"] == [2003, 2016]
    assert "não equivale ao risco atual" in fact.evidence
    assert fact.provenance.fonte_id == "defesa_civil_reconhecimentos"
    assert fact.provenance.limitacoes
    assert fact.provenance.atualizado_em == "2026-10-28T12:00:00+00:00"


async def test_coverage_gaps_are_reported_not_hidden():
    repo = FakeRepo(desastres=[d(2003, "estiagem")], cobertura=COBERTURA)
    fact = patch(await adapter(repo).run(FACTS), "historico_desastres_municipio")
    assert fact.value["anos_sem_arquivo_na_uf"] == [2004]
    assert fact.value["cobertura_parcial"] is True


async def test_no_records_is_unavailable_never_zero():
    result = await adapter(FakeRepo(cobertura=COBERTURA)).run(FACTS)

    assert all(p.key != "historico_desastres_municipio" for p in result.patches)
    item = unavailable(result, "historico_desastres_municipio")
    assert item.reason == "sem_registro_na_fonte"
    assert "ausência" in item.detail.lower()


CRIMES = [
    c(2019, "roubo_total", 1000), c(2019, "populacao", 100_000),
    c(2020, "roubo_total", 400, ressalva="só 1º semestre"), c(2020, "populacao", 100_000),
    c(2023, "roubo_estabelecimento_comercial", None, "nao_disponivel"),
    c(2022, "roubo_estabelecimento_comercial", 250), c(2022, "populacao", 125_000),
    c(2023, "roubo_total", 2500), c(2023, "populacao", 200_000),
    c(2023, "roubo_carga", None, "em_branco"),
]  # fmt: skip


async def test_crime_counts_are_observed_at_uf_level_and_skip_caveated_years():
    result = await adapter(FakeRepo(crimes=CRIMES)).run({"uf": "AL"})

    fact = patch(result, "contexto_criminalidade_uf")
    assert fact.status == "observado"
    assert fact.source == "api_seguranca"
    assert fact.value["nivel"] == "uf"
    assert fact.value["indicadores"]["roubo_total"] == {"ano": 2023, "valor": 2500}
    assert fact.value["indicadores"]["roubo_estabelecimento_comercial"] == {
        "ano": 2022,
        "valor": 250,
    }
    assert set(fact.value["indisponiveis"]) >= {"roubo_carga", "roubo_veiculo"}
    assert "roubo_carga" not in fact.value["indicadores"], "vazio não vira zero"


async def test_crime_rate_is_derived_with_population_of_the_same_year():
    result = await adapter(FakeRepo(crimes=CRIMES)).run({"uf": "AL"})

    rate = patch(result, "taxa_criminalidade_uf_100mil")
    assert rate.status == "derivado"
    assert rate.value["roubo_total"] == {"ano": 2023, "taxa": 1250.0}
    assert rate.value["roubo_estabelecimento_comercial"] == {"ano": 2022, "taxa": 200.0}
    assert "valor / população × 100.000" in rate.evidence


async def test_caveated_years_are_never_used_as_reference():
    only_2020 = [c(2020, "roubo_total", 400, ressalva="só 1º semestre"), c(2020, "populacao", 1)]
    result = await adapter(FakeRepo(crimes=only_2020)).run({"uf": "AL"})
    assert all(p.key != "contexto_criminalidade_uf" for p in result.patches)
    assert unavailable(result, "contexto_criminalidade_uf").reason == "sem_dado_informado"


@pytest.mark.parametrize("facts", [{"uf": "AL"}, {"municipio_ibge": "123", "uf": "AL"}])
async def test_missing_or_invalid_municipality_still_gives_uf_crime_context(facts):
    result = await adapter(FakeRepo(crimes=CRIMES)).run(facts)
    assert unavailable(result, "historico_desastres_municipio").reason in {
        "municipio_ausente", "municipio_invalido",
    }  # fmt: skip
    assert patch(result, "contexto_criminalidade_uf")


async def test_uf_is_derived_from_a_valid_ibge_code():
    result = await adapter(FakeRepo(crimes=CRIMES)).run({"municipio_ibge": "2700102"})
    assert patch(result, "contexto_criminalidade_uf").value["uf"] == "AL"


async def test_source_down_degrades_without_raising_and_after_two_attempts():
    repo = FakeRepo(fail={"desastres", "crimes"})
    result = await adapter(repo).run(FACTS)

    assert result.status == "failed"
    assert result.patches == []
    assert {u.reason for u in result.unavailable} == {"fonte_indisponivel"}
    assert repo.calls.count("desastres") == 2


async def test_one_block_failing_keeps_the_other():
    repo = FakeRepo(desastres=[d(2003, "estiagem")], cobertura=COBERTURA, crimes=CRIMES,
                    fail={"crimes"})  # fmt: skip
    result = await adapter(repo).run(FACTS)
    assert result.status == "partial"
    assert patch(result, "historico_desastres_municipio")
    assert unavailable(result, "contexto_criminalidade_uf").reason == "fonte_indisponivel"


async def test_slow_source_times_out_instead_of_hanging():
    repo = FakeRepo(desastres=[d(2003, "estiagem")], delay=0.5)
    result = await adapter(repo, timeout=0.05).run({"municipio_ibge": "2700102"})
    assert result.status == "failed"


async def test_results_are_cached_and_failures_are_not():
    repo = FakeRepo(desastres=[d(2003, "estiagem")], cobertura=COBERTURA, crimes=CRIMES)
    ad = adapter(repo)
    await ad.run(FACTS)
    calls = len(repo.calls)
    await ad.run(FACTS)
    assert len(repo.calls) == calls, "segunda execução deve sair do cache"

    flaky = FakeRepo(desastres=[d(2003, "estiagem")], cobertura=COBERTURA,
                     fail={"desastres", "crimes"})  # fmt: skip
    ad2 = adapter(flaky)
    assert (await ad2.run({"municipio_ibge": "2700102"})).status == "failed"
    flaky.fail.clear()
    assert (await ad2.run({"municipio_ibge": "2700102"})).status == "done"


async def test_cache_entries_expire_after_ttl():
    now = [0.0]
    repo = FakeRepo(desastres=[d(2003, "estiagem")], cobertura=COBERTURA)
    ad = adapter(repo, ttl_s=10, clock=lambda: now[0])
    await ad.run({"municipio_ibge": "2700102"})
    calls = len(repo.calls)
    now[0] = 11
    await ad.run({"municipio_ibge": "2700102"})
    assert len(repo.calls) > calls


async def test_end_to_end_against_the_database(engine, pg_url, disasters_zip, crimes_xlsx):
    run_etl(engine, disasters_zip=disasters_zip, crimes_xlsx=crimes_xlsx)
    repo = SqlRepository(pg_url)
    try:
        result = await adapter(repo).run({"municipio_ibge": "2700102"})
    finally:
        await repo.aclose()

    municipal = patch(result, "historico_desastres_municipio")
    assert municipal.value["total_reconhecimentos"] == 1
    assert municipal.provenance.periodo == [2003, 2010]
    assert municipal.value["anos_sem_arquivo_na_uf"] == [2004, 2005, 2006, 2007, 2008, 2009, 2010]
    assert patch(result, "contexto_criminalidade_uf").value["uf"] == "AL"


async def test_flagged_crime_values_are_not_used_as_reference():
    rows = [
        c(2022, "roubo_total", 4869), c(2022, "populacao", 800_000),
        {**c(2023, "roubo_total", 45789), "qa_flags": ["atipico_vs_serie"]},
        c(2023, "populacao", 830_000),
    ]  # fmt: skip
    result = await adapter(FakeRepo(crimes=rows)).run({"uf": "AC"})

    fact = patch(result, "contexto_criminalidade_uf")
    assert fact.value["indicadores"]["roubo_total"] == {"ano": 2022, "valor": 4869}
    assert fact.value["alertas_ignorados"] == [
        {"indicador": "roubo_total", "ano": 2023, "alertas": ["atipico_vs_serie"]}
    ]
    assert patch(result, "taxa_criminalidade_uf_100mil").value["roubo_total"]["taxa"] == 608.6
