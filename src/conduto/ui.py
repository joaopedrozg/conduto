"""Ajustes de renderização dos prompts do questionary.

O questionary renderiza a pergunta como ``"{qmark} {mensagem} "``, então mesmo com
``qmark=""`` sobra um espaço antes do texto. Aqui removemos esse espaço extra para
manter os prompts alinhados com os demais (HOST:, PORT:, etc.).
"""

from typing import Any, List, Optional, Tuple

import questionary
from prompt_toolkit.document import Document
from prompt_toolkit.lexers import Lexer, SimpleLexer
from prompt_toolkit.shortcuts.prompt import PromptSession
from prompt_toolkit.styles import Style
from questionary.constants import DEFAULT_QUESTION_PREFIX, INSTRUCTION_MULTILINE
from questionary.prompts import common
from questionary.prompts.common import build_validator
from questionary.question import Question
from questionary.styles import merge_styles_default


def _sem_espaco(tokens: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Remove o espaço inicial que o questionary coloca antes da pergunta."""
    ajustados = []
    for estilo, texto in tokens:
        if estilo in ("class:question", "class:instruction") and texto.startswith(" "):
            texto = texto[1:]
        ajustados.append((estilo, texto))
    return ajustados


_layout_original = common.create_inquirer_layout


def _layout_sem_espaco(ic, get_prompt_tokens, **kwargs):
    def tokens_sem_espaco():
        return _sem_espaco(get_prompt_tokens())

    return _layout_original(ic, tokens_sem_espaco, **kwargs)


def _texto_sem_espaco(
    message: str,
    default: str = "",
    validate: Any = None,
    qmark: str = DEFAULT_QUESTION_PREFIX,
    style: Optional[Style] = None,
    multiline: bool = False,
    instruction: Optional[str] = None,
    lexer: Optional[Lexer] = None,
    **kwargs: Any,
) -> Question:
    """Versão do questionary.text sem o espaço inicial antes da pergunta."""
    merged_style = merge_styles_default([style])
    lexer = lexer or SimpleLexer("class:answer")
    validator = build_validator(validate)

    if instruction is None and multiline:
        instruction = INSTRUCTION_MULTILINE

    def get_prompt_tokens() -> List[Tuple[str, str]]:
        tokens = [("class:qmark", qmark), ("class:question", " {} ".format(message))]
        if instruction:
            tokens.append(("class:instruction", " {} ".format(instruction)))
        return _sem_espaco(tokens)

    p: PromptSession = PromptSession(
        get_prompt_tokens,
        style=merged_style,
        validator=validator,
        lexer=lexer,
        multiline=multiline,
        **kwargs,
    )
    p.default_buffer.reset(Document(default))

    return Question(p.app)


def _senha_sem_espaco(
    message: str,
    default: str = "",
    validate: Any = None,
    qmark: str = DEFAULT_QUESTION_PREFIX,
    style: Optional[Style] = None,
    **kwargs: Any,
) -> Question:
    return _texto_sem_espaco(message, default, validate, qmark, style, is_password=True, **kwargs)


def aplicar_ajustes():
    """Aplica os ajustes de renderização nos prompts do questionary."""
    common.create_inquirer_layout = _layout_sem_espaco
    questionary.text = _texto_sem_espaco
    questionary.password = _senha_sem_espaco
