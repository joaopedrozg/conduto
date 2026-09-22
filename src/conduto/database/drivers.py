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
import sysconfig
from pathlib import Path
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


def em_venv() -> bool:
    """True quando o interpretador em uso roda dentro de um venv.

    Cobertos por isso: ``uvx``/``uv tool``/``pipx`` (criam venv próprio) e um
    ``python -m venv`` local. Falso quando o conduto foi instalado direto no
    Python do sistema (``pip install --user``, ``--break-system-packages``).
    """
    return sys.prefix != sys.base_prefix


def gerenciado_pelo_sistema() -> bool:
    """True quando o PEP 668 barra ``pip install`` neste interpretador.

    Debian/Ubuntu, Fedora, Arch e o Homebrew marcam o Python como
    *externally-managed*; o pip (e o ``uv pip install``) se recusam a instalar
    fora de um venv. Windows instalado pelo python.org não tem o marker.

    Atenção aos dois termos: dentro de um venv o ``stdlib`` de ``sysconfig``
    pode apontar para o diretório do sistema — onde o marker existe — mesmo
    que a instalação funcione normalmente. Por isso a checagem é
    ``fora de venv`` **e** ``marker presente``; só o arquivo daria falso
    positivo no ambiente correto.
    """
    if em_venv():
        return False
    return (Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED").exists()


def _candidatos_instalacao(
    requisicoes: List[str], quebrar_sistema: bool = False
) -> List[List[str]]:
    """Comandos possíveis para instalar, em ordem de preferência.

    ``uv pip install --python`` cobre ambientes gerados por uv (incluindo
    ``uvx``, que não traz pip); o ``pip`` do próprio interpretador cobre as
    instalações clássicas.

    Sob PEP 668 os dois recusariam de qualquer jeito, então devolve lista vazia
    a menos que o usuário tenha autorizado ``--break-system-packages`` — assim
    o erro vira uma explicação clara em vez do mural de texto da distribuição.
    """
    gerenciado = gerenciado_pelo_sistema()
    if gerenciado and not quebrar_sistema:
        return []
    flag = ["--break-system-packages"] if gerenciado else []

    candidatos: List[List[str]] = []
    uv = shutil.which("uv")
    if uv:
        candidatos.append(
            [uv, "pip", "install", "--python", sys.executable, *flag, *requisicoes]
        )
    if importlib.util.find_spec("pip") is not None:
        candidatos.append([sys.executable, "-m", "pip", "install", *flag, *requisicoes])
    return candidatos


def instalar_drivers(tipo: str, quebrar_sistema: bool = False) -> Tuple[bool, str]:
    """Instala no ambiente atual da CLI os drivers que faltam para o SGBD.

    Devolve ``(ok, mensagem)`` — a mesma assinatura dos testes de conexão,
    para o chamar imprimir ``sucesso``/``erro`` sem tratar o caso à parte.

    ``quebrar_sistema`` só é considerado quando o interpretador é
    *externally-managed* (ver :func:`gerenciado_pelo_sistema`).
    """
    pendentes = requisicoes_pendentes(tipo)
    if not pendentes:
        return True, t(
            "Todas as dependências do {tipo} já estão instaladas.", tipo=tipo
        )

    candidatos = _candidatos_instalacao(pendentes, quebrar_sistema)
    if not candidatos:
        if gerenciado_pelo_sistema():
            return False, t(
                "O Python em uso não é um venv e é gerenciado pelo sistema "
                "(PEP 668), então a instalação é bloqueada. Alternativas: "
                "rode o conduto com uvx/pipx (usa um venv isolado), crie um "
                "venv com `uv venv`, ou autorize com "
                "`pip install --break-system-packages {requisicoes}`.",
                requisicoes=" ".join(pendentes),
            )
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
