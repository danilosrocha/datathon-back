"""Risco regional por município (data/risco_municipio.csv) e roubo por UF (data/risco_uf.csv).
Sempre `estimado`; nunca decide elegibilidade. Município fora da tabela: sem risco climático."""

import csv
from functools import cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
CLIMATE_KEYS = ("risco_vendaval_regiao", "risco_granizo_regiao", "risco_alagamento_regiao")
SOURCES = {
    "risco_vendaval_regiao": "api_desastres",
    "risco_granizo_regiao": "api_desastres",
    "risco_alagamento_regiao": "api_desastres",
    "risco_roubo_regiao": "api_seguranca",
}
EVIDENCE = {
    "api_desastres": "Atlas Digital de Desastres 2003–2016, nível município",
    "api_seguranca": "Roubos por 100 mil hab. 2018–2023, nível UF",
}


@cache
def _table(name: str, key: str) -> dict[str, dict]:
    path = DATA / name
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {row[key]: row for row in csv.DictReader(f)}


def regional_risk(municipio_ibge: str, uf: str | None) -> dict[str, str]:
    """{chave de risco: nível}."""
    risks = {}
    place = _table("risco_municipio.csv", "municipio_ibge").get(municipio_ibge)
    if place:
        risks |= {k: place[k] for k in CLIMATE_KEYS if place.get(k)}
        uf = uf or place.get("uf")
    state = _table("risco_uf.csv", "uf").get(uf or "")
    if state and state.get("risco_roubo_regiao"):
        risks["risco_roubo_regiao"] = state["risco_roubo_regiao"]
    return risks
