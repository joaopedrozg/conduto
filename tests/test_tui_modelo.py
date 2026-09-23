"""Modelo de seleção: filtro, flegagem uma a uma e "selecionar todas".

Tudo aqui é puro (sem terminal): é o modelo que decide o que a tela desenha
e o que os prompts devolvem — marcação item a item, marcação em massa das
visíveis, filtro e ordem de saída.
"""

import pytest

from conduto.tui.modelo import (
    MULTIPLA,
    UNICA,
    Choice,
    ModeloSelecao,
    para_choice,
    valores_de,
)
from conduto.tui.tema import Status


def _escolhas():
    return [
        Choice(title="alpha", value="a"),
        Choice(title="beta", value="b"),
        Choice(title="gamma", value="c"),
    ]


def _multipla(itens=None):
    return ModeloSelecao(itens if itens is not None else _escolhas(), modo=MULTIPLA)


# ---------------------------------------------------------------------------
# Choice / para_choice
# ---------------------------------------------------------------------------


def test_choice_sem_value_devolve_o_titulo():
    assert Choice(title="clientes").value == "clientes"


def test_choice_com_value_guarda_o_value_e_o_status():
    escolha = Choice(title="public", value={"schema": "public"}, status=Status.INFO, detalhe="2 tabelas")
    assert escolha.value == {"schema": "public"}
    assert escolha.status is Status.INFO
    assert escolha.detalhe == "2 tabelas"


def test_para_choice_passa_uma_choice_e_converte_texto():
    escolha = Choice(title="x", value=1)
    assert para_choice(escolha) is escolha
    assert para_choice("clientes").value == "clientes"
    assert para_choice(7).title == "7"


def test_valores_de_devolve_os_valores_na_ordem():
    assert valores_de(_escolhas()) == ["a", "b", "c"]
    assert valores_de(["x", "y"]) == ["x", "y"]


def test_modo_desconhecido_levanta_erro():
    with pytest.raises(ValueError, match="Modo de seleção desconhecido"):
        ModeloSelecao(_escolhas(), modo="qualquer")


# ---------------------------------------------------------------------------
# Flegagem uma a uma
# ---------------------------------------------------------------------------


def test_comeca_sem_nada_marcado_no_modo_multipla():
    modelo = _multipla()
    assert modelo.marcados == set()
    assert modelo.selecionados() == []


def test_alternar_flega_e_desflega_uma_por_uma():
    modelo = _multipla()
    assert modelo.alternar(1) is True
    assert modelo.marcados == {1}
    assert modelo.alternar(2) is True
    assert modelo.marcados == {1, 2}
    assert modelo.alternar(1) is False
    assert modelo.marcados == {2}


def test_alternar_fora_da_lista_nao_muda_nada():
    modelo = _multipla()
    assert modelo.alternar(99) is False
    assert modelo.alternar(-1) is False
    assert modelo.marcados == set()


def test_modo_unico_marca_so_a_escolhida():
    modelo = ModeloSelecao(_escolhas(), modo=UNICA)
    assert modelo.alternar(2) is True
    assert modelo.marcados == {2}
    modelo.alternar(0)
    assert modelo.marcados == {0}


def test_modo_unico_comeca_na_primeira_opcao():
    # Sem nada marcado o enter confirmaria "vazio".
    modelo = ModeloSelecao(_escolhas(), modo=UNICA)
    assert modelo.marcados == {0}


# ---------------------------------------------------------------------------
# Filtro
# ---------------------------------------------------------------------------


def test_filtro_e_sem_diferenca_de_maiuscula_e_pega_detalhe():
    escolhas = [
        Choice(title="clientes", value="clientes"),
        Choice(title="pedidos", value="pedidos", detalhe="já existe"),
    ]
    modelo = ModeloSelecao(escolhas)

    modelo.filtrar("CLIENT")
    assert modelo.visiveis == [escolhas[0]]

    modelo.filtrar("EXISTE")  # busca também no detalhe
    assert modelo.visiveis == [escolhas[1]]

    modelo.filtrar("nada_disso")
    assert modelo.visiveis == []


def test_filtro_vazio_mostra_tudo():
    modelo = _multipla()
    modelo.filtrar("alpha")
    modelo.filtrar("")
    assert modelo.indices_visiveis == [0, 1, 2]


def test_marca_feita_antes_do_filtro_continua_depois():
    modelo = _multipla()
    modelo.alternar(2)
    modelo.filtrar("alpha")
    assert modelo.marcados == {2}  # gamma saiu da tela, mas segue marcada
    modelo.filtrar("")
    assert modelo.selecionados() == ["c"]


def test_selecionados_vem_na_ordem_da_lista_original():
    modelo = _multipla()
    modelo.alternar(2)
    modelo.alternar(0)
    assert modelo.selecionados() == ["a", "c"]


def test_modo_unico_a_marca_sempre_fica_numa_opcao_visivel():
    modelo = ModeloSelecao(_escolhas(), modo=UNICA)
    modelo.filtrar("gamma")
    assert modelo.marcados == {2}
    modelo.filtrar("nada_disso")
    assert modelo.marcados == set()
    modelo.filtrar("beta")
    assert modelo.marcados == {1}


# ---------------------------------------------------------------------------
# Selecionar todas / limpar
# ---------------------------------------------------------------------------


def test_marcar_todas_marca_tudo_sem_filtro():
    modelo = _multipla()
    assert modelo.marcar_todas() == 3
    assert modelo.marcados == {0, 1, 2}
    assert modelo.selecionados() == ["a", "b", "c"]


def test_marcar_todas_marca_só_o_que_esta_visivel():
    modelo = _multipla()
    modelo.alternar(0)  # alpha já estava marcada
    modelo.filtrar("beta")
    modelo.marcar_todas()
    assert modelo.marcados == {0, 1}  # gamma não está visível: fica de fora
    assert modelo.contagem == (2, 1, 3)


def test_marcar_todas_com_filtro_semResultado_nao_marca_nada():
    modelo = _multipla()
    modelo.filtrar("nada_disso")
    assert modelo.marcar_todas() == 0
    assert modelo.marcados == set()


def test_limpar_desflega_tudo():
    modelo = _multipla()
    modelo.marcar_todas()
    modelo.limpar()
    assert modelo.marcados == set()
    assert modelo.selecionados() == []


def test_limpar_no_modo_unico_nao_fica_sem_resposta():
    modelo = ModeloSelecao(_escolhas(), modo=UNICA)
    modelo.selecionar(2)
    modelo.limpar()
    assert modelo.marcados == {0}


# ---------------------------------------------------------------------------
# Barra de status
# ---------------------------------------------------------------------------


def test_contagem_e_marcadas_visiveis_total():
    modelo = _multipla()
    assert modelo.contagem == (0, 3, 3)
    modelo.alternar(0)
    modelo.filtrar("alpha")
    assert modelo.contagem == (1, 1, 3)


def test_visiveis_com_atencao_conta_somente_aviso_e_erro_visiveis():
    escolhas = [
        Choice(title="clientes", value="clientes"),  # neutro
        Choice(title="pedidos", value="pedidos", status=Status.AVISO, detalhe="já existe"),
        Choice(title="produtos", value="produtos", status=Status.ERRO),
        Choice(title="vendas", value="vendas", status=Status.INFO, detalhe="2 tabelas"),
    ]
    modelo = ModeloSelecao(escolhas)
    assert modelo.visiveis_com_atencao == 2

    modelo.filtrar("clientes")
    assert modelo.visiveis_com_atencao == 0  # nenhum visível está em atenção


def test_visiveis_com_atencao_com_filtro_sobre_a_tabela_existente():
    escolhas = [
        Choice(title="public.clientes", value="clientes", status=Status.INFO, detalhe="3 tabelas"),
        Choice(title="public.pedidos", value="pedidos", status=Status.AVISO, detalhe="já existe"),
    ]
    modelo = ModeloSelecao(escolhas)
    modelo.filtrar("clientes")
    assert modelo.visiveis_com_atencao == 0
    modelo.filtrar("já existe")
    assert modelo.visiveis_com_atencao == 1
