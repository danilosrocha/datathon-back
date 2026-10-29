"""Cold start do context graph (ARQUITETURA §4.3): α/β de atividade → característica calculados a
partir da base de exploração. Grava app/graph/ontology/priors_base.yaml.

Peso de cada caso: fato `observado`/`confirmado` conta 1,0; `derivado`/`estimado` conta 0,3.
α = 1 + Σ pesos verdadeiros, β = 1 + Σ pesos falsos. Gera por subclasse CNAE e por divisão
(para o back-off quando a subclasse tem pouca evidência).

Uso: uv run python -m app.graph.seed_priors --input <pasta da base>
"""

import argparse
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.batch.loader import load_cases
from app.domain.facts import FactStatus
from app.graph.store import ONTOLOGY_DIR

# Características que a base só registra quando existem (bem cadastrado). Para a estatística, e só
# para ela, a ausência conta como "não" com peso fraco; nas decisões, ausência segue DESCONHECIDO.
ONE_SIDED = {"maquinas_equipamentos": 0.3, "eletronicos_relevantes": 0.3, "letreiro_luminoso": 0.3}
WEIGHTS = {
    FactStatus.CONFIRMADO: 1.0,
    FactStatus.OBSERVADO: 1.0,
    FactStatus.DERIVADO: 0.3,
    FactStatus.ESTIMADO: 0.3,
}


def characteristic_keys() -> list[str]:
    raw = yaml.safe_load((ONTOLOGY_DIR / "caracteristicas.yaml").read_text(encoding="utf-8"))
    return sorted(c["fact_key"] for c in raw)


def compute(base: Path) -> list[dict]:
    keys = characteristic_keys()
    counts: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for case in load_cases(base, datetime(2026, 10, 28, tzinfo=UTC)):
        cnae = case.facts["cnae_principal"].value
        for key in keys:
            fact = case.facts.get(key)
            if fact is not None and isinstance(fact.value, bool):
                value, weight = fact.value, WEIGHTS[fact.status]
            elif fact is None and key in ONE_SIDED:
                value, weight = False, ONE_SIDED[key]
            else:
                continue
            for node in (f"CNAE:{cnae}", f"CNAE:{cnae[:2]}"):
                counts[(node, key)][0 if value else 1] += weight
    return [
        {
            "atividade": node,
            "caracteristica": key,
            "alpha": round(1 + trues, 2),
            "beta": round(1 + falses, 2),
        }
        for (node, key), (trues, falses) in sorted(counts.items())
    ]


def write_priors(priors: list[dict], out: Path) -> None:
    header = (
        "# Gerado por app/graph/seed_priors.py a partir da base de exploração — não editar à mão.\n"
        "# Peso: observado 1,0; derivado/estimado 0,3. α = 1 + verdadeiros, β = 1 + falsos.\n"
        "# Bens só registrados quando existem (máquinas, eletrônicos, letreiro): ausência = 'não'\n"
        "# com peso 0,3, só para a estatística.\n"
    )
    body = "\n".join(
        f'- {{ atividade: "{p["atividade"]}", caracteristica: {p["caracteristica"]}, '
        f"alpha: {p['alpha']}, beta: {p['beta']} }}"
        for p in priors
    )
    out.write_text(header + body + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ONTOLOGY_DIR / "priors_base.yaml")
    args = parser.parse_args()
    priors = compute(args.input)
    write_priors(priors, args.out)
    print(f"{len(priors)} priors → {args.out}")


if __name__ == "__main__":
    main()
