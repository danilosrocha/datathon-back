import shutil

import pytest

from app.engine.catalog import CATALOG_DIR, CatalogError, load_catalog


def test_official_catalog_is_valid(catalog) -> None:
    fixas = [c for c in catalog.coverages.values() if c.grupo == "fixa"]
    assert len(fixas) == 6
    assert "PROTECAO_CIBERNETICA" in catalog.plans["ESSENCIAL"].fixas
    assert len(catalog.content_hash) == 64


def _broken_copy(tmp_path, file, old, new):
    shutil.copytree(CATALOG_DIR, tmp_path, dirs_exist_ok=True)
    path = tmp_path / file
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    return tmp_path


def test_unknown_fact_key_in_rule_fails(tmp_path) -> None:
    d = _broken_copy(tmp_path, "elegibilidade.yaml", "fato: imovel_em_obra", "fato: obra")
    with pytest.raises(CatalogError, match="ELG-004"):
        load_catalog(d)


def test_unknown_coverage_in_plan_fails(tmp_path) -> None:
    d = _broken_copy(
        tmp_path,
        "planos.yaml",
        "padrao: [ROUBO_FURTO_BENS, VENDAVAL_GRANIZO]\n",
        "padrao: [XPTO]\n",
    )
    with pytest.raises(CatalogError, match="XPTO"):
        load_catalog(d)


def test_coverage_without_estimate_rule_fails(tmp_path) -> None:
    d = _broken_copy(
        tmp_path, "estimativas.yaml", "cobertura: QUEBRA_VIDROS", "cobertura: RC_DANOS_MORAIS"
    )
    with pytest.raises(CatalogError, match="QUEBRA_VIDROS"):
        load_catalog(d)


def test_invalid_source_rule_fails(tmp_path) -> None:
    d = _broken_copy(
        tmp_path,
        "estimativas.yaml",
        "fato: exposicao_digital_nivel, linhas:",
        "fato: exposicao_digital_nivel, faixas:",
    )
    with pytest.raises(CatalogError, match="EST-CYB-01"):
        load_catalog(d)
