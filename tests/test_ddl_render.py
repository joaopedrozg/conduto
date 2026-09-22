"""Testes da geração de DDL (ddl_render): tipos, defaults, constraints e splitting."""

from pathlib import Path

import pytest
import yaml

from conduto.ddl.ddl_render import (
    _aspas,
    _default_sql,
    _preambulo_schema,
    carregar_tabelas,
    dividir_statement,
    gerar_ddl,
    gerar_ddl_tabela,
    ler_env,
    mapear_tipo,
)


TABELA_CLIENTES = {
    "table": "clientes",
    "schema": "public",
    "columns": [
        {"name": "id", "type": "integer", "primary_key": True, "nullable": False},
        {"name": "nome", "type": "varchar(255)", "nullable": False},
        {"name": "email", "type": "varchar", "unique": True},
        {"name": "criado_em", "type": "timestamp", "default": "CURRENT_TIMESTAMP"},
    ],
}

TABELA_PEDIDOS = {
    "table": "pedidos",
    "schema": "public",
    "columns": [
        {"name": "id", "type": "integer", "primary_key": True, "nullable": False},
        {"name": "cliente_id", "type": "integer", "foreign_key": "clientes(id)"},
        {"name": "valor", "type": "numeric(10,2)"},
    ],
}


# ---------------------------------------------------------------------------
# mapear_tipo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tipo,sgbd,esperado",
    [
        ("integer", "postgresql", "integer"),
        ("integer", "mysql", "int"),
        ("integer", "sqlserver", "int"),
        ("integer", "clickhouse", "Int32"),
        ("boolean", "sqlserver", "bit"),
        ("timestamptz", "sqlserver", "datetimeoffset"),
        ("numeric", "mysql", "decimal"),
        ("uuid", "postgresql", "uuid"),
        ("uuid", "mysql", "char(36)"),
        ("uuid", "sqlserver", "uniqueidentifier"),
        ("uuid", "clickhouse", "UUID"),
        ("jsonb", "mysql", "json"),
        ("binary", "postgresql", "bytea"),
        ("enum", "postgresql", "text"),
        ("double", "postgresql", "double precision"),
        # varchar sem tamanho vira um default por SGBD
        ("varchar", "postgresql", "text"),
        ("varchar", "mysql", "varchar(255)"),
        ("varchar", "sqlserver", "nvarchar(255)"),
        ("varchar", "clickhouse", "String"),
        ("varchar", "deltalake", "string"),
        # com tamanho preserva o parâmetro
        ("varchar(13)", "postgresql", "varchar(13)"),
        ("char(2)", "mysql", "char(2)"),
        # Delta Lake nunca tem tipo com parâmetro em texto/varchar/char
        ("varchar(255)", "deltalake", "string"),
        ("text", "deltalake", "string"),
        # tipo desconhecido cai no texto original (fallback)
        ("geometry", "postgresql", "geometry"),
        ("inet", "mysql", "inet"),
    ],
)
def test_mapear_tipo(tipo, sgbd, esperado):
    assert mapear_tipo(tipo, sgbd) == esperado


def test_mapear_tipo_clickhouse_decimal_com_parametros():
    # Decimal aceita precisao no ClickHouse: (10,2) e valido
    assert mapear_tipo("numeric(10,2)", "clickhouse") == "Decimal(10,2)"
    # sem parametros, vem o tipo cheio
    assert mapear_tipo("numeric", "clickhouse") == "Decimal"


def test_mapear_tipo_clickhouse_datetime_com_parametros():
    assert mapear_tipo("timestamp", "clickhouse") == "DateTime64(3)"


def test_mapear_tipo_case_insensitive():
    assert mapear_tipo("INTEGER", "mysql") == "int"
    assert mapear_tipo("  Integer  ", "sqlserver") == "int"


# ---------------------------------------------------------------------------
# _default_sql
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valor,sgbd,esperado",
    [
        (True, "postgresql", "TRUE"),
        (False, "postgresql", "FALSE"),
        (True, "sqlserver", "1"),
        (False, "sqlserver", "0"),
        (True, "mysql", "TRUE"),
        (42, "postgresql", "42"),
        (2.5, "postgresql", "2.5"),
        (None, "postgresql", ""),
        ("", "postgresql", ""),
        ("CURRENT_TIMESTAMP", "postgresql", "CURRENT_TIMESTAMP"),
        ("gen_random_uuid()", "postgresql", "gen_random_uuid()"),
        ("gen_random_uuid()", "sqlserver", "NEWID()"),
        ("gen_random_uuid()", "mysql", "UUID()"),
        ("gen_random_uuid()", "clickhouse", "generateUUIDv4()"),
        ("now()", "sqlserver", "GETDATE()"),
        ("NOW()", "sqlserver", "GETDATE()"),
        ("getdate()", "postgresql", "CURRENT_TIMESTAMP"),
        ("clock_timestamp()", "sqlserver", "SYSDATETIME()"),
        ("some_string", "postgresql", "'some_string'"),
        ("O'Brien", "postgresql", "'O''Brien'"),
    ],
)
def test_default_sql(valor, sgbd, esperado):
    assert _default_sql(valor, sgbd) == esperado


# ---------------------------------------------------------------------------
# aspas e preambulo de schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sgbd,esperado",
    [
        ('postgresql', '"clientes"'),
        ("mysql", "`clientes`"),
        ("sqlserver", "[clientes]"),
        ("clickhouse", "`clientes`"),
        ('duckdb', '"clientes"'),
        ('deltalake', '"clientes"'),
    ],
)
def test_aspas(sgbd, esperado):
    assert _aspas(sgbd, "clientes") == esperado


def test_preambulo_postgres_cria_schema():
    ddl = _preambulo_schema("public", "postgresql")
    assert 'CREATE SCHEMA IF NOT EXISTS "public";' in ddl


def test_preambulo_duckdb_cria_schema():
    ddl = _preambulo_schema("main", "duckdb")
    assert 'CREATE SCHEMA IF NOT EXISTS "main";' in ddl


def test_preambulo_sqlserver_cria_schema_condicional():
    ddl = _preambulo_schema("dbo", "sqlserver")
    assert "sys.schemas" in ddl
    assert "CREATE SCHEMA [dbo]" in ddl


def test_preambulo_clickhouse_cria_database():
    ddl = _preambulo_schema("analytics", "clickhouse")
    assert "CREATE DATABASE IF NOT EXISTS `analytics`;" in ddl


def test_preambulo_mysql_e_deltalake_vazio():
    # MySQL: schema == banco (nada a criar); Delta Lake: sem CREATE SCHEMA
    assert _preambulo_schema("meu_banco", "mysql") == ""
    assert _preambulo_schema("meu_banco", "deltalake") == ""


# ---------------------------------------------------------------------------
# gerar_ddl_tabela
# ---------------------------------------------------------------------------


def test_gerar_ddl_tabela_postgres():
    ddl = gerar_ddl_tabela(TABELA_CLIENTES, "postgresql")
    assert ddl.startswith('CREATE TABLE IF NOT EXISTS "public"."clientes" (')
    assert '"id" integer NOT NULL' in ddl
    assert '"nome" varchar(255) NOT NULL' in ddl
    # varchar sem tamanho vira text no PostgreSQL
    assert '"email" text' in ddl
    assert "CONSTRAINT \"pk_clientes\" PRIMARY KEY (\"id\")" in ddl
    assert "CONSTRAINT \"uq_clientes_email\" UNIQUE" in ddl
    assert "DEFAULT CURRENT_TIMESTAMP" in ddl
    assert ddl.endswith(";")


def test_gerar_ddl_tabela_foreign_key():
    ddl = gerar_ddl_tabela(TABELA_PEDIDOS, "postgresql")
    assert (
        'CONSTRAINT "fk_pedidos_cliente_id" FOREIGN KEY ("cliente_id") '
        'REFERENCES "public"."clientes" ("id")'
    ) in ddl
    assert '"valor" numeric(10,2)' in ddl


def test_gerar_ddl_tabela_sqlserver_tem_guard_if_object_id():
    ddl = gerar_ddl_tabela(TABELA_CLIENTES, "sqlserver")
    assert ddl.startswith("IF OBJECT_ID(N'public.clientes', N'U') IS NULL")
    assert ddl.startswith("IF OBJECT_ID") and "BEGIN" in ddl and ddl.endswith("END")
    assert "[id] int NOT NULL" in ddl


def test_gerar_ddl_tabela_clickhouse_engine_e_order_by():
    ddl = gerar_ddl_tabela(TABELA_CLIENTES, "clickhouse")
    assert "ENGINE = MergeTree" in ddl
    # ORDER BY sai das PKs, com aspas do proprio ClickHouse (crase)
    assert "ORDER BY (`id`)" in ddl
    # ClickHouse nao tem constraints
    assert "CONSTRAINT" not in ddl
    # coluna nullable vira Nullable(...)
    assert "Nullable(String)" in ddl


def test_gerar_ddl_tabela_clickhouse_engine_customizado():
    tabela = dict(TABELA_CLIENTES, engine="ReplacingMergeTree", order_by="id, nome")
    ddl = gerar_ddl_tabela(tabela, "clickhouse")
    assert "ENGINE = ReplacingMergeTree" in ddl
    # order_by como texto entra cru (sem aspas por coluna)
    assert "ORDER BY (id, nome)" in ddl


def test_gerar_ddl_tabela_deltalake_sem_constraints():
    ddl = gerar_ddl_tabela(TABELA_CLIENTES, "deltalake")
    assert "CONSTRAINT" not in ddl
    assert '"id" integer NOT NULL' in ddl


def test_gerar_ddl_tabela_coluna_duplicada_uma_vez():
    tabela = {
        "table": "t",
        "schema": "public",
        "columns": [
            {"name": "id", "type": "integer"},
            {"name": "id", "type": "integer"},
        ],
    }
    ddl = gerar_ddl_tabela(tabela, "postgresql")
    assert ddl.count('"id" integer') == 1


# ---------------------------------------------------------------------------
# gerar_ddl (composição)
# ---------------------------------------------------------------------------


def test_gerar_ddl_com_cabecalho_e_preambulos():
    ddl = gerar_ddl([TABELA_CLIENTES, TABELA_PEDIDOS], "postgresql")
    assert "-- DDL gerado pelo Conduto" in ddl
    assert "-- Destino: postgresql | schema(s): public | tabelas: 2" in ddl
    assert 'CREATE SCHEMA IF NOT EXISTS "public";' in ddl
    assert 'CREATE TABLE IF NOT EXISTS "public"."clientes"' in ddl
    assert 'CREATE TABLE IF NOT EXISTS "public"."pedidos"' in ddl
    # ordem de dependência preservada: clientes antes de pedidos
    assert ddl.index('"clientes"') < ddl.index('"pedidos"')


def test_gerar_ddl_mysql_sem_preambulo_de_schema():
    ddl = gerar_ddl([TABELA_CLIENTES], "mysql")
    assert "CREATE SCHEMA" not in ddl
    assert "CREATE TABLE IF NOT EXISTS" in ddl


# ---------------------------------------------------------------------------
# dividir_statement
# ---------------------------------------------------------------------------


def test_dividir_statement_postgres():
    ddl = gerar_ddl([TABELA_CLIENTES, TABELA_PEDIDOS], "postgresql")
    comandos = dividir_statement(ddl)
    # cabeçalho + CREATE SCHEMA sao uma sentenca; cada tabela, outra
    assert len(comandos) >= 3
    assert any("CREATE SCHEMA" in c for c in comandos)
    assert sum("CREATE TABLE" in c for c in comandos) == 2


def test_dividir_statement_sqlserver_preserva_begin_end():
    ddl = gerar_ddl([TABELA_CLIENTES], "sqlserver")
    comandos = dividir_statement(ddl)
    bloqueio = next(c for c in comandos if "IF OBJECT_ID" in c)
    # o BEGIN...END (com o ; interno do CREATE TABLE) nao pode ser quebrado
    assert bloqueio.count("BEGIN") == 1
    assert bloqueio.count("END") == 1
    assert "CREATE TABLE" in bloqueio
    assert all("IF OBJECT_ID" not in c or c == bloqueio for c in comandos)


def test_dividir_statement_texto_vazio():
    assert dividir_statement("") == []
    assert dividir_statement("   \n  \n") == []


# ---------------------------------------------------------------------------
# leitura do projeto
# ---------------------------------------------------------------------------


def _escrever_projeto(tmp_path: Path) -> Path:
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas" / "clientes.yml").write_text(
        yaml.safe_dump(TABELA_CLIENTES, sort_keys=False), encoding="utf-8"
    )
    (tmp_path / "schemas" / "pedidos.yml").write_text(
        yaml.safe_dump(TABELA_PEDIDOS, sort_keys=False), encoding="utf-8"
    )
    (tmp_path / "main.yml").write_text(
        yaml.safe_dump(
            {
                "version": "1.0",
                "project": "teste",
                "tables": [
                    {"path": "schemas/clientes.yml"},
                    {"path": "schemas/pedidos.yml"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_carregar_tabelas_respeita_ordem_do_main(tmp_path):
    projeto = _escrever_projeto(tmp_path)
    tabelas = carregar_tabelas(projeto)
    assert [t["table"] for t in tabelas] == ["clientes", "pedidos"]
    assert tabelas[0]["path"] == "schemas/clientes.yml"


def test_carregar_tabelas_sem_main_usa_ordem_alphabetica(tmp_path):
    projeto = _escrever_projeto(tmp_path)
    (projeto / "main.yml").unlink()
    tabelas = carregar_tabelas(projeto)
    assert [t["table"] for t in tabelas] == ["clientes", "pedidos"]


def test_carregar_tabelas_pula_arquivo_sem_colunas(tmp_path):
    projeto = _escrever_projeto(tmp_path)
    (projeto / "schemas" / "vazia.yml").write_text("table: vazia\n", encoding="utf-8")
    tabelas = carregar_tabelas(projeto)
    assert [t["table"] for t in tabelas] == ["clientes", "pedidos"]


def test_carregar_tabelas_caminho_inexistente_e_ignorado(tmp_path):
    projeto = _escrever_projeto(tmp_path)
    main = yaml.safe_load((projeto / "main.yml").read_text(encoding="utf-8"))
    main["tables"].append({"path": "schemas/nao_existe.yml"})
    (projeto / "main.yml").write_text(yaml.safe_dump(main), encoding="utf-8")
    tabelas = carregar_tabelas(projeto)
    assert [t["table"] for t in tabelas] == ["clientes", "pedidos"]


def test_carregar_tabelas_diretorio_sem_projeto(tmp_path):
    assert carregar_tabelas(tmp_path) == []


# ---------------------------------------------------------------------------
# ler_env
# ---------------------------------------------------------------------------


def test_ler_env(tmp_path):
    (tmp_path / ".env").write_text(
        "# comentario\n"
        "\n"
        "DB_DESTINO_TYPE=postgresql\n"
        "DB_DESTINO_HOST = localhost \n"
        "SENHA_SE_IGUAL=a=b\n",
        encoding="utf-8",
    )
    env = ler_env(tmp_path)
    assert env["DB_DESTINO_TYPE"] == "postgresql"
    assert env["DB_DESTINO_HOST"] == "localhost"
    assert env["SENHA_SE_IGUAL"] == "a=b"
    assert "#" not in "".join(env.keys())


def test_ler_env_sem_arquivo_levanta_erro(tmp_path):
    with pytest.raises(FileNotFoundError, match=".env"):
        ler_env(tmp_path)
