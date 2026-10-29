"""Saída do motor (CONTRATOS_API §3.4 e §3.5). Serializável e determinística."""

from typing import Any, Literal

from pydantic import BaseModel

PlanCode = Literal["ESSENCIAL", "PRATICO", "TOTAL"]
CoverageGroup = Literal["fixa", "padrao_plano", "especifica_atividade", "opcional"]


class Blocker(BaseModel):
    rule_id: str
    description: str
    fact_keys: list[str]


class Pending(BaseModel):
    fact_key: str
    rule_id: str
    why: str


class Eligibility(BaseModel):
    status: Literal["elegivel", "inelegivel", "pendente"]
    blockers: list[Blocker] = []
    pending: list[Pending] = []
    rules_version: str
    redirect_to: str | None = None


class Hypothesis(BaseModel):
    """Característica inferida pelo context graph a partir do CNAE (natureza `estimado`)."""

    fact_key: str
    value: bool
    p: float


class NeedEvidence(BaseModel):
    fact_key: str
    risk: str
    origin: Literal["fato", "estimado", "hipotese"]
    strength: float  # p(característica) × peso da exposição


class Need(BaseModel):
    dimension: str
    priority: Literal["alta", "media", "baixa"]
    score: float
    evidence: list[NeedEvidence]


class InsuredAmount(BaseModel):
    min: int
    max: int


class OfferCoverage(BaseModel):
    code: str
    name: str
    group: CoverageGroup
    # Trilha: toda cobertura aponta a regra, os fatos, o risco e a necessidade que a trouxeram.
    rule_id: str
    fact_keys: list[str]
    risk: str | None
    need: str
    justification: str
    to_confirm: list[str] = []
    insured_amount: InsuredAmount | None = None
    confidence: float | None = None
    data_used: list[str] = []
    calc_rule: str | None = None
    note: str | None = None
    # `adicionada_cliente`: incluída em Personalizar (não estava na oferta de origem).
    origin: Literal["sugerida", "adicionada_cliente"] = "sugerida"
    is_escolhida: int | None = None  # IS escolhida em Personalizar; None mantém a sugerida


class CoverageCard(BaseModel):
    """Um card por cobertura do catálogo: o que está coberto, o que dá para incluir e o que está
    bloqueado (com motivo). É a base da tela de Personalizar."""

    code: str
    name: str
    group: CoverageGroup
    dimension: str
    status: Literal["incluida", "disponivel", "indisponivel"]
    suggested: bool  # estava na oferta de origem do motor
    origin: Literal["sugerida", "adicionada_cliente"] | None = None  # só quando incluída
    actions: list[Literal["remover", "adicionar", "ajustar_is"]] = []
    lock_reason: str | None = None
    insured_amount: InsuredAmount | None = None
    is_escolhida: int | None = None
    is_limits: InsuredAmount | None = None
    justification: str | None = None
    warning: str | None = None


class Reason(BaseModel):
    fact_keys: list[str]
    risk: str | None
    need: str
    coverage_code: str
    rule_id: str
    text: str


class Address(BaseModel):
    cep: str | None
    municipio_ibge: str | None
    uf: str | None


class PrefillCoverage(BaseModel):
    code: str
    ativa: bool
    is_sugerida: int | None


class QuotePrefill(BaseModel):
    """A oferta traduzida nos campos da cotação oficial (ARQUITETURA §3.1)."""

    tipo_pessoa: str | None
    atividade: str | None
    subatividade: str | None
    objeto_seguro: str
    em_shopping: bool | None
    endereco: Address
    vigencia_anos: int
    plano: PlanCode
    coberturas: list[PrefillCoverage]
    beneficio_premium: str | None


OfferKind = Literal["melhor_ajuste", "custo_beneficio", "protecao_ampliada", "personalizada"]


class Offer(BaseModel):
    offer_id: str
    kind: OfferKind
    plan_code: PlanCode
    plan_rule_ids: list[str]
    coverages: list[OfferCoverage]
    assistance_packages: list[str]
    premium_benefit: dict | None = None
    title: str = ""
    reasons: list[Reason] = []
    diff_vs_best: list[str] = []
    limitations: list[str] = []
    quote_prefill: QuotePrefill | None = None
    explanation_md: str = ""
    explanation_source: Literal["template", "llm_validado"] = "template"
    base_offer_id: str | None = None  # só na `personalizada`: oferta de origem
    coverage_cards: list[CoverageCard] = []


class Confidence(BaseModel):
    overall: float
    level: Literal["alta", "media", "baixa"]
    # Componentes: sustentação das faixas e da escolha do plano (overall = média dos dois).
    ranges: float | None = None
    plan: float | None = None


class QuestionOption(BaseModel):
    value: str
    label: str


class QuestionInput(BaseModel):
    type: str
    options: list[QuestionOption] = []
    min: float | None = None
    max: float | None = None


class Question(BaseModel):
    question_id: str
    fact_key: str
    prompt: str
    style: Literal["aberta", "confirmacao"]
    input: QuestionInput
    reason: str
    score: float


class CoverageChange(BaseModel):
    code: str
    active: bool
    insured_amount: int | None = None  # IS escolhida no formulário


class CustomizeRequest(BaseModel):
    coverages: list[CoverageChange] = []
    vigencia_anos: int | None = None
    premium_benefit: str | None = None
    reset: bool = False


ViolationCode = Literal[
    "cobertura_desconhecida",
    "fixa_nao_removivel",
    "grupo_nao_permitido_no_plano",
    "incompativel_atividade",
    "is_fora_dos_limites",
    "vigencia_fora_dos_limites",
    "beneficio_premium_invalido",
]


class Violation(BaseModel):
    """Recusa do motor em Personalizar (CONTRATOS_API §6.1)."""

    code: ViolationCode
    coverage_code: str | None = None
    message: str


class CustomizeResult(BaseModel):
    offer: Offer | None
    violations: list[Violation] = []


class Versions(BaseModel):
    rules: str
    rules_hash: str
    kg: int


class Decision(BaseModel):
    status: Literal["conclusiva", "preliminar"] | None  # None quando inelegível
    eligibility: Eligibility
    derived: dict[str, Any]  # fatos derivados pelo motor (is_basica_estimada, atividade_aceita)
    hypotheses: list[Hypothesis]
    needs: list[Need]
    offers: list[Offer]
    confidence: Confidence | None
    confirmation_questions: list[str]
    external_sources: list[str]
    versions: Versions
