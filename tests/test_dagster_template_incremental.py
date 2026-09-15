import unittest
from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src" / "conduto" / "templates" / "dagster" / "conduto_dagster" / "etl.py.jinja"


class TestDagsterIncrementalTemplate(unittest.TestCase):
    def test_template_has_empty_table_guard_and_upsert(self):
        texto = TEMPLATE_PATH.read_text(encoding="utf-8")

        self.assertIn("def _tabela_vazia", texto)
        self.assertIn("if _tabela_vazia(conn_destino, destino):", texto)
        self.assertIn("_copiar_postgres_upsert", texto)
        self.assertIn("ON CONFLICT", texto)


if __name__ == "__main__":
    unittest.main()
