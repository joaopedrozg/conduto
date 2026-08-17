import typer
import questionary
from pathlib import Path
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.rule import Rule
from rich.prompt import Prompt
from .env_render import env_render
from .gerar_project import setup_uv_environment
from .schemas_render import schemas_render

app = typer.Typer()
console = Console()

custom_style = questionary.Style([
    ('pointer', 'fg:cyan bold'),      # Cor da setinha (ponteiro) e negrito
    ('highlighted', 'fg:green bold'), # Cor do texto do item atualmente selecionado
    ('answer', 'fg:yellow bold'),     # Cor após confirmar a escolha
])

@app.command()
def init(project_name: str = typer.Argument(None, help="Nome do projeto (opcional se já estiver em um projeto uv)")):
    # Detecta se já estamos dentro de um projeto uv (existe pyproject.toml)
    cwd = Path.cwd()
    em_projeto_uv = (cwd / "pyproject.toml").exists()

    # Cria o texto principal
    texto_titulo = Text("Bem vindo ao Conduto!", style="bold cyan")

    if em_projeto_uv:
        project_dir = cwd
        nome_projeto = project_name or cwd.name
        texto_instrucao = Text("\nProjeto uv detectado! Adaptando a estrutura ao projeto atual.", style="dim white")
        mensagem_completa = texto_titulo + texto_instrucao
    else:
        if project_name is None:
            console.print(Text("Informe um nome de projeto: conduto init meu_projeto", style="bold red"))
            raise typer.Exit(code=1)
        project_dir = cwd / project_name
        nome_projeto = project_name
        texto_instrucao = Text("\nVamos criar um novo projeto chamado: ", style="dim white")
        nome_projeto_arte = Text(f" {nome_projeto} ", style="bold white on blue")
        mensagem_completa = texto_titulo + texto_instrucao + nome_projeto_arte

    # Exibe dentro de um painel com bordas
    console.print(Panel(mensagem_completa, border_style="green", expand=False, width=100))

    console.print(Rule(style="dim blue"))

    db_origem = questionary.select(
        "Selecione o SGBD de origem:",
        choices=[
            "1) PostgreSQL",
            "2) MySQL",
            "3) SQLServer"
        ],
        style=custom_style
    ).ask()
    console.print(Rule(style="dim blue"))
    console.print(Text('Credenciais do banco de dados de origem', style="bold yellow"))

    host_db_origem = Prompt.ask("HOST:", default="localhost")
    port_db_origem = Prompt.ask("PORT:", default="5432")
    database_db_origem = Prompt.ask("DATABASE:", default="postgres")
    user_db_origem = Prompt.ask("USERNAME:", default="postgres")
    senha_db_origem = Prompt.ask("PASSWORD:", default="postgres", password=True)

    console.print(Rule(style="dim blue"))

    db_destino = questionary.select(
        "Selecione o SGBD de destino:",
        choices=[
            "1) PostgreSQL",
            "2) MySQL",
            "3) SQLServer"
        ],
        style=custom_style
    ).ask()

    console.print(Rule(style="dim blue"))

    console.print(Text('Credenciais do banco de dados de destino', style="bold yellow"))

    host_db_destino = Prompt.ask("HOST:", default="localhost")
    port_db_destino = Prompt.ask("PORT:", default="5432")
    database_db_destino = Prompt.ask("DATABASE:", default="postgres")
    user_db_destino = Prompt.ask("USERNAME:", default="postgres")
    senha_db_destino = Prompt.ask("PASSWORD:", default="postgres", password=True)

    context = {
        "project_name": nome_projeto,
        "db_destino_tipo": db_destino,
        "origem": {
            "host": host_db_origem,
            "port": port_db_origem,
            "database": database_db_origem,
            "user": user_db_origem,
            "password": senha_db_origem,
        },
        "destino": {
            "host": host_db_destino,
            "port": port_db_destino,
            "database": database_db_destino,
            "user": user_db_destino,
            "password": senha_db_destino,
        }
    }

    if not em_projeto_uv:
        project_dir.mkdir(exist_ok=True)

    env_path = env_render(context, output_dir=project_dir)
    schemas_render(project_dir, context)
    if env_path is not None and env_path.exists():
        setup_uv_environment(project_dir)

@app.command()
def build():
    """
    Build the project.
    """
    typer.echo("Building the project...")
    # Add logic to build the project here


if __name__ == "__main__":
    app()
