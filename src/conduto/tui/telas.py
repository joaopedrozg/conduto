"""Telas Textual do Conduto: os abrigos avulsos dos painéis.

Cada ``Tela*`` hospeda um painel de :mod:`conduto.tui.paineis` em tela
cheia — o mesmo painel que o shell do wizard monta dentro da etapa atual.
É o que aparece num terminal interativo **sem** sessão do wizard (prompt
avulso); sem terminal interativo os prompts caem no ``input()`` numerado
(ver :mod:`conduto.tui.prompts`).

Cores são sempre status: verde = marcado/OK, âmbar = atenção, azul =
informação, cinza = neutro, vermelho = erro/sem resultado (ver
:mod:`conduto.tui.tema`).
"""

from __future__ import annotations

from typing import Any, List

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer

from conduto.tui.modelo import ModeloSelecao
from conduto.tui.paineis import PainelConfirmacao, PainelSelecao, PainelTexto
from conduto.tui.tema import CSS_TEMA

__all__ = ["TelaConfirmacao", "TelaSelecao", "TelaTexto"]


class _TelaBase(App):
    """Base das telas: tema único, paleta de status e cancelamento.

    ``ctrl+c`` tem binding de prioridade para vencer o ``copy`` do ``Input``
    quando o campo de busca estiver focado; ``esc``/``enter``/``y``/``n``
    são do painel hospedado e chegam pela cadeia de foco, do mesmo jeito que
    dentro do shell.
    """

    CSS = CSS_TEMA
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+c", "cancelar", show=False, priority=True),
    ]

    #: O painel hospedado — focado na abertura para os atalhos valerem.
    _painel: Any = None

    def action_cancelar(self) -> None:
        """``ctrl+c``: sai sem resposta (o chamador trata como cancelar)."""
        self._finalizar(None)

    def action_help_quit(self) -> None:
        """Fallback do ``ctrl+c`` caso o binding de prioridade não pegue."""
        self.action_cancelar()

    def _finalizar(self, resultado: Any) -> None:
        """Encerra a tela devolvendo ``resultado`` para quem chamou ``run()``."""
        self.exit(resultado)

    def rodar(self) -> Any:
        """Roda a tela em tela cheia e devolve o resultado de :meth:`_finalizar`."""
        return self.run()

    def on_mount(self) -> None:
        if self._painel is not None:
            self._painel.ao_exibir()


class TelaSelecao(_TelaBase):
    """Seleção de opções com marcação individual e "selecionar todas".

    Comportamento, atalhos e barra de status moram no
    :class:`conduto.tui.paineis.PainelSelecao`; aqui a tela só hospeda.
    """

    def __init__(
        self,
        pergunta: str,
        modelo: ModeloSelecao,
        instrucao: str | None = None,
        com_busca: bool = True,
    ) -> None:
        super().__init__()
        self.pergunta = pergunta
        self.modelo = modelo
        self.instrucao = instrucao or ""
        self.com_busca = com_busca
        self.painel = PainelSelecao(
            pergunta=pergunta,
            modelo=modelo,
            instrucao=self.instrucao,
            com_busca=com_busca,
            ao_responder=self._finalizar,
            ao_cancelar=lambda: self._finalizar(None),
        )
        self._painel = self.painel

    @property
    def ordem(self) -> List[int]:
        """Índices absolutos exibidos, na ordem das linhas da tabela."""
        return self.painel.ordem

    @property
    def barra_status(self) -> str:
        """Texto puro da barra de status (sem cor)."""
        return self.painel.barra_status

    def compose(self) -> ComposeResult:
        yield self.painel
        yield Footer()


class TelaTexto(_TelaBase):
    """Campo de texto (ou senha) — ``enter`` confirma, ``esc`` cancela."""

    def __init__(
        self,
        pergunta: str,
        valor_inicial: str = "",
        senha: bool = False,
        instrucao: str | None = None,
    ) -> None:
        super().__init__()
        self.pergunta = pergunta
        self.valor_inicial = valor_inicial
        self.senha = senha
        self.instrucao = instrucao or ""
        self.painel = PainelTexto(
            pergunta=pergunta,
            valor_inicial=valor_inicial,
            senha=senha,
            instrucao=self.instrucao,
            ao_responder=self._finalizar,
            ao_cancelar=lambda: self._finalizar(None),
        )
        self._painel = self.painel

    def compose(self) -> ComposeResult:
        yield self.painel
        yield Footer()


class TelaConfirmacao(_TelaBase):
    """Pergunta de sim/não — ``y``/``n`` respondem, ``enter`` aceita o padrão."""

    def __init__(
        self,
        pergunta: str,
        padrao: bool = True,
        instrucao: str | None = None,
    ) -> None:
        super().__init__()
        self.pergunta = pergunta
        self.padrao = padrao
        self.instrucao = instrucao or ""
        self.painel = PainelConfirmacao(
            pergunta=pergunta,
            padrao=padrao,
            instrucao=self.instrucao,
            ao_responder=self._finalizar,
            ao_cancelar=lambda: self._finalizar(None),
        )
        self._painel = self.painel

    def compose(self) -> ComposeResult:
        yield self.painel
        yield Footer()
