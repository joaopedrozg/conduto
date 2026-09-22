import queue
import unittest
from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src" / "conduto" / "templates" / "dagster" / "conduto_dagster" / "etl.py.jinja"

# Schema reduzido no molde do SF2010 (Protheus): PK inteira R_E_C_N_O_ e
# watermark nullable S_T_A_M_P_, como no caso relatado pelo usuario.
TABELA_SF2010 = {
    "table": "SF2010",
    "schedule": {
        "cron": "0 * * * *",
        "mode": "incremental",
        "full_load": False,
        "truncate": False,
        "incremental_column": "S_T_A_M_P_",
    },
    "columns": [
        {"name": "F2_DOC", "type": "varchar(13)", "nullable": False},
        {"name": "F2_CLIENTE", "type": "varchar(8)", "nullable": False},
        {"name": "R_E_C_N_O_", "type": "integer", "primary_key": True, "nullable": False},
        {"name": "S_T_A_M_P_", "type": "timestamp", "nullable": True},
    ],
}


def _carregar_modulo_template():
    """Renderiza o jinja com um project_name fixo e executa como modulo Python."""
    texto = TEMPLATE_PATH.read_text(encoding="utf-8")
    texto = texto.replace("{{ project_name }}", "projeto_teste")
    namespace = {"__name__": "conduto_dagster_etl_teste", "__file__": str(TEMPLATE_PATH)}
    exec(compile(texto, str(TEMPLATE_PATH), "exec"), namespace)
    return namespace


class _FakeCopy:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, dados):
        self._conn.copy_writes.append(dados)


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._resultado = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executados.append(sql)
        if sql.strip().upper().startswith("SELECT 1"):
            self._resultado = None if self._conn.vazia else (1,)

    def fetchone(self):
        return self._resultado

    def copy(self, sql):
        self._conn.copy_calls.append(sql)
        return _FakeCopy(self._conn)

    def executemany(self, sql, params):
        self._conn.executemany_calls.append((sql, params))


class _FakeConexaoPostgres:
    """Conexao falsa que so registra as chamadas feitas por _copiar/_tabela_vazia."""

    def __init__(self, vazia: bool):
        self.vazia = vazia
        self.executados = []
        self.copy_calls = []
        self.copy_writes = []
        self.executemany_calls = []

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        pass


def _fila_com_uma_linha():
    fila = queue.Queue()
    fila.put(["F2_DOC", "F2_CLIENTE", "R_E_C_N_O_", "S_T_A_M_P_"])
    fila.put([("NF001", "CLI01", 1, "2026-09-15 10:00:00")])
    return fila


class TestDagsterIncrementalTemplate(unittest.TestCase):
    def test_template_has_empty_table_guard_and_upsert(self):
        texto = TEMPLATE_PATH.read_text(encoding="utf-8")

        self.assertIn("def _tabela_vazia", texto)
        self.assertIn("tabela_vazia = _tabela_vazia(conn_destino, destino)", texto)
        self.assertIn("_copiar_postgres_upsert", texto)
        self.assertIn("ON CONFLICT", texto)

    def test_copiar_usa_copy_quando_tabela_destino_vazia(self):
        modulo = _carregar_modulo_template()
        fila = _fila_com_uma_linha()
        fila.put(modulo["_FIM"])
        conn = _FakeConexaoPostgres(vazia=True)

        total = modulo["_copiar"](conn, "postgresql", '"public"."SF2010"', fila, None, TABELA_SF2010)

        self.assertEqual(total, 1)
        self.assertEqual(len(conn.copy_calls), 1)
        self.assertEqual(len(conn.executemany_calls), 0)

    def test_copiar_usa_upsert_quando_tabela_destino_tem_dados(self):
        modulo = _carregar_modulo_template()
        fila = _fila_com_uma_linha()
        fila.put(modulo["_FIM"])
        conn = _FakeConexaoPostgres(vazia=False)

        total = modulo["_copiar"](conn, "postgresql", '"public"."SF2010"', fila, None, TABELA_SF2010)

        self.assertEqual(total, 1)
        self.assertEqual(len(conn.copy_calls), 0)
        self.assertEqual(len(conn.executemany_calls), 1)
        sql_upsert = conn.executemany_calls[0][0]
        self.assertIn("ON CONFLICT", sql_upsert)
        self.assertIn('"R_E_C_N_O_"', sql_upsert)


class _ConnFalsa:
    """Conexao que so aceita fechar (carregar_tabela fecha no finally)."""

    def close(self):
        pass


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


class TestSchemaDeOrigemPorTabela(unittest.TestCase):
    """Cada tabela tem de ser lida do schema da origem onde ela mora.

    Caso relatado: .env com DB_ORIGEM_SCHEMA=HumanResources e a tabela em
    Person -> o ETL montava HumanResources.BusinessEntity e o SQL Server
    respondia 42S02 "Invalid object name".
    """

    def _origem_de(self, tabela_extra, env_extra=None, apagar_env=()):
        modulo = _carregar_modulo_template()
        env = dict(_ENV_BASE)
        env.update(env_extra or {})
        for chave in apagar_env:
            env.pop(chave, None)

        capturado = {}
        modulo["ler_env"] = lambda: env
        modulo["conectar"] = lambda *a, **k: _ConnFalsa()

        def _falso_colunas(conn, tipo, origem):
            capturado["origem"] = origem
            return []  # aborta logo apos montar a origem

        modulo["_colunas_origem"] = _falso_colunas

        tabela = {"table": "BusinessEntity", "schema": "destino"}
        tabela.update(tabela_extra)
        self.assertEqual(modulo["carregar_tabela"](tabela), 0)
        self.assertIn("origem", capturado)
        return capturado["origem"]

    def test_regressao_nao_usa_o_schema_global_do_env(self):
        # O caso relatado, reproduzido.
        origem = self._origem_de(
            {"source_schema": "Person"},
            env_extra={"DB_ORIGEM_SCHEMA": "HumanResources"},
        )
        self.assertEqual(origem, "[Person].[BusinessEntity]")
        self.assertNotIn("HumanResources", origem)

    def test_source_schema_vence_o_env(self):
        origem = self._origem_de({"source_schema": "staging"})
        self.assertEqual(origem, "[staging].[BusinessEntity]")

    def test_chave_schema_do_destino_nao_vira_origem(self):
        origem = self._origem_de(
            {"schema": "destino", "source_schema": "Person"}
        )
        self.assertEqual(origem, "[Person].[BusinessEntity]")
        self.assertNotIn("destino", origem)

    def test_sem_source_schema_cai_no_db_origem_schema(self):
        # Projetos antigos, sem a chave: comportamento anterior preservado.
        origem = self._origem_de({})
        self.assertEqual(origem, "[dbo].[BusinessEntity]")

    def test_sem_source_schema_nem_env_cai_no_public(self):
        origem = self._origem_de({}, apagar_env=("DB_ORIGEM_SCHEMA",))
        self.assertEqual(origem, "[public].[BusinessEntity]")

    def test_env_vazio_tambem_cai_no_public(self):
        origem = self._origem_de({}, env_extra={"DB_ORIGEM_SCHEMA": ""})
        self.assertEqual(origem, "[public].[BusinessEntity]")

    def test_postgres_usa_aspas_duplas_do_schema_de_origem(self):
        modulo = _carregar_modulo_template()
        env = dict(_ENV_BASE, DB_ORIGEM_TYPE="postgresql")
        capturado = {}
        modulo["ler_env"] = lambda: env
        modulo["conectar"] = lambda *a, **k: _ConnFalsa()
        modulo["_colunas_origem"] = lambda conn, tipo, origem: (
            capturado.update(origem=origem) or []
        )
        modulo["carregar_tabela"](
            {"table": "clientes", "source_schema": "vendas", "schema": "public"}
        )
        self.assertEqual(capturado["origem"], '"vendas"."clientes"')

    def test_sql_de_amostra_carrega_o_schema_de_origem(self):
        # E exatamente esse SELECT que o SQL Server reclamou (42S02).
        modulo = _carregar_modulo_template()
        self.assertEqual(
            modulo["_sql_amostra"]("sqlserver", "[Person].[BusinessEntity]"),
            "SELECT TOP (0) * FROM [Person].[BusinessEntity]",
        )

    def test_deltalake_ignora_schema_e_usa_so_a_tabela(self):
        origem = self._origem_de(
            {"table": "minha_tabela", "source_schema": "qualquer"},
            env_extra={"DB_ORIGEM_TYPE": "deltalake"},
        )
        self.assertEqual(origem, "minha_tabela")


if __name__ == "__main__":
    unittest.main()
