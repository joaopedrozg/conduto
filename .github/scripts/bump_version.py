"""Bump/seta a versao do pacote (semver) em pyproject.toml e uv.lock.

Uso:
  python bump_version.py [patch|minor|major]  # bump a partir da versao atual
  python bump_version.py set X.Y.Z            # define uma versao exata

Imprime a nova versao no stdout.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def bump(version: str, part: str) -> str:
    match = _SEMVER.fullmatch(version)
    if not match:
        sys.exit(f"Versao atual nao e semver simples (esperado X.Y.Z): {version!r}")
    major, minor, patch = (int(group) for group in match.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    sys.exit(f"Tipo de bump invalido: {part!r} (use patch, minor, major ou set)")


def escrever_versao(new_version: str) -> None:
    """Escreve a versao em pyproject.toml e no entry 'conduto' do uv.lock."""
    pyproject = ROOT / "pyproject.toml"
    lock = ROOT / "uv.lock"

    project_text = pyproject.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not re.search(r'(?m)^version = "([^"]+)"', project_text):
        sys.exit("Nao encontrei 'version' no pyproject.toml")
    pyproject.write_text(
        re.sub(
            r'(?m)^version = "[^"]+"',
            f'version = "{new_version}"',
            project_text,
            count=1,
        ),
        encoding="utf-8",
    )

    lock_text = lock.read_text(encoding="utf-8").replace("\r\n", "\n")
    lock_pattern = re.compile(r'(?m)^(\[\[package\]\]\nname = "conduto"\n)version = "[^"]+"')
    if not lock_pattern.search(lock_text):
        sys.exit("Nao encontrei o entry 'conduto' no uv.lock")
    lock.write_text(
        lock_pattern.sub(
            lambda found: found.group(1) + f'version = "{new_version}"',
            lock_text,
            count=1,
        ),
        encoding="utf-8",
    )


def main() -> None:
    args = sys.argv[1:]
    part = args[0] if args else "patch"

    pyproject = ROOT / "pyproject.toml"
    match = re.search(r'(?m)^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"))
    if not match:
        sys.exit("Nao encontrei 'version' no pyproject.toml")
    current = match.group(1)

    if part == "set":
        if len(args) < 2:
            sys.exit("Uso: bump_version.py set X.Y.Z")
        new_version = args[1]
        if not _SEMVER.fullmatch(new_version):
            sys.exit(f"Versao invalida (esperado X.Y.Z): {new_version!r}")
    else:
        new_version = bump(current, part)

    escrever_versao(new_version)
    print(new_version)


if __name__ == "__main__":
    main()