"""Setup do ambiente uv e geração do comando para subir o Dagster."""

import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from conduto.schedules.dagster_render import garantir_config_dagster

console = Console()


def gerar_comando_dagster(project_dir: Path) -> None:
    """Gera scripts prontos para subir o servidor Dagster do projeto."""
    project_dir = Path(project_dir)
    if not garantir_config_dagster(project_dir):
        console.print(Text(
            "Código Dagster não encontrado — rode 'conduto schedules' para gerar antes de usar os scripts.",
            style="bold yellow",
        ))
    ps1 = project_dir / "run_dagster.ps1"
    ps1.write_text(
        "# Sobe o servidor Dagster do projeto\n"
        "uv run dagster dev\n",
        encoding="utf-8",
    )
    sh = project_dir / "run_dagster.sh"
    sh.write_text(
        "#!/usr/bin/env sh\n"
        "# Sobe o servidor Dagster do projeto\n"
        "set -e\n"
        "uv run dagster dev\n",
        encoding="utf-8",
    )
    try:
        sh.chmod(0o755)
    except OSError:
        pass
    console.print(f"[bold green]Gerado:[/bold green] [yellow]{ps1}[/yellow]")
    console.print(f"[bold green]Gerado:[/bold green] [yellow]{sh}[/yellow]")
    return ps1


def setup_uv_environment(base_path: Path, drivers: list | None = None):
    """Inicializa o projeto uv (sem pasta src) e adiciona as dependências do pipeline."""
    pyproject = base_path / "pyproject.toml"

    # 1. Inicializar projeto uv (caso pyproject.toml nao exista)
    if not pyproject.exists():
        console.print(Text("Configurando o ambiente uv do projeto...", style="bold cyan"))
        with console.status("[bold cyan]Executando uv init (sem pasta src)...[/bold cyan]"):
            init_result = subprocess.run(
                ["uv", "init", "--no-readme", "--bare"],
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
        console.print(Text("Projeto uv detectado, pulando 'uv init'.", style="dim"))

    # 2. Adicionar apenas as dependencias que ainda nao estao declaradas
    dependencies = ["pyyaml", "jinja2", "polars", "dagster", "dagster-webserver"] + list(drivers or [])

    def _nome_dep(dep: str) -> str:
        return dep.split("[")[0].split(">=")[0].strip()

    ja_declaradas = []
    if pyproject.exists():
        conteudo = pyproject.read_text(encoding="utf-8")
        for dep in dependencies:
            if _nome_dep(dep) in conteudo:
                ja_declaradas.append(dep)
    pendentes = [dep for dep in dependencies if dep not in ja_declaradas]

    if not pendentes:
        console.print(Text("Dependências já declaradas no projeto, nada a fazer.", style="dim"))
        return

    console.print(Text(f"Adicionando dependências: {', '.join(pendentes)}", style="bold cyan"))
    with console.status(f"[bold cyan]Instalando {len(pendentes)} dependência(s)...[/bold cyan]"):
        result = subprocess.run(
            ["uv", "add", *pendentes],
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
        raise subprocess.CalledProcessError(result.returncode, ["uv", "add", *pendentes])

    corpo = Text()
    corpo.append("Ambiente configurado com sucesso!", style="bold green")
    corpo.append("\n\n")
    corpo.append("Dependências: ", style="dim")
    corpo.append(", ".join(dependencies), style="yellow")
    console.print(Panel(corpo, border_style="green", title="Setup", expand=False))
