"""Telas Textual: flegagem item a item, "selecionar todas", filtro e cancelamento.

Roda o app em modo headless (``App.run_test()``) com o ``Pilot`` digitando as
mesmas teclas que um usuário usaria. O que a tela *decide* (filtrar, marcar,
devolver valores) mora em :mod:`conduto.tui.modelo`; aqui garantimos que os
atalhos, os botões e a barra de status estão ligados nele.
"""

import asyncio

import pytest
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input

from conduto.i18n import definir_idioma
from conduto.tui.modelo import MULTIPLA, UNICA, Choice, ModeloSelecao
from conduto.tui.telas import TelaConfirmacao, TelaSelecao, TelaTexto
from conduto.tui.tema import Status, cor


@pytest.fixture(autouse=True)
def _idioma():
    definir_idioma("pt")


def _escolhas():
    return [
        Choice(title="alpha", value="a"),
        Choice(title="beta", value="b"),
        Choice(title="gamma", value="c"),
    ]


def _multipla(itens=None):
    return ModeloSelecao(itens if itens is not None else _escolhas(), modo=MULTIPLA)


def _rodar(cenario):
    """Roda um cenário assíncrono do Textual num teste síncrono (sem pytest-asyncio)."""
    return asyncio.run(cenario())


# ---------------------------------------------------------------------------
# Montagem / barra de status
# ---------------------------------------------------------------------------


def test_tela_multipla_mostra_pergunta_lista_e_status():
    async def cenario():
        app = TelaSelecao(pergunta="Selecione as tabelas para gerar os schemas:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert str(app.query_one("#pergunta").content) == (
                "Selecione as tabelas para gerar os schemas:"
            )
            tabela = app.query_one("#tabela", DataTable)
            assert tabela.row_count == 3
            assert [c for c in app.ordem] == [0, 1, 2]
            # nada marcado, três visíveis, nenhuma em atenção
            assert app.barra_status == "0 marcadas  ·  3 visíveis"
            assert app.query_one("#busca", Input).value == ""
        return None

    _rodar(cenario)


def test_tela_multipla_traz_os_botoes_e_a_dica_de_busca():
    async def cenario():
        app = TelaSelecao(
            pergunta="Selecione os schemas da origem:",
            modelo=_multipla(),
            instrucao="(setas navegam, a marca todas)",
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            for botao in ("#btn-alternar", "#btn-todas", "#btn-limpar", "#btn-confirmar", "#btn-cancelar"):
                assert len(app.query(botao)) == 1, botao
            assert "(setas navegam, a marca todas)" in str(app.query_one("#dica").content)
            # o filtro vem focado: já dá para digitar na abertura
            assert app.query_one("#busca", Input).has_focus
        return None

    _rodar(cenario)


def test_tela_unica_nao_traz_botao_de_marcar_todas():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha o banco:", modelo=ModeloSelecao(_escolhas(), modo=UNICA), com_busca=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.query("#btn-todas")) == 0
            assert len(app.query("#btn-limpar")) == 0
            assert len(app.query("#busca")) == 0  # sem busca não há onde filtrar
            assert app.query_one("#tabela", DataTable).has_focus
        return None

    _rodar(cenario)


# ---------------------------------------------------------------------------
# Flegagem item a item (espaço / botão Alternar)
# ---------------------------------------------------------------------------


def test_os_botoes_tem_altura_e_largura_para_o_rotulo():
    """Regression do CSS da barra de botões: borda + rótulo cortado = erro visual."""

    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            esperado = {
                "#btn-alternar": "Alternar",
                "#btn-todas": "Selecionar todas",
                "#btn-limpar": "Limpar",
                "#btn-confirmar": "Confirmar",
                "#btn-cancelar": "Cancelar",
            }
            for seletor, rotulo in esperado.items():
                botao = app.query_one(seletor)
                # `region`/`outer_size` incluem a borda `tall` (2 linhas);
                # `.size` é só a área de conteúdo (1 linha para o rótulo).
                assert botao.region.height >= 3, seletor  # borda + linha do rótulo
                assert botao.size.height >= 1, seletor  # o rótulo cabe em uma linha
                assert botao.size.width >= len(rotulo) + 2, seletor
        return None

    _rodar(cenario)


def test_espaco_na_lista_flega_uma_vez_por_vez():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")  # sai do filtro, foca a lista

            await pilot.press("down", "space")  # beta
            assert app.modelo.marcados == {1}
            assert app.barra_status == "1 marcadas  ·  3 visíveis"

            await pilot.press("down", "space")  # gamma
            assert app.modelo.marcados == {1, 2}
            assert app.barra_status == "2 marcadas  ·  3 visíveis"

            await pilot.press("space")  # gamma de novo: desflega
            assert app.modelo.marcados == {1}
            assert app.barra_status == "1 marcadas  ·  3 visíveis"
        return None

    _rodar(cenario)


def test_botao_alternar_flega_a_linha_do_cursor():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.click("#btn-alternar")
            await pilot.pause()
            assert app.modelo.marcados == {0}
            # o botão ignora cliques enquanto a animação "-active" durar
            await pilot.pause(delay=app.query_one("#btn-alternar").active_effect_duration)
            await pilot.click("#btn-alternar")
            await pilot.pause()
            assert app.modelo.marcados == set()
        return None

    _rodar(cenario)


def test_a_coluna_da_marca_muda_na_tela():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape", "space")
            await pilot.pause()
            marca = app.query_one("#tabela", DataTable).get_cell_at(Coordinate(0, 0))
            assert marca.plain == "\u2713"  # ✓
            assert str(marca.style) == cor(Status.OK)  # verde: marcada
        return None

    _rodar(cenario)


# ---------------------------------------------------------------------------
# Selecionar todas / limpar
# ---------------------------------------------------------------------------


def test_tecla_a_marca_todas_e_l_limpa():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")

            await pilot.press("a")
            assert app.modelo.marcados == {0, 1, 2}
            assert app.barra_status == "3 marcadas  ·  3 visíveis"

            await pilot.press("l")
            assert app.modelo.marcados == set()
            assert app.barra_status == "0 marcadas  ·  3 visíveis"
        return None

    _rodar(cenario)


def test_botao_selecionar_todas_marca_tudo():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#btn-todas")
            await pilot.pause()
            assert app.modelo.marcados == {0, 1, 2}
            # a dica do botão avisa que o filtro manda
            assert app.query_one("#btn-todas").tooltip is not None
        return None

    _rodar(cenario)


def test_botao_limpar_desflega_tudo():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#btn-todas")
            await pilot.pause()
            await pilot.click("#btn-limpar")
            await pilot.pause()
            assert app.modelo.marcados == set()
        return None

    _rodar(cenario)


# ---------------------------------------------------------------------------
# Filtro de busca
# ---------------------------------------------------------------------------


def test_digitar_no_filtro_reduz_a_lista_e_o_contador():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b", "e")
            await pilot.pause()
            assert app.query_one("#tabela", DataTable).row_count == 1
            assert app.barra_status == "0 marcadas  ·  1 visíveis"
        return None

    _rodar(cenario)


def test_filtro_sem_resultado_mostra_o_aviso_em_vermelho():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("z", "z", "z")
            await pilot.pause()
            assert app.query_one("#tabela", DataTable).row_count == 0
            assert app.barra_status == "nenhum resultado"
        return None

    _rodar(cenario)


def test_esc_do_filtro_volta_para_a_lista():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#busca", Input).has_focus
            await pilot.press("escape")
            await pilot.pause()
            assert app.query_one("#tabela", DataTable).has_focus
        return None

    _rodar(cenario)


def test_selecionar_todas_marca_somente_o_que_o_filtro_mostra():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b", "e")  # deixa só "beta" visível
            await pilot.press("escape")
            await pilot.press("a")
            await pilot.pause()
            assert app.modelo.marcados == {1}  # alpha e gamma fora do filtro
            assert app.barra_status == "1 marcadas  ·  1 visíveis"
        return None

    _rodar(cenario)


def test_enter_no_filtro_confirma_o_que_esta_marcado():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("g", "a", "m")  # deixa só "gamma" visível
            await pilot.press("escape")  # volta para a lista
            await pilot.press("space")  # marca a única visível
            await pilot.press("/")  # de novo no filtro...
            await pilot.press("enter")  # ...enter de lá confirma
        return app.return_value

    assert _rodar(cenario) == ["c"]


# ---------------------------------------------------------------------------
# Confirmação e cancelamento
# ---------------------------------------------------------------------------


def test_enter_na_lista_devolve_os_valores_marcados_na_ordem_original():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("down", "down", "space")  # gamma
            await pilot.press("up", "up", "space")  # alpha
            await pilot.press("enter")
        return app.return_value

    assert _rodar(cenario) == ["a", "c"]


def test_botao_confirmar_devolve_o_que_esta_marcado():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#btn-todas")
            await pilot.pause()
            await pilot.click("#btn-confirmar")
        return app.return_value

    assert _rodar(cenario) == ["a", "b", "c"]


def test_nada_marcado_confirma_com_lista_vazia():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#btn-confirmar")
        return app.return_value

    assert _rodar(cenario) == []


def test_esc_e_botao_cancelar_devolvem_none():
    async def cenario_esc():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
        return app.return_value

    async def cenario_botao():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#btn-cancelar")
        return app.return_value

    assert _rodar(cenario_esc) is None
    assert _rodar(cenario_botao) is None


def test_ctrl_c_cancela_mesmo_com_o_foco_no_filtro():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=_multipla())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#busca", Input).has_focus
            await pilot.press("ctrl+c")
        return app.return_value

    assert _rodar(cenario) is None


# ---------------------------------------------------------------------------
# Modo único
# ---------------------------------------------------------------------------


def test_modo_unico_o_cursor_da_lista_e_a_escolha():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha o banco:", modelo=ModeloSelecao(_escolhas(), modo=UNICA), com_busca=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.modelo.marcados == {0}
            await pilot.press("down")
            await pilot.pause()
            assert app.modelo.marcados == {1}
            await pilot.press("enter")
        return app.return_value

    assert _rodar(cenario) == ["b"]


def test_modo_unico_clique_na_linha_confirma_a_linha():
    async def cenario():
        app = TelaSelecao(pergunta="Escolha o banco:", modelo=ModeloSelecao(_escolhas(), modo=UNICA), com_busca=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            # y do clique = linha do cabeçalho + índice da linha (uma linha cada)
            linha = 2
            await pilot.click("#tabela", offset=(1, linha + 1))
            await pilot.pause()
            assert app.modelo.marcados == {linha}
            # o 1º clique só move o cursor; o 2º na mesma linha confirma
            await pilot.click("#tabela", offset=(1, linha + 1))
        return app.return_value

    assert _rodar(cenario) == ["c"]


# ---------------------------------------------------------------------------
# Status por linha (cor = status)
# ---------------------------------------------------------------------------


def test_tabela_de_schemas_mostra_a_contagem_e_a_de_tabelas_o_aviso():
    itens = [
        Choice(title="analytics", value="analytics", status=Status.INFO, detalhe="1 tabela"),
        Choice(title="public", value="public", status=Status.INFO, detalhe="2 tabelas"),
        Choice(title="staging", value="staging", status=Status.AVISO, detalhe="já existe"),
    ]

    async def cenario():
        app = TelaSelecao(pergunta="Escolha:", modelo=ModeloSelecao(itens))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.barra_status == "0 marcadas  ·  3 visíveis  ·  1 com atenção"
            tabela = app.query_one("#tabela", DataTable)
            assert tabela.get_cell_at(Coordinate(0, 2)).plain == "\u25c6 1 tabela"  # ◆
            assert tabela.get_cell_at(Coordinate(2, 2)).plain == "\u25b2 já existe"  # ▲
        return None

    _rodar(cenario)


# ---------------------------------------------------------------------------
# Tela de texto (pedir / pedir_senha)
# ---------------------------------------------------------------------------


def test_tela_texto_devolve_o_que_foi_digitado():
    async def cenario():
        app = TelaTexto(pergunta="Novo host:", valor_inicial="")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("d", "b", "0", "1")
            await pilot.press("enter")
        return app.return_value

    assert _rodar(cenario) == "db01"


def test_tela_texto_em_branco_devolve_o_padrao():
    async def cenario():
        app = TelaTexto(pergunta="Host:", valor_inicial="localhost")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
        return app.return_value

    assert _rodar(cenario) == "localhost"


def test_tela_texto_botao_cancelar_devolve_none():
    async def cenario():
        app = TelaTexto(pergunta="Host:", valor_inicial="localhost")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#btn-cancelar")
        return app.return_value

    assert _rodar(cenario) is None


def test_tela_texto_de_senha_usa_campo_mascarado():
    async def cenario():
        app = TelaTexto(pergunta="Senha:", senha=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#entrada", Input).password is True
            app.exit("fim")
        return app.return_value

    assert _rodar(cenario) == "fim"


# ---------------------------------------------------------------------------
# Tela de confirmação (sim/não)
# ---------------------------------------------------------------------------


def test_confirmacao_enter_aceita_o_padrao_sim():
    async def cenario():
        app = TelaConfirmacao(pergunta="Aplicar o DDL agora?", padrao=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
        return app.return_value

    assert _rodar(cenario) is True


def test_confirmacao_tecla_y_e_n_respondem_direto():
    async def cenario_sim():
        app = TelaConfirmacao(pergunta="Aplicar?", padrao=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("y")
        return app.return_value

    async def cenario_nao():
        app = TelaConfirmacao(pergunta="Aplicar?", padrao=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
        return app.return_value

    assert _rodar(cenario_sim) is True
    assert _rodar(cenario_nao) is False


def test_confirmacao_botao_nao_com_padrao_sim():
    async def cenario():
        app = TelaConfirmacao(pergunta="Aplicar?", padrao=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#btn-nao")
        return app.return_value

    assert _rodar(cenario) is False


def test_confirmacao_esc_devolve_none():
    async def cenario():
        app = TelaConfirmacao(pergunta="Aplicar?", padrao=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
        return app.return_value

    assert _rodar(cenario) is None
