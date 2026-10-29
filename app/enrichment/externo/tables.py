"""Schema `externo`: dados públicos históricos usados como contexto territorial.

Fonte única da estrutura: o ETL cria/atualiza o schema a partir destas definições.
Cada tabela preserva a granularidade original da fonte; nada aqui é agregado.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

SCHEMA = "externo"
metadata = sa.MetaData(schema=SCHEMA)

_now = sa.text("now()")

fonte = sa.Table(
    "fonte",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("nome", sa.Text, nullable=False),
    sa.Column("orgao", sa.Text, nullable=False),
    sa.Column("granularidade", sa.Text, nullable=False),
    sa.Column("periodo_inicio", sa.SmallInteger),
    sa.Column("periodo_fim", sa.SmallInteger),
    sa.Column("licenca", sa.Text, nullable=False),
    sa.Column("limitacoes", sa.Text, nullable=False),
    sa.Column("url", sa.Text),
    sa.Column("arquivo_origem", sa.Text),
    sa.Column("sha256", sa.String(64)),
    sa.Column("ultima_carga_em", sa.DateTime(timezone=True)),
)

desastre_reconhecimento = sa.Table(
    "desastre_reconhecimento",
    metadata,
    sa.Column("ano", sa.SmallInteger, nullable=False),
    sa.Column("uf", sa.CHAR(2), nullable=False),
    sa.Column("linha_origem", sa.Integer, nullable=False),
    sa.Column("numero", sa.Integer),
    sa.Column("cod_ibge", sa.CHAR(7)),
    sa.Column("municipio", sa.Text, nullable=False),
    sa.Column("desastre_original", sa.Text, nullable=False),
    sa.Column("tipo_evento", sa.Text, nullable=False),
    sa.Column("se_ecp", sa.Text),
    sa.Column("numero_decreto", sa.Text),
    sa.Column("data_decreto", sa.Date),
    sa.Column("numero_portaria", sa.Text),
    sa.Column("data_portaria", sa.Date),
    sa.Column("numero_dou", sa.Text),
    sa.Column("data_dou", sa.Date),
    sa.Column("rito", sa.Text),
    sa.Column("arquivo_origem", sa.Text, nullable=False),
    sa.Column("qa_flags", pg.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
    sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=_now),
    sa.PrimaryKeyConstraint("ano", "uf", "linha_origem"),
    sa.Index("ix_desastre_uf_ano", "uf", "ano"),
    sa.Index("ix_desastre_cod_ibge_ano", "cod_ibge", "ano"),
    sa.Index("ix_desastre_tipo_ano", "tipo_evento", "ano"),
    sa.Index("ix_desastre_uf_tipo", "uf", "tipo_evento"),
    sa.Index("ix_desastre_cod_ibge_tipo", "cod_ibge", "tipo_evento"),
)

# Uma linha por UF × ano do intervalo coberto. Arquivo ausente != zero reconhecimentos.
desastre_cobertura = sa.Table(
    "desastre_cobertura",
    metadata,
    sa.Column("uf", sa.CHAR(2), nullable=False),
    sa.Column("ano", sa.SmallInteger, nullable=False),
    sa.Column("arquivo_presente", sa.Boolean, nullable=False),
    sa.Column("registros_lidos", sa.Integer),
    sa.Column("total_declarado", sa.Integer),
    sa.Column("total_municipios_declarado", sa.Integer),
    sa.Column("municipios_distintos", sa.Integer),
    sa.Column("divergencia_total", sa.Boolean),
    sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=_now),
    sa.PrimaryKeyConstraint("uf", "ano"),
)

crime_uf_indicador = sa.Table(
    "crime_uf_indicador",
    metadata,
    sa.Column("uf", sa.CHAR(2), nullable=False),
    sa.Column("ano", sa.SmallInteger, nullable=False),
    sa.Column("indicador", sa.Text, nullable=False),
    sa.Column("valor", sa.BigInteger),
    sa.Column("situacao", sa.Text, nullable=False),
    sa.Column("valor_bruto", sa.Text),
    sa.Column("ressalva", sa.Text),
    sa.Column("aba_origem", sa.Text, nullable=False),
    sa.Column("linha_origem", sa.Integer, nullable=False),
    sa.Column("qa_flags", pg.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
    sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=_now),
    sa.PrimaryKeyConstraint("uf", "ano", "indicador"),
    sa.Index("ix_crime_uf_ano", "uf", "ano"),
    sa.Index("ix_crime_indicador_ano", "indicador", "ano"),
    sa.CheckConstraint(
        "situacao IN ('informado','nao_disponivel','em_branco','invalido')",  # noqa: E501
        name="ck_crime_situacao",
    ),
)

etl_execucao = sa.Table(
    "etl_execucao",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("fonte_id", sa.Text, nullable=False),
    sa.Column("arquivo", sa.Text, nullable=False),
    sa.Column("sha256", sa.String(64), nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("iniciado_em", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finalizado_em", sa.DateTime(timezone=True), nullable=False),
    sa.Column("lidas", sa.Integer),
    sa.Column("inseridas", sa.Integer),
    sa.Column("atualizadas", sa.Integer),
    sa.Column("inalteradas", sa.Integer),
    sa.Column("removidas", sa.Integer),
    sa.Column("rejeitadas", sa.Integer),
    sa.Column("versao_etl", sa.Text, nullable=False),
    sa.Column("mensagem", sa.Text),
)

etl_rejeicao = sa.Table(
    "etl_rejeicao",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("fonte_id", sa.Text, nullable=False),
    sa.Column("arquivo", sa.Text, nullable=False),
    sa.Column("linha", sa.Integer, nullable=False),
    sa.Column("motivo", sa.Text, nullable=False),
    sa.Column("conteudo", pg.JSONB, nullable=False),
    sa.Column("registrada_em", sa.DateTime(timezone=True), nullable=False, server_default=_now),
    sa.Index("ix_etl_rejeicao_fonte", "fonte_id"),
)

# Permissões para o Supabase (PostgREST). Só atuam se os papéis existirem; fora do Supabase
# (Postgres local) é um no-op. Dados públicos, mas o acesso é só do backend (service_role):
# RLS ligada sem políticas bloqueia `anon` e `authenticated`.
PERMISSIONS_SQL = """
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['fonte','desastre_reconhecimento','desastre_cobertura',
                           'crime_uf_indicador','etl_execucao','etl_rejeicao']
  LOOP
    EXECUTE format('ALTER TABLE externo.%I ENABLE ROW LEVEL SECURITY', t);
  END LOOP;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    REVOKE ALL ON SCHEMA externo FROM anon, authenticated;
    REVOKE ALL ON ALL TABLES IN SCHEMA externo FROM anon, authenticated;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    GRANT USAGE ON SCHEMA externo TO service_role;
    GRANT SELECT ON ALL TABLES IN SCHEMA externo TO service_role;
  END IF;
END $$;
"""


# Colunas acrescentadas depois da primeira versão: `create_all` não altera tabelas existentes.
COLUMN_UPGRADES = [
    "ALTER TABLE externo.crime_uf_indicador "
    "ADD COLUMN IF NOT EXISTS qa_flags text[] NOT NULL DEFAULT '{}'",
]


def ensure_schema(engine: sa.engine.Engine) -> None:
    """Cria o schema, tabelas e índices se ainda não existirem (idempotente)."""
    with engine.begin() as conn:
        conn.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        metadata.create_all(conn, checkfirst=True)
        for statement in COLUMN_UPGRADES:
            conn.execute(sa.text(statement))
        conn.execute(sa.text(PERMISSIONS_SQL))
