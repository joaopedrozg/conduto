"""Geração do código Dagster padrão a partir dos schedules dos schemas."""

from pathlib import Path

from jinja2 import Template

from conduto.ui import console, erro, gerado, neutro, t


def gerar_dagster(project_dir: Path, project_name: str) -> Path:
    """Renderiza os templates Dagster no projeto.

    Gera o pacote ``conduto_dagster/`` (etl.py + definitions.py) e o
    ``definitions.py`` na raiz, que o ``dagster dev`` descobre sozinho.
    """
    package_dir = Path(__file__).resolve().parent.parent
    templates_dir = package_dir / "templates" / "dagster"
    target_dir = Path(project_dir)
    context = {"project_name": project_name}

    template_paths = sorted(templates_dir.rglob("*.jinja"))
    if not template_paths:
        console.print(erro("Nenhum template Dagster encontrado."))
        raise FileNotFoundError(t("Nenhum template Dagster em: {diretorio}", diretorio=templates_dir))

    for template_path in template_paths:
        rel = template_path.relative_to(templates_dir)
        output_path = target_dir / rel.with_suffix("")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        template = Template(template_path.read_text(encoding="utf-8"))
        rendered = template.render(context)
        output_path.write_text(rendered, encoding="utf-8")
        console.print(gerado(output_path))

    return target_dir / "definitions.py"

def garantir_config_dagster(project_dir: Path) -> bool:
    """Adiciona o bloco [tool.dagster] ao pyproject.toml, apontando para as definições.

    O 'dagster dev' (versões recentes) exige argumentos ou um bloco [tool.dagster]
    no pyproject.toml para localizar as definições. Devolve True se o bloco está
    presente (já existia ou foi adicionado).
    """
    project_dir = Path(project_dir)
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.exists():
        return False
    if not (project_dir / "conduto_dagster" / "definitions.py").exists():
        return False
    conteudo = pyproject.read_text(encoding="utf-8")
    if "[tool.dagster]" in conteudo:
        return True
    bloco = (
        "\n[tool.dagster]\n"
        "# Módulo com os assets e schedules gerados pelo Conduto\n"
        'module_name = "conduto_dagster.definitions"\n'
    )
    pyproject.write_text(conteudo.rstrip() + "\n" + bloco, encoding="utf-8")
    console.print(neutro("Bloco [tool.dagster] adicionado ao pyproject.toml (dagster dev)."))
    return True
