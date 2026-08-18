
from jinja2 import Template
from pathlib import Path

from rich import console
from rich.console import Console

console = Console()

def env_render(context, output_dir=None):
    package_dir = Path(__file__).resolve().parent.parent
    template_path = package_dir / "templates" / "env" / "env-example.jinja"

    if not template_path.exists():
        console.print(
            f"[bold red]Erro:[/bold red] O template não foi encontrado no caminho: [yellow]{template_path}[/yellow]")
        raise FileNotFoundError(f"Template não encontrado: {template_path}")


    with open(template_path, "r", encoding="utf-8") as f:
        template_content = f.read()

    template = Template(template_content)
    rendered_env = template.render(context)

    # Salva o arquivo final no diretorio do projeto
    target_dir = Path(output_dir) if output_dir else Path.cwd()
    env_path = target_dir / ".env"
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(rendered_env)
        console.print(f"[bold green]Sucesso:[/bold green] Arquivo .env gerado em: [yellow]{env_path}[/yellow]")

    return env_path
