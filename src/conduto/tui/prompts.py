"""Prompts públicos do Conduto em Textual, com *fallback* sem terminal.

As assinaturas espelham o antigo ``conduto.ui`` (a interface de prompts de
sempre) para que ``conduto.cli`` e ``conduto.schemas.schemas_auto`` continuem
iguais:

- ``selecionar`` devolve o **valor** da opção escolhida (``None`` ao cancelar);
- ``multi_selecionar`` devolve a **lista de valores** marcados (``None`` ao
  cancelar, ``[]`` quando nada foi marcado);
- ``confirmar`` devolve ``True``/``False`` (``None`` ao cancelar);
- ``pedir``/``pedir_senha`` devolvem o texto digitado (``None`` ao cancelar).

Kwargs cujo nome aparece como ``{nome}`` na pergunta são formatação do
``t()``; os demais são ignorados (eram opções do questionary — ex. ``style``).
Sem terminal interativo (CI, pipe, ``CONDUTO_SEM_TUI``), cai num ``input()``
numerado em vez de quebrar.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from conduto.i18n import t
from conduto.tui.modelo import MULTIPLA, UNICA, Choice, ModeloSelecao, para_choice
from conduto.tui.paineis import (
    TIPO_CONFIRMACAO,
    TIPO_MULTIPLA,
    TIPO_TEXTO,
    TIPO_UNICA,
    PainelConfirmacao,
    PainelSelecao,
    PainelTexto,
)
from conduto.tui.shell import sessao_ativa
from conduto.tui.telas import TelaConfirmacao, TelaSelecao, TelaTexto

__all__ = [
    "Choice",
    "confirmar",
    "multi_selecionar",
    "pedir",
    "pedir_senha",
    "selecionar",
]

# Mensagens do fallback sem terminal (traduzidas na hora do uso).
ROTULO_NUMERO = "Número"
ROTULO_VARIOS = "Números separados por vírgula (ou todos)"
FALHA_ESCOLHA = "Escolha um número da lista."
FALHA_ENTRADA = "Entrada inválida."
TODOS_OS_VALORES = ("todos", "todas", "all", "*")
SIM = ("s", "sim", "y", "yes")
NAO = ("n", "nao", "não", "no")


def _tem_terminal() -> bool:
    """Há terminal interativo para a TUI? (``CONDUTO_SEM_TUI`` desliga.)"""
    if os.environ.get("CONDUTO_SEM_TUI"):
        return False
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def _separar_formatacao(
    mensagem: str, kwargs: Dict[str, Any], *outras_mensagens: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Separa kwargs de formatação (usados em ``t()``) dos demais."""
    textos = (mensagem,) + outras_mensagens
    formatacao: Dict[str, Any] = {}
    demais: Dict[str, Any] = {}
    for chave, valor in kwargs.items():
        if any("{" + chave + "}" in texto for texto in textos):
            formatacao[chave] = valor
        else:
            demais[chave] = valor
    return formatacao, demais


def _dica_de(kwargs: Dict[str, Any]) -> Optional[str]:
    instrucao = kwargs.get("instrucao")
    return instrucao or None


def _mostrar_dica(dica: Optional[str]) -> None:
    if dica:
        print(f"  {dica}")


# ---------------------------------------------------------------------------
# Shell do wizard (o prompt vira painel dentro da etapa atual)
# ---------------------------------------------------------------------------


def _no_shell(especificacao: Dict[str, Any], construir: Callable[[], Any]) -> Tuple[bool, Any]:
    """``(houve, resposta)`` — True quando o prompt foi atendido pelo shell.

    Dentro do ``conduto init``/``ddl`` (sessão do wizard aberta) o prompt
    bloqueia num futuro que a UI resolve: o corpo espera como sempre e o
    painel aparece na etapa atual. Sem sessão (prompt avulso, testes) o
    chamador segue o caminho de sempre — tela cheia ou ``input()``.
    """
    sessao = sessao_ativa()
    if sessao is None:
        return False, None
    return True, sessao.esperar(especificacao, construir)


# ---------------------------------------------------------------------------
# Fallback sem terminal (input numerado)
# ---------------------------------------------------------------------------


def _pedir_linha(rotulo: str) -> str:
    """Lê uma linha; ``ctrl+c``/EOF viram ``None`` via ``KeyboardInterrupt``."""
    try:
        return input(rotulo)
    except (KeyboardInterrupt, EOFError):
        raise _Cancelado from None


class _Cancelado(Exception):
    """O usuário cancelou no meio do fallback (ctrl+c/EOF)."""


def _escolher_sem_tty(
    pergunta: str,
    escolhas: Sequence[Any],
    modo: str,
    dica: Optional[str] = None,
) -> Optional[List[Any]]:
    """Prompt numerado de ``input()``; devolve lista de valores ou ``None``."""
    itens = [para_choice(e) for e in escolhas]
    if not itens:
        return [] if modo == MULTIPLA else None

    print(pergunta)
    _mostrar_dica(dica)
    for numero, item in enumerate(itens, start=1):
        sufixo = f" \u2014 {item.detalhe}" if item.detalhe else ""
        print(f"  {numero:>2}. {item.title}{sufixo}")

    try:
        if modo == MULTIPLA:
            while True:
                bruto = _pedir_linha(f"{t(ROTULO_VARIOS)}: ").strip().lower()
                if not bruto:
                    return []
                if bruto in TODOS_OS_VALORES:
                    return [item.value for item in itens]
                try:
                    indices = [
                        int(parte.strip())
                        for parte in bruto.replace(";", ",").split(",")
                    ]
                except ValueError:
                    print(FALHA_ESCOLHA)
                    continue
                if not all(1 <= i <= len(itens) for i in indices):
                    print(FALHA_ESCOLHA)
                    continue
                vistos: set = set()
                escolhidos: List[Any] = []
                for indice in indices:
                    if indice not in vistos:
                        vistos.add(indice)
                        escolhidos.append(itens[indice - 1].value)
                return escolhidos

            # modo único
        while True:
            bruto = _pedir_linha(f"{t(ROTULO_NUMERO)}: ").strip()
            if not bruto:
                return [itens[0].value]
            try:
                indice = int(bruto)
            except ValueError:
                print(FALHA_ESCOLHA)
                continue
            if 1 <= indice <= len(itens):
                return [itens[indice - 1].value]
            print(FALHA_ESCOLHA)
    except _Cancelado:
        return None


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def selecionar(pergunta: str, escolhas: Sequence[Any], **kwargs: Any) -> Any:
    """Seleção única; devolve o valor escolhido ou ``None`` ao cancelar."""
    formatacao, _demais = _separar_formatacao(
        pergunta, kwargs, _dica_de(kwargs) or ""
    )
    texto = t(pergunta, **formatacao)
    dica = _dica_de(kwargs)
    if dica:
        dica = t(dica, **formatacao)

    modelo = ModeloSelecao(list(escolhas), modo=UNICA)
    houve, resposta = _no_shell(
        {
            "tipo": TIPO_UNICA,
            "pergunta": texto,
            "dica": dica,
            "escolhas": list(modelo.itens),
            "com_busca": False,
        },
        lambda: PainelSelecao(
            pergunta=texto, modelo=modelo, instrucao=dica, com_busca=False
        ),
    )
    if houve:
        return resposta[0] if resposta else None

    if not _tem_terminal():
        resultado = _escolher_sem_tty(texto, escolhas, UNICA, dica)
        return resultado[0] if resultado else None

    tela = TelaSelecao(pergunta=texto, modelo=modelo, instrucao=dica, com_busca=False)
    resultado = tela.rodar()
    return resultado[0] if resultado else None


def multi_selecionar(
    pergunta: str,
    escolhas: Sequence[Any],
    instrucao: str = "",
    use_search_filter: bool = True,
    **kwargs: Any,
) -> Optional[List[Any]]:
    """Seleção múltipla com marcação individual e "selecionar todas".

    ``instrucao`` vira a linha de dica da tela; ``use_search_filter`` liga o
    campo de filtro. ``style``/``use_jk_keys`` (legado questionary) são
    aceitos e ignorados. Devolve os **valores** marcados, ``None`` ao cancelar.
    """
    formatacao, _demais = _separar_formatacao(pergunta, kwargs, instrucao)
    texto = t(pergunta, **formatacao)
    dica = t(instrucao, **formatacao) if instrucao else None

    modelo = ModeloSelecao(list(escolhas), modo=MULTIPLA)
    houve, resposta = _no_shell(
        {
            "tipo": TIPO_MULTIPLA,
            "pergunta": texto,
            "dica": dica,
            "escolhas": list(modelo.itens),
            "com_busca": bool(use_search_filter),
        },
        lambda: PainelSelecao(
            pergunta=texto,
            modelo=modelo,
            instrucao=dica,
            com_busca=bool(use_search_filter),
        ),
    )
    if houve:
        return resposta

    if not _tem_terminal():
        return _escolher_sem_tty(texto, escolhas, MULTIPLA, dica)

    tela = TelaSelecao(
        pergunta=texto,
        modelo=modelo,
        instrucao=dica,
        com_busca=bool(use_search_filter),
    )
    return tela.rodar()


def confirmar(pergunta: str, padrao: bool = True, **kwargs: Any) -> Optional[bool]:
    """Sim/não; ``None`` quando cancelado (esc/ctrl+c), como no questionary."""
    formatacao, _demais = _separar_formatacao(
        pergunta, kwargs, _dica_de(kwargs) or ""
    )
    texto = t(pergunta, **formatacao)
    dica = _dica_de(kwargs)
    if dica:
        dica = t(dica, **formatacao)

    houve, resposta = _no_shell(
        {
            "tipo": TIPO_CONFIRMACAO,
            "pergunta": texto,
            "dica": dica,
            "padrao": bool(padrao),
        },
        lambda: PainelConfirmacao(
            pergunta=texto, padrao=bool(padrao), instrucao=dica
        ),
    )
    if houve:
        return resposta

    if not _tem_terminal():
        _mostrar_dica(dica)
        while True:
            try:
                bruto = _pedir_linha(f"{texto} [{t('sim')}/{t('não')}]: ").strip().lower()
            except _Cancelado:
                return None
            if not bruto:
                return bool(padrao)
            if bruto in SIM:
                return True
            if bruto in NAO:
                return False
            print(FALHA_ENTRADA)

    tela = TelaConfirmacao(pergunta=texto, padrao=padrao, instrucao=dica)
    return tela.rodar()


def pedir(
    pergunta: str,
    padrao: Any = "",
    senha: bool = False,
    **kwargs: Any,
) -> Optional[str]:
    """Campo de texto (ou senha); ``None`` quando cancelado."""
    padrao_txt = "" if padrao is None else str(padrao)
    formatacao, _demais = _separar_formatacao(
        pergunta, kwargs, _dica_de(kwargs) or ""
    )
    texto = t(pergunta, **formatacao)
    dica = _dica_de(kwargs)
    if dica:
        dica = t(dica, **formatacao)

    houve, resposta = _no_shell(
        {
            "tipo": TIPO_TEXTO,
            "pergunta": texto,
            "dica": dica,
            "valor": padrao_txt,
            "senha": bool(senha),
        },
        lambda: PainelTexto(
            pergunta=texto,
            valor_inicial=padrao_txt,
            senha=bool(senha),
            instrucao=dica,
        ),
    )
    if houve:
        return resposta

    if not _tem_terminal():
        _mostrar_dica(dica)
        sufixo = f" [{padrao_txt}]" if padrao_txt else ""
        try:
            bruto = _pedir_linha(f"{texto}{sufixo}: ")
        except _Cancelado:
            return None
        return bruto if bruto.strip() else padrao_txt

    tela = TelaTexto(
        pergunta=texto,
        valor_inicial=padrao_txt,
        senha=senha,
        instrucao=dica,
    )
    return tela.rodar()


def pedir_senha(pergunta: str, padrao: Any = "", **kwargs: Any) -> Optional[str]:
    """Senha sem eco; mesma semântica de cancelamento de :func:`pedir`."""
    return pedir(pergunta, padrao=padrao, senha=True, **kwargs)
