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
        # tipo customizado degrada para texto aceito pelo destino
        ("geometry", "postgresql", "geometry"),
        ("inet", "mysql", "text"),
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
# tipos customizados
# ---------------------------------------------------------------------------


DESTINOS = [
    "postgresql",
    "mysql",
    "sqlserver",
    "clickhouse",
    "duckdb",
    "deltalake",
]


@pytest.mark.parametrize(
    "tipo",
    [
        "ltree",
        "citext",
        "hstore",
        "tsvector",
        "inet",
        "cidr",
        "geometry",
        "geography",
        "point",
        "line",
        "lseg",
        "box",
        "path",
        "polygon",
        "circle",
        "interval",
        "varbit",
        "jsonpath",
        "hierarchyid",
        "sql_variant",
        "year",
        "set",
    ],
)
def test_tipo_customizado_tem_regra_para_todos_os_destinos(tipo):
    # Nenhum destino pode ficar sem regra: sem ela o tipo passaria cru e o
    # CREATE TABLE falharia no banco.
    from conduto.ddl.ddl_render import _TIPOS_CUSTOMIZADOS

    assert tipo in _TIPOS_CUSTOMIZADOS, f"{tipo} sem regra em _TIPOS_CUSTOMIZADOS"
    for sgbd in DESTINOS:
        regra = _TIPOS_CUSTOMIZADOS[tipo].get(sgbd)
        assert regra, f"{tipo} sem regra para {sgbd}"


@pytest.mark.parametrize(
    "tipo,sgbd,esperado",
    [
        # O tipo e mantido onde existe nativamente...
        ("ltree", "postgresql", "ltree"),
        ("citext", "postgresql", "citext"),
        ("inet", "postgresql", "inet"),
        ("geometry", "postgresql", "geometry"),
        ("hierarchyid", "sqlserver", "hierarchyid"),
        ("sql_variant", "sqlserver", "sql_variant"),
        ("geometry", "sqlserver", "geometry"),
        ("year", "mysql", "year"),
        ("interval", "duckdb", "interval"),
        # ...e degrada para texto portatil onde nao existe
        ("ltree", "mysql", "text"),
        ("ltree", "sqlserver", "nvarchar(max)"),
        ("ltree", "clickhouse", "String"),
        ("ltree", "duckdb", "varchar"),
        ("ltree", "deltalake", "string"),
        ("inet", "mysql", "text"),
        ("citext", "deltalake", "string"),
        ("geometry", "mysql", "text"),
        ("geometry", "deltalake", "string"),
        # Tipos exclusivos do SQL Server nao existem no PostgreSQL
        ("hierarchyid", "postgresql", "text"),
        ("sql_variant", "postgresql", "text"),
        # 'year' do MySQL vira inteiro onde nao existe tipo de ano
        ("year", "postgresql", "smallint"),
        ("year", "deltalake", "integer"),
        # Arrays do PostgreSQL so existem la dentro
        ("_int4", "postgresql", "_int4"),
        ("_int4", "mysql", "text"),
        ("array", "postgresql", "text[]"),
        ("array", "sqlserver", "nvarchar(max)"),
    ],
)
def test_mapear_tipo_customizado(tipo, sgbd, esperado):
    assert mapear_tipo(tipo, sgbd) == esperado


def test_tipo_customizado_nunca_e_truncado_no_destino():
    # Texto portatil nao tem limite de tamanho, entao o valor cru vindo da
    # origem nao estoura o CREATE TABLE nem a carga.
    from conduto.ddl.ddl_render import _TIPOS_CUSTOMIZADOS

    for tipo, regras in _TIPOS_CUSTOMIZADOS.items():
        for sgbd, regra in regras.items():
            assert "(" in regra or sgbd == "clickhouse" or len(regra) < 20, (
                f"{tipo}->{sgbd} = {regra!r} parece ter tamanho limitado"
            )


def test_tipo_desconhecido_passa_cru_com_aviso():
    from conduto.ddl import ddl_render

    with ddl_render.console.capture() as captura:
        assert mapear_tipo("meu_tipo_exotico", "mysql") == "meu_tipo_exotico"
    saida = captura.get()
    assert "meu_tipo_exotico" in saida
    assert "types:" in saida


def test_override_no_yaml_vence_qualquer_regra():
    # types: da coluna e o escape hatch para o usuario decidir
    assert (
        mapear_tipo("geometry", "mysql", {"mysql": "point"}) == "point"
    )
    assert (
        mapear_tipo("ltree", "postgresql", {"postgresql": "text"}) == "text"
    )
    # override so para outro destino nao afeta este
    assert (
        mapear_tipo("ltree", "mysql", {"postgresql": "text"}) == "text"
    )
    # override vazio nao muda nada
    assert mapear_tipo("integer", "mysql", {}) == "int"
    assert mapear_tipo("integer", "mysql", {"mysql": ""}) == "int"


def test_override_vence_mesmo_para_tipo_padrao():
    assert mapear_tipo("varchar", "mysql", {"mysql": "varchar(500)"}) == "varchar(500)"


def test_override_de_tipos_customizados_no_gerar_ddl():
    tabela = {
        "table": "pontos",
        "schema": "public",
        "columns": [
            {
                "name": "localizacao",
                "type": "geometry",
                "nullable": True,
                "types": {"mysql": "point", "deltalake": "binary"},
            }
        ],
    }
    ddl_mysql = gerar_ddl_tabela(tabela, "mysql")
    assert "`localizacao` point" in ddl_mysql

    ddl_delta = gerar_ddl_tabela(tabela, "deltalake")
    assert '"localizacao" binary' in ddl_delta

    # sem override para o destino, cai na regra da tabela
    ddl_pg = gerar_ddl_tabela(tabela, "postgresql")
    assert '"localizacao" geometry' in ddl_pg


def test_gerar_ddl_tabela_aceita_tipo_customizado_em_todos_os_destinos():
    # Regressao: qualquer tipo customizado tem de virar um DDL valido, nunca
    # uma excecao nem um tipo cru que o destino nao conhece.
    tabela = {
        "table": "rede",
        "schema": "public",
        "columns": [
            {"name": "ip", "type": "inet", "nullable": False},
            {"name": "caminho", "type": "ltree", "nullable": False},
            {"name": "busca", "type": "tsvector"},
        ],
    }
    esperado_mysql = {
        "ip": "text",
        "caminho": "text",
        "busca": "text",
    }
    for sgbd in DESTINOS:
        ddl = gerar_ddl_tabela(tabela, sgbd)
        assert "CREATE TABLE" in ddl, f"DDL quebrado para {sgbd}: {ddl}"
        if sgbd == "mysql":
            for coluna, tipo in esperado_mysql.items():
                assert f"`{coluna}` {tipo}" in ddl, ddl


# ---------------------------------------------------------------------------
# _tipo_arrow (criacao de tabela Delta)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tipo",
    ["ltree", "inet", "citext", "hstore", "geometry", "point", "tsvector", "meu_tipo"],
)
def test_tipo_arrow_nao_quebra_para_tipo_customizado(tipo):
    # Regressao: _tipo_arrow lancava ValueError e derrubava a criacao da
    # tabela Delta inteira com qualquer tipo customizado.
    from conduto.ddl.ddl_render import _tipo_arrow

    pa = pytest.importorskip("pyarrow")
    assert _tipo_arrow(tipo) == pa.string()


def test_tipo_arrow_preserva_os_tipos_padrao():
    from conduto.ddl.ddl_render import _tipo_arrow

    pa = pytest.importorskip("pyarrow")
    assert _tipo_arrow("integer") == pa.int32()
    assert _tipo_arrow("bigint") == pa.int64()
    assert _tipo_arrow("boolean") == pa.bool_()
    assert _tipo_arrow("timestamp") == pa.timestamp("us")
    assert _tipo_arrow("binary") == pa.binary()
    assert _tipo_arrow("numeric(10,2)") == pa.decimal128(10, 2)


# ---------------------------------------------------------------------------
# introspecao preserva o tipo customizado
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tipo_origem",
    ["geometry", "geography", "hierarchyid", "sql_variant"],
)
def test_inferir_tipo_preserva_customizado(tipo_origem):
    # Antes estes tipos viravam 'text' ja na introspecao, e a informacao
    # sumia antes de chegar ao DDL -- nao havia nem como dar override.
    from conduto.database.introspect import inferir_tipo

    assert inferir_tipo(tipo_origem) == tipo_origem



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


def test_gerar_ddl_tabela_nao_emite_foreign_key():
    """Ambiente analítico: a FK declarada não vira constraint no destino.

    A coluna continua existindo (a carga lê dela) e o YAML continua documentando
    a relação — só o ``FOREIGN KEY`` do ``CREATE TABLE`` foi removido, para que
    ``pedidos`` possa ser carregada sem ``clientes``.
    """
    ddl = gerar_ddl_tabela(TABELA_PEDIDOS, "postgresql")

    assert "FOREIGN KEY" not in ddl
    assert "REFERENCES" not in ddl
    assert '"cliente_id" integer' in ddl
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
    # a ordem recebida é preservada — sem reordenação por FK
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
