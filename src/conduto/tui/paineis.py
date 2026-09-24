"""Painéis das perguntas: o conteúdo das telas, como widgets montáveis.

Os mesmos painéis servem os dois abrigos: a :class:`conduto.tui.telas.Tela*`
(avulsa, em tela cheia — o caso sem sessão do wizard) e o shell
:mod:`conduto.tui.shell`, em que cada painel entra na etapa atual do fluxo.

A regra de negócio — filtrar, flegar, "selecionar todas" e devolver os
valores — mora em :mod:`conduto.tui.modelo`. Aqui só desenhamos, ligamos os
atalhos de teclado (visíveis no rodapé) e traduzimos os rótulos via
:func:`conduto.i18n.t`.

Um painel ``bloqueado=True`` é a **revisão** de uma pergunta já respondida:
os mesmos widgets, sem atalhos e sem edição (o shell o mostra ao clicar na
etapa lateral).

Cores são sempre status: verde = marcado/OK, âmbar = atenção, azul =
informação, cinza = neutro, vermelho = erro/sem resultado (ver
:mod:`conduto.tui.tema`).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.css.query import NoMatches
from textual.widgets import Button, DataTable, Input, Static

from conduto.i18n import t
from conduto.tui.modelo import MULTIPLA, UNICA, Choice, ModeloSelecao
from conduto.tui.tema import Status, cor, glifo

__all__ = [
    "PainelConfirmacao",
    "PainelSelecao",
    "PainelTexto",
    "Revisao",
]

#: Tipos de pergunta gravados na revisão (espelham os painéis).
TIPO_MULTIPLA = "multipla"
TIPO_UNICA = "unica"
TIPO_TEXTO = "texto"
TIPO_CONFIRMACAO = "confirmacao"


def _sem_enter(bindings: List[Binding]) -> List[Binding]:
    """As bindings do widget **menos** ``enter`` — o ``enter`` é do painel.

    Com a tecla livre, o binding do painel (descrição traduzida no momento do
    uso) fica ativo e aparece no rodapé como "enter Confirmar"; a ação do
    painel faz o mesmo que o widget faria.
    """
    return [
        vinculo
        for vinculo in bindings
        if "enter" not in {chave.strip() for chave in vinculo.key.split(",")}
    ]


class _InputBusca(Input, inherit_bindings=False):
    """Campo de filtro: ``esc`` volta para a lista, ``enter`` confirma no painel."""

    BINDINGS = [
        *_sem_enter(Input.BINDINGS),
        Binding("escape", "focar_tabela", show=False),
    ]

    def action_focar_tabela(self) -> None:
        # Escopo é o painel que me contém — no shell há várias tabelas.
        no = self.parent
        while no is not None and not isinstance(no, PainelSelecao):
            no = no.parent
        if no is not None:
            no.query_one("#tabela", DataTable).focus()


class _Entrada(Input, inherit_bindings=False):
    """Campo de texto em que ``enter`` vai para o painel (``action_enviar``)."""

    BINDINGS = _sem_enter(Input.BINDINGS)


class _Tabela(DataTable, inherit_bindings=False):
    """Lista em que ``enter`` vai para o painel (``action_confirmar``)."""

    BINDINGS = _sem_enter(DataTable.BINDINGS)


class _Painel(Vertical):
    """Base dos painéis: pergunta, dica e o par confirmar/cancelar.

    Os atalhos (``enter``/``esc`` e amigos) são bindings **do painel** — na
    cadeia de foco eles valem do mesmo jeito que bindings de app, e é assim
    que os mesmos widgets funcionam avulsos ou dentro do shell.

    ``can_focus`` liga o painel como widget focável: a confirmação não tem
    campo nenhum e precisa receber o foco para ``y``/``n``/``enter`` chegarem
    nela.
    """

    can_focus = True
    #: Este painel aceita foco quando exibido? (revisão bloqueada de texto: não)
    pode_focar: bool = True
    #: O shell monta o painel dentro da etapa: focar quando a montagem terminar
    #: (é o momento em que campo/lista já existem). Avulso quem foca é a tela.
    focar_ao_montar: bool = False

    def __init__(
        self,
        pergunta: Any,
        instrucao: Optional[str] = None,
        *,
        bloqueado: bool = False,
        ao_responder: Optional[Callable[[Any], None]] = None,
        ao_cancelar: Optional[Callable[[], None]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.pergunta = pergunta
        self.instrucao = instrucao or ""
        self.bloqueado = bloqueado
        #: Chamado com a resposta (o shell liga isto ao futuro do prompt).
        self.ao_responder = ao_responder
        #: Chamado quando o usuário cancela (esc) — o shell destrava com ``None``.
        self.ao_cancelar = ao_cancelar
        if bloqueado:
            self.add_class("bloqueado")

    def _vincular(
        self, chave: str, acao: str, descricao: str, key_display: Optional[str] = None
    ) -> None:
        """Liga uma tecla ao painel.

        ``Widget`` não tem ``.bind()``; as bindings de instância entram no
        mapa próprio do nó (cópia do merge de classe feita na construção).
        """
        self._bindings.bind(chave, acao, description=descricao, key_display=key_display)

    def _finalizar(self, resultado: Any) -> None:
        """Devolve a resposta ao hospedeiro (ou ignora, se bloqueado)."""
        if self.bloqueado:
            return
        if self.ao_responder is not None:
            self.ao_responder(resultado)

    def action_cancelar(self) -> None:
        """``esc``: cancela o prompt (o chamador trata ``None`` como sair)."""
        if self.bloqueado:
            return
        if self.ao_cancelar is not None:
            self.ao_cancelar()

    def focar(self) -> None:
        """Foca o widget de entrada do painel (ou o painel, se não houver)."""
        raise NotImplementedError

    def ao_exibir(self) -> None:
        """Chamado por quem hospeda quando o painel fica visível e ativo."""
        if self.pode_focar:
            self.focar()

    def on_mount(self) -> None:
        # No shell o painel é montado dinamicamente dentro da etapa: o foco
        # vem aqui, quando os filhos (campo/lista) já estão no DOM.
        if self.focar_ao_montar:
            self.focar_ao_montar = False
            self.ao_exibir()

    def _cabecalho(self):
        """Pergunta + linha de dica (compartilhado por todos os painéis)."""
        yield Static(self.pergunta, id="pergunta")
        if self.instrucao:
            yield Static(self.instrucao, id="dica")


class PainelSelecao(_Painel):
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
        *,
        bloqueado: bool = False,
        ao_responder: Optional[Callable[[Any], None]] = None,
        ao_cancelar: Optional[Callable[[], None]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            pergunta,
            instrucao,
            bloqueado=bloqueado,
            ao_responder=ao_responder,
            ao_cancelar=ao_cancelar,
            **kwargs,
        )
        self.modelo = modelo
        self.com_busca = com_busca
        #: Índices absolutos exibidos, na ordem das linhas da tabela.
        self.ordem: List[int] = []
        #: Texto puro da barra de status (sem cor) — útil para testes e logs.
        self.barra_status = ""
        if bloqueado:
            return  # revisão: sem atalhos (só rolagem da tabela)
        if modelo.modo == MULTIPLA:
            self._vincular(
                "space",
                "alternar",
                t("Alternar marcação"),
                key_display=t("espaço"),
            )
            self._vincular("a", "marcar_todas", t("Selecionar todas"))
            self._vincular("l", "limpar", t("Limpar"))
        if com_busca:
            self._vincular("slash", "focar_busca", t("Filtrar"))
        # enter confirma em qualquer foco (no rodapé é a dica de confirmar);
        # o widget focado tem prioridade, então lista/filtro/botão seguem
        # respondendo primeiro — este binding é o fallback e o rótulo.
        self._vincular("enter", "confirmar", t("Confirmar"))
        self._vincular("escape", "cancelar", t("Cancelar"))

    # ------------------------------------------------------------------
    # Montagem
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield from self._cabecalho()
        barra = self._barra()
        if barra:
            yield Horizontal(*barra, id="acoes")
        yield _Tabela(id="tabela", cursor_type="row", zebra_stripes=False)
        yield Static("", id="status")

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
                _InputBusca(
                    placeholder=t("Digite para filtrar..."),
                    id="busca",
                    disabled=self.bloqueado,
                )
            )
        if self.modelo.modo == MULTIPLA:
            if not itens:
                itens.append(Static("", id="espacador"))
            itens += [
                Button(t("Alternar"), id="btn-alternar", disabled=self.bloqueado),
                Button(t("Selecionar todas"), id="btn-todas", disabled=self.bloqueado),
                Button(t("Limpar"), id="btn-limpar", disabled=self.bloqueado),
            ]
        return itens

    def on_mount(self) -> None:
        super().on_mount()  # foco pós-montagem (focar_ao_montar do shell)
        self._desenhar_linhas()
        if self.modelo.modo != MULTIPLA:
            return
        try:
            botao = self.query_one("#btn-todas", Button)
        except NoMatches:
            # O shell pode estar fechando no meio da montagem: o corpo acabou
            # logo depois da resposta e o ``app.exit()`` derrubou a barra
            # (neta no DOM) antes de ela subir. O tooltip é enfeite — não
            # pode derrubar o comando com um NoMatches.
            return
        botao.tooltip = t("Marca só o que está visível com o filtro atual.")

    def focar(self) -> None:
        if self.com_busca and not self.bloqueado:
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
    # Ações (atalhos do painel + botões)
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
        if self.com_busca and not self.bloqueado:
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
        if self.bloqueado or self.modelo.modo != UNICA or not self.ordem:
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
        if self.bloqueado:
            return  # revisão: clicar na linha só rola, não responde
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


class PainelTexto(_Painel):
    """Campo de texto (ou senha) — ``enter`` confirma, ``esc`` cancela.

    Só o campo, sem botões: o rodapé mostra os dois atalhos.
    """

    def __init__(
        self,
        pergunta: str,
        valor_inicial: str = "",
        senha: bool = False,
        instrucao: Optional[str] = None,
        *,
        bloqueado: bool = False,
        ao_responder: Optional[Callable[[Any], None]] = None,
        ao_cancelar: Optional[Callable[[], None]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            pergunta,
            instrucao,
            bloqueado=bloqueado,
            ao_responder=ao_responder,
            ao_cancelar=ao_cancelar,
            **kwargs,
        )
        self.valor_inicial = valor_inicial
        self.senha = senha
        #: Revisão bloqueada não tem widget focável.
        self.pode_focar = not bloqueado
        if bloqueado:
            return
        self._vincular("enter", "enviar", t("Confirmar"))
        self._vincular("escape", "cancelar", t("Cancelar"))

    def compose(self) -> ComposeResult:
        yield from self._cabecalho()
        yield _Entrada(
            value=self.valor_inicial,
            password=self.senha,
            placeholder=t("Digite..."),
            id="entrada",
            disabled=self.bloqueado,
        )

    def focar(self) -> None:
        self.query_one("#entrada", _Entrada).focus()

    def action_enviar(self) -> None:
        """``enter``: devolve o texto do campo (mostrado no rodapé)."""
        self._finalizar(self.query_one("#entrada", Input).value)


class PainelConfirmacao(_Painel):
    """Pergunta de sim/não — ``y``/``n`` respondem, ``enter`` aceita o padrão.

    Sem botões: o padrão aparece ao lado da pergunta (``[Sim/não]``, letra
    maiúscula = padrão) e as respostas ficam no rodapé. Na revisão de uma
    etapa (``bloqueado``), o padrão é trocado pela **resposta dada**.
    """

    def __init__(
        self,
        pergunta: str,
        padrao: bool = True,
        instrucao: Optional[str] = None,
        *,
        bloqueado: bool = False,
        ao_responder: Optional[Callable[[Any], None]] = None,
        ao_cancelar: Optional[Callable[[], None]] = None,
        resposta: Optional[bool] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            pergunta,
            instrucao,
            bloqueado=bloqueado,
            ao_responder=ao_responder,
            ao_cancelar=ao_cancelar,
            **kwargs,
        )
        self.padrao = padrao
        #: Resposta já dada (revisão) — ``None`` na tela normal.
        self.resposta = resposta
        #: Sem campo: o próprio painel recebe o foco nos modos ativos.
        self.pode_focar = not bloqueado
        if bloqueado:
            return
        self._vincular("y", "sim", t("Sim"))
        self._vincular("n", "nao", t("Não"))
        self._vincular("enter", "responder", t("Confirmar"))
        self._vincular("escape", "cancelar", t("Cancelar"))

    def compose(self) -> ComposeResult:
        yield Static(self._pergunta_com_padrao(), id="pergunta")
        if self.instrucao:
            yield Static(self.instrucao, id="dica")

    def _pergunta_com_padrao(self) -> Text:
        """Pergunta + marca do padrão (ou da resposta, na revisão) em azul."""
        texto = Text(str(self.pergunta))
        if self.resposta is not None:
            # Revisão: o que foi respondido, não o que seria respondido.
            rotulo = t("sim") if self.resposta else t("não")
            texto.append(f"  \u2192 {rotulo.capitalize()}", style=cor(Status.INFO))
            return texto
        sim, nao = t("sim"), t("n\u00e3o")
        if self.padrao:
            rotulo = f"[{sim.capitalize()}/{nao.lower()}]"
        else:
            rotulo = f"[{sim.lower()}/{nao.capitalize()}]"
        texto.append(f"  {rotulo}", style=cor(Status.INFO))
        return texto

    def focar(self) -> None:
        self.focus()

    def action_sim(self) -> None:
        self._finalizar(True)

    def action_nao(self) -> None:
        self._finalizar(False)

    def action_responder(self) -> None:
        """``enter``: aceita o padrão marcado ao lado da pergunta."""
        self._finalizar(self.padrao)


class Revisao(VerticalScroll):
    """Etapa já respondida: as perguntas como painéis bloqueados, em coluna."""

    def __init__(self, especificacoes: List[Dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.especificacoes = especificacoes

    def compose(self) -> ComposeResult:
        yield Static(t("Revis\u00e3o \u00b7 somente leitura"), classes="titulo-revisao")
        for especificacao in self.especificacoes:
            yield painel_de(especificacao)


def painel_de(especificacao: Dict[str, Any]) -> _Painel:
    """Reconstrói o painel de uma pergunta já respondida (sempre bloqueado).

    A especificação é o que o prompt gravou ao obter a resposta: pergunta,
    dica, opções e o valor dado — o suficiente para redesenhar o mesmo
    widget sem voltar a perguntar.
    """
    tipo = especificacao["tipo"]
    if tipo in (TIPO_MULTIPLA, TIPO_UNICA):
        modo = MULTIPLA if tipo == TIPO_MULTIPLA else UNICA
        modelo = ModeloSelecao(list(especificacao["escolhas"]), modo=modo)
        if tipo == TIPO_MULTIPLA:
            marcados = especificacao.get("valor") or []
            for indice, item in enumerate(modelo.itens):
                if item.value in marcados:
                    modelo.alternar(indice)
        else:
            valor = especificacao.get("valor")
            if isinstance(valor, list):
                # O painel grava as marcas (lista), como no múltiplo: a revisão
                # do único fica com a primeira delas — o valor do prompt.
                valor = valor[0] if valor else None
            for indice, item in enumerate(modelo.itens):
                if item.value == valor:
                    modelo.selecionar(indice)
                    break
        return PainelSelecao(
            especificacao["pergunta"],
            modelo,
            especificacao.get("dica") or None,
            bool(especificacao.get("com_busca", True)),
            bloqueado=True,
        )
    if tipo == TIPO_TEXTO:
        return PainelTexto(
            especificacao["pergunta"],
            especificacao.get("valor") or "",
            senha=bool(especificacao.get("senha", False)),
            instrucao=especificacao.get("dica") or None,
            bloqueado=True,
        )
    if tipo == TIPO_CONFIRMACAO:
        return PainelConfirmacao(
            especificacao["pergunta"],
            padrao=bool(especificacao.get("padrao", True)),
            instrucao=especificacao.get("dica") or None,
            bloqueado=True,
            resposta=especificacao.get("valor"),
        )
    raise ValueError(f"Pergunta de revis\u00e3o com tipo desconhecido: {tipo!r}")
