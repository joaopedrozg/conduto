"""Fixtures globais de teste.

O ``CONDUTO_SEM_TUI=1`` garante que nenhum teste (inclusive sob ``pytest -s``,
com stdout interativo) abra um shell Textual de verdade: ``_tem_terminal()``
cai no fallback numerado e ``rodar_no_shell`` roda o corpo direto. Testes que
querem o caminho TUI removem a variável/repinçam ``_tem_terminal``, como já
fazem.
"""

import pytest


@pytest.fixture(autouse=True)
def _sem_tui_nos_testes(monkeypatch):
    monkeypatch.setenv("CONDUTO_SEM_TUI", "1")
