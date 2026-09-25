#!/usr/bin/env python
"""Confere se README.md (pt-BR) e README.en.md (en) seguem em sincronia.

Uso:
    uv run python scripts/check_readme_sync.py

Sai com código 1 e aponta as diferenças quando os dois arquivos divergem.
As checagens são estruturais — nunca de conteúdo — para a tradução poder
fluir em ritmo diferente da revisão:

1. os dois arquivos existem;
2. a estrutura de headings é idêntica (mesma sequência de níveis);
3. o número de blocos de código é o mesmo;
4. todo link de sumário (#âncora) aponta para um heading existente;
5. o seletor de idioma do topo aponta para o arquivo do outro idioma;
6. o ``readme`` do ``pyproject.toml`` aponta para um dos dois (quebra o
   build se o arquivo sumir).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RAIZ = Path(__file__).resolve().parents[1]
PT = RAIZ / "README.md"
EN = RAIZ / "README.en.md"

#: De/para do seletor: em cada arquivo, o link deve apontar para o outro.
SELETOR = {"README.md": "README.en.md", "README.en.md": "README.md"}


def linhas_fora_de_codigo(texto: str) -> list[str]:
    """Remove os blocos ``` para comentários (`# ...`) não virarem headings."""
    fora: list[str] = []
    dentro = False
    for linha in texto.splitlines():
        if linha.lstrip().startswith("```"):
            dentro = not dentro
            continue
        if not dentro:
            fora.append(linha)
    return fora


def headings(texto: str) -> list[tuple[int, str]]:
    """Todos os headings ATX, fora de código, como (nível, título)."""
    achados: list[tuple[int, str]] = []
    for linha in linhas_fora_de_codigo(texto):
        correspondencia = re.match(r"^(#{1,6})\s+(.*?)\s*$", linha)
        if correspondencia:
            achados.append((len(correspondencia.group(1)), correspondencia.group(2)))
    return achados


def blocos_de_codigo(texto: str) -> int:
    """Quantidade de blocos cercados (``` abre e fecha)."""
    return sum(
        1
        for linha in texto.splitlines()
        if linha.lstrip().startswith("```")
    ) // 2


def slug(titulo: str) -> str:
    """Âncora no estilo GitHub: minúsculas, sem pontuação, espaço vira hífen."""
    minusculo = titulo.strip().lower()
    sem_pontuacao = re.sub(r"[^\w\- ]", "", minusculo, flags=re.UNICODE)
    return sem_pontuacao.replace(" ", "-")


def ancora_valida(texto: str) -> list[str]:
    """Links `[texto](#ancora)` do sumário que não batem com nenhum heading."""
    alvos = {slug(titulo) for _, titulo in headings(texto)}
    invalidos = []
    for ancora in re.findall(r"\]\(#([^)]+)\)", texto):
        if ancora not in alvos:
            invalidos.append(ancora)
    return invalidos


def arquivo_readme_pyproject(texto: str) -> str | None:
    """O arquivo apontado por ``readme`` no pyproject (string ou tabela)."""
    linha = re.search(r"(?m)^readme\s*=\s*(.+)$", texto)
    if not linha:
        return None
    nome = re.search(r'"([^"]+)"', linha.group(1))
    return nome.group(1) if nome else None


def conferir() -> list[str]:
    problemas: list[str] = []

    for caminho in (PT, EN):
        if not caminho.exists():
            problemas.append(f"arquivo ausente: {caminho.name}")
    if problemas:
        return problemas

    texto_pt = PT.read_text(encoding="utf-8")
    texto_en = EN.read_text(encoding="utf-8")

    # 1. estrutura de headings idêntica (mesma sequência de níveis)
    niveis_pt = [nivel for nivel, _ in headings(texto_pt)]
    niveis_en = [nivel for nivel, _ in headings(texto_en)]
    if niveis_pt != niveis_en:
        problemas.append(
            "estrutura de headings divergente: "
            f"{len(niveis_pt)} no README.md x {len(niveis_en)} no README.en.md "
            f"(pt={niveis_pt} en={niveis_en})"
        )

    # 2. mesmo número de blocos de código
    blocos_pt = blocos_de_codigo(texto_pt)
    blocos_en = blocos_de_codigo(texto_en)
    if blocos_pt != blocos_en:
        problemas.append(
            f"blocos de código divergentes: {blocos_pt} no README.md x {blocos_en} no README.en.md"
        )

    # 3. âncoras do sumário existem nos próprios arquivos
    for caminho, texto in ((PT, texto_pt), (EN, texto_en)):
        for ancora in ancora_valida(texto):
            problemas.append(f"{caminho.name}: link de sumário sem heading correspondente: #{ancora}")

    # 4. seletor de idioma aponta para o arquivo do outro idioma
    for nome, destino in SELETOR.items():
        texto = texto_pt if nome == "README.md" else texto_en
        if destino not in texto[:1000]:
            problemas.append(f"{nome}: seletor de idioma não aponta para {destino} no topo do arquivo")

    # 5. o pyproject aponta para um dos dois (quebra o build se o arquivo sumir)
    pyproject = RAIZ / "pyproject.toml"
    if pyproject.exists():
        declarado = arquivo_readme_pyproject(pyproject.read_text(encoding="utf-8"))
        if declarado not in (PT.name, EN.name):
            problemas.append(
                f"pyproject.toml: 'readme' aponta para {declarado!r}, "
                f"esperado {PT.name} ou {EN.name}"
            )
    else:
        problemas.append("pyproject.toml ausente")

    return problemas


def main() -> int:
    problemas = conferir()
    if problemas:
        print("READMEs fora de sincronia:")
        for problema in problemas:
            print(f"  - {problema}")
        print("\nAtualize os dois arquivos e rode de novo: uv run python scripts/check_readme_sync.py")
        return 1
    print("README.md e README.en.md em sincronia (headings, blocos, âncoras, seletor e pyproject).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
