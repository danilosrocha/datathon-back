import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.batch.run import run
from app.engine.catalog import default_catalog

BASE = Path(__file__).parents[1] / "fixtures" / "base_comum"
AS_OF = datetime(2026, 10, 28, tzinfo=UTC)
OFFICIAL_FIXED = {
    "INCENDIO_RAIO_EXPLOSAO_FUMACA",
    "DANOS_ELETRICOS",
    "PERDA_PAGAMENTO_ALUGUEL",
    "RESPONSABILIDADE_CIVIL_ESTABELECIMENTO",
    "DESPESAS_FIXAS",
    "PROTECAO_CIBERNETICA",
}
SPECIFIC = {
    "HOME_OFFICE",
    "DELIVERY",
    "DETERIORACAO_MERCADORIAS_FRIGORIFICADAS",
    "ROUBO_FURTO_VALORES",
}


def read(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


@pytest.fixture(scope="module")
def output(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    metrics = run(BASE, out, AS_OF)
    return out, metrics


def test_headers_match_official_templates(output) -> None:
    out, _ = output
    for name in ("template_resultado_times.csv", "template_coberturas_times.csv"):
        official, _ = read(BASE / name)
        produced, _ = read(out / name)
        assert produced == official


def test_every_case_in_result(output) -> None:
    out, _ = output
    _, expected = read(BASE / "template_resultado_times.csv")
    _, produced = read(out / "template_resultado_times.csv")
    assert [(r["empresa_id"], r["imovel_id"]) for r in produced] == [
        (r["empresa_id"], r["imovel_id"]) for r in expected
    ]
    assert all(r["elegivel"] in ("SIM", "SIM_SUJEITO_A_CONFIRMACAO", "NAO") for r in produced)


def test_six_fixed_per_eligible_case_and_no_assistance(output) -> None:
    out, _ = output
    _, results = read(out / "template_resultado_times.csv")
    _, coverages = read(out / "template_coberturas_times.csv")
    assistances = {a for p in default_catalog().plans.values() for a in p.assistencias}
    for r in results:
        rows = [c for c in coverages if c["imovel_id"] == r["imovel_id"]]
        codes = {c["cobertura"] for c in rows}
        if r["elegivel"] == "NAO":
            assert rows == []  # L-04
            assert r["motivo_inelegibilidade"]
        else:
            assert codes >= OFFICIAL_FIXED
            assert not codes & assistances


def test_ranges_are_digits_and_ordered(output) -> None:
    out, _ = output
    _, coverages = read(out / "template_coberturas_times.csv")
    for c in coverages:
        assert re.fullmatch(r"\d+", c["faixa_valor_min"]) and re.fullmatch(
            r"\d+", c["faixa_valor_max"]
        )
        assert int(c["faixa_valor_min"]) <= int(c["faixa_valor_max"])
        assert c["regra_calculo_utilizada"].startswith("EST-")


def test_no_specific_coverage_in_essential(output) -> None:
    out, _ = output
    _, results = read(out / "template_resultado_times.csv")
    _, coverages = read(out / "template_coberturas_times.csv")
    plans = {r["imovel_id"]: r["plano_recomendado"] for r in results}
    for c in coverages:
        if plans[c["imovel_id"]] == "ESSENCIAL":
            assert c["cobertura"] not in SPECIFIC


def test_ineligible_case_in_construction(output) -> None:
    out, _ = output
    _, results = read(out / "template_resultado_times.csv")
    blocked = [r for r in results if r["elegivel"] == "NAO"]
    assert blocked and all("ELG-004" in r["motivo_inelegibilidade"] for r in blocked)


def test_metrics_complete(output) -> None:
    out, metrics = output
    expected = {
        "casos_total",
        "pct_processados",
        "taxa_falhas",
        "tempo_execucao_s",
        "pct_com_justificativa",
        "violacoes_elegibilidade",
        "pct_coberturas_fixas_completas",
        "inconsistencias_plano_coberturas",
        "pct_coberturas_sem_faixa",
        "media_perguntas_confirmacao",
        "pct_confianca_baixa",
        "estabilidade",
        "consistencia_casos_semelhantes",
        "sensibilidade_faixas",
        "hash_reprodutibilidade",
    }
    saved = json.loads((out / "metricas.json").read_text(encoding="utf-8"))
    assert expected <= set(saved)
    assert saved["pct_processados"] == 1.0
    assert saved["violacoes_elegibilidade"] == 0
    assert saved["pct_coberturas_fixas_completas"] == 1.0
    assert saved["inconsistencias_plano_coberturas"] == 0
    assert saved == metrics | {"tempo_execucao_s": saved["tempo_execucao_s"]}


def test_trace_has_provenance(output) -> None:
    out, _ = output
    lines = (out / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    for fact in first["facts"].values():
        assert fact["status"] and fact["source"]
    assert first["decision"]["versions"]["rules"]
    if first["decision"]["offers"]:
        assert first["decision"]["offers"][0]["quote_prefill"]


def test_territory_only_by_municipality(output) -> None:
    out, _ = output
    first = json.loads((out / "trace.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert "cep" not in first["facts"]  # CEP e coordenadas da base são fictícios
    risks = [f for k, f in first["facts"].items() if k.startswith("risco_")]
    assert risks and all(f["status"] == "estimado" for f in risks)


def test_reproducible(tmp_path) -> None:
    a = run(BASE, tmp_path / "a", AS_OF)["hash_reprodutibilidade"]
    b = run(BASE, tmp_path / "b", AS_OF)["hash_reprodutibilidade"]
    assert a == b
