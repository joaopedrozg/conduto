"""Setup do ambiente uv e geração do comando para subir o Dagster."""

import subprocess
from pathlib import Path

from rich.text import Text

from conduto.schedules.dagster_render import garantir_config_dagster
from conduto.ui import (
    CORES,
    aviso,
    carregando,
    console,
    erro,
    gerado,
    info,
    neutro,
    painel,
    t,
)


def gerar_comando_dagster(project_dir: Path):
    """Gera scripts prontos para subir o servidor Dagster do projeto."""
    project_dir = Path(project_dir)
    if not garantir_config_dagster(project_dir):
        console.print(aviso(
            "Código Dagster não encontrado — rode 'conduto schedules' para gerar antes de usar os scripts."
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
    console.print(gerado(ps1))
    console.print(gerado(sh))
    return ps1


def setup_uv_environment(base_path: Path, drivers: list | None = None):
    """Inicializa o projeto uv (sem pasta src) e adiciona as dependências do pipeline."""
    pyproject = base_path / "pyproject.toml"

    # 1. Inicializar projeto uv (caso pyproject.toml não exista)
    if not pyproject.exists():
        console.print(info("Configurando o ambiente uv do projeto..."))
        with carregando("Executando uv init (sem pasta src)..."):
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
                console.print(erro(init_result.stderr))
            raise subprocess.CalledProcessError(init_result.returncode, init_result.args)
    else:
        console.print(neutro("Projeto uv detectado, pulando 'uv init'."))

    # 2. Adicionar apenas as dependências que ainda não estão declaradas
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
        console.print(neutro("Dependências já declaradas no projeto, nada a fazer."))
        return

    console.print(info("Adicionando dependências: {lista}", lista=", ".join(pendentes)))
    with carregando("Instalando {qtd} dependência(s)...", qtd=len(pendentes)):
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
            console.print(erro(result.stderr))
        raise subprocess.CalledProcessError(result.returncode, ["uv", "add", *pendentes])

    corpo = Text()
    corpo.append(t("Ambiente configurado com sucesso!"), style=CORES["sucesso"])
    corpo.append("\n\n")
    corpo.append(t("Dependências: "), style=CORES["neutro"])
    corpo.append(", ".join(dependencies), style=CORES["detalhe"])
    console.print(painel("Setup", corpo))
