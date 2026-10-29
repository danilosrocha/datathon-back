"""Agentes de contexto: CEP do usuário → município (ViaCEP) e município → risco regional.
Proveniência obrigatória em cada fato; território só pelo código IBGE."""

from datetime import UTC, datetime

from langgraph.config import get_stream_writer

from app.agents.profiling.state import ProfileState
from app.domain.facts import Fact, FactSource, FactStatus
from app.enrichment.regional import EVIDENCE, SOURCES, regional_risk
from app.enrichment.territory import lookup_cep

TERRITORY_CONFIDENCE = 0.9
RISK_CONFIDENCE = 0.3


def _fact(
    key: str, value, status: FactStatus, source: str, confidence: float, evidence: str
) -> Fact:
    return Fact(
        key=key,
        value=value,
        status=status,
        source=FactSource(source),
        confidence=confidence,
        evidence=evidence,
        updated_at=datetime.now(UTC),
        updated_by=f"enriquecimento:{source}",
    )


async def enrich(state: ProfileState) -> dict:
    facts = state.get("facts", {})
    writer = get_stream_writer()
    new: dict[str, Fact] = {}

    def status(source: str, value: str, detail: str = "") -> None:
        writer({"event": "enrichment.status", "source": source, "status": value, "detail": detail})

    cep = facts.get("cep")
    # CEP da base comum é fictício: só o informado pelo usuário vira município.
    if (
        cep
        and cep.is_known
        and cep.source is not FactSource.BASE_COMUM
        and "municipio_ibge" not in facts
    ):
        status("api_territorio", "running")
        place = await lookup_cep(cep.value)
        if place:
            evidence = f"ViaCEP: {place['municipio']}/{place['uf']}"
            new["municipio_ibge"] = _fact(
                "municipio_ibge",
                place["municipio_ibge"],
                FactStatus.OBSERVADO,
                "api_territorio",
                TERRITORY_CONFIDENCE,
                evidence,
            )
            new["uf"] = _fact(
                "uf",
                place["uf"],
                FactStatus.OBSERVADO,
                "api_territorio",
                TERRITORY_CONFIDENCE,
                evidence,
            )
            status("api_territorio", "done", evidence)
        else:
            status("api_territorio", "failed", "CEP não encontrado ou serviço indisponível")

    municipio = new.get("municipio_ibge") or facts.get("municipio_ibge")
    uf = new.get("uf") or facts.get("uf")
    if municipio and not any(k in facts for k in SOURCES):
        risks = regional_risk(municipio.value, uf.value if uf else None)
        for key, level in sorted(risks.items()):
            source = SOURCES[key]
            new[key] = _fact(
                key, level, FactStatus.ESTIMADO, source, RISK_CONFIDENCE, EVIDENCE[source]
            )
        status("risco_regional", "done" if risks else "failed", f"{len(risks)} indicadores")

    return {"facts": new} if new else {}
