from pathlib import Path
import subprocess

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

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
        console.print("pyproject.toml ja existe, pulando 'uv init'.")

    # 2. Instalar dependencias essenciais para parse e manipulacao
    dependencies = ["pyyaml", "jinja2", "polars", "dagster"]
    cmd = ["uv", "add"] + dependencies

    def _run():
        return subprocess.run(
            cmd,
            cwd=base_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    if console.is_terminal:
        with Progress(
            SpinnerColumn(),
            BarColumn(bar_width=40),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task(
                f"Instalando dependencias: {', '.join(dependencies)}", total=None
            )
            result = _run()
    else:
        console.print(f"Instalando dependencias: {', '.join(dependencies)}")
        result = _run()

    if result.returncode != 0:
        if result.stdout:
            console.print(result.stdout)
        if result.stderr:
            console.print(result.stderr, style="bold red")
        raise subprocess.CalledProcessError(result.returncode, cmd)

    console.print("Ambiente configurado com sucesso!")
