"""Treino do context graph a partir da base de exploração (ARQUITETURA §4.3, cold start).

1. Valida o formato da base (app/batch/validate_base.py); erro de formato interrompe o treino.
2. Calcula α/β de atividade → característica por subclasse CNAE e por divisão (seed_priors).
3. Grava app/graph/ontology/priors_base.yaml (versionado no git; o lote usa este arquivo).
4. Com DATABASE_URL, publica uma nova kg_version "treino" no Postgres (não sobrescreve as
   anteriores) — a API passa a usá-la no próximo start.

Uso: uv run python -m app.graph.train --input data/Seguro_Empresarial_Desenvolvimento [--no-db]
"""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from app.batch.validate_base import validate
from app.graph.reasoner import probability
from app.graph.seed_priors import ONTOLOGY_DIR, compute, write_priors
from app.graph.store import load_snapshot


def summary(priors: list[dict]) -> dict:
    divisions = sorted({p["atividade"] for p in priors if len(p["atividade"]) == len("CNAE:00")})
    snapshot = load_snapshot()
    keys = sorted({p["caracteristica"] for p in priors})
    table = {
        division.removeprefix("CNAE:"): {
            k: round(probability(snapshot, division.removeprefix("CNAE:") + "00", k) or 0, 2)
            for k in keys
        }
        for division in divisions
    }
    return {"priors": len(priors), "caracteristicas": keys, "p_por_divisao": table}


async def publish(note: str) -> int:
    from app.db.repositories import graph as graph_repo
    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as session, session.begin():
        return await graph_repo.publish_trained(session, load_snapshot(), note, datetime.now(UTC))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ONTOLOGY_DIR / "priors_base.yaml")
    parser.add_argument("--no-db", action="store_true", help="só gera o YAML")
    args = parser.parse_args()

    report = validate(args.input)
    for warning in report.warnings:
        print(f"aviso: {warning}")
    if not report.ok:
        raise SystemExit("base fora do formato esperado:\n- " + "\n- ".join(report.errors))

    priors = compute(args.input)
    write_priors(priors, args.out)
    info = summary(priors)
    print(f"{info['priors']} priors → {args.out}")
    for division, probs in info["p_por_divisao"].items():
        print(f"  divisão {division}: " + ", ".join(f"{k}={v}" for k, v in probs.items()))
    if not args.no_db:
        version = asyncio.run(
            publish(f"{args.input.name} ({report.stats['template_resultado_times.csv']} casos)")
        )
        print(f"kg_version {version} publicada no banco")


if __name__ == "__main__":
    main()
