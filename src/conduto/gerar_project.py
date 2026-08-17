from pathlib import Path
import subprocess

from rich.console import Console

console = Console()


def setup_uv_environment(base_path: Path):
    # 1. Inicializar projeto uv (caso pyproject.toml nao exista)
    pyproject = base_path / "pyproject.toml"
    if not pyproject.exists():
        console.print("Executando: uv init --no-readme")
        init_result = subprocess.run(
            ["uv", "init", "--no-readme"],
            cwd=base_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if init_result.returncode != 0:
            if init_result.stderr:
                console.print(init_result.stderr, style="bold red")
            raise subprocess.CalledProcessError(init_result.returncode, init_result.args)
    else:
        console.print("Projeto uv detectado, pulando 'uv init'.")

    # 2. Adicionar apenas as dependencias que ainda nao estao declaradas
    dependencies = ["pyyaml", "jinja2", "polars", "dagster"]
    ja_declaradas = []
    if pyproject.exists():
        conteudo = pyproject.read_text(encoding="utf-8")
        for dep in dependencies:
            if dep in conteudo:
                ja_declaradas.append(dep)
    pendentes = [dep for dep in dependencies if dep not in ja_declaradas]

    if not pendentes:
        console.print("Dependencias ja declaradas no projeto, nada a fazer.")
        return

    console.print(f"Adicionando dependencias: {', '.join(pendentes)}")
    cmd = ["uv", "add", *pendentes]
    result = subprocess.run(
        cmd,
        cwd=base_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        if result.stdout:
            console.print(result.stdout)
        if result.stderr:
            console.print(result.stderr, style="bold red")
        raise subprocess.CalledProcessError(result.returncode, cmd)

    console.print("Ambiente configurado com sucesso!")
