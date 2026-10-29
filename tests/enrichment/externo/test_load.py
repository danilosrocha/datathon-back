import sqlalchemy as sa

from app.etl.externo.load import run_etl


def count(engine, table, where="true"):
    with engine.connect() as conn:
        return conn.execute(sa.text(f"SELECT count(*) FROM externo.{table} WHERE {where}")).scalar()


def test_first_load_inserts_every_record(engine, disasters_zip, crimes_xlsx):
    reports = run_etl(engine, disasters_zip=disasters_zip, crimes_xlsx=crimes_xlsx)

    by_source = {r.fonte_id: r for r in reports}
    assert by_source["defesa_civil_reconhecimentos"].inseridas == 3
    assert by_source["crimes_uf_compilacao"].inseridas == 12
    assert count(engine, "desastre_reconhecimento") == 3
    assert count(engine, "crime_uf_indicador") == 12


def test_second_run_changes_nothing(engine, disasters_zip, crimes_xlsx):
    run_etl(engine, disasters_zip=disasters_zip, crimes_xlsx=crimes_xlsx)
    with engine.connect() as conn:
        before = conn.execute(
            sa.text("SELECT max(atualizado_em) FROM externo.desastre_reconhecimento")
        ).scalar()

    reports = run_etl(engine, disasters_zip=disasters_zip, crimes_xlsx=crimes_xlsx)

    for report in reports:
        assert report.inseridas == 0
        assert report.atualizadas == 0
        assert report.removidas == 0
        assert report.inalteradas == report.lidas
    assert count(engine, "desastre_reconhecimento") == 3
    assert count(engine, "crime_uf_indicador") == 12
    with engine.connect() as conn:
        after = conn.execute(
            sa.text("SELECT max(atualizado_em) FROM externo.desastre_reconhecimento")
        ).scalar()
    assert after == before, "linhas iguais não devem ser reescritas"


def test_changed_value_is_updated_in_place(engine, tmp_path, crimes_xlsx):
    from conftest import AL_ROW, make_zip
    from xls_builders import layout_2003

    first = make_zip(tmp_path / "a.zip", {"2003/AL.xls": layout_2003([AL_ROW], total=1)})
    run_etl(engine, disasters_zip=first)
    changed = list(AL_ROW)
    changed[6] = "GRANIZO"
    second = make_zip(tmp_path / "b.zip", {"2003/AL.xls": layout_2003([changed], total=1)})

    (report,) = run_etl(engine, disasters_zip=second)

    assert (report.inseridas, report.atualizadas, report.inalteradas) == (0, 1, 0)
    assert count(engine, "desastre_reconhecimento") == 1
    assert count(engine, "desastre_reconhecimento", "tipo_evento = 'granizo'") == 1


def test_rows_dropped_from_a_republished_file_are_removed(engine, tmp_path):
    from conftest import AL_ROW, AL_ROW2, make_zip
    from xls_builders import layout_2003

    run_etl(
        engine,
        disasters_zip=make_zip(tmp_path / "a.zip", {"2003/AL.xls": layout_2003([AL_ROW, AL_ROW2])}),
    )
    (report,) = run_etl(
        engine, disasters_zip=make_zip(tmp_path / "b.zip", {"2003/AL.xls": layout_2003([AL_ROW])})
    )
    assert report.removidas == 1
    assert count(engine, "desastre_reconhecimento") == 1


def test_missing_files_are_recorded_as_unknown_not_zero(engine, disasters_zip):
    run_etl(engine, disasters_zip=disasters_zip)

    with engine.connect() as conn:
        rows = {
            (r.uf, r.ano): r
            for r in conn.execute(sa.text("SELECT * FROM externo.desastre_cobertura"))
        }
    assert rows[("AL", 2003)].arquivo_presente is True
    assert rows[("AL", 2003)].registros_lidos == 2
    assert rows[("SP", 2003)].arquivo_presente is False
    assert rows[("SP", 2003)].registros_lidos is None
    assert len(rows) == 27 * 8  # 27 UFs × anos 2003..2010


def test_declared_total_divergence_is_flagged(engine, tmp_path):
    from conftest import AL_ROW, make_zip
    from xls_builders import layout_2003

    zip_path = make_zip(tmp_path / "a.zip", {"2003/AL.xls": layout_2003([AL_ROW], total=9)})
    run_etl(engine, disasters_zip=zip_path)
    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT * FROM externo.desastre_cobertura WHERE uf='AL' AND ano=2003")
        ).one()
    assert (row.total_declarado, row.registros_lidos, row.divergencia_total) == (9, 1, True)


def test_rejections_are_replaced_on_each_run(engine, tmp_path):
    from conftest import AL_ROW, make_zip
    from xls_builders import layout_2003

    zip_path = make_zip(
        tmp_path / "a.zip", {"2003/AL.xls": layout_2003([AL_ROW, ["¹ nota solta"]], total=1)}
    )
    run_etl(engine, disasters_zip=zip_path)
    run_etl(engine, disasters_zip=zip_path)
    assert count(engine, "etl_rejeicao") == 1


def test_provenance_is_recorded(engine, disasters_zip, crimes_xlsx):
    run_etl(engine, disasters_zip=disasters_zip, crimes_xlsx=crimes_xlsx)
    with engine.connect() as conn:
        fontes = {r.id: r for r in conn.execute(sa.text("SELECT * FROM externo.fonte"))}
    s2id = fontes["defesa_civil_reconhecimentos"]
    assert (s2id.periodo_inicio, s2id.periodo_fim) == (2003, 2010)
    assert len(s2id.sha256) == 64
    assert s2id.ultima_carga_em is not None
    assert "ausência" in s2id.limitacoes.lower()
    crimes = fontes["crimes_uf_compilacao"]
    assert (crimes.periodo_inicio, crimes.periodo_fim) == (2022, 2023)
    assert crimes.granularidade.startswith("UF")
    assert count(engine, "etl_execucao") == 2


def test_indexes_support_uf_municipio_ano_and_event_type_lookups(engine, disasters_zip):
    run_etl(engine, disasters_zip=disasters_zip)
    with engine.connect() as conn:
        defs = " ".join(
            conn.execute(
                sa.text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'externo'")
            ).scalars()
        )
    for expected in ("(uf, ano)", "(cod_ibge, ano)", "(tipo_evento, ano)", "(uf, tipo_evento)"):
        assert expected in defs


def test_crime_anomalies_are_flagged_in_the_database(engine, tmp_path):
    from conftest import crimes_workbook

    values = [4800, 5000, 5200, 4900, 5100, 5300, 45789]
    rows = [["Acre", 2016 + i, 100, v, None, 800_000] for i, v in enumerate(values)]
    path = tmp_path / "crimes.xlsx"
    path.write_bytes(crimes_workbook(rows).getvalue())

    run_etl(engine, crimes_xlsx=path)

    with engine.connect() as conn:
        flagged = conn.execute(
            sa.text(
                "SELECT ano, qa_flags FROM externo.crime_uf_indicador "
                "WHERE indicador = 'roubo_total' AND cardinality(qa_flags) > 0"
            )
        ).all()
    assert [(r.ano, r.qa_flags) for r in flagged] == [(2022, ["atipico_vs_serie"])]


def test_ensure_schema_upgrades_a_table_created_before_qa_flags(engine):
    from app.enrichment.externo.tables import ensure_schema

    with engine.begin() as conn:
        conn.execute(sa.text("CREATE SCHEMA externo"))
        conn.execute(
            sa.text(
                "CREATE TABLE externo.crime_uf_indicador (uf char(2), ano smallint, "
                "indicador text, valor bigint, situacao text, valor_bruto text, ressalva text, "
                "aba_origem text, linha_origem int, atualizado_em timestamptz default now(), "
                "PRIMARY KEY (uf, ano, indicador))"
            )
        )

    ensure_schema(engine)
    ensure_schema(engine)  # idempotente

    with engine.connect() as conn:
        cols = conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='externo' AND table_name='crime_uf_indicador'"
            )
        ).scalars()
        assert "qa_flags" in set(cols)
