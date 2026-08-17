import platform
import typer
import questionary
from pathlib import Path
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.rule import Rule
from rich.prompt import Prompt
from .adapters import ADAPTERS, eh_administrador, instalar_driver_sqlserver, testar_conexao
from .env_render import env_render
from .gerar_project import setup_uv_environment
from .schemas_render import schemas_render

app = typer.Typer()
console = Console()

custom_style = questionary.Style([
    ('pointer', 'fg:cyan bold'),
    ('highlighted', 'fg:green bold'),
    ('answer', 'fg:yellow bold'),
])


def cancelar():
    console.print(Text("Opera??o cancelada.", style="bold yellow"))
    raise typer.Exit(code=1)


def coletar_credenciais(rotulo: str):
    while True:
        console.print(Rule(style="dim blue"))
        sgbd = questionary.select(
            f"Selecione o SGBD de {rotulo}:",
            choices=list(ADAPTERS.keys()),
            style=custom_style,
        ).ask()
        if sgbd is None:
            cancelar()
        adapter = ADAPTERS[sgbd]

        console.print(Rule(style="dim blue"))
        console.print(Text(f'Credenciais do banco de dados de {rotulo} ({adapter.nome})', style="bold yellow"))

        credenciais = {
            "tipo": adapter.tipo,
            "host": Prompt.ask("HOST:", default=adapter.host_padrao),
            "port": Prompt.ask("PORT:", default=adapter.porta_padrao),
            "database": Prompt.ask("DATABASE:", default=adapter.banco_padrao),
            "user": Prompt.ask("USERNAME:", default=adapter.usuario_padrao),
            "password": questionary.password(
                "PASSWORD:",
                default=adapter.senha_padrao,
                style=custom_style,
            ).ask(),
        }

        while True:
            ok, erro = testar_conexao(adapter, credenciais)
            if ok:
                console.print(Text(f"Conex\u00e3o com {adapter.nome} ({rotulo}) testada com sucesso!", style="bold green"))
                return credenciais, adapter

            console.print(Text(f"Falha ao conectar em {adapter.nome}: {erro}", style="bold red"))
            opcoes = ["Digitar novamente", "Continuar mesmo assim"]
            if adapter.tipo == "sqlserver" and "driver ODBC" in erro:
                opcoes.insert(0, "Instalar driver automaticamente")
            escolha = questionary.select(
                "O que deseja fazer?",
                choices=opcoes,
                style=custom_style,
            ).ask()

            if escolha is None:
                cancelar()
            if escolha == "Digitar novamente":
                break
            if escolha == "Continuar mesmo assim":
                return credenciais, adapter

            if platform.system() == "Windows" and not eh_administrador():
                console.print(Panel(
                    "A instalação exige permissão de administrador do Windows.\n"
                    "Uma janela de confirmação (UAC) vai aparecer na frente — clique em \"Sim\".\n"
                    "O download e a instalação rodam em segundo plano, sem abrir janela do PowerShell.",
                    border_style="yellow",
                    title="Permissão de administrador",
                    expand=False,
                ))
            ok_instalacao, mensagem = instalar_driver_sqlserver()
            if ok_instalacao:
                console.print(Text(mensagem, style="bold green"))
                console.print(Text(
                    "Driver instalado. Testando a conexão novamente com as credenciais já informadas...",
                    style="bold cyan",
                ))
            else:
                console.print(Text(mensagem, style="bold red"))


@app.command()
def init(project_name: str = typer.Argument(None, help="Nome do projeto (opcional se j\u00e1 estiver em um projeto uv)")):
    cwd = Path.cwd()
    em_projeto_uv = (cwd / "pyproject.toml").exists()

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

    console.print(Panel(mensagem_completa, border_style="green", expand=False, width=100))

    origem, adapter_origem = coletar_credenciais("origem")
    destino, adapter_destino = coletar_credenciais("destino")

    context = {
        "project_name": nome_projeto,
        "origem": origem,
        "destino": destino,
    }

    if not em_projeto_uv:
        project_dir.mkdir(exist_ok=True)

    env_path = env_render(context, output_dir=project_dir)
    schemas_render(project_dir, context)
    if env_path is not None and env_path.exists():
        drivers = {adapter_origem.driver, adapter_destino.driver}
        setup_uv_environment(project_dir, drivers=drivers)


@app.command()
def install_sqlserver_driver():
    """Baixa e instala o ODBC Driver for SQL Server automaticamente."""
    console.print(Text("Instalando o ODBC Driver for SQL Server...", style="bold yellow"))
    ok, mensagem = instalar_driver_sqlserver()
    if ok:
        console.print(Text(mensagem, style="bold green"))
    else:
        console.print(Text(mensagem, style="bold red"))
        raise typer.Exit(code=1)

@app.command()
def build():
    """
    Build the project.
    """
    typer.echo("Building the project...")
    # Add logic to build the project here


if __name__ == "__main__":
    app()
