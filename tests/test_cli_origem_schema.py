"""Schema de origem perguntado uma única vez — a flegagem é a oficial.

No modo automático quem escolhe o schema de origem é a marcação (flegagem)
dentro de `gerar_schemas_automaticos`, e o prompt único foi retirado do
`coletar_credenciais` justamente para não perguntar duas vezes. No modo manual
a flegagem não existe, então ali o prompt único é o único — logo, o oficial.
"""

from types import SimpleNamespace

import pytest

from conduto import cli
from conduto.database.adapters import ADAPTERS
from conduto.i18n import t


CREDENCIAIS = {
    "tipo": "postgresql",
    "host": "localhost",
    "port": "5432",
    "user": "postgres",
    "password": "postgres",
    "database": "origem_db",
    "schema": "public",
}


@pytest.fixture()
def sem_prompt(monkeypatch):
    """Prompt do `coletar_credenciais` respondido na mão, sem banco por perto.

    `_escolher_schema` é trocado por um espião: o teste quer saber se ele foi
    chamado (e com que `permitir_criar`), não escolher schema de verdade.
    """
    estado = SimpleNamespace(
        sgbd="PostgreSQL",
        perguntas_de_schema=[],
        permite_criar=[],
    )

    def _selecionar(pergunta, escolhas, **kwargs):
        escolhas = list(escolhas)
        if estado.sgbd in escolhas:
            return estado.sgbd
        return escolhas[0]

    def _escolher_schema(adapter, credenciais, rotulo, permitir_criar):
        estado.perguntas_de_schema.append(rotulo)
        estado.permite_criar.append(permitir_criar)
        return "escolhido"

    monkeypatch.setattr(cli, "selecionar", _selecionar)
    monkeypatch.setattr(cli, "pedir", lambda pergunta, padrao="", **kw: padrao)
    monkeypatch.setattr(cli, "pedir_senha", lambda pergunta, padrao="", **kw: padrao)
    monkeypatch.setattr(cli, "testar_conexao", lambda adapter, cred: (True, None))
    monkeypatch.setattr(cli, "drivers_faltantes", lambda tipo: [])
    monkeypatch.setattr(cli, "_escolher_banco", lambda *a, **k: "origem_db")
    monkeypatch.setattr(cli, "_escolher_schema", _escolher_schema)
    return estado


# ---------------------------------------------------------------------------
# coletar_credenciais: quem pede o schema e quem não pede
# ---------------------------------------------------------------------------


def test_por_padrao_continua_perguntando_o_schema(sem_prompt):
    credenciais, _, conectou = cli.coletar_credenciais("origem")

    assert sem_prompt.perguntas_de_schema == ["origem"]
    assert credenciais["schema"] == "escolhido"
    assert conectou is True


def test_pedir_schema_false_nao_pergunta_e_usa_o_default(sem_prompt):
    credenciais, _, conectou = cli.coletar_credenciais("origem", pedir_schema=False)

    assert sem_prompt.perguntas_de_schema == []
    assert credenciais["schema"] == "public"  # default do SGBD: só fallback no .env
    assert conectou is True


def test_destino_que_e_perguntado_seu_proprio_schema(sem_prompt):
    """O destino tem um schema só e manda no CREATE TABLE: o dele continua."""
    credenciais, _, _ = cli.coletar_credenciais(
        "destino", permitir_criar=True, pedir_schema=True
    )

    assert sem_prompt.perguntas_de_schema == ["destino"]
    assert sem_prompt.permite_criar == [True]
    assert credenciais["schema"] == "escolhido"


def test_sgbd_em_que_schema_e_o_banco_nunca_pergunta(sem_prompt):
    """MySQL: schema == banco, então não existe pergunta de schema à parte."""
    sem_prompt.sgbd = "MySQL"

    credenciais, _, _ = cli.coletar_credenciais("origem")

    assert sem_prompt.perguntas_de_schema == []
    assert credenciais["schema"] == credenciais["database"] == "origem_db"


# ---------------------------------------------------------------------------
# _schema_origem_manual: o prompt único do modo manual
# ---------------------------------------------------------------------------


def test_modo_manual_com_conexao_pergunta_umas_vez_so(sem_prompt):
    adapter = ADAPTERS["PostgreSQL"]

    resultado = cli._schema_origem_manual(adapter, dict(CREDENCIAIS), conectou=True)

    assert resultado == "escolhido"
    assert sem_prompt.perguntas_de_schema == [t("origem")]
    # origem não tem "Criar novo schema...": quem cria schema é o destino
    assert sem_prompt.permite_criar == [False]


def test_modo_manual_sem_conexao_usa_o_que_ja_veio(sem_prompt):
    adapter = ADAPTERS["PostgreSQL"]
    origem = dict(CREDENCIAIS, schema="dbo_digitado")

    resultado = cli._schema_origem_manual(adapter, origem, conectou=False)

    assert resultado == "dbo_digitado"
    assert sem_prompt.perguntas_de_schema == []


def test_modo_manual_com_schema_igual_ao_banco_nao_pergunta(sem_prompt):
    adapter = ADAPTERS["MySQL"]
    origem = dict(CREDENCIAIS, schema="loja")

    resultado = cli._schema_origem_manual(adapter, origem, conectou=True)

    assert resultado == "loja"
    assert sem_prompt.perguntas_de_schema == []


# ---------------------------------------------------------------------------
# init: o prompt de schema de origem aparece uma vez só
# ---------------------------------------------------------------------------


def _preparar_init(monkeypatch, tmp_path, respostas_selecionar):
    """Roda o `init` dentro de um projeto uv, com todos os prompts na mão.

    `respostas_selecionar` é a fila de índices consumida por todos os
    `selecionar` do `init`, na ordem em que aparecem: modo, schedules, DDL
    (só no automático) e subir o Dagster.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    chamadas_credenciais = []
    respostas_credenciais = [
        (dict(CREDENCIAIS), ADAPTERS["PostgreSQL"], True),
        (dict(CREDENCIAIS, database="destino_db", schema="stg"), ADAPTERS["PostgreSQL"], True),
    ]

    def _coletar(rotulo, **kwargs):
        chamadas_credenciais.append(kwargs)
        return respostas_credenciais.pop(0)

    fila = list(respostas_selecionar)

    def _selecionar(pergunta, escolhas, **kwargs):
        return list(escolhas)[fila.pop(0)]

    estado = SimpleNamespace(
        chamadas_credenciais=chamadas_credenciais,
        perguntas_de_schema=[],
        geracoes_automaticas=0,
    )

    def _escolher_schema(adapter, credenciais, rotulo, permitir_criar):
        estado.perguntas_de_schema.append(rotulo)
        return "escolhido"

    def _gerar_automatico(*args, **kwargs):
        estado.geracoes_automaticas += 1
        return True

    monkeypatch.setattr(cli, "coletar_credenciais", _coletar)
    monkeypatch.setattr(cli, "selecionar", _selecionar)
    monkeypatch.setattr(cli, "_escolher_schema", _escolher_schema)
    monkeypatch.setattr(cli, "gerar_schemas_automaticos", _gerar_automatico)
    monkeypatch.setattr(cli, "gerar_schedules_automaticos", lambda *a, **k: None)
    monkeypatch.setattr(cli, "setup_uv_environment", lambda *a, **k: None)
    monkeypatch.setattr(cli, "gerar_comando_dagster", lambda *a, **k: None)
    estado.fila_de_prompts = fila
    return estado


def test_init_modo_automatico_so_fala_pela_flegagem(monkeypatch, tmp_path):
    """Automático: origem coletada sem perguntar schema e a flegagem que manda."""
    # modo=automático, schedules=não, ddl=apenas gerar, dagster=não
    estado = _preparar_init(monkeypatch, tmp_path, [0, 1, 1, 1])

    cli.init(None)

    assert estado.chamadas_credenciais[0].get("pedir_schema") is False
    assert estado.perguntas_de_schema == []
    assert estado.geracoes_automaticas == 1
    # percorreu o fluxo inteiro: modo, schedules, DDL e subir Dagster
    assert estado.fila_de_prompts == []


def test_init_modo_manual_pergunta_o_schema_de_origem_uma_vez(monkeypatch, tmp_path):
    """Manual: sem flegagem, então o prompt único é o que vale."""
    # modo=manual, schedules=não, dagster=não (sem pergunta de DDL)
    estado = _preparar_init(monkeypatch, tmp_path, [1, 1, 1])

    cli.init(None)

    assert estado.perguntas_de_schema == [t("origem")]
    assert estado.geracoes_automaticas == 0
    # manual não chega na pergunta de DDL: modo, schedules e subir Dagster
    assert estado.fila_de_prompts == []


def test_init_nunca_tira_o_schema_de_destino_do_lugar(monkeypatch, tmp_path):
    """O destino tem um schema só e é o do DDL: a dele segue sendo escolha dele."""
    estado = _preparar_init(monkeypatch, tmp_path, [0, 1, 1, 1])

    cli.init(None)

    assert estado.chamadas_credenciais[0].get("pedir_schema") is False
    assert "pedir_schema" not in estado.chamadas_credenciais[1]
    assert estado.fila_de_prompts == []
