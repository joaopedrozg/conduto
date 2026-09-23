"""Todas as strings novas da TUI têm de estar no catálogo EN.

A chave do catálogo é a própria mensagem em português (padrão msgid), então
o teste varre o código em busca de ``t("...")`` e confere cada literal contra
:class:`conduto.i18n.catalogo_en.CATALOGO_EN` — assim nenhum rótulo novo da
interface escapa da tradução.
"""

import ast
import re
from pathlib import Path

import pytest

from conduto.i18n import definir_idioma
from conduto.i18n.catalogo_en import CATALOGO_EN
from conduto.tui import prompts
from conduto.schemas import schemas_auto

PACOTE_TUI = Path(__file__).resolve().parents[1] / "src" / "conduto" / "tui"

#: ``t("chave")`` / ``t('chave')`` — pega literais mesmo quebrados em linhas.
CHAMADAS = re.compile(
    r"""(?<![A-Za-z_])t\(\s*(?P<literal>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""",
    re.S,
)


def _literais_de(caminho: Path) -> list[str]:
    """Chaves literais passadas para ``t()`` num arquivo, já decodificadas."""
    chaves: list[str] = []
    for achado in CHAMADAS.finditer(caminho.read_text(encoding="utf-8")):
        try:
            valor = ast.literal_eval(achado.group("literal"))
        except (SyntaxError, ValueError):
            continue
        if isinstance(valor, str):
            chaves.append(valor)
    return chaves


@pytest.fixture(autouse=True)
def _idioma():
    definir_idioma("pt")


def test_todo_literal_de_t_no_pacote_tui_tem_traducao_en():
    faltando: list[str] = []
    for arquivo in sorted(PACOTE_TUI.glob("*.py")):
        for chave in _literais_de(arquivo):
            if chave not in CATALOGO_EN:
                faltando.append(f"{arquivo.name}: {chave}")
    assert not faltando, "falta tradução no CATALOGO_EN:\n  " + "\n  ".join(faltando)


def test_os_rotulos_dos_prompts_sem_terminal_estao_no_catalogo():
    # t(ROTULO_...) recebe variável, então não aparece na varredura acima.
    for chave in (
        prompts.ROTULO_NUMERO,
        prompts.ROTULO_VARIOS,
        prompts.FALHA_ESCOLHA,
        prompts.FALHA_ENTRADA,
    ):
        assert chave in CATALOGO_EN, chave


def test_os_textos_novos_do_fluxo_de_geracao_estao_no_catalogo():
    for chave in (
        schemas_auto.INSTRUCAO_BUSCA,
        "{qtd} tabela(s)",
        "já existe",
        "Selecione os schemas da origem:",
        "Selecione as tabelas para gerar os schemas:",
    ):
        assert chave in CATALOGO_EN, chave


def test_a_dica_de_selecionar_todas_traduz():
    definir_idioma("en")
    from conduto.i18n import t

    assert t("Marca só o que está visível com o filtro atual.") == (
        "Marks only what is visible with the current filter."
    )
    definir_idioma("pt")
