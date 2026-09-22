"""Importação dos drivers de banco, organizados como *extras* do conduto.

Cada SGBD tem seu próprio extra (``pip install "conduto[postgresql]"``). Os
drivers são importados de forma preguiçosa (dentro das funções que conectam),
de modo que ``conduto --help`` e os comandos que não usam banco não precisem
de nenhum driver instalado.

Quando um driver ausente é usado, o erro levantado diz exatamente qual extra
instalar em vez de expor um ``ModuleNotFoundError`` cru.
"""

from __future__ import annotations

import importlib
import importlib.util
from typing import Tuple

from conduto.i18n import t

# Módulo do driver -> extra do pacote que o fornece.
_EXTRA_POR_MODULO = {
    "psycopg": "postgresql",
    "pymysql": "mysql",
    "pyodbc": "sqlserver",
    "clickhouse_connect": "clickhouse",
    "duckdb": "duckdb",
    "deltalake": "deltalake",
    "pyarrow": "deltalake",
    "boto3": "deltalake",
}

# Módulos que cada SGBD precisa para funcionar de ponta a ponta.
MODULOS_POR_SGBD = {
    "postgresql": ("psycopg",),
    "mysql": ("pymysql",),
    "sqlserver": ("pyodbc",),
    "clickhouse": ("clickhouse_connect",),
    "duckdb": ("duckdb",),
    "deltalake": ("deltalake", "pyarrow", "boto3"),
}


def extra_do_driver(modulo: str) -> str:
    """Devolve o nome do extra que fornece o módulo informado."""
    return _EXTRA_POR_MODULO.get(modulo, "all")


def drivers_faltantes(tipo: str) -> Tuple[str, ...]:
    """Módulos de driver do SGBD que ainda não estão instalados."""
    faltando = []
    for modulo in MODULOS_POR_SGBD.get(tipo, ()):
        try:
            disponivel = importlib.util.find_spec(modulo) is not None
        except (ImportError, ValueError):
            disponivel = False
        if not disponivel:
            faltando.append(modulo)
    return tuple(faltando)


def importar_driver(modulo: str):
    """Importa o módulo do driver ou levanta um erro apontando o extra.

    Uso::

        psycopg = importar_driver("psycopg")
        sql = importar_driver("psycopg").sql
    """
    try:
        return importlib.import_module(modulo)
    except ModuleNotFoundError as exc:
        # Só traduzimos a ausência do próprio driver; um erro do interior
        # dele (dependência quebrada) é repassado como está.
        if exc.name and exc.name != modulo and not exc.name.startswith(modulo + "."):
            raise
        extra = extra_do_driver(modulo)
        raise RuntimeError(
            t(
                "Driver '{modulo}' não instalado. Instale com: "
                "pip install \"conduto[{extra}]\" "
                "(ou: uv tool install \"conduto[{extra}]\")",
                modulo=modulo,
                extra=extra,
            )
        ) from exc
