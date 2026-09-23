"""Shell do wizard: menu lateral, ponte de prompts, revisão e registro.

O corpo do comando roda numa thread como no CLI de verdade; os prompts
bloqueiam num futuro que a UI resolve — um ``Pilot`` digita as mesmas teclas
que o usuário daria e ``_esperar`` sincroniza o teste com a thread do corpo.

O que a tela *decide* (estado das etapas, revisão, conteúdo da área central)
mora em :mod:`conduto.tui.shell`; aqui garantimos que a ponte, o foco, o menu
e o registro estão ligados nele.
"""

import asyncio
import threading

import pytest
from textual.widgets import DataTable, Footer, Input, OptionList, RichLog, Static

from conduto.i18n import definir_idioma
from conduto.i18n.catalogo_en import CATALOGO_EN
from conduto.schemas.schemas_auto import INSTRUCAO_BUSCA
from conduto.tui import prompts, shell
from conduto.tui.modelo import Choice
from conduto.tui.paineis import PainelSelecao, Revisao
from conduto.tui.shell import (
    ETAPAS_DDL,
    ETAPAS_INIT,
    Estado,
    Passo,
    Sessao,
    WizardApp,
    etapa,
    rodar_no_shell,
    sessao_ativa,
)
from conduto.ui import console

#: Três etapas de mentira com os mesmos nomes reais da origem — o suficiente
#: para exercitar atual/concluída/pulada/pendente sem rodar um init de verdade.
ETAPAS_TESTE = [
    Passo("origem_sgbd", "Origem: SGBD"),
    Passo("origem_credenciais", "Origem: credenciais"),
    Passo("origem_banco", "Origem: banco e schema"),
]

ESCOLHAS = [
    Choice(title="PostgreSQL", value="postgresql"),
    Choice(title="MySQL", value="mysql"),
    Choice(title="SQL Server", value="sqlserver"),
]


@pytest.fixture(autouse=True)
def _idioma_e_sessao_limpa():
    definir_idioma("pt")
    yield
    shell._sessao_ativa = None  # sessão vaza de um teste não pode chegar no próximo


def _rodar(cenario):
    """Roda um cenário assíncrono do Textual num teste síncrono (sem pytest-asyncio)."""
    return asyncio.run(cenario())


async def _esperar(condicao, descricao, tempo=10.0):
    """Espera a thread do corpo (ou a UI) satisfazer ``condicao``."""
    limite = asyncio.get_running_loop().time() + tempo
    while not condicao():
        assert asyncio.get_running_loop().time() < limite, f"tempo esgotado: {descricao}"
        await asyncio.sleep(0.02)


# ---------------------------------------------------------------------------
# Estado das etapas (sem UI: o marcador etapa() só mexe no estado)
# ---------------------------------------------------------------------------


def test_estado_de_cobre_atual_concluida_pulada_e_pendente():
    sessao = Sessao(ETAPAS_INIT, "init")
    assert all(
        sessao.estado_de(indice) is Estado.PENDENTE
        for indice in range(len(ETAPAS_INIT))
    )

    sessao.ir_para("origem_sgbd")
    assert sessao.estado_de(0) is Estado.ATUAL
    assert sessao.estado_de(1) is Estado.PENDENTE

    sessao.ir_para("modo_schemas")  # pula 1..5
    assert sessao.estado_de(0) is Estado.CONCLUIDA
    assert sessao.estado_de(3) is Estado.PULADA
    assert sessao.estado_de(6) is Estado.ATUAL
    assert sessao.estado_de(7) is Estado.PENDENTE


def test_sem_terminal_o_shell_roda_o_corpo_direto(monkeypatch):
    monkeypatch.setattr("conduto.tui.prompts._tem_terminal", lambda: False)
    etapa("origem_sgbd")  # sem sessão: marcador é no-op, não levanta nada
    assert sessao_ativa() is None

    chamados = []
    resultado = rodar_no_shell(
        ETAPAS_TESTE, "init", lambda: (chamados.append("corpo"), "ok")[1]
    )
    assert resultado == "ok"
    assert chamados == ["corpo"]
    assert sessao_ativa() is None


def test_todos_os_titulos_das_etapas_estao_no_catalogo_en():
    # Passo.titulo vira t(titulo) no desenho do menu: precisa de tradução.
    titulos = [passo.titulo for passo in (*ETAPAS_INIT, *ETAPAS_DDL)]
    faltando = [titulo for titulo in titulos if titulo not in CATALOGO_EN]
    assert not faltando, faltando


# ---------------------------------------------------------------------------
# A tela (cabeçalho, menu lateral, rodapé, sessão)
# ---------------------------------------------------------------------------


def test_shell_mostra_cabecalho_menu_e_rodape():
    async def cenario():
        fim = threading.Event()
        sessao = Sessao(ETAPAS_TESTE, "init")
        app = WizardApp(sessao, fim.wait, (5,), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            cabecalho = str(app.query_one("#cabecalho", Static).content)
            assert "conduto" in cabecalho
            assert "init" in cabecalho
            assert "passo" not in cabecalho  # corpo ainda não marcou etapa

            menu = app.query_one("#menu", OptionList)
            assert menu.option_count == len(ETAPAS_TESTE)
            # entrada do wizard: o menu de etapas fica com o foco
            assert menu.has_focus
            # desenho da opção: glifo do estado + título traduzido
            assert str(menu.get_option_at_index(0).prompt) == "\u25cb Origem: SGBD"
            assert menu.get_option_at_index(0).id == "origem_sgbd"
            assert sessao_ativa() is sessao

            app.query_one(Footer)
            ativo = app.screen.active_bindings
            assert ativo["f2"].binding.description == "Etapas"
            assert ativo["escape"].binding.description == "Voltar"

            fim.set()
        assert sessao.erro is None

    _rodar(cenario)


# ---------------------------------------------------------------------------
# A ponte: o prompt do corpo vira painel na etapa atual
# ---------------------------------------------------------------------------


def test_prompt_do_corpo_vira_painel_na_etapa_e_responde():
    async def cenario():
        sessao = Sessao(ETAPAS_TESTE, "init")
        resultado = {}

        def corpo():
            etapa("origem_credenciais")  # etapa 0 fica pulada de propósito
            resultado["host"] = prompts.pedir("HOST:", padrao="localhost")

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(lambda: sessao.painel_pendente is not None, "painel do prompt")
            await pilot.pause()

            painel = sessao.painel_pendente
            assert painel.has_focus_within
            entrada = painel.query_one("#entrada", Input)
            assert entrada.has_focus
            assert entrada.value == "localhost"
            # a etapa 0 pulou: o menu conta a história (cinza, sem revisão)
            assert sessao.estado_de(0) is Estado.PULADA

            # f2 alterna entre o menu e o prompt ativo
            menu = app.query_one("#menu", OptionList)
            await pilot.press("f2")
            await pilot.pause()
            assert menu.has_focus
            await pilot.press("f2")
            await pilot.pause()
            assert entrada.has_focus

            await pilot.press("enter")  # aceita o padrão
            await _esperar(lambda: "host" in resultado, "resposta do corpo")
            await _esperar(lambda: sessao.pendente is None, "prompt fechado")
        assert resultado["host"] == "localhost"
        assert sessao.erro is None

    _rodar(cenario)


def test_multipla_com_filtro_marca_so_o_que_esta_visivel():
    async def cenario():
        sessao = Sessao(ETAPAS_TESTE, "init")
        resultado = {}

        def corpo():
            etapa("origem_sgbd")
            resultado["tabelas"] = prompts.multi_selecionar(
                "Selecione as tabelas para gerar os schemas:",
                ESCOLHAS,
                instrucao=INSTRUCAO_BUSCA,
                use_search_filter=True,
            )

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(lambda: sessao.painel_pendente is not None, "painel de tabelas")
            await pilot.pause()

            painel = sessao.painel_pendente
            assert painel.com_busca is True
            assert painel.instrucao == INSTRUCAO_BUSCA
            assert painel.query_one("#busca", Input).has_focus

            # "y" (de MySQL) deixa uma única opção visível — o filtro manda
            await pilot.press("y")
            await pilot.pause()
            assert painel.modelo.contagem[1] == 1  # uma visível
            await pilot.press("escape")  # esc do filtro volta para a lista
            await pilot.pause()
            await pilot.press("space")  # marca o único visível
            await pilot.press("enter")
            await _esperar(lambda: "tabelas" in resultado, "resposta do corpo")
        assert resultado["tabelas"] == ["mysql"]
        assert sessao.erro is None

    _rodar(cenario)


def test_esc_no_prompt_cancela_e_o_corpo_recebe_none():
    async def cenario():
        sessao = Sessao(ETAPAS_TESTE, "init")
        resultado = {}

        def corpo():
            etapa("origem_sgbd")
            resultado["host"] = prompts.pedir("HOST:")

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(lambda: sessao.painel_pendente is not None, "painel do prompt")
            await pilot.pause()
            await pilot.press("escape")
            await _esperar(lambda: "host" in resultado, "corpo destravado")
        assert resultado["host"] is None
        assert sessao.erro is None

    _rodar(cenario)


# ---------------------------------------------------------------------------
# Menu lateral: revisão somente leitura e mensagens das etapas
# ---------------------------------------------------------------------------


def test_menu_revisao_somente_leitura_e_mensagem_de_etapa_futura():
    async def cenario():
        fim = threading.Event()
        sessao = Sessao(ETAPAS_TESTE, "init")
        resultado = {}

        def corpo():
            etapa("origem_sgbd")
            resultado["sgbd"] = prompts.selecionar(
                "Selecione o SGBD de {rotulo}:",
                ["postgresql", "mysql"],
                rotulo="origem",
            )
            etapa("origem_credenciais")
            fim.wait(5)

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(lambda: sessao.painel_pendente is not None, "prompt de SGBD")
            await pilot.pause()
            await pilot.press("enter")  # confirma a linha do cursor
            await _esperar(lambda: "sgbd" in resultado, "primeira resposta")
            await _esperar(lambda: sessao.atual == 1, "segunda etapa")
            await pilot.pause()

            menu = app.query_one("#menu", OptionList)
            assert sessao.estado_de(0) is Estado.CONCLUIDA
            assert sessao.estado_de(1) is Estado.ATUAL
            assert str(menu.get_option_at_index(0).prompt).startswith("\u2713")  # ✓
            assert str(menu.get_option_at_index(1).prompt).startswith("\u25cf")  # ●
            assert menu.has_focus

            # clica (teclado) na etapa concluída: revisão somente leitura
            await pilot.press("up", "enter")
            await pilot.pause()
            conteudo = app.query_one("#conteudo")
            revisao = conteudo.query_one(Revisao)
            painel = revisao.query_one(PainelSelecao)
            assert painel.bloqueado and painel.has_class("bloqueado")
            # a revisão traz a escolha dada (cursor na opção marcada)
            assert painel.modelo.marcados == {0}

            # teclar na revisão não muda nada: sem atalhos, sem marcação
            painel.query_one("#tabela", DataTable).focus()
            await pilot.pause()
            marcados_antes = set(painel.modelo.marcados)
            barra_antes = painel.barra_status
            await pilot.press("space", "a", "l", "enter")
            await pilot.pause()
            assert painel.modelo.marcados == marcados_antes
            assert painel.barra_status == barra_antes

            # etapa futura: mensagem de espera, não registro nem revisão
            menu.focus()
            await pilot.pause()
            assert menu.has_focus
            await pilot.press("down", "down", "enter")
            await pilot.pause()
            assert sessao.selecionado == 2
            assert sessao.estado_de(2) is Estado.PENDENTE
            futuro = app.query_one("#msg-aguardar", Static)
            assert futuro.display
            assert not revisao.display

            fim.set()
        assert sessao.erro is None

    _rodar(cenario)


# ---------------------------------------------------------------------------
# console.print do corpo
# ---------------------------------------------------------------------------


def test_console_do_corpo_vai_para_o_registro_e_fica_guardado():
    async def cenario():
        sessao = Sessao(ETAPAS_TESTE, "init")

        def corpo():
            console.print("mensagem vinda do corpo")
            console.print("[yellow]aviso com marcação[/yellow]")

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(lambda: len(sessao.buffer_console) >= 2, "saida guardada")
            registro = app.query_one("#registro", RichLog)
            await _esperar(lambda: bool(registro.lines), "linha no registro")
            textos = [str(args[0]) for args, _ in sessao.buffer_console]
            assert "mensagem vinda do corpo" in textos
        # o buffer só é reproduzido no terminal quando o shell fecha de vez
        # (o finally de rodar_no_shell) — aqui continua guardado.
        assert sessao.buffer_console
        assert sessao.erro is None

    _rodar(cenario)
