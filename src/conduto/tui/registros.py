"""Registros do shell em SQLite: a saída do console, guardada para consultar.

Dentro do shell nada mais é impresso na área de conteúdo. Um ``RichLog``
único, servido a todas as etapas e nunca limpo, mostrava logs velhos a cada
troca de passo (a "pisca" ao finalizar uma etapa). Aqui cada
``console.print`` vira uma linha do banco — ``~/.conduto/registros.db``, ou
o que ``CONDUTO_REGISTROS`` apontar — e a tela só aparece quando o usuário
pede, com ``F3`` (:class:`TelaRegistros`).

Duas peças neste módulo, e nenhuma delas importa o :mod:`conduto.tui.shell`
(seria ciclo — quem importa é o shell):

* a **persistência** (:func:`gravar`, :func:`consultar`, :func:`podar`),
  sempre sob um lock, porque os prints vêm da thread do corpo e a leitura da
  UI; e que **nunca levanta exceção** — um print não pode derrubar o comando;
* a :class:`TelaRegistros`, o modal que o ``F3`` sobe por cima do wizard.

Cores são sempre status (ver :mod:`conduto.tui.tema`).
"""

from __future__ import annotations

import io
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static

from conduto.i18n import t
from conduto.tui.tema import COR_BORDA, COR_FUNDO, COR_FUNDO_ALT, COR_TEXTO, Status, cor

__all__ = [
    "Registro",
    "TelaRegistros",
    "caminho",
    "consultar",
    "fechar",
    "gravar",
    "podar",
    "renderizar_print",
]

#: Formato do ``momento`` — ISO local, ordenável lexicograficamente.
_FORMATO_MOMENTO = "%Y-%m-%dT%H:%M:%S"

#: Largura fixa da renderização (o terminal real pode ser menor: a tela enrola).
_LARGURA = 160

#: Registros lidos por padrão ao abrir a tela.
_LIMITE_PADRAO = 500

#: A conexão é única (SQLite é de um arquivo só) e protegida por este lock:
#: a gravação acontece na thread do corpo, a leitura na thread da UI.
_conexao: Optional[sqlite3.Connection] = None
_caminho_conexao: Optional[Path] = None
_trava = threading.Lock()


@dataclass(frozen=True)
class Registro:
    """Uma linha guardada: quando foi, em que etapa e o que se imprimiu."""

    momento: str
    etapa: Optional[str]
    texto: str
    #: A mesma linha com ANSI — a tela reconverte com ``Text.from_ansi``.
    estilo: str = ""


# ---------------------------------------------------------------------------
# Caminho e conexão
# ---------------------------------------------------------------------------


def caminho() -> Path:
    """Arquivo do banco: ``CONDUTO_REGISTROS`` se houver, senão ``~/.conduto``."""
    alternativa = os.environ.get("CONDUTO_REGISTROS")
    if alternativa:
        return Path(alternativa).expanduser()
    return Path.home() / ".conduto" / "registros.db"


def _conectar() -> sqlite3.Connection:
    """Abre (ou reaproveita) a conexão, criando arquivo, tabela e índice."""
    global _conexao, _caminho_conexao
    arquivo = caminho()
    if _conexao is not None and _caminho_conexao == arquivo:
        return _conexao
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(str(arquivo), timeout=10, check_same_thread=False)
    # WAL + synchronous=NORMAL: um commit por linha não custa um fsync por
    # linha, e a gravação não atrasa o corpo a cada print.
    conexao.execute("PRAGMA journal_mode=WAL")
    conexao.execute("PRAGMA synchronous=NORMAL")
    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS registros (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            sessao  TEXT NOT NULL,
            comando TEXT,
            etapa   TEXT,
            momento TEXT NOT NULL,
            texto   TEXT NOT NULL,
            estilo  TEXT
        )
        """
    )
    conexao.execute(
        "CREATE INDEX IF NOT EXISTS idx_registros_sessao ON registros (sessao, id)"
    )
    conexao.commit()
    if _conexao is not None:
        try:
            _conexao.close()
        except Exception:
            pass  # a anterior já não interessa (o arquivo mudou)
    _conexao = conexao
    _caminho_conexao = arquivo
    return conexao


def fechar() -> None:
    """Solta a conexão (troca de arquivo entre testes, fim do processo)."""
    global _conexao, _caminho_conexao
    with _trava:
        if _conexao is not None:
            try:
                _conexao.close()
            except Exception:
                pass
        _conexao = None
        _caminho_conexao = None


# ---------------------------------------------------------------------------
# Renderização de um console.print
# ---------------------------------------------------------------------------


def renderizar_print(args: tuple, kwargs: dict) -> Tuple[str, str]:
    """``(texto, estilo)`` de um ``console.print``: o que se lê e o que se pinta.

    O texto sai limpo — sem marcas de markup e sem ANSI — e é o que fica
    gravado para quem abrir o banco; o estilo é a mesma linha com as cores,
    que a tela reconverte. Markup quebrado (``[bold]x[/bold]``) levanta
    ``MarkupError`` e cai para literal; um kwarg que o rich não conhece
    levanta ``TypeError`` e cai no texto corrido dos argumentos. Um print
    nunca pode derrubar o comando.
    """
    tentativas: List[Dict[str, Any]] = [kwargs]
    if kwargs.get("markup", True) is not False:
        tentativas.append({**kwargs, "markup": False})
    for tentativa in tentativas:
        console = Console(
            file=io.StringIO(),
            record=True,
            force_terminal=True,
            no_color=False,
            width=_LARGURA,
            highlight=False,
        )
        try:
            console.print(*args, **tentativa)
        except Exception:
            continue
        estilo = console.export_text(styles=True).rstrip("\n")
        return (Text.from_ansi(estilo).plain if estilo else ""), estilo
    corrido = " ".join(str(argumento) for argumento in args)
    return corrido, corrido


# ---------------------------------------------------------------------------
# Gravação e leitura
# ---------------------------------------------------------------------------


def gravar(
    sessao: str,
    comando: str,
    etapa: Optional[str],
    args: tuple,
    kwargs: dict,
) -> Optional[Registro]:
    """Guarda um ``console.print``; ``None`` quando não deu para guardar.

    **Nunca levanta exceção.** Sem banco (home sem escrita, arquivo
    corrompido, sistema de arquivos sem WAL) o comando segue adiante, só sem
    aquele registro — o mesmo contrato de sempre de que um print não quebra
    fluxo nenhum.
    """
    try:
        texto, estilo = renderizar_print(args, kwargs)
        registro = Registro(
            momento=datetime.now().strftime(_FORMATO_MOMENTO),
            etapa=etapa,
            texto=texto,
            estilo=estilo,
        )
        with _trava:
            conexao = _conectar()
            conexao.execute(
                "INSERT INTO registros"
                " (sessao, comando, etapa, momento, texto, estilo)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (sessao, comando, etapa, registro.momento, texto, estilo),
            )
            conexao.commit()
        return registro
    except Exception:
        return None


def consultar(sessao: str, limite: int = _LIMITE_PADRAO) -> List[Registro]:
    """As linhas da ``sessao``, na ordem em que foram impressas."""
    try:
        with _trava:
            linhas = _conectar().execute(
                "SELECT momento, etapa, texto, estilo FROM registros"
                " WHERE sessao = ? ORDER BY id DESC LIMIT ?",
                (sessao, limite),
            ).fetchall()
    except Exception:
        return []
    return [
        Registro(momento=momento, etapa=etapa, texto=texto, estilo=estilo or "")
        for momento, etapa, texto, estilo in reversed(linhas)
    ]


def podar(dias: int = 7) -> int:
    """Apaga registros anteriores a ``dias`` (chamado na abertura da sessão).

    Sem isto o arquivo cresceria para sempre. Devolve quantas linhas saíram.
    """
    corte = (datetime.now() - timedelta(days=dias)).strftime(_FORMATO_MOMENTO)
    try:
        with _trava:
            conexao = _conectar()
            cursor = conexao.execute(
                "DELETE FROM registros WHERE momento < ?", (corte,)
            )
            conexao.commit()
            return int(cursor.rowcount)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# A tela (F3)
# ---------------------------------------------------------------------------


class TelaRegistros(ModalScreen[None]):
    """Os registros da sessão, por cima do wizard — ``esc``/``F3`` fecha.

    Sobe como modal de propósito: o prompt pendente continua montado embaixo
    (o futuro do corpo intocado) e o laço de ``display`` do shell não a
    enxerga, porque ela não é filha de ``#conteudo`` — a tela base segue
    respondendo a ``mount``/``focus``/``query`` enquanto ela está no ar, e o
    foco de lá é o que volta quando fecha.

    ``sessao`` é a :class:`conduto.tui.shell.Sessao` (anotada como ``Any``
    para o módulo não importar o shell). Ela guarda o ponteiro daqui em
    ``tela_registros``: é por ali que o corpo espelha ao vivo as linhas novas.
    """

    # Cores literais do tema, não as variáveis ``$...``: uma tela tem a sua
    # própria folha de estilo e não se apoia na folha do app.
    CSS = f"""
    TelaRegistros {{
        align: center middle;
        background: {COR_FUNDO};
        color: {COR_TEXTO};
    }}
    #painel-registros {{
        width: 96%;
        height: 92%;
        background: {COR_FUNDO_ALT};
        border: solid {COR_BORDA};
        padding: 0 1;
    }}
    #titulo-registros {{
        height: 1;
        color: {cor(Status.INFO)};
        text-style: bold;
    }}
    #corpo-registros {{
        height: 1fr;
        background: {COR_FUNDO};
    }}
    #dica-registros {{
        height: 1;
        color: {cor(Status.NEUTRO)};
        text-align: center;
    }}
    """

    BINDINGS = [
        Binding("escape", "fechar", show=False),
        Binding("f3", "fechar", show=False),
    ]

    def __init__(self, sessao: Any, limite: int = _LIMITE_PADRAO) -> None:
        super().__init__()
        self._sessao = sessao
        self._sessao_id = sessao.id_registro
        self._limite = limite

    def compose(self) -> ComposeResult:
        with Vertical(id="painel-registros"):
            yield Static(
                Text(t("Registros \u00b7 {arquivo}", arquivo=str(caminho()))),
                id="titulo-registros",
            )
            yield RichLog(id="corpo-registros", wrap=True)
            yield Static(t("F3 ou esc volta para a etapa."), id="dica-registros")

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        # O corpo passa a espelhar as linhas novas daqui (ver registrar_console).
        self._sessao.tela_registros = self
        self._carregar()
        self.query_one("#corpo-registros", RichLog).focus()

    def action_fechar(self) -> None:
        """``esc``/``F3``: fecha — o foco volta para o que estava embaixo."""
        if getattr(self._sessao, "tela_registros", None) is self:
            self._sessao.tela_registros = None
        self.app.pop_screen()

    # ------------------------------------------------------------------
    # Conteúdo
    # ------------------------------------------------------------------

    def _carregar(self) -> None:
        """Preenche a tela com o que está no banco (uma leitura por abertura)."""
        log = self.query_one("#corpo-registros", RichLog)
        log.clear()
        linhas = consultar(self._sessao_id, limite=self._limite)
        if not linhas:
            log.write(
                Text(t("Nenhum registro nesta sess\u00e3o."), style=cor(Status.NEUTRO))
            )
            return
        etapa_anterior: Optional[str] = None
        for registro in linhas:
            if registro.etapa is not None and registro.etapa != etapa_anterior:
                log.write(self._divisor(registro.etapa))
                etapa_anterior = registro.etapa
            for linha in self._linhas_de(registro):
                log.write(linha)

    def anexar(self, registro: Registro) -> None:
        """Uma linha nova com a tela aberta: espelho ao vivo, sem reler o banco."""
        try:
            log = self.query_one("#corpo-registros", RichLog)
        except Exception:
            return  # a tela foi derrubada entre o print e o espelho
        for linha in self._linhas_de(registro):
            log.write(linha)

    @staticmethod
    def _divisor(chave: str) -> Text:
        """A faixa que separa as etapas dentro do registro."""
        rotulo = t("etapa: {chave}", chave=chave)
        return Text(f"\u2500\u2500 {rotulo} \u2500\u2500", style=cor(Status.INFO))

    @staticmethod
    def _linhas_de(registro: Registro) -> List[Text]:
        """A linha do registro com o horário na frente.

        Multilinha (uma tabela, por exemplo) alinha sob a primeira, com o
        mesmo recuo do ``[HH:MM:SS] `` — a geometria original sobrevive.
        """
        momento = registro.momento
        hora = momento[11:19] if len(momento) >= 19 else momento
        linhas: List[Text] = []
        for indice, parte in enumerate((registro.estilo or registro.texto).split("\n")):
            if indice == 0:
                linha = Text(f"[{hora}] ", style=cor(Status.NEUTRO))
            else:
                linha = Text(" " * (len(hora) + 3), style=cor(Status.NEUTRO))
            linha.append_text(Text.from_ansi(parte) if parte else Text())
            linhas.append(linha)
        return linhas
