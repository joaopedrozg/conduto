"""Conduto: o duto que leva seus dados da origem ao destino."""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

__all__ = ["__version__"]


def _versao_pyproject() -> str:
    """Le a versao do pyproject.toml quando o pacote nao esta instalado."""
    caminho = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"
    correspondencia = re.search(r'(?m)^version = "([^"]+)"', texto)
    return correspondencia.group(1) if correspondencia else "0.0.0"


try:
    __version__ = version("conduto")
except PackageNotFoundError:
    __version__ = _versao_pyproject()