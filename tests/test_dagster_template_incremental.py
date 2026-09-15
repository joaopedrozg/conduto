from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src" / "conduto" / "templates" / "dagster" / "conduto_dagster" / "etl.py.jinja"


def test_template_has_postgres_incremental_conflict_protection():
    texto = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "ON CONFLICT" in texto
    assert "_carregar_pg_para_pg_incremental" in texto
