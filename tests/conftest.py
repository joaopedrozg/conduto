"""Fixtures globais de teste.

O ``CONDUTO_SEM_TUI=1`` garante que nenhum teste (inclusive sob ``pytest -s``,
com stdout interativo) abra um shell Textual de verdade: ``_tem_terminal()``
cai no fallback numerado e ``rodar_no_shell`` roda o corpo direto. Testes que
querem o caminho TUI removem a variável/repinçam ``_tem_terminal``, como já
fazem.

O ``CONDUTO_REGISTROS`` aponta para um arquivo do ``tmp_path``: os registros
do shell (SQLite) de nenhum teste caem no ``~/.conduto`` de quem roda.
"""

import pytest

from conduto.tui import registros


@pytest.fixture(autouse=True)
def _sem_tui_nos_testes(monkeypatch):
    monkeypatch.setenv("CONDUTO_SEM_TUI", "1")


@pytest.fixture(autouse=True)
def _registros_em_tmp(monkeypatch, tmp_path):
    """Banco dos registros fora do home — um arquivo novo por teste."""
    monkeypatch.setenv("CONDUTO_REGISTROS", str(tmp_path / "registros.db"))
    registros.fechar()  # descarta conexão apontando para o arquivo do teste anterior
    yield
    registros.fechar()
