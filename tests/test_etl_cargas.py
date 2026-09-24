"""Testes das cargas do template ETL: CAST pelo catalogo e caminhos de copia.

Caso relatado: a carga do Production.Document (SQL Server -> ClickHouse) morria
no ``fetchmany`` com "ODBC SQL type -151 is not yet supported". O CAST que
existia era codigo morto: no pyodbc 5.x ``cur.description`` devolve o tipo do
Python (``<class 'bytearray'>``) em vez do codigo ODBC, entao a checagem
``isinstance(tipo, int) and tipo < 0`` nunca era verdadeira. A defesa agora
pergunta ao catalogo (``sys.columns``/``sys.types``) qual e o tipo de cada
coluna -- aqui testada com cursor falso que, de proposito, nao tem
``description`` nenhum.
"""

import datetime
import json
import queue
import tempfile
import unittest
from pathlib import Path


TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "conduto" / "templates"
    / "dagster" / "conduto_dagster" / "etl.py.jinja"
)

_ENV_BASE = {
    "DB_ORIGEM_TYPE": "sqlserver",
    "DB_ORIGEM_HOST": "host", "DB_ORIGEM_PORT": "1433",
    "DB_ORIGEM_NAME": "banco", "DB_ORIGEM_USER": "u", "DB_ORIGEM_PASSWORD": "p",
    "DB_ORIGEM_SCHEMA": "dbo",
    "DB_DESTINO_TYPE": "mysql",
    "DB_DESTINO_HOST": "host", "DB_DESTINO_PORT": "3303",
    "DB_DESTINO_NAME": "banco", "DB_DESTINO_USER": "u", "DB_DESTINO_PASSWORD": "p",
    "DB_DESTINO_SCHEMA": "destino",
}


def _carregar_modulo_template():
    """Renderiza o jinja com um project_name fixo e executa como modulo Python."""
    texto = TEMPLATE_PATH.read_text(encoding="utf-8")
    texto = texto.replace("{{ project_name }}", "projeto_teste")
    namespace = {"__name__": "conduto_dagster_etl_teste", "__file__": str(TEMPLATE_PATH)}
    exec(compile(texto, str(TEMPLATE_PATH), "exec"), namespace)
    return namespace


def _fila(modulo, colunas, *lotes):
    """Fila no formato que os consumidores esperam: colunas, lotes e o _FIM."""
    fila = queue.Queue()
    fila.put(colunas)
    for lote in lotes:
        fila.put(lote)
    fila.put(modulo["_FIM"])
    return fila


def _consumir(fila, fim):
    """Esvazia a fila ate o _FIM, devolvendo o que o produtor colocou nela."""
    itens = []
    while True:
        item = fila.get_nowait()
        if item is fim:
            return itens
        itens.append(item)


def _criar_delta(pasta, nome="clientes", linhas=5000):
    """Grava uma tabela Delta real (id, stamped e nome) para os testes lerem."""
    import pyarrow as pa
    from deltalake import write_deltalake

    caminho = str(Path(pasta) / nome)
    inicio = datetime.datetime(2026, 1, 1)
    write_deltalake(
        caminho,
        pa.table({
            "id": pa.array(range(linhas), pa.int32()),
            "stamped": pa.array(
                [inicio + datetime.timedelta(minutes=i) for i in range(linhas)],
                pa.timestamp("us"),
            ),
            "nome": pa.array([f"cliente {i}" for i in range(linhas)]),
        }),
        mode="append",
    )
    return caminho


# --------------------------------------------------------------------------
# Falsos: catalogo do SQL Server
# --------------------------------------------------------------------------


class _CursorCatalogo:
    """Cursor que so responde a consulta de catalogo.

    De proposito nao expoe ``description``: se o codigo voltar a ler o
    ``description`` do pyodbc (o bug do -151), ele quebra aqui em vez de passar
    despercebido com um tipo do Python no lugar do codigo ODBC.
    """

    def __init__(self, tipos=()):
        self.tipos = list(tipos)
        self.sqls = []
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sqls.append(sql)
        self.params = params

    def fetchall(self):
        return list(self.tipos)


class _ConexaoCatalogo:
    def __init__(self, tipos=()):
        self.cursor_obj = _CursorCatalogo(tipos)

    def cursor(self):
        return self.cursor_obj

    def close(self):
        pass


# --------------------------------------------------------------------------
# Falsos: gravacao (COPY, executemany e lote com falha)
# --------------------------------------------------------------------------


class _CopiaFalsa:
    """Contexto de COPY: aceita ``write()`` e tambem funciona como iterador."""

    def __init__(self, blocos=(), escritas=None):
        self._blocos = blocos
        self._escritas = escritas

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._blocos)

    def write(self, bloco):
        if self._escritas is not None:
            self._escritas.append(bytes(bloco))


class _CursorGravador:
    fast_executemany = False

    def __init__(self, conn, blocos=(), falhas_executemany=0):
        self._conn = conn
        self._blocos = blocos
        self._falhas = falhas_executemany

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def copy(self, sql, params=None):
        self._conn.copy_calls.append((sql, params))
        return _CopiaFalsa(self._blocos, self._conn.copy_writes)

    def executemany(self, sql, valores):
        # Registra o modo da vez: prova que o fallback desligou o
        # fast_executemany depois da primeira rejeicao do lote.
        self._conn.fast_flags.append(self.fast_executemany)
        if self._falhas:
            self._falhas -= 1
            raise RuntimeError("lote rejeitado pelo banco")
        self._conn.executemany_calls.append((sql, valores))


class _ConexaoGravadora:
    """Conexao falsa que registra COPY, executemany, commits e rollbacks."""

    def __init__(self, blocos=(), falhas_executemany=0):
        self.blocos = blocos
        self.falhas_executemany = falhas_executemany
        self.copy_calls = []
        self.copy_writes = []
        self.executemany_calls = []
        self.fast_flags = []
        self.commits = 0
        self.rollbacks = 0
        self.cursor_atual = None

    def cursor(self):
        self.cursor_atual = _CursorGravador(
            self, self.blocos, self.falhas_executemany
        )
        return self.cursor_atual

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


# --------------------------------------------------------------------------
# Falsos: clickhouse, duckdb e delta
# --------------------------------------------------------------------------


class _ClienteClickHouse:
    def __init__(self):
        self.inseridos = []

    def insert(self, tabela, linhas, column_names=None):
        self.inseridos.append((tabela, [tuple(l) for l in linhas], column_names))


class _ConexaoClickHouse:
    def __init__(self):
        self._client = _ClienteClickHouse()


class _ConexaoDuckDB:
    def __init__(self):
        self.sqls = []
        self.tabelas_registradas = []
        self.commits = 0
        self.nominais = {}

    def register(self, nome, tabela):
        self.nominais[nome] = tabela

    def unregister(self, nome):
        self.nominais.pop(nome, None)

    def execute(self, sql):
        self.sqls.append(sql)
        self.tabelas_registradas.append(self.nominais.get("_lote_conduto"))

    def commit(self):
        self.commits += 1


class _ConexaoDelta:
    def __init__(self, base):
        self.base = base
        self.storage_options = {}

    def cursor(self):
        raise AssertionError("Delta Lake nao usa cursor.")

    def close(self):
        pass


# ==========================================================================
# A. CAST decidido pelo catalogo
# ==========================================================================


class TestCastPeloCatalogo(unittest.TestCase):
    def test_casta_os_tipos_que_o_pyodbc_nao_busca(self):
        modulo = _carregar_modulo_template()
        for tipo in ("hierarchyid", "geometry", "geography", "sql_variant"):
            with self.subTest(tipo=tipo):
                conn = _ConexaoCatalogo([("DocumentNode", tipo)])
                expressoes = modulo["_cols_select_sqlserver"](
                    conn, "[Production].[Document]", ["DocumentNode"]
                )
                self.assertEqual(
                    expressoes,
                    ["CAST([DocumentNode] AS NVARCHAR(MAX)) AS [DocumentNode]"],
                )

    def test_nao_casta_tipos_que_o_driver_busca(self):
        modulo = _carregar_modulo_template()
        colunas = ["DocumentID", "Titulo", "Resumo", "Binario", "Data", "Flag"]
        conn = _ConexaoCatalogo([
            ("DocumentID", "int"),
            ("Titulo", "nvarchar"),
            ("Resumo", "xml"),
            ("Binario", "varbinary"),
            ("Data", "datetime"),
            # UDT do SQL Server (dbo.Flag): o catalogo devolve o tipo base e o
            # driver le o valor direto, sem cast.
            ("Flag", "nchar"),
        ])
        expressoes = modulo["_cols_select_sqlserver"](
            conn, "[Production].[Document]", colunas
        )
        self.assertEqual(expressoes, [f"[{c}]" for c in colunas])

    def test_cast_so_nas_colunas_que_precisam(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoCatalogo([
            ("DocumentID", "int"),
            ("DocumentNode", "hierarchyid"),
            ("Titulo", "nvarchar"),
        ])
        expressoes = modulo["_cols_select_sqlserver"](
            conn, "[Production].[Document]", ["DocumentID", "DocumentNode", "Titulo"]
        )
        self.assertEqual(expressoes[0], "[DocumentID]")
        self.assertTrue(expressoes[1].startswith("CAST("))
        self.assertEqual(expressoes[2], "[Titulo]")

    def test_regressao_nao_le_o_description_do_pyodbc(self):
        # O cursor falso nao tem ``description``. O codigo antigo lia esse
        # atributo e com ele um tipo do Python, entao o CAST nunca disparava.
        modulo = _carregar_modulo_template()
        conn = _ConexaoCatalogo([("DocumentNode", "hierarchyid")])

        expressoes = modulo["_cols_select_sqlserver"](
            conn, "[Production].[Document]", ["DocumentNode"]
        )

        self.assertIn("CAST", expressoes[0])
        self.assertFalse(hasattr(conn.cursor_obj, "description"))
        self.assertIn("sys.columns", conn.cursor_obj.sqls[0])
        self.assertIn("OBJECT_ID(?)", conn.cursor_obj.sqls[0])

    def test_passa_o_nome_qualificado_como_parametro(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoCatalogo([("DocumentNode", "hierarchyid")])

        modulo["_cols_select_sqlserver"](conn, "[Production].[Document]", ["Titulo"])

        # Parametrizado: nome de tabela vindo do YAML nao pode entrar no SQL.
        self.assertEqual(conn.cursor_obj.params, ("[Production].[Document]",))

    def test_tabela_inexistente_nao_casta_e_nao_quebra(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoCatalogo()  # catalogo devolve vazio

        expressoes = modulo["_cols_select_sqlserver"](
            conn, "[dbo].[NaoExiste]", ["Titulo"]
        )

        self.assertEqual(expressoes, ["[Titulo]"])

    def test_coluna_fora_do_catalogo_passa_cru(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoCatalogo([("DocumentNode", "hierarchyid")])

        expressoes = modulo["_cols_select_sqlserver"](
            conn, "[Production].[Document]", ["Titulo"]
        )

        self.assertEqual(expressoes, ["[Titulo]"])

    def test_lista_de_tipos_do_driver_esta_completa(self):
        # A limitacao e do pyodbc, nao do schema: esses 4 tipos derrubam o
        # fetch com HY106 e por isso tem de estar na lista.
        modulo = _carregar_modulo_template()
        self.assertEqual(
            set(modulo["_TIPOS_ODBC_NAO_SUPORTADOS"]),
            {"hierarchyid", "geometry", "geography", "sql_variant"},
        )


# ==========================================================================
# B. Caminhos de copia por destino
# ==========================================================================


class TestCaminhosDeCarga(unittest.TestCase):
    def test_despacha_para_a_funcao_do_destino(self):
        esperado = {
            "clickhouse": "_copiar_clickhouse",
            "duckdb": "_copiar_duckdb",
            "deltalake": "_copiar_delta",
        }
        for tipo, funcao in esperado.items():
            with self.subTest(tipo=tipo):
                modulo = _carregar_modulo_template()
                chamado = {}

                def _falso(*args, **kwargs):
                    chamado["nome"] = funcao
                    return 7

                modulo[funcao] = _falso
                total = modulo["_copiar"](object(), tipo, "tabela", queue.Queue())
                self.assertEqual(chamado["nome"], funcao)
                self.assertEqual(total, 7)

    def test_sqlserver_usa_fast_executemany_e_placeholder_de_interrogacao(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoGravadora()
        fila = _fila(modulo, ["ID", "Nome"], [(1, "Ana")])

        total = modulo["_copiar"](conn, "sqlserver", "[dbo].[clientes]", fila)

        self.assertEqual(total, 1)
        sql, valores = conn.executemany_calls[0]
        self.assertEqual(
            sql, "INSERT INTO [dbo].[clientes] ([ID], [Nome]) VALUES (?, ?)"
        )
        self.assertEqual(valores, [(1, "Ana")])
        self.assertEqual(conn.fast_flags, [True])
        self.assertEqual(conn.commits, 2)  # um por lote + o final

    def test_mysql_usa_percent_s_sem_fast_executemany(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoGravadora()
        fila = _fila(modulo, ["ID", "Nome"], [(1, "Ana")])

        total = modulo["_copiar"](conn, "mysql", "`destino`.`clientes`", fila)

        self.assertEqual(total, 1)
        sql, _ = conn.executemany_calls[0]
        self.assertEqual(
            sql, "INSERT INTO `destino`.`clientes` (`ID`, `Nome`) VALUES (%s, %s)"
        )
        self.assertEqual(conn.fast_flags, [False])

    def test_fallback_desliga_fast_executemany_quando_o_lote_falha(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoGravadora(falhas_executemany=1)
        fila = _fila(modulo, ["ID", "Nome"], [(1, "Ana")])

        total = modulo["_copiar"](conn, "sqlserver", "[dbo].[clientes]", fila)

        # 1a tentativa com fast (falhou), rollback e retry sem fast.
        self.assertEqual(conn.fast_flags, [True, False])
        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(total, 1)
        self.assertEqual(len(conn.executemany_calls), 1)

    def test_colunas_vazias_nao_abre_cursor(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoGravadora()
        fila = _fila(modulo, [])

        total = modulo["_copiar"](conn, "sqlserver", "[dbo].[clientes]", fila)

        self.assertEqual(total, 0)
        self.assertIsNone(conn.cursor_atual)

    def test_erro_do_produtor_na_primeira_posicao_propaga(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoGravadora()
        fila = queue.Queue()
        fila.put(RuntimeError("origem caiu"))

        with self.assertRaises(RuntimeError):
            modulo["_copiar"](conn, "sqlserver", "[dbo].[clientes]", fila)

    def test_erro_do_produtor_no_meio_da_carga_propaga(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoGravadora()
        fila = queue.Queue()
        fila.put(["ID"])
        fila.put(RuntimeError("origem caiu"))
        fila.put(modulo["_FIM"])

        with self.assertRaises(RuntimeError):
            modulo["_copiar"](conn, "sqlserver", "[dbo].[clientes]", fila)
        self.assertEqual(conn.rollbacks, 0)

    def test_clickhouse_recebe_as_linhas_em_lote_com_nome_limpo(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoClickHouse()
        fila = _fila(modulo, ["ID", "Nome"], [(1, "Ana"), (2, "Bia")])

        total = modulo["_copiar"](
            conn, "clickhouse", "`analytics_raw`.`clientes`", fila
        )

        self.assertEqual(total, 2)
        self.assertEqual(len(conn._client.inseridos), 1)
        tabela, linhas, nomes = conn._client.inseridos[0]
        self.assertEqual(tabela, "analytics_raw.clientes")
        self.assertEqual(nomes, ["ID", "Nome"])
        self.assertEqual(linhas, [(1, "Ana"), (2, "Bia")])

    def test_clickhouse_coage_bool_para_texto_quando_o_schema_manda(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoClickHouse()
        tabela = {
            "table": "clientes",
            "columns": [
                {"name": "Nome", "type": "varchar"},
                {"name": "Ativo", "type": "tinyint"},
            ],
        }
        # Origem (TINYINT(1) do MySQL) entrega bool para a coluna de texto e o
        # driver do ClickHouse so aceita str/bytes em String.
        fila = _fila(modulo, ["Nome", "Ativo"], [(True, 1)])

        total = modulo["_copiar"](conn, "clickhouse", "`clientes`", fila, None, tabela)

        self.assertEqual(total, 1)
        _, linhas, _ = conn._client.inseridos[0]
        # Só a coluna de texto (indice 0) foi coerida; a tinyint ficou int.
        self.assertEqual(linhas, [("True", 1)])

    def test_clickhouse_recebe_date_como_data_e_nao_como_texto(self):
        """Regressao: `date` virava str e o driver estourava em coluna Date.

        O `clickhouse_connect` serializa Date em binario com
        `(valor - epoch).days`; uma str nao subtrai datetime.date, entao o
        comando inteiro morria com
        `TypeError: unsupported operand type(s) for -: 'str' and 'datetime.date'`.
        """
        modulo = _carregar_modulo_template()
        conn = _ConexaoClickHouse()
        tabela = {
            "table": "clientes",
            "columns": [
                {"name": "Nome", "type": "varchar"},
                {"name": "Nascimento", "type": "date"},
            ],
        }
        nascimento = datetime.date(1990, 5, 17)
        fila = _fila(modulo, ["Nome", "Nascimento"], [("Ana", nascimento)])

        total = modulo["_copiar"](conn, "clickhouse", "`clientes`", fila, None, tabela)

        self.assertEqual(total, 1)
        _, linhas, _ = conn._client.inseridos[0]
        # A coluna de texto segue str; a de data chega como objeto de verdade.
        self.assertEqual(linhas, [("Ana", nascimento)])
        self.assertIsInstance(linhas[0][1], datetime.date)

    def test_clickhouse_coage_date_para_texto_quando_o_schema_manda(self):
        """O inverso da regressao: coluna de texto pede str, mesmo vindo de date.

        Sem isto, preservar o `date` trocava o TypeError por
        `AttributeError: 'datetime.date' object has no attribute 'encode'`.
        """
        modulo = _carregar_modulo_template()
        conn = _ConexaoClickHouse()
        tabela = {
            "table": "clientes",
            "columns": [{"name": "Cadastro", "type": "varchar"}],
        }
        fila = _fila(modulo, ["Cadastro"], [(datetime.date(1990, 5, 17),)])

        total = modulo["_copiar"](conn, "clickhouse", "`clientes`", fila, None, tabela)

        self.assertEqual(total, 1)
        _, linhas, _ = conn._client.inseridos[0]
        self.assertEqual(linhas, [("1990-05-17",)])
        self.assertIsInstance(linhas[0][0], str)

    def test_clickhouse_coage_datetime_para_texto_quando_o_schema_manda(self):
        """`datetime` em coluna de texto tambem tem de virar str."""
        modulo = _carregar_modulo_template()
        conn = _ConexaoClickHouse()
        tabela = {
            "table": "clientes",
            "columns": [{"name": "Atualizado", "type": "text"}],
        }
        momento = datetime.datetime(2026, 9, 22, 10, 30, 0)
        fila = _fila(modulo, ["Atualizado"], [(momento,)])

        modulo["_copiar"](conn, "clickhouse", "`clientes`", fila, None, tabela)

        _, linhas, _ = conn._client.inseridos[0]
        self.assertEqual(linhas, [("2026-09-22 10:30:00",)])

    def test_duckdb_registra_a_tabela_arrow_e_desregistra(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoDuckDB()
        fila = _fila(modulo, ["ID", "Nome"], [(1, "Ana"), (2, "Bia")])

        total = modulo["_copiar"](conn, "duckdb", '"public"."clientes"', fila)

        self.assertEqual(total, 2)
        self.assertEqual(
            conn.sqls, ['INSERT INTO "public"."clientes" SELECT * FROM _lote_conduto']
        )
        self.assertEqual(conn.nominais, {})  # sempre desregistrada
        self.assertEqual(conn.commits, 1)
        linhas = conn.tabelas_registradas[0].to_pylist()
        self.assertEqual(linhas, [{"ID": 1, "Nome": "Ana"}, {"ID": 2, "Nome": "Bia"}])

    def test_delta_grava_os_lotes_em_arquivo(self):
        modulo = _carregar_modulo_template()
        fila = _fila(modulo, ["ID", "Nome"], [(1, "Ana"), (2, "Bia")])

        with tempfile.TemporaryDirectory() as pasta:
            conn = _ConexaoDelta(pasta)
            total = modulo["_copiar"](conn, "deltalake", "clientes", fila)

            self.assertEqual(total, 2)
            from deltalake import DeltaTable

            gravada = DeltaTable(f"{pasta}/clientes").to_pyarrow_table()
            self.assertEqual(gravada.num_rows, 2)
            self.assertEqual(gravada.column_names, ["ID", "Nome"])

    def test_postgres_upsert_sem_pk_volta_para_o_copy(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoGravadora()
        tabela = {"table": "clientes", "columns": [{"name": "ID", "type": "integer"}]}
        fila = _fila(modulo, ["ID"], [(1,)])

        total = modulo["_copiar_postgres_upsert"](
            conn, '"public"."clientes"', tabela, fila
        )

        self.assertEqual(total, 1)
        self.assertEqual(len(conn.copy_calls), 1)
        self.assertIn("COPY", conn.copy_calls[0][0])
        self.assertEqual(conn.executemany_calls, [])

    def test_postgres_upsert_so_com_pk_vai_para_do_nothing(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoGravadora()
        tabela = {"table": "clientes", "columns": [
            {"name": "ID", "type": "integer", "primary_key": True},
        ]}
        fila = _fila(modulo, ["ID"], [(1,)])

        total = modulo["_copiar_postgres_upsert"](
            conn, '"public"."clientes"', tabela, fila
        )

        self.assertEqual(total, 1)
        sql, _ = conn.executemany_calls[0]
        self.assertIn("ON CONFLICT", sql)
        self.assertIn("DO NOTHING", sql)
        self.assertNotIn("DO UPDATE", sql)

    def test_postgres_upsert_atualiza_os_campos_fora_da_pk(self):
        modulo = _carregar_modulo_template()
        conn = _ConexaoGravadora()
        tabela = {"table": "clientes", "columns": [
            {"name": "ID", "type": "integer", "primary_key": True},
            {"name": "Nome", "type": "varchar(50)"},
        ]}
        fila = _fila(modulo, ["ID", "Nome"], [(1, "Ana")])

        modulo["_copiar_postgres_upsert"](
            conn, '"public"."clientes"', tabela, fila
        )

        sql, _ = conn.executemany_calls[0]
        self.assertIn("DO UPDATE SET", sql)
        self.assertIn('"Nome" = EXCLUDED."Nome"', sql)
        self.assertNotIn('"ID" = EXCLUDED."ID"', sql)

    def test_pg_para_pg_repassa_os_blocos_e_conta_as_linhas(self):
        modulo = _carregar_modulo_template()
        origem = _ConexaoGravadora(blocos=(b"1\tAna\n2\tBia\n", b"3\tCeu\n"))
        destino = _ConexaoGravadora()

        total = modulo["_carregar_pg_para_pg"](
            origem, destino, '"public"."clientes"', ["ID", "Nome"],
            "SELECT [ID] FROM origem", None,
        )

        self.assertEqual(total, 3)  # contagem pelos \n de cada bloco
        self.assertEqual(
            destino.copy_writes, [b"1\tAna\n2\tBia\n", b"3\tCeu\n"]
        )
        self.assertIn("COPY (SELECT", origem.copy_calls[0][0])
        self.assertEqual(destino.commits, 1)


# ==========================================================================
# C. Serializacao dos valores
# ==========================================================================


class TestSerializacaoDaCarga(unittest.TestCase):
    def test_valor_copy_para_os_casos_de_borda(self):
        modulo = _carregar_modulo_template()
        valor = modulo["_valor_copy"]
        self.assertEqual(valor(None), "\\N")
        self.assertEqual(valor(True), "t")
        self.assertEqual(valor(False), "f")
        self.assertEqual(valor(1), "1")
        self.assertEqual(valor("texto"), "texto")

    def test_valor_copy_escapa_separadores_do_copy(self):
        modulo = _carregar_modulo_template()
        self.assertEqual(modulo["_valor_copy"]("a\tb"), "a\\tb")
        self.assertEqual(modulo["_valor_copy"]("a\nb"), "a\\nb")
        self.assertEqual(modulo["_valor_copy"]("a\rb"), "a\\rb")
        self.assertEqual(modulo["_valor_copy"]("a\\b"), "a\\\\b")

    def test_valor_copy_remove_nul_e_jsona_dict_e_bytes(self):
        modulo = _carregar_modulo_template()
        valor = modulo["_valor_copy"]
        self.assertEqual(valor("a\x00b"), "ab")
        self.assertEqual(valor({"x": 1}), json.dumps({"x": 1}))
        # O backslash do prefixo \\x tambem e escapado: o COPY desfaz o \\
        # e entrega \\x0102 para o bytea ler como hexa. Com uma barra so o
        # proprio COPY consumia o escape e o valor chegava errado.
        self.assertEqual(valor(b"\x01\x02"), "\\\\x0102")

    def test_bloco_copy_uma_linha_por_registro(self):
        modulo = _carregar_modulo_template()
        bloco = modulo["_bloco_copy"]([("Ana", 1), ("B\x00ia", None)])
        self.assertEqual(bloco, b"Ana\t1\nBia\t\\N\n")

    def test_serializar_converte_dict_e_passa_date_e_datetime(self):
        """Date e datetime passam como objeto: o ClickHouse exige `datetime.date`.

        String so no COPY (via `_valor_copy`), que serializa em texto por ser
        um protocolo textual — nos drivers de objeto a data tem de chegar
        como data, ou o binario de Date do `clickhouse_connect` estoura.
        """
        modulo = _carregar_modulo_template()
        serializar = modulo["_serializar"]
        self.assertEqual(serializar({"x": 1}), '{"x": 1}')
        self.assertEqual(serializar([1, 2]), "[1, 2]")

        momento = datetime.datetime(2026, 9, 22, 10, 0, 0)
        self.assertIs(serializar(momento), momento)  # datetime passa direto

        nascimento = datetime.date(1990, 5, 17)
        self.assertIs(serializar(nascimento), nascimento)  # date tambem

        # ...mas um texto de data continua texto (origem ja em varchar)
        self.assertEqual(serializar("1990-05-17"), "1990-05-17")

    def test_serializar_remove_nul_e_stringiza_o_desconhecido(self):
        modulo = _carregar_modulo_template()
        serializar = modulo["_serializar"]
        self.assertEqual(serializar("a\x00b"), "ab")
        self.assertEqual(serializar(1), 1)
        self.assertIsNone(serializar(None))

        class _Coisa:
            def __str__(self):
                return "coisa"

        self.assertEqual(serializar(_Coisa()), "coisa")

    def test_sanitizar_remove_nul_de_aninhamentos_inteiros(self):
        modulo = _carregar_modulo_template()
        limpo = modulo["_sanitizar"](
            {"a": ["x\x00y", {"b": "c\x00d"}], "n": 3}
        )
        self.assertEqual(limpo, {"a": ["xy", {"b": "cd"}], "n": 3})


# ==========================================================================
# D. Modos de carga (schedule)
# ==========================================================================


class TestModosDeCarga(unittest.TestCase):
    """As chaves de ``schedule`` decidem se trunca e qual SELECT vai rodar."""

    def _carga(
        self, schedule, watermark=None, colunas=None, tipos=(), colunas_schema=None
    ):
        modulo = _carregar_modulo_template()
        env = dict(_ENV_BASE)
        capturado = {"truncacoes": 0}
        modulo["ler_env"] = lambda: env
        modulo["conectar"] = lambda *a, **k: _ConexaoCatalogo(tipos)
        modulo["_colunas_origem"] = lambda conn, tipo, origem: list(
            colunas if colunas is not None else ["ID", "Nome"]
        )
        modulo["_truncar"] = lambda *a: capturado.__setitem__(
            "truncacoes", capturado["truncacoes"] + 1
        )
        modulo["_ultimo_valor"] = lambda *a: watermark

        def _falso_produtor(conn, sql, params, fila, lote=None):
            capturado["sql"] = sql
            capturado["params"] = params
            fila.put(["ID", "Nome"])
            fila.put(modulo["_FIM"])

        modulo["_produtor"] = _falso_produtor
        modulo["_copiar"] = lambda *a, **k: 1

        # colunas_schema = o que o YAML permite (filtro); colunas = o que a
        # origem tem. Separados para poder testar a filtragem.
        if colunas_schema is None:
            colunas_schema = ["ID", "Nome"]
        tabela = {
            "table": "clientes",
            "schema": "destino",
            "source_schema": "vendas",
            "schedule": schedule,
            "columns": [
                {
                    "name": nome,
                    "type": "integer",
                    "primary_key": nome == "ID",
                }
                for nome in colunas_schema
            ],
        }
        capturado["total"] = modulo["carregar_tabela"](tabela)
        return capturado

    def test_full_trunca_e_carrega_tudo(self):
        carga = self._carga({"mode": "full"})
        self.assertEqual(carga["truncacoes"], 1)
        self.assertEqual(
            carga["sql"], "SELECT [ID], [Nome] FROM [vendas].[clientes]"
        )
        self.assertIsNone(carga["params"])
        self.assertEqual(carga["total"], 1)

    def test_sem_schedule_o_padrao_e_full(self):
        carga = self._carga({})
        self.assertEqual(carga["truncacoes"], 1)
        self.assertIsNone(carga["params"])

    def test_incremental_com_watermark_so_busca_o_que_e_novo(self):
        carga = self._carga(
            {"mode": "incremental", "incremental_column": "ID"}, watermark=100
        )
        self.assertEqual(carga["truncacoes"], 0)
        self.assertEqual(
            carga["sql"],
            "SELECT [ID], [Nome] FROM [vendas].[clientes] "
            "WHERE [ID] > ? ORDER BY [ID]",
        )
        self.assertEqual(carga["params"], [100])

    def test_incremental_sem_watermark_carrega_tudo_sem_truncar(self):
        carga = self._carga(
            {"mode": "incremental", "incremental_column": "ID"}, watermark=None
        )
        self.assertEqual(carga["truncacoes"], 0)
        self.assertNotIn("WHERE", carga["sql"])
        self.assertIsNone(carga["params"])

    def test_truncate_em_carga_incremental_limpa_antes(self):
        carga = self._carga(
            {
                "mode": "incremental",
                "incremental_column": "ID",
                "truncate": True,
            },
            watermark=100,
        )
        self.assertEqual(carga["truncacoes"], 1)
        self.assertIn("WHERE [ID] > ?", carga["sql"])

    def test_full_load_forca_full_e_ignora_o_watermark(self):
        carga = self._carga(
            {
                "mode": "incremental",
                "incremental_column": "ID",
                "full_load": True,
            },
            watermark=100,
        )
        self.assertEqual(carga["truncacoes"], 1)
        self.assertNotIn("WHERE", carga["sql"])
        self.assertIsNone(carga["params"])

    def test_incremental_sem_coluna_decremento_vira_full_sem_truncar(self):
        carga = self._carga({"mode": "incremental"}, watermark=100)
        self.assertEqual(carga["truncacoes"], 0)  # so trunca com truncate/full
        self.assertNotIn("WHERE", carga["sql"])
        self.assertIsNone(carga["params"])

    def test_colunas_fora_do_schema_nao_vao_para_o_select(self):
        carga = self._carga(
            {"mode": "full"}, colunas=["ID", "Nome", "Removida"]
        )
        self.assertNotIn("Removida", carga["sql"])

    def test_origem_sqlserver_manda_castar_os_tipos_do_catalogo(self):
        carga = self._carga(
            {"mode": "full"},
            colunas=["ID", "Nodo"],
            colunas_schema=["ID", "Nodo"],
            tipos=[("ID", "int"), ("Nodo", "hierarchyid")],
        )
        self.assertIn("CAST([Nodo] AS NVARCHAR(MAX)) AS [Nodo]", carga["sql"])
        self.assertIn("[ID], CAST(", carga["sql"])


# ==========================================================================
# E. Origem Delta (leitura em lote e carga incremental)
# ==========================================================================


class TestOrigemDelta(unittest.TestCase):
    """A origem Delta nao abre cursor: aqui moram os 3 bugs conhecidos.

    1. o WHERE do watermark era montado e descartado -- a carga incremental
       recarregava a tabela inteira;
    2. ``to_pyarrow_table()`` levava a tabela inteira para a memoria (OOM);
    3. ``_ultimo_valor`` fazia ``to_pylist()`` da coluna inteira so pro max.
    """

    def test_produtor_delta_parte_a_carga_em_lotes(self):
        modulo = _carregar_modulo_template()
        with tempfile.TemporaryDirectory() as pasta:
            _criar_delta(pasta, linhas=5000)
            fila = queue.Queue()

            modulo["_produtor_delta"](_ConexaoDelta(pasta), "clientes", fila, 500)
            itens = _consumir(fila, modulo["_FIM"])

        colunas, *lotes = itens
        self.assertEqual(colunas, ["id", "stamped", "nome"])
        self.assertGreater(len(lotes), 1)  # partido, nao um bloco so
        self.assertEqual(sum(len(l) for l in lotes), 5000)
        self.assertTrue(all(len(l) <= 500 for l in lotes))

    def test_produtor_delta_aplica_o_filtro_incremental(self):
        modulo = _carregar_modulo_template()
        with tempfile.TemporaryDirectory() as pasta:
            _criar_delta(pasta, linhas=5000)
            fila = queue.Queue()
            filtro = modulo["_filtro_delta"]("id", 2500)

            modulo["_produtor_delta"](
                _ConexaoDelta(pasta), "clientes", fila, 500, None, filtro
            )
            itens = _consumir(fila, modulo["_FIM"])

        colunas, *lotes = itens
        ids = [linha[0] for lote in lotes for linha in lote]
        self.assertEqual(len(ids), 2499)  # so o que passa no >
        self.assertTrue(all(i > 2500 for i in ids))

    def test_produtor_delta_pula_os_lotes_vazios_do_scanner(self):
        # Com filtro o scanner entrega lote vazio junto com o cheio, e um lote
        # vazio viraria uma linha em branco no COPY do Postgres.
        modulo = _carregar_modulo_template()
        with tempfile.TemporaryDirectory() as pasta:
            _criar_delta(pasta, linhas=5000)
            fila = queue.Queue()
            filtro = modulo["_filtro_delta"]("id", 2500)

            modulo["_produtor_delta"](
                _ConexaoDelta(pasta), "clientes", fila, 500, None, filtro
            )
            itens = _consumir(fila, modulo["_FIM"])

        _, *lotes = itens
        self.assertTrue(all(len(l) > 0 for l in lotes))

    def test_produtor_delta_respeita_as_colunas_permitidas(self):
        modulo = _carregar_modulo_template()
        with tempfile.TemporaryDirectory() as pasta:
            _criar_delta(pasta, linhas=100)
            fila = queue.Queue()

            modulo["_produtor_delta"](
                _ConexaoDelta(pasta), "clientes", fila, 50, {"id", "nome"}
            )
            itens = _consumir(fila, modulo["_FIM"])

        colunas, *lotes = itens
        self.assertEqual(colunas, ["id", "nome"])
        self.assertEqual(len(lotes[0][0]), 2)

    def test_produtor_delta_manda_erro_para_a_fila(self):
        modulo = _carregar_modulo_template()
        fila = queue.Queue()

        modulo["_produtor_delta"](_ConexaoDelta("/nao/existe"), "x", fila, 100)
        itens = _consumir(fila, modulo["_FIM"])

        self.assertEqual(len(itens), 1)
        self.assertIsInstance(itens[0], Exception)

    def test_ultimo_valor_delta_devolve_o_maximo(self):
        modulo = _carregar_modulo_template()
        with tempfile.TemporaryDirectory() as pasta:
            _criar_delta(pasta, linhas=5000)

            maximo = modulo["_ultimo_valor"](
                _ConexaoDelta(pasta), "deltalake", "clientes", "stamped"
            )

        self.assertEqual(
            maximo, datetime.datetime(2026, 1, 1) + datetime.timedelta(minutes=4999)
        )

    def test_ultimo_valor_delta_tudo_nulo_devolve_none(self):
        import pyarrow as pa
        from deltalake import write_deltalake

        modulo = _carregar_modulo_template()
        with tempfile.TemporaryDirectory() as pasta:
            write_deltalake(
                str(Path(pasta) / "vazio"),
                pa.table({"stamped": pa.array([None, None], pa.timestamp("us"))}),
                mode="append",
            )

            maximo = modulo["_ultimo_valor"](
                _ConexaoDelta(pasta), "deltalake", "vazio", "stamped"
            )

        self.assertIsNone(maximo)

    def test_ultimo_valor_delta_tabela_inexistente_devolve_none(self):
        modulo = _carregar_modulo_template()
        maximo = modulo["_ultimo_valor"](
            _ConexaoDelta("/nao/existe"), "deltalake", "clientes", "stamped"
        )
        self.assertIsNone(maximo)

    def test_filtro_delta_monta_expressao_do_pyarrow(self):
        import pyarrow.dataset

        modulo = _carregar_modulo_template()
        expr = modulo["_filtro_delta"]("id", 100)
        self.assertIsInstance(expr, pyarrow.dataset.Expression)

    def _carga_delta(self, schedule, watermark=None):
        modulo = _carregar_modulo_template()
        env = dict(_ENV_BASE, DB_ORIGEM_TYPE="deltalake")
        modulo["ler_env"] = lambda: env
        modulo["conectar"] = lambda *a, **k: _ConexaoCatalogo()
        modulo["_colunas_origem"] = lambda *a: ["id", "stamped"]
        modulo["_truncar"] = lambda *a: None
        modulo["_ultimo_valor"] = lambda *a: watermark
        modulo["_copiar"] = lambda *a, **k: 1
        capturado = {}

        def _falso_produtor_delta(conn, nome, fila, lote, permitidas, filtro=None):
            capturado.update(nome=nome, filtro=filtro, permitidas=permitidas)
            fila.put(["id", "stamped"])
            fila.put(modulo["_FIM"])

        modulo["_produtor_delta"] = _falso_produtor_delta

        capturado["total"] = modulo["carregar_tabela"]({
            "table": "clientes",
            "schema": "destino",
            "schedule": schedule,
            "columns": [
                {"name": "id", "type": "integer"},
                {"name": "stamped", "type": "timestamp"},
            ],
        })
        return capturado

    def test_carregar_tabela_repassa_o_filtro_ao_produtor_delta(self):
        # O bug: o WHERE era montado e o produtor recebia so o nome da tabela.
        carga = self._carga_delta(
            {"mode": "incremental", "incremental_column": "stamped"},
            watermark=datetime.datetime(2026, 1, 2),
        )
        self.assertEqual(carga["nome"], "clientes")
        self.assertIsNotNone(carga["filtro"])

    def test_carregar_tabela_delta_sem_watermark_passa_filtro_nulo(self):
        carga = self._carga_delta(
            {"mode": "incremental", "incremental_column": "stamped"},
            watermark=None,
        )
        self.assertIsNone(carga["filtro"])

    def test_carregar_tabela_delta_full_nao_passa_filtro(self):
        carga = self._carga_delta(
            {"mode": "full"}, watermark=datetime.datetime(2026, 1, 2)
        )
        self.assertIsNone(carga["filtro"])
        self.assertEqual(carga["total"], 1)


if __name__ == "__main__":
    unittest.main()
