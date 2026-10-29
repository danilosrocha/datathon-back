# Negócio de Pé — Backend

Recomendação explicável de **Seguro Empresarial** para pequenos negócios: elegibilidade, plano
(Essencial, Prático ou Total), coberturas com faixas de importância segurada em reais, perguntas de
confirmação e o pré-preenchimento da cotação oficial. Datathon Proteção Inteligente — desafio
**Seguro Empresarial**.

> **Identificação da equipe:** _preencher_ — nome da equipe, nomes completos dos integrantes e
> instituição/turma (sem CPF, matrícula ou outro dado pessoal desnecessário).

## Objetivo

Processar todos os casos da base comum (empresa + estabelecimento) e preencher os dois templates
oficiais, e oferecer a mesma decisão numa jornada conversacional web. Toda decisão é
determinística, rastreável e reprodutível: `decisão = f(fatos, versão das regras, versão do grafo)`.
O modelo de linguagem só extrai fatos do texto e redige perguntas e explicações; ele nunca decide
elegibilidade, plano, coberturas ou valores.

## Arquitetura

```
base comum ─┐                         ┌─ template_resultado_times.csv
            ├─ fatos (natureza, origem, confiança) ─ motor ─┼─ template_coberturas_times.csv
conversa ───┘        ▲                    ▲        │        ├─ trace.jsonl · metricas.json
(LLM extrai)         │                    │        │        └─ Decision → API / agente
              risco por município   context graph  │
              (Atlas, roubos/UF)    (hipóteses p)  └─ catálogo oficial (YAML versionado)
```

| Camada | Pasta | O que faz |
|---|---|---|
| Fatos | `app/domain/` | `Fact` com natureza (`observado` · `derivado` · `estimado` · `confirmado` · `rejeitado`), origem e confiança; registro de chaves (`fact_keys.yaml`) com tipo e guardrails |
| Catálogo | `catalog/` | Coberturas, planos, elegibilidade, recomendação, estimativas (`EST-*`), perguntas e mapa CNAE → formulário |
| Motor | `app/engine/` | Funções puras: regras em três valores, elegibilidade, necessidades, três ofertas validadas, faixas, `quote_prefill`, cards, Personalizar e próxima pergunta |
| Context graph | `app/graph/` | Atividade → característica → risco → dimensão em NetworkX; priors α/β com back-off CNAE |
| Agentes | `app/agents/` | LangGraph: Extrator (LLM rápido) → motor → Entrevistador ou Explicador (LLM + validador) |
| Lote | `app/batch/` | Base comum → templates oficiais, trace e métricas (sem LLM, sem rede) |
| Enriquecimento | `app/enrichment/` | Risco regional por município (dados públicos) e CEP → município (ViaCEP) na jornada web |
| API | `app/api/` | FastAPI: caso anônimo com `X-Case-Token`, comandos 202, SSE, ofertas, cards e Personalizar |
| Banco | `app/db/`, `migrations/` | Postgres (Supabase): casos, fatos, auditoria append-only, recomendações, grafo versionado |

Fluxo do motor (`app/engine/decide.py`):

1. **Fatos derivados** de entradas sabidas: `atividade_aceita` e `atividade_rural` pelo CNAE (L-03)
   e `is_basica_estimada` pela soma dos pisos das faixas (ELG-008).
2. **Elegibilidade** em lógica de Kleene: impedimento verdadeiro → inelegível; algum desconhecido →
   pendente; todos falsos → elegível. Fato `estimado` conta como desconhecido; ausência nunca vira
   "não".
3. **Hipóteses do grafo**: característica com p(k | CNAE) ≥ 0,8 e sem fato no caso.
4. **Necessidades**: característica → risco → dimensão, força = p × peso da exposição.
5. **Ofertas**: `melhor_ajuste` (plano mínimo pelas regras `PLN-*`), `custo_beneficio` (plano
   abaixo) e `protecao_ampliada` (plano acima), todas validadas contra o catálogo.
6. **Faixas** por regra `EST-*`, com dados usados, confiança e o que confirmar.
7. **Textos por template**, `quote_prefill` e `coverage_cards`.

## Arquivos

```
catalog/                 catálogo oficial e premissas (YAML)
app/domain/              fatos, chaves de fatos e modelos de saída
app/engine/              motor determinístico
app/graph/               context graph (ontologia, priors, raciocinador, seed_priors)
app/agents/              LLM (único ponto de chamada), nós e prompts do perfilamento
app/batch/               lote: loader, mapeamentos, writers, métricas
app/enrichment/          geração de data/risco_municipio.csv
app/api/                 rotas FastAPI (cases, offers, dev) e SSE
app/db/ · migrations/    modelos, repositórios e migrações Alembic
data/risco_*.csv         risco regional por município e roubo por UF (derivados de dados públicos)
data/fixtures/api/       respostas gravadas de APIs públicas (DEMO_MODE)
tests/                   motor, agentes, lote, API, grafo (fixtures; nenhuma chamada externa)
```

## Execução

Python 3.12 (`.python-version`) e [uv](https://docs.astral.sh/uv/). Dependências em
`pyproject.toml`/`uv.lock`; `requirements.txt` exportado para quem não usa uv.

```bash
uv sync
cp .env.example .env

# Lote: 2 templates + trace + métricas (≈ 8 s para 2.978 casos)
uv run python -m app.batch.run --input <pasta da base comum> --out-dir ../out/

# Testes e qualidade
uv run pytest
uv run ruff check . && uv run ruff format .

# API e LangGraph Studio (em memória por padrão: PERSISTENCE=memory)
uv run fastapi dev app/main.py      # http://localhost:8000/docs
uv run langgraph dev

# Persistência no Postgres/Supabase (session pooler, porta 5432): PERSISTENCE=postgres
uv run alembic upgrade head
uv run python -m app.graph.seed     # ontologia + priors → kg_version 1

# Regerar dados derivados (opcional)
uv run python -m app.enrichment.risco_municipio --contexto <pasta com registros_desastres.zip> \
  --base <pasta da base comum>
uv run python -m app.batch.validate_base --input data/Seguro_Empresarial_Desenvolvimento   # formato
uv run python -m app.graph.train --input data/Seguro_Empresarial_Desenvolvimento          # treino do grafo
uv export --format requirements-txt --no-hashes --no-dev > requirements.txt
```

Rotas principais (CONTRATOS_API §6): `POST /api/v1/cases` → `case_id` + `case_token`;
`GET /cases/{id}/events` (SSE, retoma com `Last-Event-ID`); `POST /cases/{id}/messages`,
`PUT|DELETE /cases/{id}/facts/{key}` e `POST .../confirm` respondem 202 e o resultado chega pelo SSE;
`GET /cases/{id}/recommendation`, `/explain-graph`, `/offers/{offer_id}` (com `coverage_cards`) e
`POST /offers/{offer_id}/customize` (Personalizar cumulativo; 422 com `violations`). Com
`ENABLE_DEV_ROUTES=true`, `POST /api/v1/dev/graph/rebuild` agrega os fatos confirmados numa nova
versão rascunho do grafo e `POST /api/v1/dev/graph/publish/{v}` a publica para os próximos casos.

O lote não usa LLM nem rede. Para a jornada conversacional, defina `ANTHROPIC_API_KEY`; os modelos
vêm de `LLM_MODEL_MAIN` e `LLM_MODEL_FAST` (para demonstração barata, `claude-haiku-5-5` nos dois).

## Premissas

Lacunas do Guia e premissas adotadas (detalhe em `docs/LACUNAS.md` do repositório de contexto):

| ID | Premissa |
|---|---|
| L-01 | Cobertura padrão não é adicionada ao Essencial: se for necessária, o plano sobe para o Prático |
| L-02 | Faixas das coberturas, exceto a básica, por regras `EST-*` da equipe, sujeitas às condições gerais |
| L-03 | Atividade aceita e não rural = CNAE fora da seção A (divisões 01–03) |
| L-04 | Caso inelegível não tem linhas no template de coberturas; o motivo vai no template de resultado |
| L-05 | Impedimento sem campo na base → elegível **sujeito a confirmação** (`SIM_SUJEITO_A_CONFIRMACAO`), com recomendação preliminar e pergunta de confirmação |
| L-09 | "Tipo, uso ou localização" = tipo de estabelecimento sugerido + nível de risco territorial do município |
| L-10 | `PROTECAO_CIBERNETICA` incluída nos três planos como código provisório (ausente no CSV, exigida pelo Guia) |
| L-11 | Piso de R$ 100 mil na cobertura básica |
| L-12 | Nenhum preço é calculado |
| L-15 | `is_sugerida` = ponto médio da faixa, arredondado para baixo a R$ 5 mil |

Premissas da equipe no motor:

- **`PLN-01`/`PLN-02`** (`catalog/recomendacao.yaml`): exposição climática, estoque ou risco de roubo
  médio/alto → Prático; fachada de vidro ou 10+ empregados → Total.
- **`PLN-ESP`**: se uma cobertura específica da atividade se aplica, o plano sobe para o Prático.
- **Hipóteses**: p ≥ 0,8 vira hipótese (mesmo limiar do estilo "confirmação" das perguntas).
- **Faixas `EST-*`** (`catalog/estimativas.yaml`): 7 regras do contrato e 10 da equipe; sem entrada,
  tabela da equipe com natureza `estimado`. Confiança = média dos fatores das **vagas de entrada**
  (confirmado 1,0 · observado 0,8 · derivado 0,7 · estimado 0,4; vaga vazia 0). Alternativas
  ("prédio ou conteúdo") ocupam uma vaga só e entradas que não se aplicam ao caso (o prédio de quem
  só protege o conteúdo) não contam nem viram pergunta.
- **IS básica para ELG-008**: soma dos **pisos** das faixas sabidas — só redireciona quando nem o
  mínimo cabe em R$ 7,5 mi.
- **Fontes em ordem** (tipo `fontes` em `estimativas.yaml`): a faixa cibernética usa primeiro o
  índice de exposição digital da base (`indice_exposicao_digital`, índice recalculável → `derivado`,
  em tercis: ≤ 0,366 baixo · ≤ 0,472 médio · acima alto) e, sem ele, os sinais da conversa; a de
  quebra de vidros usa primeiro a fachada de vidro informada e, sem ela, o tipo de estabelecimento.
  Isso dimensiona a faixa, mas não muda o plano: `PLN-02` continua exigindo fachada informada.
- **Inquilino sem objeto do seguro** protege só o conteúdo; proprietário, prédio e conteúdo.
- **Confiança geral** = média de dois componentes (ambos no `trace`): **faixas** (média da confiança
  das coberturas) e **plano** (quão sustentada está a escolha do plano: a evidência mais forte que o
  fez subir — um risco regional estimado sustenta pouco — ou, no Essencial, o descarte mais fraco
  das regras de subida; condição desconhecida vale 0). Cada entrada vale
  min(fator da natureza, confiança do dado): a natureza é o teto e a qualidade declarada na base
  (ex.: vínculo BAIXA dos bens) pode baixar. Fatos que ainda podem subir o plano viram perguntas de
  confirmação. A pendência de elegibilidade não entra no número: já aparece no status
  (`preliminar`, `SIM_SUJEITO_A_CONFIRMACAO`) e nas perguntas.

Mapeamento da base (`app/batch/input_mapping.yaml`): campos cadastrais → `observado`; valores
recalculáveis (estoque, despesa, bens ponderados) → `derivado`; probabilidades e índices →
`estimado`. Limiares (ex.: probabilidade ≥ 0,6 vira hipótese "sim") estão no YAML. CEP e
coordenadas da base são fictícios e nunca são usados; o território entra só pelo código IBGE.

## Treino do context graph

`app/graph/train.py` valida o formato da base (`app/batch/validate_base.py`: arquivos, colunas,
chaves, integridade entre tabelas, domínios e faixas), calcula α/β de atividade → característica por
subclasse CNAE e por divisão (observado 1,0; derivado/estimado 0,3), grava
`app/graph/ontology/priors_base.yaml` (usado pelo lote) e publica uma nova `kg_version` no banco sem
sobrescrever as anteriores. Na base de desenvolvimento: 11 características, 396 priors, 8 divisões
CNAE; a versão 2 (treino) tem 423 arestas.

A validação mostrou limiares do mapeamento que não informavam nada e foram recalibrados na
distribuição real (`app/batch/input_mapping.yaml`): delivery observado só com receita de delivery
≥ 15% (5% marcava 25% dos escritórios); vendas online ≥ 60% = sim, ≤ 20% = não (a mediana é 0,47 em
todas as atividades); recebimentos digitais ≥ 50% = sim, ≤ 10% = não. Entre o "sim" e o "não" o fato
fica desconhecido. Bens só registrados quando existem (máquinas, eletrônicos, letreiro) contam a
ausência como "não" com peso 0,3 apenas na estatística dos priors.

## Dados externos

| Fonte | Uso | Nível | Método e transformação | Limitações | Acesso |
|---|---|---|---|---|---|
| Atlas Digital de Desastres no Brasil (MIDR/Defesa Civil, S2iD) | Risco de vendaval, granizo e alagamento | Município | Reconhecimentos de SE/ECP 2003–2016 por tipologia → 0 baixo · 1–2 médio · ≥ 3 alto | Subnotificação; registra reconhecimentos, não todos os eventos | 28/10/2026 |
| Dados de criminalidade por UF | Risco de roubo | UF | Mediana 2018–2023 de roubos por 100 mil hab. → tercis entre UFs | Nível UF, não município; confiança baixa | 28/10/2026 |

| ViaCEP (`viacep.com.br`) | CEP informado pelo usuário → município (jornada web) | Logradouro | API REST sob demanda, cache em memória | Não usado no lote (CEP da base é fictício) | sob demanda |

Os riscos regionais entram sempre como `estimado` (confiança 0,3) e não decidem elegibilidade.
Recorte versionado em `data/risco_municipio.csv` (4.213 municípios) e `data/risco_uf.csv`; código de
geração em `app/enrichment/risco_municipio.py`. Município sem registro no Atlas fica sem risco
climático (desconhecido), só com o roubo da UF. **Licença: confirmar os termos de cada fonte no site.**

### Carga no banco (ETL de desastres e crimes)

```bash
uv run python -m app.etl.externo --data-dir ../xenga-datathon-context --check    # alvo e modo de acesso
uv run python -m app.etl.externo --data-dir ../xenga-datathon-context            # carga idempotente (UPSERT)
```

Detalhes, tabelas e limitações em `docs/DADOS_EXTERNOS.md` (repositório de contexto).

## Métricas e resultados (base de desenvolvimento, 2.978 casos)

| Métrica | Valor |
|---|---|
| Casos processados / taxa de falhas | 100% / 0% |
| Tempo de execução | ≈ 7 s |
| Recomendações com justificativa | 100% |
| Violações de elegibilidade | 0 |
| Casos elegíveis com as 6 fixas no template | 100% |
| Inconsistências plano × coberturas | 0 |
| Coberturas sem faixa | 0% |
| Perguntas de confirmação por caso (média) | 5,4 |
| Confiança geral: média / desvio / casos < 0,5 | 0,61 / 0,11 / 23,8% |
| Confiança por plano (Total / Prático / Essencial) | 0,67 / 0,61 / 0,32 |
| Estabilidade (perturbar atributo irrelevante) | 100% |
| Consistência entre casos semelhantes | 64,6% |
| Sensibilidade da básica (conteúdo sobe uma faixa) | +265% no ponto médio |
| Reprodutibilidade | mesmo hash em execuções repetidas |

Distribuição: 2.900 elegíveis sujeitos a confirmação (três impedimentos não existem na base) e 78
inelegíveis (imóvel em obra); planos: Prático 1.609, Total 1.125, Essencial 166. Resultados com o
grafo treinado (kg_version 2).

## Limitações

- Três impedimentos (localização restrita, imóvel tombado, objeto já segurado na BB) não existem na
  base: todo caso sem impedimento conhecido sai como elegível sujeito a confirmação.
- Nenhum caso do Essencial tem a escolha do plano sustentada: a base nunca informa fachada de
  vidro, então a regra que levaria ao Total não pode ser descartada (vira pergunta de confirmação).
  532 casos sobem para o Prático só pelo risco regional estimado (nível UF) e ficam com confiança
  de plano 0,3.
- Nenhum caso do lote chega a confiança "alta" (≥ 0,75): a base traz dados observados (0,8) e
  derivados (0,7), nunca confirmados, e os valores agregados (bens, estoque, despesas) são
  derivados por fórmula. Ponderar a média por valor segurado ou por grupo foi testado e não muda o
  resultado (0,694–0,696). A confiança sobe na jornada web, à medida que o cliente
  confirma os cards.
- Faixas monetárias de entrada são largas (ex.: R$ 200 mil a 1 milhão); por isso as faixas de saída
  também são, e a sensibilidade a uma mudança de faixa é alta.
- Valores das regras `EST-*` da equipe e os limiares do mapeamento são pontos de partida a calibrar.
- O risco de roubo é por UF; o de clima depende de reconhecimentos oficiais.
- A lista de atividades do formulário oficial não é pública (L-10): `quote_prefill.atividade` fica
  `null`.
- Sem banco configurado, a API guarda casos e o checkpointer em memória (uma instância): reiniciar
  apaga os casos. Com `PERSISTENCE=postgres`, ficam no Supabase.

## Uso de IA

Ferramentas de IA (Claude Code) apoiaram a escrita de código, testes e documentação, sempre a partir
das especificações da equipe (`docs/` do repositório de contexto) e com revisão humana. Na solução,
o Claude é usado apenas na jornada conversacional para extrair fatos do texto, redigir perguntas e
reescrever a explicação, que passa por um validador; nenhum campo de decisão vem do modelo. O lote
é 100% determinístico.
# datathon-back
