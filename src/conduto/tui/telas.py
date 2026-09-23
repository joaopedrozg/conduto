"""Telas Textual do Conduto: seleção (múltipla/única), texto e confirmação.

A regra de negócio — filtrar, flegar, "selecionar todas" e devolver os
valores — mora em :mod:`conduto.tui.modelo`. Aqui só desenhamos, ligamos os
atalhos de teclado (visíveis no rodapé) e traduzimos os rótulos via
:func:`conduto.i18n.t`.

Cores são sempre status: verde = marcado/OK, âmbar = atenção, azul =
informação, cinza = neutro, vermelho = erro/sem resultado (ver
:mod:`conduto.tui.tema`).
"""

from __future__ import annotations

from typing import Any, List, Optional

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.coordinate import Coordinate
from textual.widgets import Button, DataTable, Footer, Input, Static

from conduto.i18n import t
from conduto.tui.modelo import MULTIPLA, UNICA, Choice, ModeloSelecao
from conduto.tui.tema import CSS_TEMA, Status, cor, glifo

__all__ = ["TelaConfirmacao", "TelaSelecao", "TelaTexto"]


def _sem_enter(bindings: List[Binding]) -> List[Binding]:
    """As bindings do widget **menos** ``enter`` — o ``enter`` é do app.

    Com a tecla livre, o binding do app (descrição traduzida no momento do
    uso) fica ativo e aparece no rodapé como "enter Confirmar"; a ação do
    app faz o mesmo que o widget faria.
    """
    return [
        vinculo
        for vinculo in bindings
        if "enter" not in {chave.strip() for chave in vinculo.key.split(",")}
    ]


class _InputBusca(Input, inherit_bindings=False):
    """Campo de filtro: ``esc`` volta para a lista, ``enter`` confirma no app."""

    BINDINGS = [
        *_sem_enter(Input.BINDINGS),
        Binding("escape", "focar_tabela", show=False),
    ]

    def action_focar_tabela(self) -> None:
        self.app.query_one("#tabela", DataTable).focus()


class _Entrada(Input, inherit_bindings=False):
    """Campo de texto em que ``enter`` vai para o app (``action_enviar``)."""

    BINDINGS = _sem_enter(Input.BINDINGS)


class _Tabela(DataTable, inherit_bindings=False):
    """Lista em que ``enter`` vai para o app (``action_confirmar``)."""

    BINDINGS = _sem_enter(DataTable.BINDINGS)


class _TelaBase(App):
    """Base das telas: tema único, paleta de status e cancelamento.

    ``ctrl+c`` tem binding de prioridade para vencer o ``copy`` do ``Input``
    quando o campo de busca estiver focado; ``ctrl+q`` (herdado) encerra com
    ``None``, que também significa cancelamento.
    """

    CSS = CSS_TEMA
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+c", "cancelar", show=False, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.bind("escape", "cancelar", description=t("Cancelar"), show=True)

    def action_cancelar(self) -> None:
        """``esc``/``ctrl+c``: sai sem resposta (o chamador trata como cancelar)."""
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


class TelaSelecao(_TelaBase):
    """Seleção de opções com marcação individual e "selecionar todas".

    No modo ``MULTIPLA`` a barra de ferramentas traz filtro + os botões de
    marcação (``espaço``/``a``/``l`` também); no modo ``UNICA`` vale o cursor
    da lista (como um rádio). Confirmar/cancelar são só teclado — ``enter``
    e ``esc``, com o par no rodapé. O filtro (quando presente) vem focado:
    dá para digitar já na abertura, ``esc`` leva para a lista e ``/`` volta
    para o filtro.
    """

    def __init__(
        self,
        pergunta: str,
        modelo: ModeloSelecao,
        instrucao: Optional[str] = None,
        com_busca: bool = True,
    ) -> None:
        super().__init__()
        self.pergunta = pergunta
        self.modelo = modelo
        self.instrucao = instrucao or ""
        self.com_busca = com_busca
        #: Índices absolutos exibidos, na ordem das linhas da tabela.
        self.ordem: List[int] = []
        #: Texto puro da barra de status (sem cor) — útil para testes e logs.
        self.barra_status = ""
        if modelo.modo == MULTIPLA:
            self.bind(
                "space",
                "alternar",
                description=t("Alternar marcação"),
                key_display=t("espaço"),
            )
            self.bind("a", "marcar_todas", description=t("Selecionar todas"))
            self.bind("l", "limpar", description=t("Limpar"))
        if com_busca:
            self.bind("slash", "focar_busca", description=t("Filtrar"))
        # enter confirma em qualquer foco (no rodapé é a dica de confirmar);
        # o widget focado tem prioridade, então lista/filtro/botão seguem
        # respondendo primeiro — este binding é o fallback e o rótulo.
        self.bind("enter", "confirmar", description=t("Confirmar"))

    # ------------------------------------------------------------------
    # Montagem
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(self.pergunta, id="pergunta")
        if self.instrucao:
            yield Static(self.instrucao, id="dica")
        barra = self._barra()
        if barra:
            yield Horizontal(*barra, id="acoes")
        yield _Tabela(id="tabela", cursor_type="row", zebra_stripes=False)
        yield Static("", id="status")
        yield Footer()

    def _barra(self) -> List[Any]:
        """Barra de ferramentas: filtro à esquerda, marcação à direita.

        Sem pares de botões grandes: confirmar é ``enter`` e cancelar é
        ``esc``, os dois visíveis no rodapé. Os botões daqui são chips de
        uma linha — ações específicas desta tela (``espaço``/``a``/``l``
        fazem o mesmo pelo teclado).
        """
        itens: List[Any] = []
        if self.com_busca:
            itens.append(
                _InputBusca(placeholder=t("Digite para filtrar..."), id="busca")
            )
        if self.modelo.modo == MULTIPLA:
            if not itens:
                itens.append(Static("", id="espacador"))
            itens += [
                Button(t("Alternar"), id="btn-alternar"),
                Button(t("Selecionar todas"), id="btn-todas"),
                Button(t("Limpar"), id="btn-limpar"),
            ]
        return itens

    def on_mount(self) -> None:
        self._desenhar_linhas()
        if self.modelo.modo == MULTIPLA:
            self.query_one("#btn-todas", Button).tooltip = t(
                "Marca só o que está visível com o filtro atual."
            )
        if self.com_busca:
            self.query_one("#busca", _InputBusca).focus()
        else:
            self.query_one("#tabela", DataTable).focus()

    # ------------------------------------------------------------------
    # Desenho da lista
    # ------------------------------------------------------------------

    def _garantir_colunas(self) -> None:
        tabela = self.query_one("#tabela", DataTable)
        if not tabela.columns:
            tabela.add_column("", width=3)  # marca (✓ / ● / ○)
            tabela.add_column(t("Opção"))
            tabela.add_column("")  # estado (glifo + detalhe)

    def _desenhar_linhas(self) -> None:
        """Redesenha as linhas visíveis preservando cursor e marcação."""
        tabela = self.query_one("#tabela", DataTable)
        self._garantir_colunas()
        cursor_antigo = tabela.cursor_row
        self.ordem = list(self.modelo.indices_visiveis)
        cursor = min(cursor_antigo, max(len(self.ordem) - 1, 0))
        if self.modelo.modo == UNICA and self.modelo.marcados:
            # No modo único o cursor acompanha a opção marcada, se visível.
            marcado = next(iter(self.modelo.marcados))
            if marcado in self.ordem:
                cursor = self.ordem.index(marcado)
        tabela.clear()
        for absoluto in self.ordem:
            escolha = self.modelo.itens[absoluto]
            tabela.add_row(
                self._celula_marca(absoluto),
                escolha.title,
                self._celula_estado(escolha),
            )
        if self.ordem:
            tabela.move_cursor(row=cursor, animate=False)
        self._atualizar_status()

    def _celula_marca(self, absoluto: int) -> Text:
        marcado = self.modelo.esta_marcado(absoluto)
        if self.modelo.modo == UNICA:
            status = Status.OK if marcado else Status.NEUTRO
            return Text(glifo(status), style=cor(status))
        if marcado:
            return Text("\u2713", style=cor(Status.OK))  # ✓
        return Text(glifo(Status.NEUTRO), style=cor(Status.NEUTRO))  # ○

    @staticmethod
    def _celula_estado(escolha: Choice) -> Text:
        if escolha.status is Status.NEUTRO and not escolha.detalhe:
            return Text("")
        rotulo = f"{glifo(escolha.status)} {escolha.detalhe}".rstrip()
        return Text(rotulo, style=cor(escolha.status))

    def _atualizar_marcas(self) -> None:
        """Atualiza só a coluna da marca (sem mexer no cursor da tabela)."""
        tabela = self.query_one("#tabela", DataTable)
        for linha, absoluto in enumerate(self.ordem):
            tabela.update_cell_at(
                Coordinate(linha, 0), self._celula_marca(absoluto)
            )

    def _atualizar_status(self) -> None:
        marcadas, visiveis, _total = self.modelo.contagem
        barra = Text()
        if visiveis == 0:
            barra.append(t("nenhum resultado"), style=cor(Status.ERRO))
        else:
            if self.modelo.modo == MULTIPLA:
                barra.append(
                    t("{qtd} marcadas", qtd=marcadas), style=cor(Status.OK)
                )
                barra.append("  \u00b7  ", style=cor(Status.NEUTRO))
            barra.append(
                t("{qtd} vis\u00edveis", qtd=visiveis), style=cor(Status.NEUTRO)
            )
            atencao = self.modelo.visiveis_com_atencao
            if atencao:
                barra.append("  \u00b7  ", style=cor(Status.NEUTRO))
                barra.append(
                    t("{qtd} com aten\u00e7\u00e3o", qtd=atencao),
                    style=cor(Status.AVISO),
                )
        self.barra_status = str(barra)
        self.query_one("#status", Static).update(barra)

    # ------------------------------------------------------------------
    # Ações (atalhos do app + botões)
    # ------------------------------------------------------------------

    def action_alternar(self) -> None:
        if not self.ordem:
            return
        linha = self.query_one("#tabela", DataTable).cursor_row
        if not 0 <= linha < len(self.ordem):
            linha = 0
        absoluto = self.ordem[linha]
        self.modelo.alternar(absoluto)
        self._atualizar_marcas()
        self._atualizar_status()

    def action_marcar_todas(self) -> None:
        """Marca todas as opções **visíveis** (o filtro manda)."""
        self.modelo.marcar_todas()
        self._atualizar_marcas()
        self._atualizar_status()

    def action_limpar(self) -> None:
        """Desflega tudo."""
        self.modelo.limpar()
        self._atualizar_marcas()
        self._atualizar_status()

    def action_confirmar(self) -> None:
        """Confirma a seleção (ou a opção do cursor no modo único)."""
        self._finalizar(self.modelo.selecionados())

    def action_focar_busca(self) -> None:
        if self.com_busca:
            self.query_one("#busca", _InputBusca).focus()

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------

    @on(Input.Changed, "#busca")
    def _ao_filtrar(self, evento: Input.Changed) -> None:
        del evento
        self.modelo.filtrar(self.query_one("#busca", _InputBusca).value)
        self._desenhar_linhas()

    @on(DataTable.RowHighlighted, "#tabela")
    def _ao_realcar_linha(self, evento: DataTable.RowHighlighted) -> None:
        if self.modelo.modo != UNICA or not self.ordem:
            return
        if not 0 <= evento.cursor_row < len(self.ordem):
            return
        absoluto = self.ordem[evento.cursor_row]
        if self.modelo.marcados == {absoluto}:
            return
        self.modelo.selecionar(absoluto)
        self._atualizar_marcas()

    @on(DataTable.RowSelected, "#tabela")
    def _ao_escolher_linha(self, evento: DataTable.RowSelected) -> None:
        if self.modelo.modo == UNICA and self.ordem:
            if 0 <= evento.cursor_row < len(self.ordem):
                self.modelo.selecionar(self.ordem[evento.cursor_row])
        self.action_confirmar()

    @on(Button.Pressed)
    def _ao_pressionar_botao(self, evento: Button.Pressed) -> None:
        acoes = {
            "btn-alternar": self.action_alternar,
            "btn-todas": self.action_marcar_todas,
            "btn-limpar": self.action_limpar,
        }
        acao = acoes.get(evento.button.id or "")
        if acao is not None:
            acao()


class TelaTexto(_TelaBase):
    """Campo de texto (ou senha) — ``enter`` confirma, ``esc`` cancela.

    Só o campo, sem botões: o rodapé mostra os dois atalhos.
    """

    def __init__(
        self,
        pergunta: str,
        valor_inicial: str = "",
        senha: bool = False,
        instrucao: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.pergunta = pergunta
        self.valor_inicial = valor_inicial
        self.senha = senha
        self.instrucao = instrucao or ""
        self.bind("enter", "enviar", description=t("Confirmar"))

    def compose(self) -> ComposeResult:
        yield Static(self.pergunta, id="pergunta")
        if self.instrucao:
            yield Static(self.instrucao, id="dica")
        yield _Entrada(
            value=self.valor_inicial,
            password=self.senha,
            placeholder=t("Digite..."),
            id="entrada",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#entrada", _Entrada).focus()

    def action_enviar(self) -> None:
        """``enter``: devolve o texto do campo (mostrado no rodapé)."""
        self._finalizar(self.query_one("#entrada", Input).value)


class TelaConfirmacao(_TelaBase):
    """Pergunta de sim/não — ``y``/``n`` respondem, ``enter`` aceita o padrão.

    Sem botões: o padrão aparece ao lado da pergunta (``[Sim/não]``, letra
    maiúscula = padrão) e as respostas ficam no rodapé.
    """

    def __init__(
        self,
        pergunta: str,
        padrao: bool = True,
        instrucao: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.pergunta = pergunta
        self.padrao = padrao
        self.instrucao = instrucao or ""
        self.bind("y", "sim", description=t("Sim"))
        self.bind("n", "nao", description=t("Não"))
        self.bind("enter", "responder", description=t("Confirmar"))

    def compose(self) -> ComposeResult:
        yield Static(self._pergunta_com_padrao(), id="pergunta")
        if self.instrucao:
            yield Static(self.instrucao, id="dica")
        yield Footer()

    def _pergunta_com_padrao(self) -> Text:
        """Pergunta + marca do padrão em azul (letra maiúscula = padrão)."""
        sim, nao = t("sim"), t("não")
        if self.padrao:
            rotulo = f"[{sim.capitalize()}/{nao.lower()}]"
        else:
            rotulo = f"[{sim.lower()}/{nao.capitalize()}]"
        texto = Text(self.pergunta)
        texto.append(f"  {rotulo}", style=cor(Status.INFO))
        return texto

    def action_sim(self) -> None:
        self._finalizar(True)

    def action_nao(self) -> None:
        self._finalizar(False)

    def action_responder(self) -> None:
        """``enter``: aceita o padrão marcado ao lado da pergunta."""
        self._finalizar(self.padrao)
