"""Importação dos drivers de banco, organizados como *extras* do conduto.

Cada SGBD tem seu próprio extra (``pip install "conduto[postgresql]"``). Os
drivers são importados de forma preguiçosa (dentro das funções que conectam),
de modo que ``conduto --help`` e os comandos que não usam banco não precisem
de nenhum driver instalado.

Quando um driver ausente é usado, o erro levantado diz exatamente qual extra
instalar em vez de expor um ``ModuleNotFoundError`` cru. O fluxo interativo
também pode instalar os drivers faltantes direto no ambiente atual da CLI
(:func:`instalar_drivers`).
"""

from __future__ import annotations

import importlib
import importlib.util
import shutil
import subprocess
import sys
from typing import Dict, List, Tuple

from conduto.i18n import t

# Módulo do driver -> extra do pacote que o fornece.
_EXTRA_POR_MODULO: Dict[str, str] = {
    "psycopg": "postgresql",
    "pymysql": "mysql",
    "pyodbc": "sqlserver",
    "clickhouse_connect": "clickhouse",
    "duckdb": "duckdb",
    "deltalake": "deltalake",
    "pyarrow": "deltalake",
    "boto3": "deltalake",
}

# Módulo -> requisito pip (o que se passa para `pip install`).
_REQ_POR_MODULO: Dict[str, str] = {
    "psycopg": "psycopg[binary]",
    "pymysql": "pymysql",
    "pyodbc": "pyodbc",
    "clickhouse_connect": "clickhouse-connect",
    "duckdb": "duckdb",
    "deltalake": "deltalake",
    "pyarrow": "pyarrow",
    "boto3": "boto3",
}

# Módulos que cada SGBD precisa para funcionar de ponta a ponta.
MODULOS_POR_SGBD: Dict[str, Tuple[str, ...]] = {
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


def requisicoes_pendentes(tipo: str) -> List[str]:
    """Requisitos pip dos drivers faltantes (ex.: ``['psycopg[binary]']``)."""
    return [_REQ_POR_MODULO.get(m, m.replace("_", "-")) for m in drivers_faltantes(tipo)]


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


# ---------------------------------------------------------------------------
# Instalação dos drivers faltantes no ambiente atual da CLI
# ---------------------------------------------------------------------------


def _resumir(saida: str, limite: int = 400) -> str:
    """Corta a saída do instalador para caber num prompt de erro."""
    texto = (saida or "").strip()
    if len(texto) > limite:
        texto = "..." + texto[-limite:]
    return texto or "sem saída"


def _rodar(comando: List[str]) -> Tuple[str, bool]:
    """Executa o comando e devolve (saída, falhou). Nunca levanta exceção."""
    try:
        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return str(exc), True
    if resultado.returncode == 0:
        return resultado.stdout or "", False
    saida = resultado.stderr or resultado.stdout or ""
    return _resumir(saida), True


def _candidatos_instalacao(requisicoes: List[str]) -> List[List[str]]:
    """Comandos possíveis para instalar, em ordem de preferência.

    ``uv pip install --python`` cobre ambientes gerados por uv (incluindo
    ``uvx``, que não traz pip); o ``pip`` do próprio interpretador cobre as
    instalações clássicas, onde o uv se recusaria a agir sem um venv.
    """
    candidatos: List[List[str]] = []
    uv = shutil.which("uv")
    if uv:
        candidatos.append([uv, "pip", "install", "--python", sys.executable, *requisicoes])
    if importlib.util.find_spec("pip") is not None:
        candidatos.append([sys.executable, "-m", "pip", "install", *requisicoes])
    return candidatos


def instalar_drivers(tipo: str) -> Tuple[bool, str]:
    """Instala no ambiente atual da CLI os drivers que faltam para o SGBD.

    Devolve ``(ok, mensagem)`` — a mesma assinatura dos testes de conexão,
    para o chamar imprimir ``sucesso``/``erro`` sem tratar o caso à parte.
    """
    pendentes = requisicoes_pendentes(tipo)
    if not pendentes:
        return True, t(
            "Todas as dependências do {tipo} já estão instaladas.", tipo=tipo
        )

    candidatos = _candidatos_instalacao(pendentes)
    if not candidatos:
        return False, t(
            "Instale manualmente com: {comando}",
            comando="pip install " + " ".join(pendentes),
        )

    ultimo_erro = ""
    for comando in candidatos:
        saida, falhou = _rodar(comando)
        if not falhou:
            return True, t(
                "Dependências do {tipo} instaladas com sucesso: {lista}",
                tipo=tipo,
                lista=", ".join(pendentes),
            )
        ultimo_erro = saida

    return False, (
        t("Falha ao instalar as dependências do {tipo}: {erro}", tipo=tipo, erro=ultimo_erro)
        + "\n"
        + t("Instale manualmente com: {comando}", comando="pip install " + " ".join(pendentes))
    )
