"""Tema do Conduto: paleta discreta em que **cada cor é um status**.

Nada de cor decorativa — a cor sempre diz o estado de algo:

===================  ========  =====================================
Status               Cor       Quando aparece
===================  ========  =====================================
``Status.OK``        verde     sucesso, concluído, item marcado
``Status.AVISO``     âmbar     atenção, pendente, item já existe
``Status.ERRO``      vermelho  falha, bloqueio
``Status.INFO``      azul      informação, foco, dado complementar
``Status.NEUTRO``    cinza     disponível, sem estado
===================  ========  =====================================

Os tons são propositalmente abafados: a cor informa o status, não compete
com o conteúdo. A mesma paleta alimenta as duas interfaces do conduto — o
**rich** (saída do CLI, via :data:`CORES`) e o **Textual** (telas da TUI,
via :data:`CSS_TEMA`) — para os dois meios falarem a mesma linguagem de cor.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict


class Status(str, Enum):
    """Status que uma cor representa no Conduto."""

    OK = "ok"  # sucesso / concluído / marcado
    AVISO = "aviso"  # atenção / pendente / já existe
    ERRO = "erro"  # falha / bloqueio
    INFO = "info"  # informação / foco / dado complementar
    NEUTRO = "neutro"  # disponível / sem estado


#: Cores hex discretas de cada status (usadas pelo rich e pelo Textual).
CORES_STATUS: Dict[Status, str] = {
    Status.OK: "#7fbf9a",
    Status.AVISO: "#c9a45c",
    Status.ERRO: "#cc7a72",
    Status.INFO: "#7fa9cc",
    Status.NEUTRO: "#8b9099",
}

#: Glifo de cada status — junto com a cor, identifica a linha sem depender só do tom.
GLIFOS: Dict[Status, str] = {
    Status.OK: "\u25cf",  # ●
    Status.AVISO: "\u25b2",  # ▲
    Status.ERRO: "\u2715",  # ✕
    Status.INFO: "\u25c6",  # ◆
    Status.NEUTRO: "\u25cb",  # ○
}

# Cores neutras da interface (fundo, texto e bordas) — também discretas.
COR_TEXTO = "#d7dae0"
COR_TITULO = "#eef1f5"
COR_BORDA = "#39424c"
COR_FUNDO = "#14171c"
COR_FUNDO_ALT = "#1b2028"
COR_FOCO = "#26384a"
COR_PRIMARIA = "#2d4a63"


def cor(status: Status) -> str:
    """Cor hexadecimal de um status (vale para rich e para Textual)."""
    return CORES_STATUS[status]


def glifo(status: Status) -> str:
    """Glifo que identifica um status nas linhas das tabelas da TUI."""
    return GLIFOS[status]


# ---------------------------------------------------------------------------
# rich (saída do CLI) — mesmas chaves de sempre, com a paleta de status
# ---------------------------------------------------------------------------

CORES: Dict[str, str] = {
    "erro": cor(Status.ERRO),
    "aviso": cor(Status.AVISO),
    "sucesso": cor(Status.OK),
    "info": cor(Status.INFO),
    "neutro": cor(Status.NEUTRO),
    "discreto": f"{cor(Status.NEUTRO)} dim",
    "titulo": f"{COR_TITULO} bold",
    "texto": COR_TEXTO,
    "destaque": f"{COR_TITULO} bold on {COR_PRIMARIA}",
    "detalhe": cor(Status.INFO),
    "borda": "#3f4a56",
    "linha": COR_BORDA,
    "progresso": cor(Status.INFO),
    "coluna_titulo": f"{COR_TITULO} bold",
    "coluna_valor": COR_TEXTO,
    "coluna_sucesso": cor(Status.OK),
    "coluna_info": cor(Status.INFO),
    "coluna_detalhe": cor(Status.INFO),
}

# Estilos semânticos usados pelas colunas da :func:`conduto.ui.tabela`.
ESTILOS_COLUNA: Dict[str, str] = {
    "titulo": CORES["coluna_titulo"],
    "texto": CORES["coluna_valor"],
    "sucesso": CORES["coluna_sucesso"],
    "info": CORES["coluna_info"],
    "detalhe": CORES["coluna_detalhe"],
}

# ---------------------------------------------------------------------------
# Textual (TUI) — a mesma paleta como variáveis de CSS
# ---------------------------------------------------------------------------

CSS_TEMA = f"""
$status-ok: {cor(Status.OK)};
$status-aviso: {cor(Status.AVISO)};
$status-erro: {cor(Status.ERRO)};
$status-info: {cor(Status.INFO)};
$status-neutro: {cor(Status.NEUTRO)};

$cor-texto: {COR_TEXTO};
$cor-titulo: {COR_TITULO};
$cor-borda: {COR_BORDA};
$cor-fundo: {COR_FUNDO};
$cor-fundo-alt: {COR_FUNDO_ALT};
$cor-foco: {COR_FOCO};
$cor-primaria: {COR_PRIMARIA};

Screen {{
    background: $cor-fundo;
    color: $cor-texto;
}}

#pergunta {{
    height: auto;
    padding: 1 2 0 2;
    color: $cor-titulo;
    text-style: bold;
    border-bottom: solid $cor-borda;
}}

#dica {{
    height: auto;
    padding: 0 2 1 2;
    color: $status-neutro;
}}

Input {{
    width: 1fr;
    height: 1;
    padding: 0 2;
    background: $cor-fundo-alt;
    color: $cor-texto;
    border: none;
}}
Input:focus {{
    background: $cor-foco;
}}
Input > .input--placeholder {{
    color: $status-neutro;
}}
Input > .input--cursor {{
    color: $cor-titulo;
}}

#acoes {{
    height: auto;
    padding: 1 2;
    background: $cor-fundo;
    align: center middle;
}}
#acoes Input {{
    width: 1fr;
    padding: 0;
    background: transparent;
}}
#acoes Input:focus {{
    background: $cor-foco;
}}
#acoes Button {{
    height: 1;
    margin-left: 1;
}}
#espacador {{
    width: 1fr;
}}

Button {{
    width: auto;
    min-width: 1;
    height: 1;
    padding: 0 1;
    background: $cor-fundo-alt;
    color: $cor-texto;
    border: none;
    text-style: none;
}}
Button:hover {{
    background: $cor-foco;
    color: $cor-titulo;
}}
Button:focus {{
    background: $cor-foco;
    color: $cor-titulo;
    text-style: bold;
}}
Button.-active {{
    background: $cor-primaria;
    color: $cor-titulo;
}}
Button.-primary {{
    background: $cor-primaria;
    color: $cor-titulo;
}}

DataTable {{
    height: 1fr;
    background: $cor-fundo;
    color: $cor-texto;
}}
DataTable > .datatable--header {{
    background: $cor-fundo-alt;
    color: $status-info;
    text-style: bold;
}}
DataTable:focus > .datatable--cursor {{
    background: $cor-foco;
    color: $cor-titulo;
}}

#status {{
    height: 1;
    padding: 0 2;
    background: $cor-fundo-alt;
    color: $status-neutro;
}}

Footer {{
    background: $cor-fundo-alt;
}}
Footer > FooterKey {{
    color: $status-neutro;
}}
"""
