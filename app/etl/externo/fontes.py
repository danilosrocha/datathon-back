"""Metadados de proveniência de cada fonte (gravados em `externo.fonte` a cada carga)."""

from dataclasses import dataclass

VERSAO_ETL = "1"

LICENCA_NAO_VERIFICADA = (
    "Não verificada: dado público recebido no pacote do datathon; confirmar os termos de uso "
    "na fonte antes de redistribuir."
)


@dataclass(frozen=True)
class FonteInfo:
    id: str
    nome: str
    orgao: str
    granularidade: str
    licenca: str
    limitacoes: str
    url: str | None = None


DESASTRES = FonteInfo(
    id="defesa_civil_reconhecimentos",
    nome="Reconhecimentos federais de Situação de Emergência (SE) e Estado de Calamidade "
    "Pública (ECP)",
    orgao="Ministério da Integração Nacional, Secretaria Nacional de Proteção e Defesa Civil "
    "(conforme o cabeçalho dos arquivos)",
    granularidade="Município × reconhecimento (um registro por portaria), arquivos por UF e ano",
    licenca=LICENCA_NAO_VERIFICADA,
    limitacoes=(
        "Lista apenas eventos que geraram reconhecimento federal de SE/ECP; não é inventário de "
        "ocorrências. Ausência de registro não significa ausência de evento. Há UF×ano sem "
        "arquivo (ver desastre_cobertura) e alguns arquivos divergem do próprio total declarado. "
        "Rótulos de evento mudam ao longo dos anos; tipo_evento é agrupamento da equipe e o "
        "rótulo original é preservado. Dado histórico: contexto territorial, não risco atual."
    ),
)

CRIMES = FonteInfo(
    id="crimes_uf_compilacao",
    nome="Indicadores de criminalidade por UF (planilha consolidada, aba 'dados completos')",
    orgao="Compilação de terceiros; a fonte primária não é declarada no arquivo",
    granularidade="UF × ano × indicador (sem recorte municipal)",
    licenca=LICENCA_NAO_VERIFICADA,
    limitacoes=(
        "Nível UF: não representa o município nem o endereço do estabelecimento. Séries "
        "incompletas: '...' e células vazias significam dado não disponível, nunca zero. Alguns "
        "anos trazem ressalvas (ex.: 2020 com dados do 1º semestre). Definições e subnotificação "
        "variam entre UFs. A taxa de homicídio da planilha (fórmula) não é carregada; taxas são "
        "derivadas na consulta."
    ),
)
