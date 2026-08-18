from pathlib import Path

from jinja2 import Template

from conduto.ui import console, erro, gerado, t


def schemas_render(project_dir, context):
    package_dir = Path(__file__).resolve().parent.parent
    templates_dir = package_dir / "templates" / "schemas"
    target_dir = Path(project_dir)
    schemas_dir = target_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)

    template_paths = sorted(templates_dir.glob("*.jinja"))
    if not template_paths:
        console.print(erro("Nenhum template encontrado em: {diretorio}", diretorio=templates_dir))
        raise FileNotFoundError(t("Nenhum template encontrado em: {diretorio}", diretorio=templates_dir))

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

        console.print(gerado(output_path))

    return target_dir / "main.yml"
