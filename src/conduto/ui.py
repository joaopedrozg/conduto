"""Ajustes de renderização e componentes visuais modernos do Conduto.

Centraliza as cores de aviso/sucesso/erro/info, os widgets de carregamento
(spinner e barra de progresso) e os helpers de mensagens e prompts com
tradução via :mod:`conduto.i18n`.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, List, Optional, Tuple

import questionary
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

console = Console()

# ---------------------------------------------------------------------------
# Tema central: referências de cor para avisos, sucesso, erros etc.
# ---------------------------------------------------------------------------

CORES = {
    "erro": "bold red",
    "aviso": "bold yellow",
    "sucesso": "bold green",
    "info": "bold cyan",
    "neutro": "dim white",
    "discreto": "dim",
    "destaque": "bold white on blue",
    "titulo": "bold white",
    "texto": "white",
    "detalhe": "yellow",
    "borda": "green",
    "linha": "dim blue",
    "progresso": "cyan",
    "coluna_titulo": "bold white",
    "coluna_valor": "white",
    "coluna_sucesso": "green",
    "coluna_info": "cyan",
    "coluna_detalhe": "yellow",
}

# Estilos semânticos usados pelas colunas da :func:`tabela`.
ESTILOS_COLUNA = {
    "titulo": CORES["coluna_titulo"],
    "texto": CORES["coluna_valor"],
    "sucesso": CORES["coluna_sucesso"],
    "info": CORES["coluna_info"],
    "detalhe": CORES["coluna_detalhe"],
}

# Cores dos prompts (formato do prompt_toolkit, independente do tema rich).
COR_PROMPT = {
    "pointer": "cyan",
    "highlighted": "green",
    "answer": "yellow",
}

ESTILO_PROMPT = questionary.Style([
    ("pointer", f"fg:{COR_PROMPT['pointer']} bold"),
    ("highlighted", f"fg:{COR_PROMPT['highlighted']} bold"),
    ("answer", f"fg:{COR_PROMPT['answer']} bold"),
])


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
# Prompts (questionary) com o tema e a tradução centralizados
# ---------------------------------------------------------------------------


def _separar_formatacao(mensagem: str, kwargs: dict, *outras_mensagens: str) -> Tuple[dict, dict]:
    """Separa kwargs de formatação (usados em ``t()``) dos kwargs do questionary."""
    textos = (mensagem,) + outras_mensagens
    formatacao = {}
    questionario = {}
    for chave, valor in kwargs.items():
        if any("{" + chave + "}" in texto for texto in textos):
            formatacao[chave] = valor
        else:
            questionario[chave] = valor
    return formatacao, questionario


def selecionar(pergunta: str, escolhas: Iterable[str], **kwargs: Any) -> Optional[str]:
    formatacao, questionario = _separar_formatacao(pergunta, kwargs)
    return questionary.select(
        t(pergunta, **formatacao),
        choices=list(escolhas),
        style=ESTILO_PROMPT,
        qmark="",
        **questionario,
    ).ask()


def confirmar(pergunta: str, padrao: bool = True, **kwargs: Any) -> Optional[bool]:
    formatacao, questionario = _separar_formatacao(pergunta, kwargs)
    return questionary.confirm(
        t(pergunta, **formatacao),
        default=padrao,
        style=ESTILO_PROMPT,
        qmark="",
        **questionario,
    ).ask()


def pedir(pergunta: str, padrao: str = "", **kwargs: Any) -> Optional[str]:
    formatacao, questionario = _separar_formatacao(pergunta, kwargs)
    return questionary.text(
        t(pergunta, **formatacao),
        default=padrao,
        style=ESTILO_PROMPT,
        qmark="",
        **questionario,
    ).ask()


def pedir_senha(pergunta: str, padrao: str = "", **kwargs: Any) -> Optional[str]:
    formatacao, questionario = _separar_formatacao(pergunta, kwargs)
    return questionary.password(
        t(pergunta, **formatacao),
        default=padrao,
        style=ESTILO_PROMPT,
        qmark="",
        **questionario,
    ).ask()


def multi_selecionar(
    pergunta: str,
    escolhas: Iterable[Any],
    instrucao: str = "",
    style: Optional[questionary.Style] = None,
    **kwargs: Any,
) -> Optional[List[Any]]:
    """Checkbox do questionary (multi-seleção) com o tema e a tradução centralizados."""
    formatacao, questionario = _separar_formatacao(pergunta, kwargs, instrucao)
    return questionary.checkbox(
        t(pergunta, **formatacao),
        choices=list(escolhas),
        style=style or ESTILO_PROMPT,
        qmark="",
        instruction=t(instrucao, **formatacao) if instrucao else "",
        **questionario,
    ).ask()
