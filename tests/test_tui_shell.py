"""Shell do wizard: menu lateral, ponte de prompts, revisão e registro.

O corpo do comando roda numa thread como no CLI de verdade; os prompts
bloqueiam num futuro que a UI resolve — um ``Pilot`` digita as mesmas teclas
que o usuário daria e ``_esperar`` sincroniza o teste com a thread do corpo.

O que a tela *decide* (estado das etapas, revisão, conteúdo da área central)
mora em :mod:`conduto.tui.shell`; aqui garantimos que a ponte, o foco, o menu
e os registros (SQLite, abertos no ``F3``) estão ligados nele.
"""

import asyncio
import threading

import pytest
from textual.widgets import DataTable, Footer, Input, OptionList, RichLog, Static

from conduto.i18n import definir_idioma
from conduto.i18n.catalogo_en import CATALOGO_EN
from conduto.schemas.schemas_auto import INSTRUCAO_BUSCA
from conduto.tui import prompts, registros, shell
from conduto.tui.modelo import Choice
from conduto.tui.paineis import PainelSelecao, Revisao
from conduto.tui.registros import TelaRegistros
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
# console.print do corpo: sai da tela, vai pro SQLite e só aparece no F3
# ---------------------------------------------------------------------------


def test_console_do_corpo_vai_para_o_sqlite_e_fica_no_buffer():
    async def cenario():
        sessao = Sessao(ETAPAS_TESTE, "init")

        def corpo():
            etapa("origem_sgbd")
            console.print("mensagem vinda do corpo")
            console.print("[yellow]aviso com marcação[/yellow]")

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(lambda: len(sessao.buffer_console) >= 2, "saida guardada")
            # nada de RichLog na tela: o registro agora mora no banco
            assert not list(app.query(RichLog))
            await _esperar(
                lambda: len(registros.consultar(sessao.id_registro)) >= 2,
                "linha no banco",
            )
            guardados = registros.consultar(sessao.id_registro)
            assert [registro.texto for registro in guardados] == [
                "mensagem vinda do corpo",
                "aviso com marcação",
            ]
            # a etapa vigente do corpo é a que vai junto com a linha
            assert {registro.etapa for registro in guardados} == {"origem_sgbd"}
            # texto de leitura limpo, estilo com a cor preservada
            assert guardados[0].estilo == guardados[0].texto
            assert guardados[1].estilo != guardados[1].texto
            textos = [str(args[0]) for args, _ in sessao.buffer_console]
            assert "mensagem vinda do corpo" in textos
        # o buffer só é reproduzido no terminal quando o shell fecha de vez
        # (o finally de rodar_no_shell) — aqui continua guardado.
        assert sessao.buffer_console
        assert sessao.erro is None

    _rodar(cenario)


def test_responder_etapa_e_entrar_na_proxima_nunca_mostram_log_velho():
    """O bug que motivateu o SQLite: log antigo piscava a cada troca de etapa."""

    async def cenario():
        sessao = Sessao(ETAPAS_TESTE, "init")
        resultado = {}
        pode_seguir = threading.Event()
        fim = threading.Event()

        def corpo():
            etapa("origem_sgbd")
            console.print("log antigo da etapa um")
            console.print("[yellow]aviso antigo[/yellow]")
            resultado["sgbd"] = prompts.selecionar(
                "Selecione o SGBD de {rotulo}:",
                ["postgresql", "mysql"],
                rotulo="origem",
            )
            # segura com a resposta já gravada: a tela não pode voltar a
            # mostrar o registro velho enquanto o corpo ainda não seguiu
            pode_seguir.wait(5)
            etapa("origem_credenciais")
            fim.wait(5)

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(lambda: sessao.painel_pendente is not None, "prompt")
            await pilot.pause()
            # o registro não é mais um widget da área de conteúdo
            assert not list(app.query(RichLog))

            await pilot.press("enter")  # confirma a linha do cursor
            await _esperar(lambda: "sgbd" in resultado, "primeira resposta")
            await _esperar(lambda: sessao.pendente is None, "prompt fechado")
            await pilot.pause()

            # 1) fim da etapa: a revisão assume o lugar — nenhum log antigo
            conteudo = app.query_one("#conteudo")
            visiveis = [f for f in conteudo.children if f.display]
            assert [type(f).__name__ for f in visiveis] == ["Revisao"]

            pode_seguir.set()
            await _esperar(lambda: sessao.atual == 1, "segunda etapa")
            await pilot.pause()

            # 2) etapa nova ainda sem prompt: aviso em andamento, não o log
            visiveis = [f for f in conteudo.children if f.display]
            assert [type(f).__name__ for f in visiveis] == ["Static"]
            assert visiveis[0].id == "msg-executando"
            # a dica diz onde o registro foi parar
            assert "Etapa em andamento." in visiveis[0].content
            assert str(registros.caminho()) in visiveis[0].content

            fim.set()
        assert sessao.erro is None

    _rodar(cenario)


def test_menu_da_etapa_respondida_vai_para_a_revisao_sem_tocar_no_log():
    """Clicar na etapa atual concluída não tem mais o que alternar: é revisão."""

    async def cenario():
        sessao = Sessao(ETAPAS_TESTE, "init")
        resultado = {}
        fim = threading.Event()

        def corpo():
            etapa("origem_sgbd")
            console.print("log da etapa um")
            resultado["sgbd"] = prompts.selecionar(
                "Selecione o SGBD de {rotulo}:",
                ["postgresql", "mysql"],
                rotulo="origem",
            )
            fim.wait(5)

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(lambda: sessao.painel_pendente is not None, "prompt")
            await pilot.pause()
            await pilot.press("enter")
            await _esperar(lambda: "sgbd" in resultado, "resposta")
            await pilot.pause()

            menu = app.query_one("#menu", OptionList)
            for _ in range(3):
                await pilot.press("enter")  # reentra na etapa 0
                await pilot.pause()
                visiveis = [
                    f
                    for f in app.query_one("#conteudo").children
                    if f.display
                ]
                assert [type(f).__name__ for f in visiveis] == ["Revisao"]
                assert not any(isinstance(f, RichLog) for f in visiveis)

            fim.set()
        assert sessao.erro is None

    _rodar(cenario)


def test_f3_abre_os_registros_do_banco_e_esc_devolve_o_foco():
    async def cenario():
        sessao = Sessao(ETAPAS_TESTE, "init")
        fim = threading.Event()

        def corpo():
            etapa("origem_sgbd")
            console.print("linha guardada no banco")
            fim.wait(10)

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(
                lambda: len(registros.consultar(sessao.id_registro)) >= 1,
                "linha no banco",
            )
            await pilot.pause()
            menu = app.query_one("#menu", OptionList)
            assert menu.has_focus  # o foco de entrada, antes do F3

            await pilot.press("f3")
            await pilot.pause()
            tela = app.screen
            assert isinstance(tela, TelaRegistros)
            assert sessao.tela_registros is tela
            # a tela base continua de pé embaixo (sobe como modal)
            assert menu.display

            corpo_log = tela.query_one("#corpo-registros", RichLog)
            assert corpo_log.has_focus  # dá para rolar já na abertura
            linhas = [strip.text for strip in corpo_log.lines]
            do_log = [linha for linha in linhas if "linha guardada no banco" in linha]
            assert do_log, linhas
            assert do_log[0].lstrip().startswith("[")  # horário na frente
            assert any("etapa: origem_sgbd" in linha for linha in linhas)

            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, TelaRegistros)
            assert sessao.tela_registros is None  # para de espelhar
            assert menu.has_focus  # devolveu o foco de onde veio

            fim.set()
        assert sessao.erro is None

    _rodar(cenario)


def test_f3_com_prompt_pendente_nao_rouba_o_futuro():
    """Abrir os registros em cima de um prompt não trava o corpo depois."""

    async def cenario():
        sessao = Sessao(ETAPAS_TESTE, "init")
        resultado = {}
        fim = threading.Event()

        def corpo():
            etapa("origem_sgbd")
            console.print("linha antes do prompt")
            resultado["host"] = prompts.pedir("HOST:")
            fim.wait(5)

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(lambda: sessao.painel_pendente is not None, "prompt")
            await pilot.pause()
            painel = sessao.painel_pendente

            await pilot.press("f3")
            await pilot.pause()
            assert isinstance(app.screen, TelaRegistros)
            # o prompt continua montado embaixo, com o futuro intacto
            assert painel.is_attached
            assert not sessao.pendente["futuro"].done()

            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, TelaRegistros)
            assert sessao.painel_pendente is not None
            assert not sessao.pendente["futuro"].done()

            # responder depois funciona normal (o futuro era o mesmo)
            await pilot.press("h", "o", "s", "t")
            await pilot.press("enter")
            await _esperar(lambda: "host" in resultado, "resposta")
            assert resultado["host"] == "host"

            fim.set()
        assert sessao.erro is None

    _rodar(cenario)


def test_reproduzir_console_devolve_a_saida_e_ignora_render_estragado(monkeypatch):
    """Replay ao fechar o shell: o buffer vai todo pro terminal real.

    Um ``print`` que levanta (render estragado) não pode abortar o resto do
    replay nem deixar o buffer preso — senão a saída se perde na virada.
    """
    chamadas: list = []

    class Gravador:
        def print(self, *args, **kwargs):
            chamadas.append((args, kwargs))
            if args and args[0] == "primeira":
                raise ValueError("render estragado")

    monkeypatch.setattr("conduto.ui.console", Gravador())

    sessao = Sessao(ETAPAS_TESTE, "init")
    sessao.buffer_console.append((("primeira",), {}))
    sessao.buffer_console.append((("segunda",), {"markup": False}))
    sessao.buffer_console.append((("terceira",), {}))

    sessao.reproduzir_console()

    # as três foram tentadas, mesmo com a primeira explodindo
    assert chamadas == [
        (("primeira",), {}),
        (("segunda",), {"markup": False}),
        (("terceira",), {}),
    ]
    assert not sessao.buffer_console  # esvaziou: não repete na próxima chamada

    sessao.reproduzir_console()
    assert len(chamadas) == 3  # sem buffer não imprime nada


def test_f3_sem_nenhum_registro_mostra_o_avazio():
    async def cenario():
        sessao = Sessao(ETAPAS_TESTE, "init")
        fim = threading.Event()

        def corpo():
            etapa("origem_sgbd")
            fim.wait(10)  # nada de console.print: o banco fica vazio

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(lambda: sessao.atual == 0, "etapa marcada")
            await pilot.pause()
            await pilot.press("f3")
            await pilot.pause()
            tela = app.screen
            assert isinstance(tela, TelaRegistros)
            linhas = [
                strip.text
                for strip in tela.query_one("#corpo-registros", RichLog).lines
            ]
            assert any("Nenhum registro nesta sessão." in l for l in linhas), linhas
            # o título diz o arquivo em que a gravação cairia
            titulo = tela.query_one("#titulo-registros", Static)
            assert str(registros.caminho()) in str(titulo.content)

            await pilot.press("escape")
            fim.set()
        assert sessao.erro is None

    _rodar(cenario)


def test_com_a_tela_aberta_o_print_novo_espelha_na_hora_sem_reler_o_banco():
    async def cenario():
        sessao = Sessao(ETAPAS_TESTE, "init")
        pode_imprimir = threading.Event()
        fim = threading.Event()

        def corpo():
            etapa("origem_sgbd")
            console.print("linha antes de abrir")
            pode_imprimir.wait(10)
            console.print("[green]linha depois de abrir[/green]")
            fim.wait(10)

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(
                lambda: len(registros.consultar(sessao.id_registro)) >= 1,
                "linha no banco",
            )
            await pilot.pause()
            await pilot.press("f3")
            await pilot.pause()
            tela = app.screen
            assert isinstance(tela, TelaRegistros)
            log = tela.query_one("#corpo-registros", RichLog)
            assert sessao.tela_registros is tela  # ligação para o espelho
            antes = len(log.lines)
            assert any("linha antes de abrir" in s.text for s in log.lines)

            pode_imprimir.set()
            await _esperar(lambda: len(log.lines) > antes, "espelho ao vivo")
            assert any(
                "linha depois de abrir" in s.text for s in log.lines
            ), [s.text for s in log.lines]

            await pilot.press("escape")
            fim.set()
        assert sessao.erro is None

    _rodar(cenario)


def test_o_corpo_terminar_logo_apos_responder_nao_derruba_o_shell():
    """Regressão: o ``exit`` chega no meio da montagem da revisão.

    O corpo acaba logo depois da resposta e o ``app.exit()`` derruba a
    barra do painel (neta no DOM) antes de ela subir — o ``on_mount`` não
    pode estourar um ``NoMatches`` em cima de um tooltip.
    """

    async def cenario():
        sessao = Sessao(ETAPAS_TESTE, "init")
        resultado = {}

        def corpo():
            etapa("origem_sgbd")
            resultado["tabelas"] = prompts.multi_selecionar(
                "Selecione as tabelas para gerar os schemas:",
                ESCOLHAS,
                use_search_filter=False,
            )

        app = WizardApp(sessao, corpo, (), {})
        async with app.run_test(size=(110, 32)) as pilot:
            await _esperar(lambda: sessao.painel_pendente is not None, "painel")
            await pilot.pause()
            await pilot.press("space")
            await pilot.press("enter")
            await _esperar(lambda: "tabelas" in resultado, "resposta")
            # o corpo já acabou: o shell fecha com a revisão montando
        assert resultado["tabelas"] == ["postgresql"]
        assert sessao.erro is None

    _rodar(cenario)
