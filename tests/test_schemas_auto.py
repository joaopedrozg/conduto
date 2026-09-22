"""Seleção de schemas da origem: filtro de tabelas e o prompt de schemas.

Cobre o `filtrar_tabelas_por_schema` (puro), o `listar_tabelas(schemas=...)`,
o `_escolher_schemas` (prompt) e o fluxo completo do
`gerar_schemas_automaticos` com o banco e os prompts simulados.
"""

from contextlib import contextmanager

import pytest
import typer

from conduto.database import introspect
from conduto.database.adapters import Adapter
from conduto.database.introspect import filtrar_tabelas_por_schema, listar_tabelas
from conduto.schemas import schemas_auto
from conduto.schemas.schemas_auto import _escolher_schemas, gerar_schemas_automaticos


TABELAS = [
    {"schema": "analytics", "table": "metricas"},
    {"schema": "public", "table": "clientes"},
    {"schema": "public", "table": "pedidos"},
    {"schema": "staging", "table": "stg_clientes"},
]

SESSAO = {"schema": "sessao", "table": "sessoes"}


# ---------------------------------------------------------------------------
# filtrar_tabelas_por_schema
# ---------------------------------------------------------------------------


def test_filtrar_sem_schema_informado_lista_tudo():
    assert filtrar_tabelas_por_schema(TABELAS, None) is TABELAS


def test_filtrar_com_lista_vazia_nao_mantem_nada():
    assert filtrar_tabelas_por_schema(TABELAS, []) == []


def test_filtrar_um_schema_so():
    resultado = filtrar_tabelas_por_schema(TABELAS, ["public"])
    assert [t["table"] for t in resultado] == ["clientes", "pedidos"]
    assert all(t["schema"] == "public" for t in resultado)


def test_filtrar_varios_schemas():
    resultado = filtrar_tabelas_por_schema(TABELAS, ["public", "staging"])
    assert [t["table"] for t in resultado] == ["clientes", "pedidos", "stg_clientes"]


def test_filtrar_preserva_a_ordem_original():
    resultado = filtrar_tabelas_por_schema(TABELAS, ["staging", "analytics"])
    assert [t["table"] for t in resultado] == ["metricas", "stg_clientes"]


def test_filtrar_schema_inexistente_retorna_vazio():
    assert filtrar_tabelas_por_schema(TABELAS, ["nao_existe"]) == []


def test_filtrar_e_exato_sensivel_a_maiusculas():
    assert filtrar_tabelas_por_schema(TABELAS, ["PUBLIC"]) == []


def test_filtrar_schemas_duplicados_nao_duplica_tabelas():
    resultado = filtrar_tabelas_por_schema(TABELAS, ["public", "public"])
    assert [t["table"] for t in resultado] == ["clientes", "pedidos"]


def test_filtrar_ignora_entradas_vazias_na_selecao():
    # '' e None nao sao schemas: nao podem destravar a listagem inteira
    resultado = filtrar_tabelas_por_schema(TABELAS, ["", None, "public"])
    assert [t["table"] for t in resultado] == ["clientes", "pedidos"]


def test_filtrar_sem_conceito_de_schema_descarta_tabela_sem_schema():
    # Só filtramos quando ha schemas distintos; aqui a semantica pedida e
    # "somente as tabelas dos schemas selecionados".
    tabelas = [SESSAO, {"schema": "public", "table": "clientes"}]
    assert filtrar_tabelas_por_schema(tabelas, ["public"]) == [
        {"schema": "public", "table": "clientes"}
    ]


def test_filtrar_nao_muta_a_lista_original():
    original = list(TABELAS)
    filtrar_tabelas_por_schema(original, ["public"])
    assert original == TABELAS


# ---------------------------------------------------------------------------
# listar_tabelas(schemas=...)
# ---------------------------------------------------------------------------


def _adapter(tipo: str) -> Adapter:
    return Adapter(nome=tipo, tipo=tipo, driver="driver_qualquer")


@pytest.mark.parametrize(
    "tipo,funeção",
    [
        ("postgresql", "_listar_tabelas_postgres"),
        ("mysql", "_listar_tabelas_mysql"),
        ("sqlserver", "_listar_tabelas_sqlserver"),
        ("clickhouse", "_listar_tabelas_clickhouse"),
        ("duckdb", "_listar_tabelas_duckdb"),
        ("deltalake", "_listar_tabelas_deltalake"),
    ],
)
def test_listar_tabelas_filtra_por_schema_em_todo_sgbd(monkeypatch, tipo, funeção):
    monkeypatch.setattr(introspect, funeção, lambda cred: list(TABELAS))
    resultado = listar_tabelas(_adapter(tipo), {}, schemas=["public"])
    assert [t["table"] for t in resultado] == ["clientes", "pedidos"]


@pytest.mark.parametrize(
    "tipo,funeção",
    [
        ("postgresql", "_listar_tabelas_postgres"),
        ("mysql", "_listar_tabelas_mysql"),
        ("sqlserver", "_listar_tabelas_sqlserver"),
        ("clickhouse", "_listar_tabelas_clickhouse"),
        ("duckdb", "_listar_tabelas_duckdb"),
        ("deltalake", "_listar_tabelas_deltalake"),
    ],
)
def test_listar_tabelas_sem_filtro_lista_tudo(monkeypatch, tipo, funeção):
    monkeypatch.setattr(introspect, funeção, lambda cred: list(TABELAS))
    assert listar_tabelas(_adapter(tipo), {}) == TABELAS


def test_listar_tabelas_adapter_desconhecido(monkeypatch):
    with pytest.raises(ValueError, match="Adapter desconhecido"):
        listar_tabelas(_adapter("oracle"), {})


def test_listar_tabelas_repassa_credenciais(monkeypatch):
    chamadas = []

    def _falso(cred):
        chamadas.append(cred)
        return list(TABELAS)

    monkeypatch.setattr(introspect, "_listar_tabelas_postgres", _falso)
    listar_tabelas(_adapter("postgresql"), {"host": "db"}, schemas=["public"])
    assert chamadas == [{"host": "db"}]


# ---------------------------------------------------------------------------
# _escolher_schemas (prompt)
# ---------------------------------------------------------------------------


class _Escolhas:
    """Grava cada chamada de multi_selecionar e devolve respostas ensaiadas."""

    def __init__(self, respostas):
        self._respostas = list(respostas)
        self.registros: list = []

    def __call__(self, pergunta, escolhas, **kwargs):
        self.registros.append(
            {"pergunta": pergunta, "escolhas": list(escolhas), "kwargs": kwargs}
        )
        return self._respostas.pop(0)

    @property
    def ultima(self) -> dict:
        return self.registros[-1]

    @property
    def titulos(self) -> list:
        return [c.title for c in self.ultima["escolhas"]]


def test_escolher_schemas_com_unico_schema_nao_pergunta(monkeypatch):
    # MySQL, ClickHouse e Delta Lake tem um schema so: prompt seria ruído.
    falha = lambda *a, **k: pytest.fail("nao deveria perguntar")
    monkeypatch.setattr(schemas_auto, "multi_selecionar", falha)
    tabelas = [{"schema": "meu_banco", "table": "t1"}]
    assert _escolher_schemas(tabelas) is tabelas


def test_escolher_schemas_sem_conceito_de_schema_nao_pergunta(monkeypatch):
    falha = lambda *a, **k: pytest.fail("nao deveria perguntar")
    monkeypatch.setattr(schemas_auto, "multi_selecionar", falha)
    tabelas = [SESSAO, {"schema": "", "table": "outra"}]
    assert _escolher_schemas(tabelas) is tabelas


def test_escolher_schemas_mostra_schemas_distintos_ordenados(monkeypatch):
    escolhas = _Escolhas([["public"]])
    monkeypatch.setattr(schemas_auto, "multi_selecionar", escolhas)
    _escolher_schemas(TABELAS)

    assert escolhas.ultima["pergunta"] == "Selecione os schemas da origem:"
    assert escolhas.titulos == ["analytics", "public", "staging"]
    # os valores devolve o nome do schema (string), nao um dict
    assert escolhas.ultima["escolhas"][0].value == "analytics"


def test_escolher_schemas_devolve_somente_tabelas_escolhidas(monkeypatch):
    escolhas = _Escolhas([["public", "staging"]])
    monkeypatch.setattr(schemas_auto, "multi_selecionar", escolhas)

    resultado = _escolher_schemas(TABELAS)
    assert [t["table"] for t in resultado] == [
        "clientes",
        "pedidos",
        "stg_clientes",
    ]


def test_escolher_schemas_cancelado_sai_do_programa(monkeypatch):
    escolhas = _Escolhas([None])
    monkeypatch.setattr(schemas_auto, "multi_selecionar", escolhas)
    with pytest.raises(typer.Exit):
        _escolher_schemas(TABELAS)


def test_escolher_schemas_nada_marcado_devolve_vazio(monkeypatch):
    escolhas = _Escolhas([[]])
    monkeypatch.setattr(schemas_auto, "multi_selecionar", escolhas)
    assert _escolher_schemas(TABELAS) == []


def test_escolher_schemas_usa_a_mesma_instrucao_de_busca(monkeypatch):
    escolhas = _Escolhas([["public"]])
    monkeypatch.setattr(schemas_auto, "multi_selecionar", escolhas)
    _escolher_schemas(TABELAS)
    assert escolhas.ultima["kwargs"]["instrucao"] == schemas_auto.INSTRUCAO_BUSCA
    assert escolhas.ultima["kwargs"]["use_search_filter"] is True


# ---------------------------------------------------------------------------
# gerar_schemas_automaticos (fluxo completo com banco simulado)
# ---------------------------------------------------------------------------


class _Barra:
    def advance(self, tarefa):
        pass


@contextmanager
def _sem_carregando(*args, **kwargs):
    yield


@contextmanager
def _sem_progresso(*args, **kwargs):
    yield _Barra(), 0


def _descrever(adapter, credenciais, schema, table, conexao=None):
    return {
        "table": table,
        "columns": [
            {"name": "id", "type": "integer", "primary_key": True, "nullable": False}
        ],
    }


def _preparar(monkeypatch, respostas, tabelas=None):
    """Planta banco simulado, prompts ensaiados e desliga o feedback visual."""
    if tabelas is None:
        tabelas = TABELAS
    escolhas = _Escolhas(respostas)
    monkeypatch.setattr(schemas_auto, "multi_selecionar", escolhas)
    monkeypatch.setattr(
        schemas_auto, "listar_tabelas", lambda adapter, cred: list(tabelas)
    )
    monkeypatch.setattr(schemas_auto, "descrever_tabela", _descrever)
    monkeypatch.setattr(schemas_auto, "abrir_conexao", lambda adapter, cred: None)
    monkeypatch.setattr(schemas_auto, "carregando", _sem_carregando)
    monkeypatch.setattr(schemas_auto, "progresso", _sem_progresso)
    return escolhas


def _tabelas_oferecidas(escolhas, indice: int) -> list:
    return [c.value for c in escolhas.registros[indice]["escolhas"]]


def test_fluxo_prompt_de_tabelas_so_tem_schemas_escolhidos(tmp_path, monkeypatch):
    escolhas = _preparar(
        monkeypatch,
        # 1a resposta: schemas; 2a resposta: tabelas (pega a primeira)
        [["public"], [{"schema": "public", "table": "clientes"}]],
    )
    ok = gerar_schemas_automaticos(tmp_path, "proj", None, {}, "destino")

    assert ok is True
    assert len(escolhas.registros) == 2
    assert escolhas.registros[0]["pergunta"] == "Selecione os schemas da origem:"
    assert escolhas.registros[1]["pergunta"] == "Selecione as tabelas para gerar os schemas:"

    oferecidas = _tabelas_oferecidas(escolhas, 1)
    assert "metricas" not in oferecidas
    assert "stg_clientes" not in oferecidas
    assert oferecidas == [
        {"schema": "public", "table": "clientes"},
        {"schema": "public", "table": "pedidos"},
    ]
    # os titulos do checkbox mostram schema.tabela
    assert escolhas.registros[1]["escolhas"][0].title == "public.clientes"


def test_fluxo_gera_arquivos_so_dos_schemas_escolhidos(tmp_path, monkeypatch):
    _preparar(
        monkeypatch,
        [["analytics"], [{"schema": "analytics", "table": "metricas"}]],
    )
    gerar_schemas_automaticos(tmp_path, "proj", None, {}, "destino")

    gerados = sorted(p.name for p in (tmp_path / "schemas").glob("*.yml"))
    assert gerados == ["metricas.yml"]
    assert (tmp_path / "main.yml").exists()
    conteudo = (tmp_path / "main.yml").read_text(encoding="utf-8")
    assert "metricas" in conteudo
    assert "clientes" not in conteudo


def test_fluxo_dois_schemas_gera_os_dois(tmp_path, monkeypatch):
    _preparar(
        monkeypatch,
        [
            ["public", "staging"],
            [
                {"schema": "public", "table": "clientes"},
                {"schema": "staging", "table": "stg_clientes"},
            ],
        ],
    )
    gerar_schemas_automaticos(tmp_path, "proj", None, {}, "destino")
    gerados = sorted(p.name for p in (tmp_path / "schemas").glob("*.yml"))
    assert gerados == ["clientes.yml", "stg_clientes.yml"]


def test_fluxo_cancelar_schemas_aborta_sem_gerar_arquivo(tmp_path, monkeypatch):
    _preparar(monkeypatch, [None])
    with pytest.raises(typer.Exit):
        gerar_schemas_automaticos(tmp_path, "proj", None, {}, "destino")

    assert not (tmp_path / "schemas").exists()
    assert not (tmp_path / "main.yml").exists()


def test_fluxo_nada_marcado_em_schemas_devolve_false(tmp_path, monkeypatch):
    escolhas = _preparar(monkeypatch, [[]])
    ok = gerar_schemas_automaticos(tmp_path, "proj", None, {}, "destino")

    assert ok is False
    # abortou antes de perguntar as tabelas
    assert len(escolhas.registros) == 1
    assert not (tmp_path / "schemas").exists()


def test_fluxo_schema_unico_pula_o_prompt_de_schemas(tmp_path, monkeypatch):
    tabelas = [{"schema": "unico", "table": "t1"}, {"schema": "unico", "table": "t2"}]
    escolhas = _preparar(
        monkeypatch,
        [[{"schema": "unico", "table": "t1"}]],
        tabelas=tabelas,
    )
    ok = gerar_schemas_automaticos(tmp_path, "proj", None, {}, "destino")

    assert ok is True
    assert len(escolhas.registros) == 1
    assert escolhas.registros[0]["pergunta"] == "Selecione as tabelas para gerar os schemas:"
    assert _tabelas_oferecidas(escolhas, 0) == [
        {"schema": "unico", "table": "t1"},
        {"schema": "unico", "table": "t2"},
    ]


def test_fluxo_banco_sem_tabelas_aborta_antes_de_perguntar(tmp_path, monkeypatch):
    escolhas = _preparar(monkeypatch, [], tabelas=[])
    ok = gerar_schemas_automaticos(tmp_path, "proj", None, {}, "destino")

    assert ok is False
    assert escolhas.registros == []
    assert not (tmp_path / "schemas").exists()


def test_fluxo_cancelar_tabelas_tambem_aborta(tmp_path, monkeypatch):
    _preparar(monkeypatch, [["public"], None])
    with pytest.raises(typer.Exit):
        gerar_schemas_automaticos(tmp_path, "proj", None, {}, "destino")

    assert not (tmp_path / "schemas").exists()
