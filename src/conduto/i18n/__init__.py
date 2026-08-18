"""Internacionalização (i18n) do Conduto.

Detecta o idioma da máquina (pt ou en) e oferece a função :func:`t`
para traduzir as mensagens do CLI conforme o idioma detectado.
"""

from __future__ import annotations

import ctypes
import locale
import os
from typing import Optional

from conduto.i18n.catalogo_en import CATALOGO_EN

IDIOMAS_SUPORTADOS = ("pt", "en")
_NOMES_NATIVOS = {
    "pt": "Português (pt)",
    "en": "English (en)",
}

_idioma_atual = "pt"


def _base(valor: Optional[str]) -> Optional[str]:
    """Normaliza um valor como ``pt_BR.UTF-8`` ou ``en-US`` para ``pt``/``en``."""
    if not valor:
        return None
    base = valor.lower().split("_")[0].split("-")[0].strip()
    return base if base in IDIOMAS_SUPORTADOS else None


def _idioma_windows() -> Optional[str]:
    """Lê o idioma de interface do usuário do Windows (LANGID)."""
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "pt" if lang_id in (0x0416, 0x0816) else "en"
    except Exception:
        return None


def _idioma_ambiente() -> Optional[str]:
    """Lê variáveis de ambiente e o locale do Python."""
    for variavel in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        idioma = _base(os.environ.get(variavel))
        if idioma:
            return idioma
    for funcao in (locale.getlocale, locale.getdefaultlocale):
        try:
            codigo, _ = funcao()
            idioma = _base(codigo)
            if idioma:
                return idioma
        except Exception:
            continue
    return None


def detectar_idioma() -> str:
    """Detecta o idioma do usuário.

    Ordem: ``CONDUTO_LANG`` > variáveis de ambiente/locale do Python >
    idioma de interface do Windows > ``pt``.
    """
    override = _base(os.environ.get("CONDUTO_LANG"))
    if override:
        return override
    return _idioma_ambiente() or _idioma_windows() or "pt"


def definir_idioma(idioma: str) -> None:
    """Define o idioma atual (``pt`` ou ``en``); valores inválidos caem em ``pt``."""
    global _idioma_atual
    _idioma_atual = _base(idioma) or "pt"


def idioma_atual() -> str:
    """Devolve o idioma atual (``pt`` ou ``en``)."""
    return _idioma_atual


def nome_idioma(idioma: Optional[str] = None) -> str:
    """Devolve o nome nativo do idioma (ex.: ``Português (pt)``)."""
    return _NOMES_NATIVOS.get(_base(idioma) or _idioma_atual, _NOMES_NATIVOS["pt"])


def t(mensagem: str, **kwargs: object) -> str:
    """Traduz a mensagem para o idioma atual.

    A chave é a própria mensagem em português (padrão msgid); o
    catálogo EN traduz quando o idioma atual é ``en``. Placeholders
    nomeados (``{nome}``) são aplicados após a tradução.
    """
    if _idioma_atual == "en":
        mensagem = CATALOGO_EN.get(mensagem, mensagem)
    return mensagem.format(**kwargs) if kwargs else mensagem
