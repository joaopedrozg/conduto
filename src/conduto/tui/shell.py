"""Shell do wizard: cabeçalho, menu lateral de etapas e área de conteúdo.

O ``conduto init``/``conduto ddl`` rodam dentro deste app Textual. O **corpo**
do comando (mensagens, arquivos, conexões) vive numa thread de verdade e os
prompts bloqueiam num :class:`concurrent.futures.Future` que só a UI resolve
— é assim que um ``selecionar`` escrito como código síncrono vira um painel
dentro da etapa atual, sem reescrever o fluxo.

O menu lateral lista os passos do processo. Cada passo tem um estado:

=============  =========================================================
Estado         Significado
=============  =========================================================
``ATUAL``      onde o fluxo está (azul ●) — é a etapa com o conteúdo
               ativo, com o prompt pendente ou a revisão
``CONCLUIDA``  passou e já tem resposta (verde ✓) — clique: revisão
``PULADA``     o fluxo passou reto, sem perguntar (cinza —)
``PENDENTE``   ainda vai vir (cinza ○)
=============  =========================================================

O rodapé mostra os atalhos globais (``F2`` etapas, ``esc`` voltar); cada
painel acrescenta os seus (``enter`` confirmar, ``esc`` cancelar...) pela
cadeia de foco. Cores são sempre status (ver :mod:`conduto.tui.tema`).
"""

from __future__ import annotations

import threading
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from conduto import __version__
from conduto.i18n import t
from conduto.tui.paineis import Revisao
from conduto.tui.tema import COR_TEXTO, CSS_TEMA, Status, cor, glifo

__all__ = [
    "CSS_SHELL",
    "ETAPAS_DDL",
    "ETAPAS_INIT",
    "Estado",
    "GLIFOS_ESTADO",
    "MenuEtapas",
    "Passo",
    "Sessao",
    "WizardApp",
    "etapa",
    "rodar_no_shell",
    "sessao_ativa",
]

#: A sessão do shell aberto (``None`` fora dele). Os prompts e o console
#: consultam isto para decidir se atende dentro da tela ou do jeito avulso.
_sessao_ativa: Optional["Sessao"] = None

#: Teto do que fica guardado para reproduzir no terminal quando o shell fecha.
_MAX_SAIDA_GUARDADA = 4000


class Estado(str, Enum):
    """Estado de um passo no menu lateral do shell."""

    ATUAL = "atual"  # azul ● — onde o fluxo está
    CONCLUIDA = "concluida"  # verde ✓ — passou e respondeu
    PENDENTE = "pendente"  # cinza ○ — ainda vai vir
    PULADA = "pulada"  # cinza — — o fluxo passou reto


#: Glifo + status de cada estado (o menu desenha por aqui — cores são status).
GLIFOS_ESTADO: Dict[Estado, Tuple[str, Status]] = {
    Estado.ATUAL: ("\u25cf", Status.INFO),  # ●
    Estado.CONCLUIDA: ("\u2713", Status.OK),  # ✓
    Estado.PENDENTE: ("\u25cb", Status.NEUTRO),  # ○
    Estado.PULADA: ("\u2014", Status.NEUTRO),  # —
}


@dataclass(frozen=True)
class Passo:
    """Um passo do processo no menu lateral.

    ``titulo`` é a chave em português; o desenho traduz com
    :func:`conduto.i18n.t` para o idioma valer também no catálogo EN.
    """

    id: str
    titulo: str


#: Os passos do ``conduto init`` (o passo a passo do README) no shell.
ETAPAS_INIT: Tuple[Passo, ...] = (
    Passo("origem_sgbd", "Origem: SGBD"),
    Passo("origem_credenciais", "Origem: credenciais"),
    Passo("origem_banco", "Origem: banco e schema"),
    Passo("destino_sgbd", "Destino: SGBD"),
    Passo("destino_credenciais", "Destino: credenciais"),
    Passo("destino_banco", "Destino: banco e schema"),
    Passo("modo_schemas", "Modo dos schemas"),
    Passo("schemas_origem", "Schemas de origem"),
    Passo("tabelas", "Tabelas"),
    Passo("schedules", "Schedules"),
    Passo("ddl", "DDL no destino"),
    Passo("dagster", "Servidor Dagster"),
)

#: Os passos do ``conduto ddl``.
ETAPAS_DDL: Tuple[Passo, ...] = (
    Passo("ddl_aplicacao", "Aplicação do DDL"),
)

#: CSS do shell, acrescido do tema (status + neutras) do :mod:`conduto.tui.tema`.
#: Precisa vir antes da classe (o ``CSS`` dela é avaliado na definição).
CSS_SHELL = """
#cabecalho {
    height: 1;
    padding: 0 1;
    background: $cor-fundo-alt;
    color: $cor-texto;
}

#corpo {
    height: 1fr;
}

#menu {
    width: 34;
    min-width: 24;
    height: 1fr;
    padding: 0 1;
    background: $cor-fundo;
    border-right: solid $cor-borda;
}
#menu > .option-list--option-highlighted {
    background: $cor-foco;
}

#conteudo {
    width: 1fr;
    height: 1fr;
    background: $cor-fundo;
}
#conteudo > * {
    height: 1fr;
}

.conteudo-msg {
    content-align: center middle;
    text-align: center;
    padding: 0 6;
    color: $status-neutro;
}

.revisao {
    background: $cor-fundo;
}
.titulo-revisao {
    height: auto;
    padding: 1 2;
    background: $cor-fundo-alt;
    color: $status-info;
    text-style: bold;
}
/* Revisão: a tabela tem altura fixa porque o próprio Revisao rola. */
PainelSelecao.bloqueado #tabela {
    height: 12;
}
.bloqueado Input {
    background: $cor-fundo-alt;
    color: $status-neutro;
}
.bloqueado Button {
    background: $cor-fundo;
    color: $status-neutro;
}
"""


class Sessao:
    """Estado compartilhado entre o corpo (thread) e a UI (thread principal).

    Os prompts bloqueiam em :meth:`esperar` até a UI montar o painel da
    etapa atual e a resposta chegar pelo futuro; toda mutação de UI passa
    por :meth:`_na_ui`, que usa ``call_from_thread`` (bloqueante) — a ordem
    entre corpo e tela fica determinística e o Textual nunca é tocado de
    outra thread.
    """

    def __init__(self, etapas: Sequence[Passo], comando: str) -> None:
        self.etapas: List[Passo] = list(etapas)
        self.comando = comando
        #: Índice da etapa em que o corpo está (``None`` antes do 1º marcador).
        self.atual: Optional[int] = None
        #: Etapa selecionada no menu (costuma acompanhar :attr:`atual`).
        self.selecionado: int = 0
        #: Etapas que o fluxo já deixou para trás.
        self.visitados: set = set()
        #: Pergunta em andamento (``None`` quando o corpo está computando).
        self.pendente: Optional[Dict[str, Any]] = None
        #: Respostas dadas por etapa — a revisão se alimenta daqui.
        self.respostas: Dict[str, List[Dict[str, Any]]] = {}
        #: O corpo pediu para o shell sair da frente (ex.: servidor no ar).
        self.abandonado: bool = False
        self.erro: Optional[BaseException] = None
        self.resultado: Any = None
        self.concluido: bool = False
        #: Texto da linha de atividade no cabeçalho.
        self.atividade_txt: str = ""
        self.app: Optional[WizardApp] = None
        self._app_vivo: bool = False
        self._shell_fechado = threading.Event()
        #: Saída rica guardada enquanto o shell está no ar (reproduzida ao fechar).
        self.buffer_console: deque = deque(maxlen=_MAX_SAIDA_GUARDADA)
        #: Revisão montada por etapa com a versão de respostas em que vale.
        self._revisoes: Dict[str, Tuple[int, Revisao]] = {}
        self._versao: int = 0
        #: Clique na etapa atual já respondida alterna registro x revisão.
        self._mostrar_log: bool = True

    # ------------------------------------------------------------------
    # Etapas (alimentadas pelos marcadores ``etapa()`` do corpo)
    # ------------------------------------------------------------------

    def _indice(self, chave: str) -> int:
        for indice, passo in enumerate(self.etapas):
            if passo.id == chave:
                return indice
        raise ValueError(
            f"Etapa desconhecida para o comando {self.comando!r}: {chave!r}"
        )

    def _chave(self, indice: int) -> str:
        return self.etapas[indice].id

    def estado_de(self, indice: int) -> Estado:
        """Estado do passo ``indice`` no menu lateral."""
        if indice == self.atual:
            return Estado.ATUAL
        if indice in self.visitados:
            return Estado.CONCLUIDA
        if self.atual is None or indice > self.atual:
            return Estado.PENDENTE
        return Estado.PULADA  # atrás do atual e nunca visitado: pulou

    def ir_para(self, chave: str) -> None:
        """Move o fluxo para a etapa ``chave`` (o marcador que o corpo chama)."""
        novo = self._indice(chave)
        anterior = self.atual
        if novo == anterior:
            return  # repetiu o marcador (ex.: retry de credenciais)
        if anterior is not None and novo > anterior:
            self.visitados.add(anterior)
        self.atual = novo
        self.selecionado = novo
        self._mostrar_log = True  # etapa nova começa no registro
        self._na_ui(self._desenhar_ui)

    def atividade(self, texto: str) -> None:
        """Atualiza a linha de atividade do cabeçalho (``""`` limpa)."""
        self.atividade_txt = texto
        self._na_ui(self._cabecalho_ui)

    # ------------------------------------------------------------------
    # Prompts: a ponte entre o corpo e a UI
    # ------------------------------------------------------------------

    @property
    def painel_pendente(self) -> Optional[Any]:
        """O painel do prompt em andamento (``None`` sem prompt)."""
        if self.pendente is None:
            return None
        return self.pendente.get("painel")

    def esperar(
        self, especificacao: Dict[str, Any], construir: Callable[[], Any]
    ) -> Any:
        """Bloqueia o corpo até a UI responder o prompt da etapa atual.

        ``None`` quando o prompt foi cancelado (esc/ctrl+c) ou o shell saiu
        da frente — o chamador trata como cancelar, como em qualquer prompt.
        ``especificacao`` é o que a revisão vai redesenhar depois.
        """
        if self.abandonado or not self._app_vivo:
            return None
        futuro: Future = Future()
        pendente: Dict[str, Any] = {
            "futuro": futuro,
            "especificacao": especificacao,
            "construir": construir,
            "painel": None,
        }
        self.pendente = pendente
        self._na_ui(self._mostrar_ui, pendente)
        # Rede de segurança: o shell pode ter morrido entre a checagem e a
        # fila; sem isto o futuro nunca seria resolvido e o corpo travaria.
        if not self._app_vivo and not futuro.done():
            if self.pendente is pendente:
                self.pendente = None
            futuro.set_result(None)
        return futuro.result()

    def _mostrar_ui(self, pendente: Dict[str, Any]) -> None:
        """Monta o painel do prompt na etapa atual (chamado na thread da UI)."""
        if self.pendente is not pendente or pendente["futuro"].done():
            return
        painel = pendente["construir"]()
        painel.ao_responder = lambda valor: self._responder_ui(pendente, valor)
        painel.ao_cancelar = lambda: self._responder_ui(pendente, None)
        pendente["painel"] = painel
        mostrar = self.atual is None or self.selecionado == self.atual
        # O foco vem no on_mount do painel, quando os filhos já existem.
        painel.focar_ao_montar = mostrar
        if not mostrar:
            painel.display = False  # etapa visitada: não rouba tela nem foco
        self._conteudo().mount(painel)
        if mostrar:
            self._exibir(painel, focar_painel=False)

    def _responder_ui(self, pendente: Dict[str, Any], valor: Any) -> None:
        """Grava a resposta, destrava o corpo e tira o painel da tela."""
        futuro = pendente["futuro"]
        if futuro.done():
            return
        # Grava ANTES de destravar: o corpo pode marcar a próxima etapa na hora
        # e o registro da resposta tem de valer para a etapa de quando perguntou.
        if valor is not None and self.atual is not None:
            especificacao = dict(pendente["especificacao"])
            especificacao["valor"] = valor
            chave = self._chave(self.atual)
            self.respostas.setdefault(chave, []).append(especificacao)
            self._versao += 1
            self._descartar_revisoes()  # as montadas ficaram velhas
        if self.pendente is pendente:
            self.pendente = None
        futuro.set_result(valor)
        painel = pendente.get("painel")
        if painel is not None:
            try:
                painel.remove()
            except Exception:
                pass  # shell fechando: ninguém mais precisa do painel
        self._atualizar_conteudo()

    def selecionar_indice(self, indice: int) -> None:
        """Clique/enter numa etapa do menu: leva o conteúdo para ela."""
        if not 0 <= indice < len(self.etapas):
            return
        if (
            indice == self.atual
            and self.pendente is None
            and self.respostas.get(self._chave(indice))
        ):
            # Etapa atual já respondida: alterna entre registro e revisão.
            self._mostrar_log = not self._mostrar_log
        self.selecionado = indice
        self._atualizar_conteudo()

    def voltar(self) -> None:
        """``esc`` fora do painel: volta para a etapa em que o corpo está."""
        if self.atual is None or self.selecionado == self.atual:
            return  # já está lá (ou o fluxo nem começou)
        self.selecionado = self.atual
        self._atualizar_conteudo(focar_painel=True)

    # ------------------------------------------------------------------
    # Cancelamento / saída
    # ------------------------------------------------------------------

    def cancelar_ou_abandonar(self) -> None:
        """``ctrl+c``: responde ``None`` ao prompt; sem prompt, abandona o fluxo."""
        pendente = self.pendente
        if pendente is not None:
            self._responder_ui(pendente, None)
            return
        if not self.abandonado:
            self.abandonado = True
            self.atividade(t("Cancelando..."))

    def cancelar_pendente(self) -> None:
        """Destrava um prompt órfão (o shell está fechando)."""
        pendente = self.pendente
        if pendente is not None:
            self._responder_ui(pendente, None)

    def sair(self) -> None:
        """Fecha o shell e devolve o terminal — o corpo segue fora dele.

        Usado antes de um ``Popen`` que precisa do terminal de verdade (ex.:
        o ``dagster dev`` e o próximo Ctrl+C do usuário). Espera o shell
        fechar de vez (saída reproduzida) para o corpo não imprimir por cima.
        """
        esperar = self._app_vivo
        self._na_ui(self._sair_ui)
        if esperar:
            self._shell_fechado.wait(timeout=30)
        _limpar_sessao(self)

    def terminar_corpo(self) -> None:
        """Fim do corpo: fecha o shell, se ainda estiver no ar."""
        self.concluido = True
        self._na_ui(self._sair_ui)

    def liberar_shell(self) -> None:
        """Avisa que o shell fechou (terminal devolvido e saída reproduzida)."""
        self._shell_fechado.set()

    # ------------------------------------------------------------------
    # console.print dentro do shell
    # ------------------------------------------------------------------

    def registrar_console(self, args: tuple, kwargs: dict) -> None:
        """Guarda a saída e a espelha no registro (``RichLog``) da tela."""
        self.buffer_console.append((args, kwargs))
        if not self._app_vivo:
            return
        self._na_ui(self._registrar_ui, args, kwargs)

    def _registrar_ui(self, args: tuple, kwargs: dict) -> None:
        if self.app is None:
            return
        if args:
            conteudo: Any = (
                args[0] if len(args) == 1 else " ".join(str(a) for a in args)
            )
        else:
            conteudo = str(kwargs)
        if isinstance(conteudo, str):
            if kwargs.get("markup", True) is False:
                conteudo = Text(conteudo)  # literal (SQL com colchetes, ex.)
            else:
                try:
                    conteudo = Text.from_markup(conteudo)
                except Exception:
                    conteudo = Text(conteudo)
        self.app.query_one("#registro", RichLog).write(conteudo)

    def reproduzir_console(self) -> None:
        """Devolve a saída guardada ao terminal real depois que o shell fecha."""
        if not self.buffer_console:
            return
        from conduto.ui import console  # import tardio: `ui` importa este módulo

        for args, kwargs in self.buffer_console:
            try:
                console.print(*args, **kwargs)
            except Exception:
                pass  # nada de um render estragado derrubar o fim do comando
        self.buffer_console.clear()

    # ------------------------------------------------------------------
    # UI (tudo na thread da UI, via _na_ui)
    # ------------------------------------------------------------------

    def ao_montar(self) -> None:
        """A UI subiu: cabeçalho, menu e conteúdo inicial antes do corpo."""
        self._app_vivo = True
        self._cabecalho_ui()
        self._menu().desenhar()
        self._atualizar_conteudo()

    def _na_ui(self, funcao: Callable[..., None], *args: Any) -> None:
        """Roda ``funcao`` na thread da UI (ou pula, se o shell já morreu).

        ``call_from_thread`` bloqueia até a ação terminar: a ordem entre o
        corpo e a tela fica determinística.
        """
        if not self._app_vivo:
            return
        if threading.current_thread() is threading.main_thread():
            funcao(*args)
            return
        try:
            self.app.call_from_thread(funcao, *args)
        except RuntimeError:
            pass  # shell fechando: o finally de rodar_no_shell destrava o corpo

    def _sair_ui(self) -> None:
        """Fecha o app (fim do corpo, ou o chamador pediu ``sair()``)."""
        if self.app is None:
            return
        self._app_vivo = False
        self.app.exit()

    def _desenhar_ui(self) -> None:
        """Redesenha cabeçalho, menu e conteúdo ao mudar de etapa."""
        if not self._app_vivo or self.app is None:
            return
        self._cabecalho_ui()
        self._menu().desenhar()
        self._atualizar_conteudo()

    def _cabecalho_ui(self) -> None:
        if not self._app_vivo or self.app is None:
            return
        texto = Text()
        texto.append(
            f" {glifo(Status.INFO)} conduto {__version__} ",
            style=f"{cor(Status.INFO)} bold",
        )
        texto.append(f"{self.comando} ", style=cor(Status.INFO))
        if self.atual is not None:
            texto.append(
                f" \u00b7 {t('passo {atual}/{total}', atual=self.atual + 1, total=len(self.etapas))} ",
                style=cor(Status.NEUTRO),
            )
        if self.atividade_txt:
            texto.append(
                f"\u00b7 {self.atividade_txt}", style=f"{cor(Status.NEUTRO)} dim"
            )
        self.app.query_one("#cabecalho", Static).update(texto)

    def _conteudo(self) -> Vertical:
        return self.app.query_one("#conteudo", Vertical)

    def _menu(self) -> "MenuEtapas":
        return self.app.query_one("#menu", MenuEtapas)

    def _registro(self) -> RichLog:
        return self.app.query_one("#registro", RichLog)

    def _mensagem(self, identificador: str) -> Static:
        return self.app.query_one(f"#{identificador}", Static)

    def _painel_para(self, indice: int) -> Any:
        """Widget do conteúdo da etapa ``indice``.

        A atual tem prioridade para o prompt pendente; depois vem a revisão
        (etapa já respondida) e o registro do shell. Etapas de trás mostram a
        revisão ou o motivo de não ter perguntado; as da frente, o aviso de
        que ainda vão vir.
        """
        painel = self.painel_pendente
        if self.atual is None or indice == self.atual:
            if painel is not None:
                return painel
            if self.respostas.get(self._chave(indice)) and not self._mostrar_log:
                return self._revisao(indice)
            return self._registro()
        if indice < self.atual or indice in self.visitados:
            if self.respostas.get(self._chave(indice)):
                return self._revisao(indice)
            return self._mensagem("msg-sem") if indice in self.visitados else self._mensagem("msg-pulada")
        return self._mensagem("msg-aguardar")

    def _revisao(self, indice: int) -> Revisao:
        """A revisão da etapa (montada uma vez por versão de respostas)."""
        chave = self._chave(indice)
        guardada = self._revisoes.get(chave)
        if guardada is not None and guardada[0] == self._versao:
            return guardada[1]
        revisao = Revisao(
            list(self.respostas[chave]),
            id=f"revisao-{indice}-{self._versao}",
            classes="revisao",
        )
        self._conteudo().mount(revisao)
        self._revisoes[chave] = (self._versao, revisao)
        return revisao

    def _descartar_revisoes(self) -> None:
        """Derruba as revisões montadas: a resposta nova as deixou velhas."""
        for _chave, (_versao, revisao) in list(self._revisoes.items()):
            try:
                revisao.remove()
            except Exception:
                pass
        self._revisoes.clear()

    def _atualizar_conteudo(self, focar_painel: bool = False) -> None:
        alvo = self._painel_para(self.selecionado)
        pendente = self.painel_pendente
        # Painel pendente visível SEMPRE leva o foco: é o que o corpo espera.
        self._exibir(alvo, focar_painel or alvo is pendente)

    def _exibir(self, alvo: Any, focar_painel: bool) -> None:
        """Mostra ``alvo`` na área de conteúdo e resolve o foco.

        Ocultar o widget que estava focado solta o foco para um escondido —
        por isso o foco é sempre fixado aqui, explícito, a cada troca.
        """
        for filho in self._conteudo().children:
            filho.display = filho is alvo
        if focar_painel and getattr(alvo, "pode_focar", False):
            alvo.ao_exibir()
        else:
            self._menu().focus()


class MenuEtapas(OptionList):
    """Menu lateral dos passos: clique/enter leva o conteúdo para a etapa."""

    def __init__(self, sessao: Sessao, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sessao = sessao

    def on_mount(self) -> None:
        self.desenhar()

    @on(OptionList.OptionSelected)
    def _ao_escolher(self, evento: OptionList.OptionSelected) -> None:
        self.sessao.selecionar_indice(evento.option_index)

    def desenhar(self) -> None:
        """(Re)desenha as opções com o estado atual, preservando a seleção."""
        opcoes = [self._opcao(indice) for indice in range(len(self.sessao.etapas))]
        self.clear_options()
        self.add_options(opcoes)
        if opcoes:
            self.highlighted = min(max(self.sessao.selecionado, 0), len(opcoes) - 1)

    def _opcao(self, indice: int) -> Option:
        passo = self.sessao.etapas[indice]
        estado = self.sessao.estado_de(indice)
        glif, status = GLIFOS_ESTADO[estado]
        texto = Text()
        texto.append(f"{glif} ", style=cor(status))
        if estado is Estado.ATUAL:
            estilo = f"{COR_TEXTO} bold"
        elif estado is Estado.CONCLUIDA:
            estilo = COR_TEXTO
        else:
            estilo = f"{cor(Status.NEUTRO)} dim"
        texto.append(t(passo.titulo), style=estilo)
        return Option(texto, id=passo.id)


class WizardApp(App):
    """O shell do wizard: menu lateral + área de conteúdo que troca no clique."""

    CSS = CSS_TEMA + "\n" + CSS_SHELL
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        # priority vence o ``copy`` do Input focado — o corpo desiste na hora.
        Binding("ctrl+c", "cancelar", show=False, priority=True),
        Binding("ctrl+q", "cancelar", show=False, priority=True),
    ]

    def __init__(
        self,
        sessao: Sessao,
        funcao: Callable[..., Any],
        args: Sequence[Any] = (),
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__()
        self.title = f"conduto {sessao.comando}"  # título da janela/aba
        self._sessao = sessao
        self._funcao = funcao
        self._args = tuple(args)
        self._kwargs = dict(kwargs or {})
        self._thread: Optional[threading.Thread] = None
        # Bindings de instância para traduzir na hora (--lang muda no meio).
        self.bind("f2", "alternar_menu", description=t("Etapas"), key_display="F2")
        self.bind("escape", "voltar", description=t("Voltar"))
        sessao.app = self

    def compose(self) -> ComposeResult:
        yield Static(id="cabecalho")
        with Horizontal(id="corpo"):
            yield MenuEtapas(self._sessao, id="menu")
            with Vertical(id="conteudo"):
                yield RichLog(id="registro", max_lines=500)
                yield Static(
                    t("Etapa aguardando as anteriores."),
                    id="msg-aguardar",
                    classes="conteudo-msg",
                )
                yield Static(
                    t("Etapa não executada neste fluxo."),
                    id="msg-pulada",
                    classes="conteudo-msg",
                )
                yield Static(
                    t("Etapa concluída sem perguntas."),
                    id="msg-sem",
                    classes="conteudo-msg",
                )
        yield Footer()

    def on_mount(self) -> None:
        _definir_sessao(self._sessao)  # os prompts do corpo enxergam a sessão
        self._sessao.ao_montar()
        self._thread = threading.Thread(
            target=self._executar_corpo, daemon=True, name="conduto-corpo"
        )
        self._thread.start()

    def _executar_corpo(self) -> None:
        """Roda o comando de verdade na thread de fora da UI."""
        sessao = self._sessao
        try:
            sessao.resultado = self._funcao(*self._args, **self._kwargs)
        except BaseException as exc:  # reexibida em rodar_no_shell
            sessao.erro = exc
        finally:
            sessao.terminar_corpo()

    def aguardar_corpo(self, tempo_limite: Optional[float] = None) -> None:
        """Espera a thread do corpo (sem limite por padrão: ele manda)."""
        if self._thread is not None:
            self._thread.join(tempo_limite)

    def action_alternar_menu(self) -> None:
        """``f2``: vai para o menu (ou de volta ao prompt ativo)."""
        menu = self.query_one("#menu", MenuEtapas)
        if menu.has_focus:
            pendente = self._sessao.painel_pendente
            if pendente is not None and pendente.display:
                pendente.ao_exibir()
            return  # sem prompt visível: o conteúdo é de leitura, fica no menu
        menu.focus()

    def action_voltar(self) -> None:
        """``esc`` fora do painel: volta para a etapa em que o corpo está."""
        self._sessao.voltar()

    def action_cancelar(self) -> None:
        """``ctrl+c``/``ctrl+q``: cancela o prompt ou abandona o fluxo."""
        self._sessao.cancelar_ou_abandonar()

    def action_help_quit(self) -> None:
        # O ctrl+c é nosso (binding com priority); se chegar por aqui, idem.
        self.action_cancelar()


def _definir_sessao(sessao: Sessao) -> None:
    global _sessao_ativa
    _sessao_ativa = sessao


def _limpar_sessao(sessao: Sessao) -> None:
    """Só limpa se ainda formos a sessão vigente (nunca a de outro shell)."""
    global _sessao_ativa
    if _sessao_ativa is sessao:
        _sessao_ativa = None


def sessao_ativa() -> Optional[Sessao]:
    """A sessão do shell aberto — ``None`` fora dele (prompt avulso, CI...)."""
    return _sessao_ativa


def etapa(chave: str) -> None:
    """Marca que o corpo entrou na etapa ``chave`` (no-op sem sessão).

    O ``conduto init``/``ddl`` intercalam estes marcadores com os prompts:
    é o que alimenta o menu lateral (estado, revisão e conteúdo da etapa).
    """
    sessao = sessao_ativa()
    if sessao is not None:
        sessao.ir_para(chave)


def rodar_no_shell(
    etapas: Sequence[Passo],
    comando: str,
    funcao: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Roda ``funcao`` dentro do shell (ou direto, sem terminal interativo).

    Com terminal interativo o corpo roda numa thread e a tela manda; sem
    terminal (CI, pipe, ``CONDUTO_SEM_TUI``) o corpo roda direto, como
    sempre — testes e o fallback numerado seguem iguais.
    """
    from conduto.tui.prompts import _tem_terminal  # import tardio: evita ciclo

    if not _tem_terminal():
        return funcao(*args, **kwargs)

    sessao = Sessao(etapas, comando)
    aplicativo = WizardApp(sessao, funcao, args, kwargs)
    try:
        aplicativo.run()
    except KeyboardInterrupt:
        # ctrl+c com o shell no ar: o corpo desiste pelo prompt/flag.
        sessao.abandonado = True
    finally:
        sessao.cancelar_pendente()
        _limpar_sessao(sessao)
        sessao.reproduzir_console()
        sessao.liberar_shell()  # quem chamou sair() pode seguir agora
        try:
            aplicativo.aguardar_corpo()
        except KeyboardInterrupt:
            # ctrl+c na espera (ex.: dagster): o sinal já foi pro processo
            # filho — um tempo e o corpo desembarga, sem travar pra sempre.
            aplicativo.aguardar_corpo(tempo_limite=15)
    if sessao.erro is not None:
        raise sessao.erro
    return sessao.resultado
