"""Decide a versao a publicar no PyPI no gatilho de merge na main.

O release e automatico no push para main:
- se o PR ja bumpou a versao (atual > ultima publicada), publica a atual;
- caso contrario, faz bump patch sobre a ultima versao publicada no PyPI.

A versao decidida e aplicada apenas no working tree (pyproject + uv.lock)
para o build/publish — nao e commitada na main (o ruleset exige PR para
push direto).

Saidas (stdout, formato chave=valor):
  version=<versao a publicar>
  bump=no
  published=false
"""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJETO = "conduto"


def _semver(chave: str):
    return tuple(int(x) for x in chave.split("."))


def current_version() -> str:
    texto = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version = "([^"]+)"', texto)
    if not match:
        sys.exit("Nao encontrei 'version' no pyproject.toml")
    return match.group(1)


def latest_published() -> str:
    """Maior versao do conduto ja publicada no PyPI (simple index)."""
    try:
        with urllib.request.urlopen(
            f"https://pypi.org/simple/{PROJETO}/", timeout=20
        ) as resposta:
            html = resposta.read().decode("utf-8", "replace")
        versoes = re.findall(rf"{PROJETO}-(\d+\.\d+\.\d+)(?:-|\.)", html)
        if not versoes:
            return "0.0.0"
        return max(versoes, key=_semver)
    except Exception:
        sys.exit("Nao consegui consultar o PyPI para descobrir a ultima versao.")


def bump(version: str, part: str) -> str:
    major, minor, patch = _semver(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    sys.exit(f"Tipo de bump invalido: {part!r} (use patch, minor ou major)")


def aplicar_versao(version: str) -> None:
    resultado = subprocess.run(
        [sys.executable, str(ROOT / ".github/scripts/bump_version.py"), "set", version],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        sys.exit(resultado.stderr.strip() or "Falha ao aplicar a versao.")


def main() -> None:
    part = sys.argv[1] if len(sys.argv) > 1 else "patch"

    atual = current_version()
    ultima = latest_published()

    if _semver(atual) > _semver(ultima):
        # O PR ja bumpou a versao (ainda nao publicada): publica direto.
        nova = atual
    else:
        nova = bump(ultima, part)

    aplicar_versao(nova)
    print(f"version={nova}")
    print("bump=no")
    print("published=false")


if __name__ == "__main__":
    main()