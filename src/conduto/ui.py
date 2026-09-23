"""Ajustes de renderização e componentes visuais modernos do Conduto.

Centraliza as cores de aviso/sucesso/erro/info (paleta de status vinda de
:mod:`conduto.tui.tema`), os widgets de carregamento (spinner e barra de
progresso) e os helpers de mensagens com tradução via :mod:`conduto.i18n`.

Os prompts (seleção, confirmação e texto) agora são telas Textual — ver
:mod:`conduto.tui` — e são reexportados aqui de forma que os chamadores de
sempre (``cli``, ``schemas_auto``) continuem iguais.

Paleta: a mesma de :mod:`conduto.tui.tema`, em que cada cor é um status
(verde = sucesso/marcado, âmbar = atenção, vermelho = erro, azul = informação,
cinza = neutro) — cores discretas que informam, não decoram.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from conduto.i18n import nome_idioma, t
from conduto.tui.modelo import Choice  # reexport (mesma interface de sempre)
from conduto.tui.prompts import (
    confirmar,
    multi_selecionar,
    pedir,
    pedir_senha,
    selecionar,
)
from conduto.tui.tema import CORES, ESTILOS_COLUNA

console = Console()

# ---------------------------------------------------------------------------
# Tema central: referências de cor para avisos, sucesso, erros etc.
#
# Vem de `conduto.tui.tema` — a mesma paleta discreta em que cada cor é um
# status (verde=OK, âmbar=atenção, vermelho=erro, azul=info, cinza=neutro) e
# que também alimenta o CSS das telas Textual: CLI e TUI falam a mesma cor.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Mensagens temáticas (traduzidas conforme o idioma atual)
# ---------------------------------------------------------------------------


def erro(mensagem: str, **kwargs: object) -> Text:
    return Text(t(mensagem, **kwargs), style=CORES["erro"])


def aviso(mensagem: str, **kwargs: object) -> Text:
    return Text(t(mensagem, **kwargs), style=CORES["aviso"])


def sucesso(mensagem: str, **kwargs: object) -> Text:
    return Text(t(mensagem, **kwargs), style=CORES["sucesso"])


def info(mensagem: str, **kwargs: object) -> Text:
    return Text(t(mensagem, **kwargs), style=CORES["info"])


def neutro(mensagem: str, **kwargs: object) -> Text:
    return Text(t(mensagem, **kwargs), style=CORES["neutro"])


def destaque(mensagem: str, **kwargs: object) -> Text:
    return Text(t(mensagem, **kwargs), style=CORES["destaque"])


def detalhe(mensagem: str, **kwargs: object) -> Text:
    return Text(t(mensagem, **kwargs), style=CORES["detalhe"])


def separador() -> Rule:
    return Rule(style=CORES["linha"])


def painel(titulo: str, corpo: Any, cor: str = CORES["borda"], largura: Optional[int] = None) -> Panel:
    return Panel(corpo, border_style=cor, title=t(titulo), expand=False, width=largura)


def banner(titulo: str, subtitulo: Optional[str] = None, nome: Optional[str] = None) -> Panel:
    """Painel de boas-vindas usado no fluxo do ``conduto init``."""
    corpo = Text()
    corpo.append(t(titulo) + "\n", style=CORES["titulo"])
    if subtitulo:
        corpo.append(t(subtitulo), style=CORES["neutro"])
    if nome:
        corpo.append("\n", style=CORES["neutro"])
        corpo.append(f" {nome} ", style=CORES["destaque"])
    corpo.append("\n", style=CORES["neutro"])
    corpo.append(t("Interface: {idioma}", idioma=nome_idioma()), style=CORES["discreto"])
    return Panel(corpo, border_style=CORES["borda"], expand=False, width=100)


def gerado(caminho: Any) -> Text:
    """Mensagem de arquivo gerado (rótulo de sucesso + caminho em destaque)."""
    texto = Text()
    texto.append(t("Gerado: "), style=CORES["sucesso"])
    texto.append(str(caminho), style=CORES["detalhe"])
    return texto


def tabela(
    titulo: str,
    colunas: List[Tuple[str, str]],
    linhas: Iterable[Iterable[Any]],
    largura_min: int = 14,
) -> Table:
    """Tabela rica com borda, cabeçalho e estilos semânticos centralizados."""
    grade = Table(
        title=t(titulo),
        border_style=CORES["linha"],
        header_style=CORES["info"],
        pad_edge=False,
    )
    for rotulo, estilo in colunas:
        grade.add_column(
            t(rotulo) if rotulo else "",
            style=ESTILOS_COLUNA.get(estilo, estilo),
            no_wrap=True,
            min_width=largura_min,
        )
    for linha in linhas:
        grade.add_row(*[str(celula) for celula in linha])
    return grade


# ---------------------------------------------------------------------------
# Widgets de carregamento modernos
# ---------------------------------------------------------------------------


@contextmanager
def carregando(descricao: str, **kwargs: object):
    """Widget de carregamento moderno (spinner + tempo decorrido)."""
    with Progress(
        SpinnerColumn(spinner_name="dots12", style=CORES["progresso"]),
        TextColumn("[progress.description]{task.description}", style=CORES["texto"]),
        TimeElapsedColumn(),
        console=console,
    ) as progresso_ui:
        tarefa = progresso_ui.add_task(t(descricao, **kwargs), total=None)
        try:
            yield progresso_ui, tarefa
        finally:
            progresso_ui.stop_task(tarefa)


@contextmanager
def progresso(total: int, descricao: str, **kwargs: object):
    """Barra de progresso determinada para tarefas com etapas conhecidas."""
    with Progress(
        TextColumn("[progress.description]{task.description}", style=CORES["texto"]),
        BarColumn(bar_width=28, style=CORES["progresso"], complete_style=CORES["sucesso"]),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progresso_ui:
        tarefa = progresso_ui.add_task(t(descricao, **kwargs), total=total)
        try:
            yield progresso_ui, tarefa
        finally:
            progresso_ui.stop_task(tarefa)


# ---------------------------------------------------------------------------
# Prompts: telas Textual (ver `conduto.tui`), reexportadas com as assinaturas
# de sempre — `selecionar`, `confirmar`, `pedir`, `pedir_senha` e
# `multi_selecionar` (importadas no topo deste módulo).
# ---------------------------------------------------------------------------
