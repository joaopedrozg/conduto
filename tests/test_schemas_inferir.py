"""Inferência de colunas: cada tabela é lida do schema da origem onde mora.

Regressão do "Invalid object name" (42S02): a inferência usava o
DB_ORIGEM_SCHEMA único do .env para toda tabela, ignorando o source_schema
gravado no YAML de cada uma.
"""

from contextlib import contextmanager

import pytest
import yaml

from conduto.schemas import schemas_inferir as si


class _Barra:
    def advance(self, tarefa):
        pass


@contextmanager
def _progresso(*args, **kwargs):
    yield _Barra(), 0


def _alvo(dados):
    return {"table": dados["table"], "path": f"schemas/{dados['table']}.yml", "dados": dados}


def _preparar(monkeypatch, alvo, schema_env="dbo", sem_env_schema=False):
    """Simula o banco e devolve a lista de schemas consultados."""
    env = {
        "DB_ORIGEM_TYPE": "sqlserver",
        "DB_DESTINO_TYPE": "postgresql",
        "DB_DESTINO_SCHEMA": "destino",
    }
    if not sem_env_schema:
        env["DB_ORIGEM_SCHEMA"] = schema_env

    consultas: list = []
    monkeypatch.setattr(si, "ler_env", lambda project_dir: env)
    # _credenciais_origem nao e mockada de proposito: e pura (so le o .env e o
    # ADAPTERS) e resolve o schema com env ou o padrao do SGBD.
    monkeypatch.setattr(si, "_candidatas", lambda project_dir, alvo_t: [alvo])
    monkeypatch.setattr(si, "abrir_conexao", lambda adapter, cred: None)
    monkeypatch.setattr(si, "progresso", _progresso)
    monkeypatch.setattr(si, "_mostrar_resumo", lambda resumo: None)

    def _descrever(adapter, credenciais, schema, table, conexao=None):
        consultas.append({"schema": schema, "table": table})
        return {
            "table": table,
            "schema": schema,
            "columns": [{"name": "id", "type": "integer", "nullable": False}],
        }

    monkeypatch.setattr(si, "descrever_tabela", _descrever)
    return consultas


def test_inferir_le_a_tabela_no_source_schema_do_yaml(tmp_path, monkeypatch):
    alvo = _alvo(
        {
            "table": "BusinessEntity",
            "schema": "destino",
            "source_schema": "Person",
        }
    )
    consultas = _preparar(monkeypatch, alvo, schema_env="HumanResources")

    si.inferir_colunas(tmp_path)

    # Antes consultava HumanResources (o do .env) e falhava com 42S02.
    assert consultas == [{"schema": "Person", "table": "BusinessEntity"}]


def test_inferir_sem_source_schema_usa_o_env(tmp_path, monkeypatch):
    # Projeto antigo, sem a chave: comportamento anterior preservado.
    alvo = _alvo({"table": "clientes", "schema": "destino"})
    consultas = _preparar(monkeypatch, alvo, schema_env="dbo")

    si.inferir_colunas(tmp_path)

    assert consultas == [{"schema": "dbo", "table": "clientes"}]


def test_inferir_sem_source_schema_nem_env_usa_o_padrao_do_sgbd(tmp_path, monkeypatch):
    # Sem DB_ORIGEM_SCHEMA no .env, _credenciais_origem resolve o padrao do
    # SGBD (dbo no SQL Server) -- nao "public".
    alvo = _alvo({"table": "clientes", "schema": "destino"})
    consultas = _preparar(monkeypatch, alvo, sem_env_schema=True)

    si.inferir_colunas(tmp_path)

    assert consultas == [{"schema": "dbo", "table": "clientes"}]


def test_inferir_sem_source_schema_usa_o_db_origem_schema_do_env(tmp_path, monkeypatch):
    alvo = _alvo({"table": "clientes", "schema": "destino"})
    consultas = _preparar(monkeypatch, alvo, schema_env="HumanResources")

    si.inferir_colunas(tmp_path)

    assert consultas == [{"schema": "HumanResources", "table": "clientes"}]


def test_inferir_grava_source_schema_no_arquivo(tmp_path, monkeypatch):
    alvo = _alvo(
        {"table": "BusinessEntity", "schema": "destino", "source_schema": "Person"}
    )
    _preparar(monkeypatch, alvo)

    si.inferir_colunas(tmp_path)

    dados = yaml.safe_load(
        (tmp_path / "schemas" / "BusinessEntity.yml").read_text(encoding="utf-8")
    )
    assert dados["source_schema"] == "Person"
    assert dados["schema"] == "destino"


def test_inferir_adiciona_source_schema_em_projeto_antigo(tmp_path, monkeypatch):
    # Fixa o schema que acabou de funcionar: a proxima inferencia e o ETL
    # nao voltam a depender do .env.
    alvo = _alvo({"table": "clientes", "schema": "destino"})
    _preparar(monkeypatch, alvo, schema_env="vendas")

    si.inferir_colunas(tmp_path)

    dados = yaml.safe_load(
        (tmp_path / "schemas" / "clientes.yml").read_text(encoding="utf-8")
    )
    assert dados["source_schema"] == "vendas"


def test_inferir_preserva_schema_do_destino(tmp_path, monkeypatch):
    alvo = _alvo(
        {"table": "t", "schema": "staging", "source_schema": "origem_a"}
    )
    _preparar(monkeypatch, alvo)

    si.inferir_colunas(tmp_path)

    dados = yaml.safe_load((tmp_path / "schemas" / "t.yml").read_text(encoding="utf-8"))
    # "schema" continua sendo o do destino, intocado
    assert dados["schema"] == "staging"
    assert dados["source_schema"] == "origem_a"


def test_inferir_registra_no_main(tmp_path, monkeypatch):
    alvo = _alvo({"table": "t", "schema": "destino", "source_schema": "origem"})
    _preparar(monkeypatch, alvo)

    si.inferir_colunas(tmp_path)

    main = yaml.safe_load((tmp_path / "main.yml").read_text(encoding="utf-8"))
    assert main["tables"] == [{"path": "schemas/t.yml"}]


def test_inferir_nao_pula_tabela_quando_descrever_falha(tmp_path, monkeypatch):
    alvo = _alvo({"table": "t", "schema": "destino", "source_schema": "origem"})
    consultas = _preparar(monkeypatch, alvo)

    def _quebra(adapter, credenciais, schema, table, conexao=None):
        consultas.append({"schema": schema, "table": table})
        raise RuntimeError("Invalid object name")

    monkeypatch.setattr(si, "descrever_tabela", _quebra)

    assert si.inferir_colunas(tmp_path) == []
    assert consultas == [{"schema": "origem", "table": "t"}]
    assert not (tmp_path / "schemas" / "t.yml").exists()


# ---------------------------------------------------------------------------
# ORDEM_SCHEMA / _reordenar
# ---------------------------------------------------------------------------


def test_ordem_schema_inclui_source_schema():
    assert "source_schema" in si.ORDEM_SCHEMA
    # logo apos "schema": as duas chaves juntas no YAML
    assert si.ORDEM_SCHEMA.index("source_schema") == si.ORDEM_SCHEMA.index("schema") + 1


def test_reordenar_preserva_source_schema():
    dados = {
        "columns": [],
        "source_schema": "Person",
        "description": "d",
        "schema": "destino",
        "table": "t",
    }
    novo = si._reordenar(dados, si.ORDEM_SCHEMA)
    assert novo["source_schema"] == "Person"
    assert list(novo) == [
        "table",
        "schema",
        "source_schema",
        "description",
        "columns",
    ]


def test_reordenar_com_dados_sem_source_schema_nao_inventa_chave():
    dados = {"columns": [], "schema": "destino", "table": "t"}
    novo = si._reordenar(dados, si.ORDEM_SCHEMA)
    assert "source_schema" not in novo
    assert list(novo) == ["table", "schema", "columns"]
