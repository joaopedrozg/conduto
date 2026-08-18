"""Renderização do arquivo .env a partir do template padrão do Conduto."""

from pathlib import Path

from jinja2 import Template

from conduto.ui import console, erro, sucesso


def env_render(context, output_dir=None):
    """Renderiza o template do .env no diretório do projeto."""
    package_dir = Path(__file__).resolve().parent.parent
    template_path = package_dir / "templates" / "env" / "env-example.jinja"

    if not template_path.exists():
        console.print(erro("O template não foi encontrado no caminho: {caminho}", caminho=template_path))
        raise FileNotFoundError(f"Template não encontrado: {template_path}")

    template = Template(template_path.read_text(encoding="utf-8"))
    rendered_env = template.render(context)

    # Salva o arquivo final no diretório do projeto
    target_dir = Path(output_dir) if output_dir else Path.cwd()
    env_path = target_dir / ".env"
    env_path.write_text(rendered_env, encoding="utf-8")
    console.print(sucesso("Arquivo .env gerado em: {caminho}", caminho=env_path))
    return env_path
