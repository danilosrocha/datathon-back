"""Sinalização de anomalias nos indicadores de crime.

Não corrige nem remove dados: marca em `qa_flags` valores que a própria planilha contradiz
(ex.: o total de roubos menor que um de seus componentes) ou que destoam da série da UF. O
adaptador não usa valores sinalizados como referência.
"""

from collections import defaultdict
from statistics import median

from app.etl.externo.parse_crimes import CrimeRecord

MIN_SERIES = 4  # outros anos informados necessários para julgar um valor
MIN_MEDIAN = 20  # abaixo disso a contagem é ruidosa demais para julgar
RATIO = 5.0  # acima de 5× ou abaixo de 1/5 da mediana da própria série da UF
COMPONENTES_ROUBO = (
    "roubo_veiculo",
    "roubo_estabelecimento_comercial",
    "roubo_carga",
    "roubo_instituicao_financeira",
)


def _usable(r: CrimeRecord) -> bool:
    return r.situacao == "informado" and r.valor is not None


def flag_crime_anomalies(records: list[CrimeRecord]) -> None:
    by_series: dict[tuple[str, str], list[CrimeRecord]] = defaultdict(list)
    by_year: dict[tuple[str, int], dict[str, CrimeRecord]] = defaultdict(dict)
    for r in records:
        if _usable(r):
            by_series[(r.uf, r.indicador)].append(r)
            by_year[(r.uf, r.ano)][r.indicador] = r

    for series in by_series.values():
        reference = [r for r in series if not r.ressalva]
        for r in reference:
            others = [o.valor for o in reference if o is not r]
            if len(others) < MIN_SERIES:
                continue
            base = median(others)
            if base >= MIN_MEDIAN and (r.valor > RATIO * base or r.valor < base / RATIO):
                r.qa_flags.append("atipico_vs_serie")

    for indicators in by_year.values():
        total = indicators.get("roubo_total")
        if total is None:
            continue
        parts = [indicators[i].valor for i in COMPONENTES_ROUBO if i in indicators]
        if parts and total.valor < max(parts):
            total.qa_flags.append("total_menor_que_componente")
