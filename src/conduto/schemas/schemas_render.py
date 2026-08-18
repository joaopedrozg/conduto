from pathlib import Path

from jinja2 import Template
from rich.console import Console

console = Console()


def schemas_render(project_dir, context):
    package_dir = Path(__file__).resolve().parent.parent
    templates_dir = package_dir / "templates" / "schemas"
    target_dir = Path(project_dir)
    schemas_dir = target_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)

    template_paths = sorted(templates_dir.glob("*.jinja"))
    if not template_paths:
        console.print(
            f"[bold red]Erro:[/bold red] Nenhum template encontrado em: [yellow]{templates_dir}[/yellow]"
        )
        raise FileNotFoundError(f"Nenhum template encontrado em: {templates_dir}")

    for template_path in template_paths:
        output_name = template_path.name.removesuffix("-example.yml.jinja") + ".yml"
        output_path = (
            target_dir / output_name
            if output_name == "main.yml"
            else schemas_dir / output_name
        )

        with open(template_path, "r", encoding="utf-8") as f:
            template = Template(f.read())
        rendered = template.render(context)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(rendered)

        console.print(f"[bold green]Gerado:[/bold green] [yellow]{output_path}[/yellow]")

    return target_dir / "main.yml"
