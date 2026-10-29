import sqlalchemy as sa

from app.etl.externo.cli import main


def args(disasters_zip, crimes_xlsx, url, *extra):
    return ["--disasters-zip", str(disasters_zip), "--crimes-xlsx", str(crimes_xlsx),
            "--database-url", url, *extra]  # fmt: skip


def test_cli_loads_and_reports_without_leaking_the_password(
    engine, pg_url, disasters_zip, crimes_xlsx, capsys
):
    code = main(args(disasters_zip, crimes_xlsx, pg_url))

    out = capsys.readouterr().out
    assert code == 0
    assert "defesa_civil_reconhecimentos" in out and "crimes_uf_compilacao" in out
    assert "inseridas=3" in out
    assert "postgres:postgres" not in out
    with engine.connect() as conn:
        assert (
            conn.execute(sa.text("SELECT count(*) FROM externo.desastre_reconhecimento")).scalar()
            == 3
        )


def test_cli_dry_run_parses_but_does_not_touch_the_database(
    engine, pg_url, disasters_zip, crimes_xlsx, capsys
):
    code = main(args(disasters_zip, crimes_xlsx, pg_url, "--dry-run"))

    assert code == 0
    assert "dry-run" in capsys.readouterr().out
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT to_regclass('externo.fonte')")).scalar() is None


def test_cli_missing_input_file_exits_with_error(pg_url, tmp_path, capsys):
    code = main(["--disasters-zip", str(tmp_path / "nao_existe.zip"), "--database-url", pg_url])
    assert code == 2
    assert "não encontrado" in capsys.readouterr().err


def test_cli_check_explains_target_and_access_mode(pg_url, capsys, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://abcdefghijklmnopqrst.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "sb_publishable_x")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        code = main(["--check", "--database-url", pg_url])
    finally:
        get_settings.cache_clear()

    out = capsys.readouterr().out
    assert code == 0
    assert "NÃO é o projeto Supabase abcdefghijklmnopqrst" in out
    assert "modo de leitura: rest" in out
    assert "sem privilégio" in out
