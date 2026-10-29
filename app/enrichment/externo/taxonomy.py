"""Normalização compartilhada entre o ETL e o adaptador de dados externos."""

import re
import unicodedata

UF_BY_IBGE_PREFIX = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}  # fmt: skip
UFS = frozenset(UF_BY_IBGE_PREFIX.values())

UF_BY_NAME = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA",
    "ceara": "CE", "distrito federal": "DF", "espirito santo": "ES", "goias": "GO",
    "maranhao": "MA", "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI",
    "rio de janeiro": "RJ", "rio grande do norte": "RN", "rio grande do sul": "RS",
    "rondonia": "RO", "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP",
    "sergipe": "SE", "tocantins": "TO",
}  # fmt: skip

_FOOTNOTE = re.compile(r"[¹²³⁴⁵⁶⁷⁸⁹⁰*]+")
_SPACES = re.compile(r"\s+")


def fold(text: str) -> str:
    """Minúsculas, sem acentos e com espaços colapsados (para comparação)."""
    ascii_text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return _SPACES.sub(" ", ascii_text.lower()).strip()


def clean_label(raw: str) -> str:
    """Remove marcas de nota de rodapé e espaços extras, preservando o texto original."""
    return _SPACES.sub(" ", _FOOTNOTE.sub("", str(raw))).strip()


# Ordem importa: o primeiro padrão que casar vence.
_TIPO_PATTERNS: list[tuple[str, str]] = [
    (r"vendaval|ventos? costeiros?", "vendaval"),
    (r"granizo", "granizo"),
    (r"chuvas? intensas?", "chuvas_intensas"),
    (r"enxurrada", "enxurrada"),
    (r"alagamento", "alagamento"),
    (r"inundac|enchente", "inundacao"),
    (r"estiagem|seca", "estiagem"),
    (r"deslizamento|corrida de massa", "deslizamento"),
    (r"erosao", "erosao"),
    (r"incendio", "incendio"),
    (r"geada", "geada"),
    (r"tornado", "tornado"),
    (r"ciclone|mares? de tempestade|ressaca", "ciclone_ressaca"),
    (r"frentes? frias?", "frente_fria"),
]


def normalize_tipo_evento(raw: str | None) -> str:
    """Agrupa o rótulo livre da fonte em um tipo canônico; o rótulo original é guardado à parte."""
    label = fold(clean_label(raw or ""))
    if label in {"", "desastres"}:
        return "nao_informado"
    for pattern, tipo in _TIPO_PATTERNS:
        if re.search(pattern, label):
            return tipo
    return "outros"


def uf_from_ibge(code: str) -> str | None:
    return UF_BY_IBGE_PREFIX.get(str(code)[:2])


def is_valid_ibge(code: str) -> bool:
    """Código de município IBGE: 7 dígitos, prefixo de UF existente e dígito verificador correto."""
    code = str(code)
    if not re.fullmatch(r"\d{7}", code) or uf_from_ibge(code) is None:
        return False
    total = 0
    for digit, weight in zip(code[:6], (1, 2, 1, 2, 1, 2), strict=True):
        product = int(digit) * weight
        total += product - 9 if product > 9 else product
    return (10 - total % 10) % 10 == int(code[6])


def parse_br_int(raw: object) -> tuple[int | None, str]:
    """Interpreta contagens vindas de planilha. Devolve (valor, situação).

    Células vazias e marcadores como "..." nunca viram zero.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, "em_branco"
    if isinstance(raw, bool):
        return None, "invalido"
    if isinstance(raw, int | float):
        return (int(raw), "informado") if float(raw).is_integer() else (None, "invalido")
    text = str(raw).strip()
    if text in {"...", "…", "-", "--"}:
        return None, "nao_disponivel"
    if re.fullmatch(r"\d{1,3}(\.\d{3})+|\d+", text):
        return int(text.replace(".", "")), "informado"
    return None, "invalido"
