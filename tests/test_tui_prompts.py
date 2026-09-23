"""Prompts públicos no modo sem terminal (CI, pipe, ``CONDUTO_SEM_TUI``).

Sem TUI o prompt cai num ``input()`` numerado — o CLI nunca deve quebrar por
falta de terminal. Aqui também ficam as assinaturas de sempre: ``selecionar``
devolve o valor, ``multi_selecionar`` devolve a lista de valores (``None`` ao
cancelar) e os kwargs de formatação (``{placeholder}``) separam dos demais.
"""

import builtins

import pytest

from conduto.i18n import definir_idioma
from conduto.tui import prompts
from conduto.tui.modelo import Choice
from conduto.tui.tema import Status


ESCOLHAS = [
    Choice(title="PostgreSQL", value="postgresql"),
    Choice(title="MySQL", value="mysql"),
    Choice(title="SQL Server", value="sqlserver"),
]


@pytest.fixture(autouse=True)
def _sem_tty(monkeypatch):
    """Força o fallback numerado e reseta o idioma (asserções em pt)."""
    definir_idioma("pt")
    monkeypatch.setenv("CONDUTO_SEM_TUI", "1")
    yield


def _com_entradas(entradas, monkeypatch):
    """Troca o ``input()`` por uma fila de respostas ensaiadas.

    Um item que é classe de exceção (``KeyboardInterrupt``) é levantado — é
    assim que o ``ctrl+c``/EOF chega num prompt de verdade.
    """
    fila = list(entradas)

    def _input(rotulo=""):
        print(rotulo, end="")
        if not fila:
            raise EOFError
        resposta = fila.pop(0)
        if isinstance(resposta, BaseException):
            raise resposta
        if isinstance(resposta, type) and issubclass(resposta, BaseException):
            raise resposta()
        return resposta

    monkeypatch.setattr(builtins, "input", _input)
    return fila


def _capturar(monkeypatch, saidas):
    """Guarda o que o fallback imprimiu (pergunta, lista e avisos)."""
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: saidas.append(" ".join(str(a) for a in args)))


# ---------------------------------------------------------------------------
# _tem_terminal
# ---------------------------------------------------------------------------


def test_variavel_conduto_sem_tui_desliga_a_tui():
    assert prompts._tem_terminal() is False


def test_sem_variavel_e_sem_tty_na_tambem_desliga(monkeypatch):
    monkeypatch.delenv("CONDUTO_SEM_TUI", raising=False)
    monkeypatch.setattr(prompts.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(prompts.sys.stdout, "isatty", lambda: True)
    assert prompts._tem_terminal() is False


def test_com_tty_interativo_a_tui_continua_ligada(monkeypatch):
    monkeypatch.delenv("CONDUTO_SEM_TUI", raising=False)
    monkeypatch.setattr(prompts.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(prompts.sys.stdout, "isatty", lambda: True)
    assert prompts._tem_terminal() is True


# ---------------------------------------------------------------------------
# _separar_formatacao
# ---------------------------------------------------------------------------


def test_formatacao_usa_so_os_kwargs_que_estao_na_mensagem():
    formatacao, demais = prompts._separar_formatacao(
        "Selecione o SGBD de {rotulo}:",
        {"rotulo": "origem", "style": "antigo", "use_jk_keys": False},
    )
    assert formatacao == {"rotulo": "origem"}
    assert demais == {"style": "antigo", "use_jk_keys": False}


def test_a_dica_tambem_pode_ter_placeholder():
    formatacao, demais = prompts._separar_formatacao(
        "Credenciais de {rotulo}",
        {"nome": "prod", "rotulo": "origem"},
        "{nome} está em {rotulo}",
    )
    assert formatacao == {"nome": "prod", "rotulo": "origem"}
    assert demais == {}


# ---------------------------------------------------------------------------
# selecionar (seleção única)
# ---------------------------------------------------------------------------


def test_selecionar_devolve_o_value_escolhido(monkeypatch):
    _com_entradas(["2"], monkeypatch)
    assert prompts.selecionar("Selecione o SGBD de {rotulo}:", ESCOLHAS, rotulo="origem") == "mysql"


def test_selecionar_em_branco_pega_o_primeiro(monkeypatch):
    _com_entradas([""], monkeypatch)
    assert prompts.selecionar("Selecione:", ESCOLHAS) == "postgresql"


def test_selecionar_fora_da_lista_pede_de_novo(monkeypatch):
    saidas = []
    _com_entradas(["9", "abc", "3"], monkeypatch)
    _capturar(monkeypatch, saidas)
    assert prompts.selecionar("Selecione:", ESCOLHAS) == "sqlserver"
    assert any("Escolha um número da lista." in linha for linha in saidas)


def test_selecionar_cancelado_devolve_none(monkeypatch):
    _com_entradas([KeyboardInterrupt], monkeypatch)
    assert prompts.selecionar("Selecione:", ESCOLHAS) is None


def test_selecionar_mostra_a_lista_com_o_detalhe(monkeypatch):
    saidas = []
    _com_entradas(["1"], monkeypatch)
    _capturar(monkeypatch, saidas)
    escolhas = [Choice(title="public", value="public", status=Status.INFO, detalhe="3 tabelas")]
    prompts.selecionar("Selecione os schemas da origem:", escolhas)
    assert any("Selecione os schemas da origem:" in linha for linha in saidas)
    assert any("public — 3 tabelas" in linha for linha in saidas)


# ---------------------------------------------------------------------------
# multi_selecionar (flegagem)
# ---------------------------------------------------------------------------


def test_multi_devolve_a_lista_de_valores_marcados(monkeypatch):
    _com_entradas(["1,3"], monkeypatch)
    assert prompts.multi_selecionar("Selecione:", ESCOLHAS) == ["postgresql", "sqlserver"]


def test_multi_em_branco_devolve_lista_vazia(monkeypatch):
    # Marcou nada: lista vazia (não é cancelamento).
    _com_entradas([""], monkeypatch)
    assert prompts.multi_selecionar("Selecione:", ESCOLHAS) == []


def test_multi_aceita_todos_ou_all(monkeypatch):
    for resposta in ("todos", "all", "*"):
        _com_entradas([resposta], monkeypatch)
        assert prompts.multi_selecionar("Selecione:", ESCOLHAS) == ["postgresql", "mysql", "sqlserver"]


def test_multi_remove_indices_repetidos(monkeypatch):
    _com_entradas(["2,2,1"], monkeypatch)
    assert prompts.multi_selecionar("Selecione:", ESCOLHAS) == ["mysql", "postgresql"]


def test_multi_ignora_estilo_e_use_jk_keys_legados(monkeypatch):
    _com_entradas(["1"], monkeypatch)
    resultado = prompts.multi_selecionar(
        "Selecione:",
        ESCOLHAS,
        instrucao="(setas navegam)",
        use_search_filter=True,
        style="antigo",
        use_jk_keys=False,
    )
    assert resultado == ["postgresql"]


def test_multi_sem_use_search_filter_ainda_funciona(monkeypatch):
    _com_entradas(["2"], monkeypatch)
    assert (
        prompts.multi_selecionar("Selecione:", ESCOLHAS, use_search_filter=False)
        == ["mysql"]
    )


def test_multi_sem_escolhas_devolve_vazia(monkeypatch):
    assert prompts.multi_selecionar("Selecione:", []) == []


def test_selecionar_sem_escolhas_devolve_none(monkeypatch):
    _com_entradas([""], monkeypatch)
    assert prompts.selecionar("Selecione:", []) is None


def test_multi_cancelado_devolve_none(monkeypatch):
    _com_entradas([EOFError], monkeypatch)
    assert prompts.multi_selecionar("Selecione:", ESCOLHAS) is None


def test_multi_mostra_a_dica_de_instrucao(monkeypatch):
    saidas = []
    _com_entradas(["1"], monkeypatch)
    _capturar(monkeypatch, saidas)
    prompts.multi_selecionar(
        "Selecione as tabelas para gerar os schemas:",
        ESCOLHAS,
        instrucao="(setas navegam, a marca todas)",
    )
    assert any("(setas navegam, a marca todas)" in linha for linha in saidas)


# ---------------------------------------------------------------------------
# confirmar / pedir / pedir_senha
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "resposta,esperado",
    [
        ("", True),  # padrão
        ("s", True),
        ("y", True),
        ("n", False),
        ("nao", False),
    ],
)
def test_confirmar_devolve_bool(monkeypatch, resposta, esperado):
    _com_entradas([resposta], monkeypatch)
    assert prompts.confirmar("Deseja continuar?") is esperado


def test_confirmar_com_padrao_nao(monkeypatch):
    _com_entradas([""], monkeypatch)
    assert prompts.confirmar("Deseja continuar?", padrao=False) is False


def test_confirmar_entrada_ruim_pede_de_novo(monkeypatch):
    _com_entradas(["talvez", "s"], monkeypatch)
    assert prompts.confirmar("Deseja continuar?") is True


def test_confirmar_cancelado_devolve_none(monkeypatch):
    _com_entradas([KeyboardInterrupt], monkeypatch)
    assert prompts.confirmar("Deseja continuar?") is None


def test_pedir_devolve_o_texto_digitado(monkeypatch):
    _com_entradas(["meu_host"], monkeypatch)
    assert prompts.pedir("Host:", padrao="localhost") == "meu_host"


def test_pedir_em_branco_devolve_o_padrao(monkeypatch):
    _com_entradas([""], monkeypatch)
    assert prompts.pedir("Host:", padrao="localhost") == "localhost"


def test_pedir_cancelado_devolve_none(monkeypatch):
    _com_entradas([EOFError], monkeypatch)
    assert prompts.pedir("Host:") is None


def test_pedir_senha_repassa_como_senha(monkeypatch):
    _com_entradas(["segredo"], monkeypatch)
    assert prompts.pedir_senha("Senha:", padrao="") == "segredo"


def test_pedir_formata_a_pergunta_e_ignora_os_demais_kwargs(monkeypatch):
    saidas = []
    _com_entradas(["ok"], monkeypatch)
    _capturar(monkeypatch, saidas)
    prompts.pedir("Credenciais do servidor de {rotulo} ({nome})", rotulo="origem", nome="prod", style="x")
    assert any("Credenciais do servidor de origem (prod)" in linha for linha in saidas)
