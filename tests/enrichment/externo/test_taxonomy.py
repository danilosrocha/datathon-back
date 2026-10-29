import pytest

from app.enrichment.externo.taxonomy import (
    clean_label,
    is_valid_ibge,
    normalize_tipo_evento,
    parse_br_int,
    uf_from_ibge,
)


@pytest.mark.parametrize(
    ("raw", "tipo"),
    [
        ("VENDAVAL", "vendaval"),
        ("TEMPESTADE LOCAL/CONVECTIVA - VENDAVAL", "vendaval"),
        ("VENDAVAL MUITO INTENSO", "vendaval"),
        ("GRANIZOS", "granizo"),
        ("TEMPESTADE LOCAL/CONVECTIVA - GRANIZO", "granizo"),
        ("TEMPESTADE LOCAL/CONVECTIVA - CHUVAS INTENSAS", "chuvas_intensas"),
        ("INUNDAÇÕES", "inundacao"),
        ("ENCHENTES", "inundacao"),
        ("ENXURRADAS", "enxurrada"),
        ("ALAGAMENTOS", "alagamento"),
        ("SECA", "estiagem"),
        ("ESTIAGEM", "estiagem"),
        ("INCÊNDIOS EM ÁREAS PROTEGIDAS¹", "incendio"),
        ("DESLIZAMENTOS DE SOLO E/OU ROCHA", "deslizamento"),
        ("EROSÃO MARINHA", "erosao"),
        ("TORNADOS¹", "tornado"),
        ("TREMOR DE TERRA", "outros"),
        ("", "nao_informado"),
        ("DESASTRES", "nao_informado"),
    ],
)
def test_normalize_tipo_evento(raw, tipo):
    assert normalize_tipo_evento(raw) == tipo


def test_clean_label_removes_footnote_markers_and_extra_spaces():
    assert clean_label("  GEADA¹ ") == "GEADA"
    assert clean_label("FRENTES  FRIAS") == "FRENTES FRIAS"


@pytest.mark.parametrize("code", ["3550308", "2700102", "1300029", "4314902"])
def test_valid_ibge_codes(code):
    assert is_valid_ibge(code)


@pytest.mark.parametrize("code", ["3550309", "355030", "abc", "", "35503080", "0000000"])
def test_invalid_ibge_codes(code):
    assert not is_valid_ibge(code)


def test_uf_from_ibge():
    assert uf_from_ibge("3550308") == "SP"
    assert uf_from_ibge("2700102") == "AL"
    assert uf_from_ibge("9900000") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(1914, 1914), (1914.0, 1914), ("1.914", 1914), (" 12.388 ", 12388), ("640", 640)],
)
def test_parse_br_int_values(raw, expected):
    assert parse_br_int(raw) == (expected, "informado")


@pytest.mark.parametrize(
    ("raw", "situacao"),
    [(None, "em_branco"), ("", "em_branco"), ("...", "nao_disponivel"), ("…", "nao_disponivel")],
)
def test_parse_br_int_missing_markers_are_not_zero(raw, situacao):
    assert parse_br_int(raw) == (None, situacao)


def test_parse_br_int_rejects_garbage():
    assert parse_br_int("abc") == (None, "invalido")
