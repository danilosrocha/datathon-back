"""Adaptador de contexto territorial: desastres históricos do município e crimes da UF.

Princípios (docs/DADOS_EXTERNOS.md):
- O que a fonte registra é `observado`; taxas calculadas são `derivado`.
- Ausência de registro nunca é zero: vira `Unavailable`.
- Histórico é contexto, não risco atual; quem converte em `risco_*_regiao` é outra camada.
- Falha da fonte degrada (resultado `failed`/`partial`), sem levantar exceção.
"""

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.enrichment.base import (
    EnrichmentResult,
    FactPatch,
    Provenance,
    TTLCache,
    Unavailable,
)
from app.enrichment.externo.repository import ExternalDataRepository, ExternalDataUnavailable
from app.enrichment.externo.taxonomy import UFS, is_valid_ibge, uf_from_ibge

FONTE_DESASTRES = "defesa_civil_reconhecimentos"
FONTE_CRIMES = "crimes_uf_compilacao"

K_DESASTRES = "historico_desastres_municipio"
K_CRIMES = "contexto_criminalidade_uf"
K_TAXA = "taxa_criminalidade_uf_100mil"

INDICADORES_CRIME = (
    "roubo_total",
    "roubo_estabelecimento_comercial",
    "roubo_carga",
    "roubo_veiculo",
    "latrocinio",
    "homicidio_doloso",
)
CONF_OBSERVADO = 0.8  # fatores do CONTRATOS_API: observado 0,8 · derivado 0,7
CONF_DERIVADO = 0.7


class ExternalContextAdapter:
    name = "externo_territorio"
    triggers = {"municipio_ibge", "uf"}
    produces = {K_DESASTRES, K_CRIMES, K_TAXA}

    def __init__(
        self,
        repository: ExternalDataRepository,
        *,
        timeout: float = 5.0,
        attempts: int = 2,
        ttl_s: float = 30 * 24 * 3600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repo = repository
        self._timeout = timeout
        self._attempts = attempts
        self._cache = TTLCache(ttl_s, clock)

    async def _load[T](self, key: tuple, factory: Callable[[], Awaitable[T]]) -> T:
        async def with_retry() -> T:
            last: Exception | None = None
            for _ in range(self._attempts):
                try:
                    async with asyncio.timeout(self._timeout):
                        return await factory()
                except (ExternalDataUnavailable, TimeoutError) as exc:
                    last = exc
            raise ExternalDataUnavailable(str(last) or "tempo esgotado") from last

        return await self._cache.get_or_load(key, with_retry)

    async def _provenance(self, fonte_id: str, periodo: list[int] | None = None) -> Provenance:
        fontes = await self._load(("fontes", fonte_id), lambda: self._repo.fontes([fonte_id]))
        f = fontes.get(fonte_id)
        if f is None:
            raise ExternalDataUnavailable(f"fonte {fonte_id} sem registro de proveniência")
        if periodo is None and f.get("periodo_inicio") and f.get("periodo_fim"):
            periodo = [f["periodo_inicio"], f["periodo_fim"]]
        return Provenance(
            fonte=f["nome"], fonte_id=fonte_id, granularidade=f["granularidade"],
            periodo=periodo, atualizado_em=f.get("ultima_carga_em"),
            limitacoes=f["limitacoes"], licenca=f["licenca"],
        )  # fmt: skip

    async def run(self, facts: Mapping[str, Any]) -> EnrichmentResult:
        cod = str(facts.get("municipio_ibge") or "").strip()
        valid = is_valid_ibge(cod)
        uf = uf_from_ibge(cod) if valid else str(facts.get("uf") or "").upper() or None
        if uf not in UFS:
            uf = None

        blocks = {
            K_DESASTRES: self._desastres(cod, uf) if valid else self._no_municipality(cod),
            K_CRIMES: self._crimes(uf) if uf else self._no_uf(),
        }
        outcomes = await asyncio.gather(*blocks.values(), return_exceptions=True)

        result = EnrichmentResult(adapter=self.name, status="done")
        failed = 0
        for key, outcome in zip(blocks, outcomes, strict=True):
            if isinstance(outcome, ExternalDataUnavailable):
                failed += 1
                result.unavailable.append(Unavailable(key, "fonte_indisponivel", str(outcome)))
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                result.patches += outcome[0]
                result.unavailable += outcome[1]
        if failed:
            result.status = "failed" if failed == len(blocks) else "partial"
            result.detail = "fonte de dados externos indisponível"
        return result

    # -- desastres -----------------------------------------------------------------------

    async def _no_municipality(self, cod: str):
        reason = "municipio_invalido" if cod else "municipio_ausente"
        return [], [Unavailable(K_DESASTRES, reason, "sem código IBGE de município válido")]

    async def _desastres(self, cod: str, uf: str):
        rows, coverage = await asyncio.gather(
            self._load(("desastres", cod), lambda: self._repo.desastres_municipio(cod)),
            self._load(("cobertura", uf), lambda: self._repo.cobertura_desastres(uf)),
        )
        if not rows:
            return [], [Unavailable(
                K_DESASTRES, "sem_registro_na_fonte",
                "A fonte lista só reconhecimentos federais de SE/ECP; a ausência de registro "
                "não indica ausência de eventos nem zero ocorrências.",
            )]  # fmt: skip

        por_tipo: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"reconhecimentos": 0, "anos": set(), "se": 0, "ecp": 0}
        )
        for r in rows:
            item = por_tipo[r["tipo_evento"]]
            item["reconhecimentos"] += 1
            item["anos"].add(r["ano"])
            if r.get("se_ecp") in ("SE", "ECP"):
                item[r["se_ecp"].lower()] += 1
        ordered = dict(sorted(por_tipo.items(), key=lambda kv: (-kv[1]["reconhecimentos"], kv[0])))
        for item in ordered.values():
            item["anos"] = sorted(item["anos"])

        missing = sorted(c["ano"] for c in coverage if not c["arquivo_presente"])
        provenance = await self._provenance(FONTE_DESASTRES)
        ini, fim = provenance.periodo or [min(r["ano"] for r in rows), max(r["ano"] for r in rows)]
        value = {
            "total_reconhecimentos": len(rows),
            "por_tipo": ordered,
            "anos_com_registro": sorted({r["ano"] for r in rows}),
            "periodo_fonte": [ini, fim],
            "anos_sem_arquivo_na_uf": missing,
            "cobertura_parcial": bool(missing),
        }
        evidence = (
            f"{len(rows)} reconhecimento(s) federal(is) de SE/ECP no município "
            f"entre {ini} e {fim}. "
            "Histórico de reconhecimentos oficiais: não equivale ao risco atual nem a um "
            "inventário de eventos."
        )
        patch = FactPatch(K_DESASTRES, value, "observado", "api_desastres", CONF_OBSERVADO,
                          evidence, provenance)  # fmt: skip
        return [patch], []

    # -- crimes --------------------------------------------------------------------------

    async def _no_uf(self):
        return [], [Unavailable(K_CRIMES, "uf_ausente", "sem UF válida para consultar")]

    async def _crimes(self, uf: str):
        indicadores = (*INDICADORES_CRIME, "populacao")
        rows = await self._load(("crimes", uf), lambda: self._repo.crimes_uf(uf, indicadores))

        informado = [r for r in rows if r["situacao"] == "informado" and r["valor"] is not None]
        populacao = {r["ano"]: r["valor"] for r in informado if r["indicador"] == "populacao"}
        ignorados = sorted({r["ano"] for r in informado if r.get("ressalva")})
        alertas = [
            {"indicador": r["indicador"], "ano": r["ano"], "alertas": r["qa_flags"]}
            for r in informado
            if r.get("qa_flags") and r["indicador"] in INDICADORES_CRIME
        ]

        latest: dict[str, dict[str, int]] = {}
        for ind in INDICADORES_CRIME:
            usable = [
                r
                for r in informado
                if r["indicador"] == ind and not r.get("ressalva") and not r.get("qa_flags")
            ]
            if usable:
                best = max(usable, key=lambda r: r["ano"])
                latest[ind] = {"ano": best["ano"], "valor": best["valor"]}
        if not latest:
            return [], [Unavailable(
                K_CRIMES, "sem_dado_informado",
                "Nenhum indicador com valor informado e sem ressalva para a UF.",
            )]  # fmt: skip

        provenance = await self._provenance(FONTE_CRIMES)
        context = FactPatch(
            K_CRIMES,
            {
                "nivel": "uf", "uf": uf, "indicadores": latest,
                "indisponiveis": [i for i in INDICADORES_CRIME if i not in latest],
                "anos_com_ressalva_ignorados": ignorados,
                "alertas_ignorados": alertas,
            },
            "observado", "api_seguranca", CONF_OBSERVADO,
            "Contagens por UF, no ano mais recente informado de cada indicador. Contexto estadual: "
            "não descreve o município nem o estabelecimento.",
            provenance,
        )  # fmt: skip

        taxas = {
            ind: {"ano": v["ano"], "taxa": round(v["valor"] / populacao[v["ano"]] * 100_000, 1)}
            for ind, v in latest.items()
            if populacao.get(v["ano"])
        }
        if not taxas:
            return [context], [Unavailable(K_TAXA, "sem_populacao", "População do ano ausente.")]
        rate = FactPatch(
            K_TAXA, taxas, "derivado", "api_seguranca", CONF_DERIVADO,
            "Taxa = valor / população × 100.000, com a população da UF no mesmo ano do indicador.",
            provenance,
        )  # fmt: skip
        return [context, rate], []
