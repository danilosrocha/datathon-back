from app.etl.externo.parse_crimes import CrimeRecord
from app.etl.externo.quality import flag_crime_anomalies


def rec(uf, ano, indicador, valor, situacao="informado", ressalva=None):
    return CrimeRecord(uf, ano, indicador, valor, situacao, None if valor is None else str(valor),
                       ressalva, "dados completos", 2)  # fmt: skip


def series(indicador, values, uf="AC", start=2015):
    return [rec(uf, start + i, indicador, v) for i, v in enumerate(values)]


def flags(records):
    return {(r.uf, r.ano, r.indicador): r.qa_flags for r in records if r.qa_flags}


def test_value_far_from_the_ufs_own_series_is_flagged_as_atypical():
    records = series("roubo_total", [4800, 5000, 5200, 4900, 5100, 5300, 4869, 45789])
    flag_crime_anomalies(records)
    assert flags(records) == {("AC", 2022, "roubo_total"): ["atipico_vs_serie"]}


def test_sudden_collapse_is_flagged_too():
    records = series("roubo_total", [100_000, 105_000, 98_000, 102_000, 101_000, 2301])
    flag_crime_anomalies(records)
    assert list(flags(records)) == [("AC", 2020, "roubo_total")]


def test_normal_year_to_year_variation_is_not_flagged():
    records = series("roubo_total", [5000, 6500, 4200, 7000, 5500, 3900, 6100])
    flag_crime_anomalies(records)
    assert flags(records) == {}


def test_series_too_short_is_never_flagged():
    records = series("roubo_total", [100, 100, 100, 99999])
    flag_crime_anomalies(records)
    assert flags(records) == {}


def test_missing_values_are_ignored_by_the_series_and_never_flagged():
    values = [5000, 5100, 4900, 5200, 5050]
    records = series("roubo_total", values) + [rec("AC", 2021, "roubo_total", None, "em_branco")]
    flag_crime_anomalies(records)
    assert flags(records) == {}


def test_total_robbery_below_one_of_its_components_is_inconsistent():
    records = [
        rec("CE", 2023, "roubo_total", 7000),
        rec("CE", 2023, "roubo_veiculo", 7794),
        rec("CE", 2023, "roubo_estabelecimento_comercial", 2908),
        rec("CE", 2022, "roubo_total", 33916),
        rec("CE", 2022, "roubo_veiculo", 9000),
    ]
    flag_crime_anomalies(records)
    assert flags(records) == {("CE", 2023, "roubo_total"): ["total_menor_que_componente"]}


def test_caveated_years_do_not_distort_the_reference_series():
    records = series("roubo_total", [5000, 5100, 4900, 5200, 5050])
    records.append(rec("AC", 2020, "roubo_total", 2400, ressalva="1º semestre"))
    flag_crime_anomalies(records)
    assert flags(records) == {}, "valor parcial tem ressalva própria, não é anomalia"


def test_small_counts_are_too_noisy_to_call_atypical():
    records = series("latrocinio", [2, 3, 1, 4, 2, 3, 40])
    flag_crime_anomalies(records)
    assert flags(records) == {}
