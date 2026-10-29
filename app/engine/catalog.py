"""Catálogo oficial (backend/catalog/*.yaml): carga e validação. Erro aqui é bug de configuração."""

import hashlib
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from app.domain.fact_keys import get_fact_key
from app.engine.rules import COMBINATORS, OPERATORS, condition_keys

CATALOG_DIR = Path(__file__).resolve().parents[2] / "catalog"
FILES = (
    "coberturas",
    "planos",
    "elegibilidade",
    "recomendacao",
    "estimativas",
    "perguntas",
    "atividade_formulario",
)

PlanCode = Literal["ESSENCIAL", "PRATICO", "TOTAL"]
PLAN_ORDER: tuple[PlanCode, ...] = ("ESSENCIAL", "PRATICO", "TOTAL")
CoverageGroup = Literal["fixa", "padrao_plano", "especifica_atividade", "opcional"]


class CatalogError(ValueError):
    pass


class Coverage(BaseModel):
    codigo: str
    nome: str
    grupo: CoverageGroup
    dimensao: str
    quando: dict | None = None
    is_min: int | None = None
    is_max: int | None = None


class Plan(BaseModel):
    codigo: PlanCode
    fixas: list[str]
    padrao: list[str]
    permite_especificas: bool
    assistencias: list[str]
    beneficio_premium: dict | None = None


class EligibilityRule(BaseModel):
    id: str
    tipo: Literal["impedimento", "redirecionamento"]
    descricao: str
    quando: dict
    destino: str | None = None


class PlanRule(BaseModel):
    id: str
    se: dict
    plano_minimo: PlanCode
    motivo: str


class Need(BaseModel):
    dimensao: str
    prioridade: Literal["alta", "media", "baixa"]


class AdditionalRule(BaseModel):
    id: str
    se: dict
    risco: str
    necessidade: Need
    cobertura: str
    texto: str


class EstimateBase(BaseModel):
    fato: str
    fator: float


class EstimateRule(BaseModel):
    id: str
    cobertura: str
    tipo: Literal["basica", "proporcional", "tabela", "contagem", "fontes"]
    entradas: list[str]
    regra: str
    padrao: list[int] | dict[str, str]
    base: list[EstimateBase] = []
    multiplicador: tuple[float, float] | None = None
    fato: str | None = None
    fatos: list[str] = []
    linhas: dict[Any, list[int]] | list[list[int]] | None = None
    fontes: list[
        dict
    ] = []  # tipo fontes: [{fato, linhas: {valor: faixa}} | {fatos, linhas: [faixa]}]


class Estimates(BaseModel):
    money_ranges: dict[str, tuple[int, int]]
    status_factors: dict[str, float]
    rounding: int
    rules: dict[str, EstimateRule]  # por código de cobertura


class QuestionText(BaseModel):
    texto: str
    motivo: str
    confirmacao: str | None = None


class Activity(BaseModel):
    atividade: str
    subatividade: str | None = None


class Term(BaseModel):
    min: int
    max: int
    padrao: int


class Catalog(BaseModel):
    version: str
    content_hash: str
    coverages: dict[str, Coverage]
    plans: dict[PlanCode, Plan]
    eligibility: list[EligibilityRule]
    plan_rules: list[PlanRule]
    additionals: list[AdditionalRule]
    estimates: Estimates
    questions: dict[str, QuestionText]
    option_labels: dict[str, str]
    activities: dict[str, Activity]  # por CNAE (L-10)
    term: Term


def _check_condition(cond: dict, where: str) -> None:
    ops = [k for k in cond if k in OPERATORS]
    combs = [k for k in cond if k in COMBINATORS]
    if "fato" in cond:
        if len(ops) != 1 or len(cond) != 2:
            raise CatalogError(f"{where}: condição precisa de exatamente um operador: {cond}")
    elif len(combs) != 1 or len(cond) != 1 or not isinstance(cond[combs[0]], list):
        raise CatalogError(f"{where}: combinador inválido: {cond}")
    else:
        for c in cond[combs[0]]:
            _check_condition(c, where)
    for key in condition_keys(cond):
        try:
            get_fact_key(key)
        except ValueError as e:
            raise CatalogError(f"{where}: {e}") from None


def _validate(cat: Catalog) -> None:
    cov = cat.coverages
    fixas = {c for c, v in cov.items() if v.grupo == "fixa"}
    for plan in cat.plans.values():
        where = f"plano {plan.codigo}"
        for code in plan.fixas + plan.padrao:
            if code not in cov:
                raise CatalogError(f"{where}: cobertura inexistente {code}")
        if set(plan.fixas) != fixas:
            raise CatalogError(f"{where}: fixas diferentes das fixas do catálogo")
        if any(cov[c].grupo != "padrao_plano" for c in plan.padrao):
            raise CatalogError(f"{where}: padrão precisa ser do grupo padrao_plano")
    if set(cat.plans) != set(PLAN_ORDER):
        raise CatalogError("planos.yaml precisa ter ESSENCIAL, PRATICO e TOTAL")
    if cat.plans["ESSENCIAL"].permite_especificas:
        raise CatalogError("Essencial não admite coberturas específicas da atividade")

    for c in cov.values():
        if c.quando:
            _check_condition(c.quando, f"cobertura {c.codigo}")
    for r in cat.eligibility:
        _check_condition(r.quando, r.id)
        if r.tipo == "redirecionamento" and not r.destino:
            raise CatalogError(f"{r.id}: redirecionamento sem destino")
    for r in cat.plan_rules:
        _check_condition(r.se, r.id)
    for r in cat.additionals:
        _check_condition(r.se, r.id)
        if r.cobertura not in cov:
            raise CatalogError(f"{r.id}: cobertura inexistente {r.cobertura}")

    _validate_estimates(cat)
    for key in cat.questions:
        try:
            get_fact_key(key)
        except ValueError as e:
            raise CatalogError(f"perguntas.yaml: {e}") from None
    if not cat.term.min <= cat.term.padrao <= cat.term.max:
        raise CatalogError("vigencia_anos inválida em planos.yaml")

    est = list(cat.estimates.rules.values())
    ids = [r.id for r in cat.eligibility + cat.plan_rules + cat.additionals + est]
    if len(ids) != len(set(ids)):
        raise CatalogError("ids de regra duplicados")


def _check_range(value, where: str) -> None:
    if not (isinstance(value, list | tuple) and len(value) == 2 and 0 <= value[0] <= value[1]):
        raise CatalogError(f"{where}: faixa inválida {value}")


def _validate_estimates(cat: Catalog) -> None:
    est = cat.estimates
    for name, rng in est.money_ranges.items():
        _check_range(rng, f"faixa monetária {name}")
    money_options = get_fact_key("faturamento_faixa").options
    if set(est.money_ranges) != set(money_options):
        raise CatalogError("faixas_monetarias precisa cobrir todas as opções de MoneyRange")

    # Toda cobertura que pode entrar sozinha numa oferta precisa de faixa.
    required = {
        c.codigo
        for c in cat.coverages.values()
        if c.grupo in ("fixa", "padrao_plano", "especifica_atividade") or c.quando
    }
    missing = required - set(est.rules)
    if missing:
        raise CatalogError(f"coberturas sem regra EST-*: {sorted(missing)}")

    for code, r in est.rules.items():
        where = r.id
        if code not in cat.coverages:
            raise CatalogError(f"{where}: cobertura inexistente {code}")
        keys = set(r.entradas) | {b.fato for b in r.base} | set(r.fatos)
        for src in r.fontes:
            keys |= {src["fato"]} if "fato" in src else set(src.get("fatos", []))
        keys |= {r.fato} if r.fato else set()
        keys |= set(r.padrao) if isinstance(r.padrao, dict) else set()
        for key in keys:
            try:
                get_fact_key(key)
            except ValueError as e:
                raise CatalogError(f"{where}: {e}") from None
        if r.tipo == "basica":
            if not isinstance(r.padrao, dict) or not set(r.padrao.values()) <= set(
                est.money_ranges
            ):
                raise CatalogError(f"{where}: padrão da básica precisa ser faixa monetária")
            continue
        _check_range(r.padrao, f"{where} padrao")
        if r.tipo == "proporcional" and (not r.base or r.multiplicador is None):
            raise CatalogError(f"{where}: proporcional precisa de base e multiplicador")
        if r.tipo == "tabela" and (not r.fato or not isinstance(r.linhas, dict)):
            raise CatalogError(f"{where}: tabela precisa de fato e linhas")
        if r.tipo == "contagem" and (not r.fatos or len(r.linhas or []) != len(r.fatos) + 1):
            raise CatalogError(f"{where}: contagem precisa de uma linha por total possível")
        if r.tipo == "fontes":
            if not r.fontes:
                raise CatalogError(f"{where}: fontes vazias")
            for src in r.fontes:
                ok_table = "fato" in src and isinstance(src.get("linhas"), dict)
                ok_count = "fatos" in src and len(src.get("linhas") or []) == len(src["fatos"]) + 1
                if not (ok_table or ok_count):
                    raise CatalogError(f"{where}: fonte inválida {src}")
                rows = src["linhas"].values() if ok_table else src["linhas"]
                for row in rows:
                    _check_range(row, f"{where} fonte")
        rows = r.linhas.values() if isinstance(r.linhas, dict) else r.linhas or []
        for row in rows:
            _check_range(row, f"{where} linha")


def _load_estimates(raw: dict) -> Estimates:
    rules = [EstimateRule(**r) for r in raw["regras"]]
    by_code = {r.cobertura: r for r in rules}
    if len(by_code) != len(rules):
        raise CatalogError("mais de uma regra EST-* para a mesma cobertura")
    return Estimates(
        money_ranges=raw["faixas_monetarias"],
        status_factors=raw["fatores_natureza"],
        rounding=raw["arredondamento"],
        rules=by_code,
    )


def load_catalog(directory: Path = CATALOG_DIR) -> Catalog:
    texts = {name: (directory / f"{name}.yaml").read_text(encoding="utf-8") for name in FILES}
    raw = {name: yaml.safe_load(text) for name, text in texts.items()}

    codes = [c["codigo"] for c in raw["coberturas"]["coberturas"]]
    if len(codes) != len(set(codes)):
        raise CatalogError("códigos de cobertura duplicados")

    digest = hashlib.sha256("".join(texts[n] for n in FILES).encode()).hexdigest()
    cat = Catalog(
        version=raw["coberturas"]["versao"],
        content_hash=digest,
        coverages={c["codigo"]: Coverage(**c) for c in raw["coberturas"]["coberturas"]},
        plans={p["codigo"]: Plan(**p) for p in raw["planos"]["planos"]},
        eligibility=[EligibilityRule(**r) for r in raw["elegibilidade"]["regras"]],
        plan_rules=[PlanRule(**r) for r in raw["recomendacao"]["selecao_plano"]],
        additionals=[AdditionalRule(**r) for r in raw["recomendacao"]["adicionais"]],
        estimates=_load_estimates(raw["estimativas"]),
        questions={k: QuestionText(**v) for k, v in raw["perguntas"]["perguntas"].items()},
        option_labels=raw["perguntas"]["rotulos_opcoes"],
        activities={
            m["cnae"]: Activity(atividade=m["atividade"], subatividade=m.get("subatividade"))
            for m in raw["atividade_formulario"]["mapa"]
        },
        term=Term(**raw["planos"]["vigencia_anos"]),
    )
    _validate(cat)
    return cat


@cache
def default_catalog() -> Catalog:
    return load_catalog()
