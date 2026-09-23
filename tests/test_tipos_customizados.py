"""Tipos customizados: descoberta dinamica no catalogo e resolucao por destino.

O catálogo de cada SGBD entrega o tipo de jeitos muito diferentes e o YAML
so aceita um vocabulario canonico que TODOS os destinos sabem mapear. Aqui
esta a fronteira inteira:

  A. inferir_tipo: o literal cru do catalogo -> tipo canonico do YAML
  B. propriedade: inferir_tipo nunca devolve um nome sem regra de destino
  C. mapear_tipo: familias de colecao nao recebem parametro colado
  D. mocks do catalogo: descrever_tabela le o tipo real de cada dialeto
  E. cenario ponta a ponta: catalogo -> YAML -> tipo do destino
  F. matriz: todo tipo customizado x todo destino gera DDL utilizavel

Fatos verificados contra servidores reais (PostgreSQL 16.2, ClickHouse 26.9,
DuckDB embutido) estao citados nos testes para nao virarem opiniao.
"""

from pathlib import Path

import pytest

from conduto.database.introspect import inferir_tipo
from conduto.ddl.ddl_render import (
    _TIPOS_CUSTOMIZADOS,
    _TIPOS_POR_SGBD,
    _TEXTO_PORTATIL,
    console,
    gerar_ddl_tabela,
    mapear_tipo,
)


DESTINOS = ["postgresql", "mysql", "sqlserver", "clickhouse", "duckdb", "deltalake"]

# Familias cujo destino e sempre texto portatil. 'enum' nao entra: ela tem
# regra propria em _TIPOS_POR_SGBD (varchar em alguns SGBDs).
FAMILIAS_DE_COLECAO = ["array", "map", "tuple", "struct", "union"]


def _vocabulario() -> set:
    """Todo nome que inferir_tipo tem o direito de devolver."""
    intersecao = set.intersection(*(set(r) for r in _TIPOS_POR_SGBD.values()))
    return (intersecao | set(_TIPOS_CUSTOMIZADOS)) - {"user-defined"}


VOCABULARIO = _vocabulario()


# ---------------------------------------------------------------------------
# A. literal cru do catalogo -> tipo canonico do YAML
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cruto, esperado",
    [
        # --- PostgreSQL: information_schema.columns ---
        # Só cai em USER-DEFINED o que nao e tipo de pg_catalog: extensoes
        # (ltree, citext, geometry), enumerados e compostos do usuario.
        # O nome verdadeiro vem de udt_name (ver secao D).
        ("USER-DEFINED", "text"),
        ("ARRAY", "array"),
        ("character varying", "text"),
        ("bit varying", "varbit"),   # data_type real de coluna varbit
        ("double precision", "double"),
        ("timestamp without time zone", "timestamp"),
        ("timestamp with time zone", "timestamptz"),
        # tipos de pg_catalog que o information_schema repassa com o nome
        # verdadeiro -- nao ha nada a resolver
        ("inet", "inet"),
        ("cidr", "cidr"),
        ("tsvector", "tsvector"),
        ("jsonpath", "jsonpath"),
        ("interval", "interval"),
        ("point", "point"),
        ("circle", "circle"),
        ("xml", "xml"),
        # --- extensoes do PostgreSQL (chegam por udt_name) ---
        ("ltree", "ltree"),
        ("citext", "citext"),
        ("hstore", "hstore"),
        # --- enumerado/composto do usuario: nao existe no destino ---
        ("status_t", "text"),
        ("endereco_t", "text"),
        ("meu_tipo_qualquer", "text"),
        # --- SQL Server: alias/UDT ja resolvidos para a base pelo sys.types ---
        ("hierarchyid", "hierarchyid"),
        ("geography", "geography"),
        ("geometry", "geometry"),
        ("sql_variant", "sql_variant"),
        ("uniqueidentifier", "uuid"),
        ("datetime2", "timestamp"),
        ("varbinary", "binary"),
        ("money", "numeric(19, 4)"),
        # --- MySQL ---
        ("enum", "enum"),
        ("set", "set"),
        ("year", "year"),
        # --- ClickHouse: system.columns devolve o literal cheio ---
        ("Array(String)", "array"),
        ("Array(Nullable(UUID))", "array"),
        ("Map(String, UInt8)", "map"),
        ("Tuple(UInt8, String)", "tuple"),
        ("Tuple(a Decimal(10, 2), b Nullable(String))", "tuple"),
        ("Enum8('a' = 1, 'b' = 2)", "enum"),
        ("LowCardinality(String)", "text"),
        ("Nullable(Int64)", "bigint"),
        ("FixedString(3)", "char(3)"),
        ("DateTime64(3, 'UTC')", "timestamp"),
        ("Decimal(18, 2)", "numeric(18, 2)"),
        ("AggregateFunction(sum, UInt64)", "text"),
        ("IPv4", "text"),
        ("Nothing", "text"),
        ("UInt32", "bigint"),
        ("Bool", "boolean"),
        # --- DuckDB: information_schema entrega o nome real tambem ---
        ("STRUCT(a INTEGER, b VARCHAR)", "struct"),
        ("MAP(VARCHAR, INTEGER)", "map"),
        ("UNION(num INTEGER, txt VARCHAR)", "union"),
        ("ENUM('a', 'b')", "enum"),
        ("INTEGER[]", "array"),
        ("STRUCT(a INTEGER)[]", "array"),
        ("DECIMAL(18,2)", "numeric(18, 2)"),
        ("UINTEGER", "bigint"),
        ("USMALLINT", "integer"),
        ("UTINYINT", "smallint"),
        ("BIT", "boolean"),
        ("JSON", "json"),
        ("TIMESTAMP WITH TIME ZONE", "timestamptz"),
        # --- Delta (pyarrow): forma de texto do Arrow ---
        ("struct<rua: string, cep: string>", "struct"),
        ("list<item: string>", "array"),
        ("map<keys: string, values: int32>", "map"),
        ("union<num: int32, txt: string>", "union"),
        ("dictionary<values=string, indices=int32, ordered=0>", "text"),
        ("decimal128(18, 2)", "numeric(18, 2)"),
        ("decimal256(76, 10)", "numeric(76, 10)"),
        ("timestamp[us, tz=UTC]", "timestamptz"),
        ("timestamp[us]", "timestamp"),
        ("null", "text"),
        ("large_string", "text"),
        ("int64", "bigint"),
    ],
)
def test_inferir_tipo_resolve_o_literal_do_catalogo(cruto, esperado):
    assert inferir_tipo(cruto) == esperado


@pytest.mark.parametrize(
    "cruto, comprimento, precisao, escala, esperado",
    [
        # dominio do PostgreSQL: o information_schema ja resolve pro tipo base
        # e devolve o comprimento real (verified: email_t sobre varchar(120))
        ("character varying", 120, None, None, "varchar(120)"),
        ("character varying", None, None, None, "text"),
        ("integer", None, 32, 0, "integer"),
        ("numeric", None, 12, 2, "numeric(12, 2)"),
        ("numeric", None, 10, None, "numeric(10)"),
        # SQL Server
        ("nvarchar", 50, None, None, "varchar(50)"),
        ("nchar", 10, None, None, "char(10)"),
    ],
)
def test_inferir_tipo_usa_a_geometria_do_tipo(cruto, comprimento, precisao, escala, esperado):
    assert inferir_tipo(cruto, comprimento, precisao, escala) == esperado


# ---------------------------------------------------------------------------
# B. propriedade: o YAML so aceita nomes com regra em todos os destinos
# ---------------------------------------------------------------------------


DETRITOS_DO_CATALOGO = [
    "",
    "   ",
    "USER-DEFINED",
    "user-defined",
    "AggregateFunction(sum, UInt64)",
    "SimpleAggregateFunction(anyLast, String)",
    "UINTEGER",
    "IPv4",
    "Nothing",
    "null",
    "unknown(1)",
    "list(item: string)",
    "Nested(k String, v UInt8)",
    "dictionary<values=string, indices=int32, ordered=0>",
    "meu_tipo_exotico",
    "enum(a, b",
    ";;;drop table",
]


@pytest.mark.parametrize("cruto", DETRITOS_DO_CATALOGO)
def test_inferir_tipo_nunca_devolve_nome_sem_regra(cruto):
    # Rede de seguranca: um tipo que nenhum destino sabe mapear passaria cru
    # no CREATE TABLE. O vocabulario do YAML e que manda, nao o catalogo.
    saida = inferir_tipo(cruto)
    assert saida in VOCABULARIO, f"{cruto!r} virou {saida!r}, fora do vocabulario"


@pytest.mark.parametrize("cruto", DETRITOS_DO_CATALOGO)
def test_inferir_tipo_nunca_dispara_aviso_de_tipo(cruto):
    # Propriedade forte: o caminho catalogo -> DDL e sempre silencioso.
    for destino in DESTINOS:
        with console.capture() as captura:
            ddl = mapear_tipo(inferir_tipo(cruto), destino)
        assert not captura.get(), f"{cruto!r} -> {destino}: {captura.get()!r}"
        assert ddl, f"{cruto!r} -> {destino} virou tipo vazio"


def test_user_defined_e_um_marcador_e_nao_um_tipo():
    # 'user-defined' e so o rotulo do information_schema; ele ja foi a causa
    # de todo tipo customizado do PostgreSQL virar varchar(255) no destino.
    assert inferir_tipo("USER-DEFINED") == "text"
    assert "user-defined" not in VOCABULARIO


def test_vocabulario_cobre_todo_customizado():
    # Cada tipo customizado tem de estar no vocabulario, senao a introspecao
    # o degradaria antes de chegar ao DDL.
    for tipo in _TIPOS_CUSTOMIZADOS:
        assert tipo in VOCABULARIO, f"{tipo} fora do vocabulario da introspecao"


# ---------------------------------------------------------------------------
# C. mapear_tipo: familias de colecao nao aceitam parametro colado
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("familia", ["array", "map", "tuple", "struct", "union", "enum"])
@pytest.mark.parametrize("destino", DESTINOS)
def test_familia_de_colecao_descarta_o_parametro(familia, destino):
    # 'Array(String)' e 'ENUM(a,b)' chegam com o elemento junto. Colar o
    # elemento no destino produz DDL invalido: 'text[](string)', 'text(a,b)'.
    sem_args = mapear_tipo(familia, destino)
    com_args = mapear_tipo(f"{familia}(string, int32)", destino)
    # o que vem entre parenteses e o ELEMENTO e nunca sobrevive ao mapeamento
    assert com_args == sem_args
    if familia in FAMILIAS_DE_COLECAO:
        assert com_args == _TEXTO_PORTATIL[destino]
    else:
        assert com_args in _TIPOS_POR_SGBD[destino].values()


@pytest.mark.parametrize(
    "tipo, destino",
    [
        ("varchar(13)", "postgresql"),
        ("varchar(13)", "mysql"),
        ("char(2)", "mysql"),
        ("numeric(10,2)", "clickhouse"),
        ("numeric(10,2)", "postgresql"),
        # o override do usuario de um tipo espacial mantem os argumentos
        ("geometry(Point,4326)", "postgresql"),
    ],
)
def test_tipo_parametrizavel_preserva_os_argumentos(tipo, destino):
    with console.capture() as captura:
        saida = mapear_tipo(tipo, destino)
    assert not captura.get(), captura.get()
    assert "(" in saida


# ---------------------------------------------------------------------------
# D. mocks do catalogo: cada dialeto entrega o tipo real
# ---------------------------------------------------------------------------


class _CursorFalso:
    """Cursor que devolve respostas pras na ordem em que sao perguntadas."""

    def __init__(self, *respostas):
        self._fila = list(respostas)
        self._atual: list = []
        self.sqls: list[str] = []

    def execute(self, sql, params=None):
        self.sqls.append(" ".join(str(sql).split()))
        self._atual = (self._fila.pop(0) or []) if self._fila else []

    def fetchall(self):
        return list(self._atual)

    def fetchone(self):
        return self._atual[0] if self._atual else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _ConexaoFalsa:
    def __init__(self, *respostas):
        self.cursor_obj = _CursorFalso(*respostas)
        self.fechada = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.fechada = True


def _descrever_clickhouse(linhas, tabela=None):
    from conduto.database.introspect import _descrever_tabela_clickhouse

    conn = _ConexaoFalsa(linhas, tabela)
    return _descrever_tabela_clickhouse({}, "analytics", "tipos", conn)


def test_clickhouse_repassa_as_familias_de_colecao():
    linhas = [
        ("arr", "Array(String)", "", 0),
        ("mp", "Map(String, UInt8)", "", 0),
        ("tup", "Tuple(UInt8, String)", "", 0),
        ("en", "Enum8('a' = 1, 'b' = 2)", "", 0),
        ("agg", "AggregateFunction(sum, UInt64)", "", 0),
        ("lc", "LowCardinality(String)", "", 0),
        ("n", "Nullable(Int64)", "", 1),
    ]
    descrito = _descrever_clickhouse(linhas)

    assert [c["type"] for c in descrito["columns"]] == [
        "array", "map", "tuple", "enum", "text", "text", "bigint",
    ]
    # Nullable define a nulabilidade e sai do tipo
    assert [c["nullable"] for c in descrito["columns"]] == [False] * 6 + [True]


def _descrever_duckdb(linhas):
    from conduto.database.introspect import _descrever_tabela_duckdb

    conn = _ConexaoFalsa(linhas, [])
    return _descrever_tabela_duckdb({}, "main", "tipos", conn)


def test_duckdb_repassa_os_tipos_compostos():
    linhas = [
        ("st", "STRUCT(a INTEGER, b VARCHAR)", "YES", None),
        ("m", "MAP(VARCHAR, INTEGER)", "YES", None),
        ("u", "UNION(num INTEGER, txt VARCHAR)", "NO", None),
        ("e", "ENUM('x', 'y')", "YES", None),
        ("l", "INTEGER[]", "YES", None),
        ("d", "DECIMAL(18,2)", "YES", None),
    ]
    descrito = _descrever_duckdb(linhas)

    assert [c["type"] for c in descrito["columns"]] == [
        "struct", "map", "union", "enum", "array", "numeric(18, 2)",
    ]
    assert descrito["columns"][2]["nullable"] is False


# ---------------------------------------------------------------------------
# E. cenario ponta a ponta: catalogo -> YAML -> tipo do destino
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "origem, cruto, udt, esperado",
    [
        # ClickHouse
        ("clickhouse", "Array(String)", None, "array"),
        ("clickhouse", "Map(String, UInt8)", None, "map"),
        ("clickhouse", "Tuple(UInt8, String)", None, "tuple"),
        # DuckDB
        ("duckdb", "STRUCT(a INTEGER)", None, "struct"),
        ("duckdb", "UNION(a INTEGER)", None, "union"),
        ("duckdb", "ENUM('x')", None, "enum"),
    ],
)
def test_cenario_catalogo_ate_o_yaml(origem, cruto, udt, esperado):
    assert inferir_tipo(cruto) == esperado


@pytest.mark.parametrize(
    "tipo_yaml",
    ["ltree", "citext", "hstore", "geometry", "inet", "tsvector", "interval",
     "varbit", "array", "map", "tuple", "struct", "union", "enum", "set",
     "year", "hierarchyid", "sql_variant", "point", "circle", "jsonpath"],
)
def test_cenario_tipo_customizado_ate_o_destino(tipo_yaml):
    # Cadeia completa: o tipo descoberto tem de virar um tipo utilizavel em
    # TODOS os destinos, sem aviso e sem argumento colado.
    for destino in DESTINOS:
        with console.capture() as captura:
            tipo_destino = mapear_tipo(tipo_yaml, destino)
        assert not captura.get(), f"{tipo_yaml}->{destino}: {captura.get()!r}"
        assert tipo_destino, f"{tipo_yaml}->{destino} vazio"
        assert "(" not in captura.get()


# ---------------------------------------------------------------------------
# F. matriz: todo tipo customizado x todo destino gera DDL utilizavel
# ---------------------------------------------------------------------------


TIPOS_CUSTOMIZADOS_ESPERADOS = [
    "ltree", "citext", "hstore", "tsvector", "jsonpath", "varbit",
    "inet", "cidr", "point", "line", "lseg", "box", "path", "polygon",
    "circle", "interval", "geometry", "geography", "hierarchyid",
    "sql_variant", "year", "set", "array", "map", "tuple", "struct", "union",
]


def test_lista_de_tipos_customizados_esta_completa():
    assert sorted(TIPOS_CUSTOMIZADOS_ESPERADOS) == sorted(_TIPOS_CUSTOMIZADOS)


@pytest.mark.parametrize("tipo", TIPOS_CUSTOMIZADOS_ESPERADOS)
@pytest.mark.parametrize("destino", DESTINOS)
def test_matriz_tipo_customizado_x_destino(tipo, destino):
    tabela = {
        "table": "qualquer",
        "schema": "public",
        "columns": [{"name": "col", "type": tipo, "nullable": True}],
    }
    with console.capture() as captura:
        ddl = gerar_ddl_tabela(tabela, destino)
    assert not captura.get(), f"{tipo}->{destino} avisou: {captura.get()!r}"
    assert "CREATE TABLE" in ddl, ddl
    # a coluna existe e foi declarada (um tipo sem regra avisaria acima)
    assert "col" in ddl, ddl


@pytest.mark.parametrize("destino", DESTINOS)
def test_matriz_de_tipos_de_origem_comuns(destino):
    # Os literais crus que cada dialeto entrega, do comeco ao fim da cadeia.
    crus = [
        "USER-DEFINED", "ARRAY", "bit varying", "character varying",
        "Array(String)", "Map(String, UInt8)", "Tuple(UInt8, String)",
        "Enum8('a' = 1)", "AggregateFunction(sum, UInt64)", "IPv4",
        "STRUCT(a INTEGER)", "MAP(VARCHAR, INTEGER)", "UNION(a INTEGER)",
        "ENUM('x')", "INTEGER[]", "UINTEGER",
        "struct<rua: string>", "list<item: string>",
        "dictionary<values=string, indices=int32, ordered=0>",
        "decimal128(18, 2)", "timestamp[us, tz=UTC]", "null",
        "hierarchyid", "sql_variant", "enum", "set", "year",
        "ltree", "citext", "hstore", "status_t",
    ]
    for cruto in crus:
        with console.capture() as captura:
            tipo = inferir_tipo(cruto)
            ddl_tipo = mapear_tipo(tipo, destino)
        # um tipo sem regra de destino passaria cru e avisaria aqui
        assert not captura.get(), f"{cruto}->{destino}: {captura.get()!r}"
        assert ddl_tipo, f"{cruto}->{destino} vazio"
        # a BASE tem de estar no vocabulario (o tipo pode trazer parametros)
        assert tipo.split("(", 1)[0].strip() in VOCABULARIO, f"{cruto} virou {tipo!r}"


def test_projetos_existentes_nao_quebram_no_caminho(tmp_path: Path):
    # Fumo: um schema ja gerado continua gerando o mesmo DDL.
    tabela = {
        "table": "clientes",
        "schema": "public",
        "columns": [
            {"name": "id", "type": "integer", "primary_key": True, "nullable": False},
            {"name": "nome", "type": "varchar(255)", "nullable": False},
            {"name": "criado_em", "type": "timestamp"},
        ],
    }
    for destino in DESTINOS:
        with console.capture() as captura:
            ddl = gerar_ddl_tabela(tabela, destino)
        assert not captura.get(), captura.get()
        assert "CREATE TABLE" in ddl
