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


if __name__ == "__main__":
    unittest.main()
