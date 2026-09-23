"""Interface de utilizador construída em Textual.

Reexporta os prompts públicos e os modelos usados por `conduto.ui`.
"""

from __future__ import annotations

from conduto.tui.modelo import (
    MULTIPLA,
    UNICA,
    Choice,
    ModeloSelecao,
    para_choice,
    valores_de,
)
from conduto.tui.prompts import (
    confirmar,
    multi_selecionar,
    pedir,
    pedir_senha,
    selecionar,
)
from conduto.tui.tema import CORES, ESTILOS_COLUNA, GLIFOS, Status, cor, glifo

__all__ = [
    "CORES",
    "ESTILOS_COLUNA",
    "GLIFOS",
    "MULTIPLA",
    "UNICA",
    "Choice",
    "ModeloSelecao",
    "Status",
    "confirmar",
    "cor",
    "glifo",
    "multi_selecionar",
    "para_choice",
    "pedir",
    "pedir_senha",
    "selecionar",
    "valores_de",
]
