"""Lote: base comum → 2 templates oficiais + trace.jsonl + metricas.json.

Uso: uv run python -m app.batch.run --input <pasta da base> --out-dir ../out/
Sem LLM e sem rede: justificativas e perguntas vêm de templates; risco regional de
data/risco_municipio.csv. Mesma entrada e mesmas versões → mesmo hash.
"""

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from app.batch import metrics, writers
from app.batch.loader import RISK_TABLE, load_cases
from app.engine.catalog import default_catalog
from app.engine.decide import decide
from app.graph.store import load_snapshot

# Data de referência fixa dos fatos do lote (reprodutibilidade).
DEFAULT_AS_OF = "2026-10-28"


def run(base: Path, out_dir: Path, as_of: datetime, risk_path: Path = RISK_TABLE) -> dict:
    started = time.perf_counter()
    catalog, graph = default_catalog(), load_snapshot()
    cases = load_cases(base, as_of, risk_path)

    decisions, result_rows, coverage_rows, trace = [], [], [], []
    for case in cases:
        try:
            decision = decide(case.facts, catalog, graph)
        except Exception as error:  # falha de um caso não derruba o lote; entra na taxa de falhas
            decisions.append(None)
            result_rows.append(
                {
                    **dict.fromkeys(writers.mapping()["colunas_resultado"], ""),
                    "empresa_id": case.empresa_id,
                    "imovel_id": case.imovel_id,
                    "elegivel": "ERRO",
                    "justificativa_recomendacao": f"Falha no processamento: {error}",
                }
            )
            continue
        decisions.append(decision)
        result_rows.append(writers.result_row(case, decision, catalog))
        coverage_rows += writers.coverage_rows(case, decision, catalog)
        trace.append(writers.trace_line(case, decision))

    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = writers.mapping()
    result_path = out_dir / writers.RESULT_TEMPLATE
    coverage_path = out_dir / writers.COVERAGE_TEMPLATE
    writers.write_csv(
        result_path,
        writers.read_header(base, writers.RESULT_TEMPLATE),
        cfg["colunas_resultado"],
        result_rows,
    )
    writers.write_csv(
        coverage_path,
        writers.read_header(base, writers.COVERAGE_TEMPLATE),
        cfg["colunas_coberturas"],
        coverage_rows,
    )
    (out_dir / "trace.jsonl").write_text("\n".join(trace) + "\n", encoding="utf-8")

    digest = hashlib.sha256()
    for path in (result_path, coverage_path, out_dir / "trace.jsonl"):
        digest.update(path.read_bytes())

    result = metrics.compute(
        cases,
        decisions,
        coverage_rows,
        result_rows,
        catalog,
        graph,
        time.perf_counter() - started,
        digest.hexdigest(),
    )
    (out_dir / "metricas.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Processamento em lote da base comum")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--as-of", default=DEFAULT_AS_OF, help="data de referência dos fatos (AAAA-MM-DD)"
    )
    parser.add_argument("--risk-table", type=Path, default=RISK_TABLE)
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of).replace(tzinfo=UTC)
    result = run(args.input, args.out_dir, as_of, args.risk_table)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
