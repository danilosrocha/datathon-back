"""CEP → município (ViaCEP). Só para CEP informado pelo usuário: o da base comum é fictício.

DEMO_MODE=true lê respostas gravadas em data/fixtures/api (sem rede). Timeout curto, duas
tentativas e cache em memória; falha não trava o turno (o caso segue sem o fato)."""

import json
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from app.config import get_settings

VIACEP_URL = "https://viacep.com.br/ws/{cep}/json/"
FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "api"
_cache: dict[str, dict | None] = {}


@retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    stop=stop_after_attempt(2),
    wait=wait_fixed(0.2),
    reraise=True,
)
async def _fetch(cep: str) -> dict | None:
    async with httpx.AsyncClient(timeout=get_settings().enrichment_timeout_s) as client:
        response = await client.get(VIACEP_URL.format(cep=cep))
        response.raise_for_status()
        body = response.json()
    return None if body.get("erro") else body


async def lookup_cep(cep: str) -> dict | None:
    """{municipio_ibge, uf, municipio} ou None (CEP inexistente, sem rede ou sem fixture)."""
    cep = "".join(ch for ch in cep if ch.isdigit())
    if cep in _cache:
        return _cache[cep]
    if get_settings().demo_mode:
        path = FIXTURES / f"viacep_{cep}.json"
        body = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    else:
        try:
            body = await _fetch(cep)
        except httpx.HTTPError:
            return None  # não cacheia falha de rede
    result = (
        {"municipio_ibge": body["ibge"], "uf": body["uf"], "municipio": body["localidade"]}
        if body and body.get("ibge")
        else None
    )
    _cache[cep] = result
    return result
