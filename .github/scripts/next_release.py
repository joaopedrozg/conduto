"""Decide a proxima versao a publicar e faz o bump quando necessario.

Usado pelo workflow Publish to PyPI:

- Merge na main (push): se a versao atual ja esta publicada, faz bump
  patch (commit + push) e publica; se a versao atual ainda nao esta no
  PyPI (bump feito dentro do PR), publica direto.
- Run disparado pelo proprio commit de bump: publica a versao ja commitada.
- Dispatch manual: bump patch/minor/major a partir da versao atual.

Saidas (stdout, formato chave=valor):
  version=<versao a publicar>
  bump=yes|no
  published=true|false  (versao a publicar ja esta no PyPI?)
"""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJETO = "conduto"


def current_version() -> str:
    texto = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version = "([^"]+)"', texto)
    if not match:
        sys.exit("Nao encontrei 'version' no pyproject.toml")
    return match.group(1)


def head_message() -> str:
    resultado = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], capture_output=True, text=True
    )
    return resultado.stdout.strip()


def published_on_pypi(version: str) -> bool:
    """Checa se a versao ja existe no PyPI (simple index, mais rapido que a API)."""
    try:
        with urllib.request.urlopen(
            f"https://pypi.org/simple/{PROJETO}/", timeout=20
        ) as resposta:
            html = resposta.read().decode("utf-8", "replace")
        return re.search(rf"conduto-{re.escape(version)}(?:-|\.)", html) is not None
    except Exception:
        return False


def do_bump(part: str) -> str:
    """Roda o bump_version.py (edita pyproject + uv.lock) e devolve a nova versao."""
    resultado = subprocess.run(
        [sys.executable, str(ROOT / ".github/scripts/bump_version.py"), part],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        sys.exit(resultado.stderr.strip() or f"Falha no bump ({part}).")
    return resultado.stdout.strip()


def main() -> None:
    part = sys.argv[1] if len(sys.argv) > 1 else "patch"

    version = current_version()
    if head_message().startswith("chore: bump version to"):
        # Run disparado pelo proprio commit de bump: publica o que ja esta commitado.
        version_publicar = version
        precisa_bump = False
    elif published_on_pypi(version):
        # Merge normal com a versao atual ja publicada: bump patch e publica.
        version_publicar = do_bump(part)
        precisa_bump = True
    else:
        # Bump feito dentro do PR (versao ainda nao publicada): publica direto.
        version_publicar = version
        precisa_bump = False

    publicada = published_on_pypi(version_publicar)
    print(f"version={version_publicar}")
    print(f"bump={'yes' if precisa_bump else 'no'}")
    print(f"published={'true' if publicada else 'false'}")


if __name__ == "__main__":
    main()