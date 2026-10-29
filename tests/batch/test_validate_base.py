import shutil
from pathlib import Path

import pandas as pd

from app.batch.validate_base import validate

BASE = Path(__file__).parents[1] / "fixtures" / "base_comum"


def _copy(tmp_path: Path) -> Path:
    shutil.copytree(BASE, tmp_path, dirs_exist_ok=True)
    return tmp_path


def _edit(path: Path, column: str, value) -> None:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    df.loc[0, column] = value
    df.to_csv(path, index=False, encoding="utf-8-sig")


def test_fixture_base_is_valid() -> None:
    report = validate(BASE)
    assert report.ok, report.errors
    assert report.stats["template_resultado_times.csv"] == 7


def test_missing_column_is_an_error(tmp_path) -> None:
    base = _copy(tmp_path)
    df = pd.read_csv(base / "empresas.csv", encoding="utf-8-sig").drop(columns=["cnae_principal"])
    df.to_csv(base / "empresas.csv", index=False, encoding="utf-8-sig")
    assert any("cnae_principal" in e for e in validate(base).errors)


def test_domain_probability_and_format_errors(tmp_path) -> None:
    base = _copy(tmp_path)
    _edit(base / "enderecos_estabelecimentos.csv", "situacao_imovel_cadastral", "DEMOLIDO")
    _edit(
        base / "sinais_financeiros_operacionais.csv", "probabilidade_refrigeracao_referencia", "1.7"
    )
    _edit(base / "empresas.csv", "cnae_principal", "47717")
    errors = " | ".join(validate(base).errors)
    assert "DEMOLIDO" in errors
    assert "probabilidade_refrigeracao_referencia" in errors
    assert "0000-0/00" in errors


def test_template_case_without_establishment(tmp_path) -> None:
    base = _copy(tmp_path)
    _edit(base / "template_resultado_times.csv", "imovel_id", "IMO_INEXISTENTE")
    assert any("sem registro" in e for e in validate(base).errors)
