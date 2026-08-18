"""Bump the package version (semver) in pyproject.toml and uv.lock.

Usage: python bump_version.py [patch|minor|major]
Prints the new version to stdout.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def bump(version: str, part: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        sys.exit(f"Versao atual nao e semver simples (esperado X.Y.Z): {version!r}")
    major, minor, patch = (int(group) for group in match.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    sys.exit(f"Tipo de bump invalido: {part!r} (use patch, minor ou major)")


def main() -> None:
    part = sys.argv[1] if len(sys.argv) > 1 else "patch"

    pyproject = ROOT / "pyproject.toml"
    lock = ROOT / "uv.lock"

    project_text = pyproject.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(r'(?m)^version = "([^"]+)"', project_text)
    if not match:
        sys.exit("Nao encontrei 'version' no pyproject.toml")
    new_version = bump(match.group(1), part)

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
    lock_pattern = re.compile(
        r'(?m)^(\[\[package\]\]\nname = "conduto"\n)version = "[^"]+"'
    )
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

    print(new_version)


if __name__ == "__main__":
    main()
