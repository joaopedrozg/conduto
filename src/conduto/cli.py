import platform
import subprocess
import typer
import questionary
from typing import Optional
from pathlib import Path
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.rule import Rule
from rich.prompt import Prompt
from conduto.database.adapters import ADAPTERS, eh_administrador, instalar_driver_sqlserver, testar_conexao
from conduto.database.admin import (
    criar_banco,
    criar_schema,
    listar_bancos,
    listar_schemas,
    schema_padrao_sgbd,
)
from conduto.ddl.ddl_render import (
    carregar_tabelas,
    credenciais_destino,
    dividir_statement,
    executar_ddl,
    gerar_ddl,
)
from conduto.env.env_render import env_render
from conduto.project_base.gerar_project import gerar_comando_dagster, setup_uv_environment
from conduto.schemas.schemas_auto import gerar_schemas_automaticos
from conduto.schemas.schemas_inferir import inferir_colunas
from conduto.schemas.schemas_render import schemas_render
from conduto.schedules.dagster_render import garantir_config_dagster
from conduto.schedules.schedules_auto import (
    garantir_codigo_dagster,
    gerar_schedules_automaticos,
    nome_projeto as nome_projeto_projeto,
)
from conduto.ui import aplicar_ajustes

aplicar_ajustes()

app = typer.Typer()
console = Console()

custom_style = questionary.Style([
    ('pointer', 'fg:cyan bold'),
    ('highlighted', 'fg:green bold'),
    ('answer', 'fg:yellow bold'),
])


def cancelar():
    console.print(Text("Operação cancelada.", style="bold yellow"))
    raise typer.Exit(code=1)


def _dagster_webserver_instalado(project_dir: Path) -> bool:
    """Verifica se o dagster-webserver (exigido pelo 'dagster dev') está disponível."""
    pyproject = project_dir / "pyproject.toml"
    if pyproject.exists() and "dagster-webserver" in pyproject.read_text(encoding="utf-8"):
        return True
    try:
        resultado = subprocess.run(
            ["uv", "run", "python", "-c", "import dagster_webserver"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        return resultado.returncode == 0
    except Exception:
        return False


def _aguardar_dagster_responder(processo, url="http://localhost:3000", timeout=240):
    """Aguarda o servidor Dagster responder enquanto mostra um status animado.

    Devolve True se o servidor subiu (ou o tempo esgotou com o processo vivo) e
    False se o processo encerrou antes de ficar pronto.
    """
    import time
    import urllib.request

    inicio = time.monotonic()
    with console.status("[bold cyan]Aguardando o servidor Dagster iniciar...[/bold cyan]"):
        while time.monotonic() - inicio < timeout:
            if processo.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(url, timeout=1) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                pass
            time.sleep(0.5)
    return True


def _subir_servidor_dagster(project_dir: Path):
    console.print(Rule(style="dim blue"))
    with console.status("[bold cyan]Verificando dagster-webserver...[/bold cyan]"):
        tem_webserver = _dagster_webserver_instalado(project_dir)
    if not tem_webserver:
        console.print(Text(
            "dagster-webserver não encontrado — instalando automaticamente...",
            style="bold yellow",
        ))
        with console.status("[bold yellow]uv add dagster-webserver...[/bold yellow]"):
            resultado = subprocess.run(
                ["uv", "add", "dagster-webserver"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        if resultado.returncode != 0:
            console.print(Text(
                "Falha ao instalar dagster-webserver. Rode manualmente: uv add dagster-webserver",
                style="bold red",
            ))
            raise typer.Exit(code=1)

    if not garantir_codigo_dagster(project_dir):
        console.print(Text(
            "Não foi possível preparar o código Dagster do projeto (main.yml ausente?).",
            style="bold red",
        ))
        raise typer.Exit(code=1)
    if not garantir_config_dagster(project_dir):
        console.print(Text(
            "Não foi possível configurar o pyproject.toml (bloco [tool.dagster]).",
            style="bold red",
        ))
        raise typer.Exit(code=1)

    console.print(Text("Subindo o servidor Dagster...", style="bold cyan"))
    console.print(Text("Acesse http://localhost:3000 — pressione Ctrl+C para encerrar.", style="dim white"))
    try:
        processo = subprocess.Popen(["uv", "run", "dagster", "dev"], cwd=project_dir)
        if not _aguardar_dagster_responder(processo):
            console.print(Text(
                "O servidor Dagster encerrou antes de ficar pronto. Veja os erros acima.",
                style="bold red",
            ))
            raise typer.Exit(code=1)
        console.print(Text(
            "Servidor Dagster no ar em http://localhost:3000 — pressione Ctrl+C para encerrar.",
            style="bold green",
        ))
        processo.wait()
    except KeyboardInterrupt:
        console.print(Text("Servidor Dagster encerrado.", style="bold yellow"))


def coletar_credenciais(rotulo: str, permitir_criar: bool = False):
    while True:
        console.print(Rule(style="dim blue"))
        sgbd = questionary.select(
            f"Selecione o SGBD de {rotulo}:",
            choices=list(ADAPTERS.keys()),
            style=custom_style,
            qmark="",
        ).ask()
        if sgbd is None:
            cancelar()
        adapter = ADAPTERS[sgbd]

        console.print(Rule(style="dim blue"))
        console.print(Text(f'Credenciais do servidor de {rotulo} ({adapter.nome})', style="bold yellow"))

        credenciais = {
            "tipo": adapter.tipo,
            "host": Prompt.ask("HOST:", default=adapter.host_padrao),
            "port": Prompt.ask("PORT:", default=adapter.porta_padrao),
            "user": Prompt.ask("USERNAME:", default=adapter.usuario_padrao),
            "password": questionary.password(
                "PASSWORD:",
                default=adapter.senha_padrao,
                style=custom_style,
                qmark="",
            ).ask(),
        }

        conectado = False
        continuar_mesmo_assim = False
        while True:
            ok, erro = testar_conexao(adapter, credenciais)
            if ok:
                conectado = True
                console.print(Text(f"Conex\u00e3o com {adapter.nome} ({rotulo}) testada com sucesso!", style="bold green"))
                break

            console.print(Text(f"Falha ao conectar em {adapter.nome}: {erro}", style="bold red"))
            opcoes = ["Digitar novamente", "Continuar mesmo assim"]
            if adapter.tipo == "sqlserver" and "driver ODBC" in erro:
                opcoes.insert(0, "Instalar driver automaticamente")
            escolha = questionary.select(
                "O que deseja fazer?",
                choices=opcoes,
                style=custom_style,
                qmark="",
            ).ask()

            if escolha is None:
                cancelar()
            if escolha == "Digitar novamente":
                break
            if escolha == "Continuar mesmo assim":
                continuar_mesmo_assim = True
                break

            if platform.system() == "Windows" and not eh_administrador():
                console.print(Panel(
                    "A instala\u00e7\u00e3o exige permiss\u00e3o de administrador do Windows.\n"
                    "Uma janela de confirma\u00e7\u00e3o (UAC) vai aparecer na frente \u2014 clique em \"Sim\".\n"
                    "O download e a instala\u00e7\u00e3o rodam em segundo plano, sem abrir janela do PowerShell.",
                    border_style="yellow",
                    title="Permiss\u00e3o de administrador",
                    expand=False,
                ))
            ok_instalacao, mensagem = instalar_driver_sqlserver()
            if ok_instalacao:
                console.print(Text(mensagem, style="bold green"))
                console.print(Text(
                    "Driver instalado. Testando a conex\u00e3o novamente com as credenciais j\u00e1 informadas...",
                    style="bold cyan",
                ))
            else:
                console.print(Text(mensagem, style="bold red"))

        if not conectado and not continuar_mesmo_assim:
            continue  # "Digitar novamente": recome\u00e7a do SGBD

        if conectado:
            banco = _escolher_banco(adapter, credenciais, rotulo, permitir_criar)
            credenciais["database"] = banco
            if adapter.tipo == "mysql":
                credenciais["schema"] = banco
            else:
                credenciais["schema"] = _escolher_schema(adapter, credenciais, rotulo, permitir_criar)
        else:
            # continua mesmo sem conexão: banco/schema digitados manualmente
            banco = Prompt.ask("DATABASE:", default=adapter.banco_padrao)
            credenciais["database"] = banco
            credenciais["schema"] = schema_padrao_sgbd(adapter, credenciais)

        return credenciais, adapter


def _escolher_banco(adapter, credenciais: dict, rotulo: str, permitir_criar: bool) -> str:
    while True:
        try:
            bancos = listar_bancos(adapter, credenciais)
        except Exception as erro:
            console.print(Text(f"Falha ao listar bancos: {erro}", style="bold red"))
            return Prompt.ask("DATABASE:", default=adapter.banco_padrao)

        opcoes = list(bancos)
        if permitir_criar:
            opcoes.append("Criar novo banco...")
        escolha = questionary.select(
            f"Selecione o banco de dados de {rotulo}:",
            choices=opcoes,
            style=custom_style,
            qmark="",
        ).ask()
        if escolha is None:
            cancelar()
        if escolha != "Criar novo banco...":
            return escolha

        nome = Prompt.ask("Nome do novo banco:")
        if not nome or not nome.strip():
            continue
        nome = nome.strip()
        try:
            criar_banco(adapter, credenciais, nome)
            console.print(Text(f"Banco '{nome}' criado com sucesso!", style="bold green"))
            return nome
        except Exception as erro:
            console.print(Text(f"Falha ao criar o banco: {erro}", style="bold red"))


def _escolher_schema(adapter, credenciais: dict, rotulo: str, permitir_criar: bool) -> str:
    while True:
        try:
            schemas = listar_schemas(adapter, credenciais)
        except Exception as erro:
            console.print(Text(f"Falha ao listar schemas: {erro}", style="bold red"))
            return schema_padrao_sgbd(adapter, credenciais)

        opcoes = list(schemas)
        if permitir_criar:
            opcoes.append("Criar novo schema...")
        escolha = questionary.select(
            f"Selecione o schema de {rotulo}:",
            choices=opcoes,
            style=custom_style,
            qmark="",
        ).ask()
        if escolha is None:
            cancelar()
        if escolha != "Criar novo schema...":
            return escolha

        nome = Prompt.ask("Nome do novo schema:")
        if not nome or not nome.strip():
            continue
        nome = nome.strip()
        try:
            criar_schema(adapter, credenciais, nome)
            console.print(Text(f"Schema '{nome}' criado com sucesso!", style="bold green"))
            return nome
        except Exception as erro:
            console.print(Text(f"Falha ao criar o schema: {erro}", style="bold red"))


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
    destino, adapter_destino = coletar_credenciais("destino", permitir_criar=True)

    console.print(Rule(style="dim blue"))
    modo_schemas = questionary.select(
        "Como deseja configurar os schemas das tabelas?",
        choices=[
            "Gerar automaticamente a partir do banco de origem",
            "Configurar manualmente (gerar exemplos)",
        ],
        style=custom_style,
        qmark="",
    ).ask()
    if modo_schemas is None:
        cancelar()
    gerar_automatico = modo_schemas.startswith("Gerar automaticamente")

    context = {
        "project_name": nome_projeto,
        "origem": origem,
        "destino": destino,
    }

    if not em_projeto_uv:
        project_dir.mkdir(exist_ok=True)

    env_path = env_render(context, output_dir=project_dir)
    if gerar_automatico:
        try:
            gerou = gerar_schemas_automaticos(
                project_dir, nome_projeto, adapter_origem, origem, destino["schema"]
            )
        except Exception as erro:
            console.print(Text(f"Falha na geração automática: {erro}", style="bold red"))
            gerou = False
        if not gerou:
            console.print(Text("Gerando os schemas de exemplo (configuração manual).", style="bold yellow"))
            schemas_render(project_dir, context)
    else:
        schemas_render(project_dir, context)

    console.print(Rule(style="dim blue"))
    gerenciar_schedules = questionary.select(
        "Deseja gerenciar os schedules automaticamente?",
        choices=[
            "Sim, gerar schedules e código Dagster padrão",
            "Não, deixar para depois",
        ],
        style=custom_style,
        qmark="",
    ).ask()
    if gerenciar_schedules is None:
        cancelar()
    if gerenciar_schedules.startswith("Sim"):
        gerar_schedules_automaticos(project_dir, nome_projeto)

    if gerar_automatico and gerou:
        aplicar_ddl = questionary.select(
            "Deseja aplicar o DDL no banco de destino agora?",
            choices=[
                "Aplicar agora no banco de destino",
                "Apenas gerar o DDL (aplicar depois)",
            ],
            style=custom_style,
            qmark="",
        ).ask()
        if aplicar_ddl is None:
            cancelar()
        if aplicar_ddl.startswith("Aplicar"):
            tabelas_ddl = carregar_tabelas(project_dir)
            texto_ddl = gerar_ddl(tabelas_ddl, adapter_destino.tipo)
            comandos = dividir_statement(texto_ddl)
            console.print(Rule(style="dim blue"))
            console.print(Text("Aplicando DDL no banco de destino...", style="bold cyan"))
            try:
                erros = executar_ddl(adapter_destino.tipo, destino, comandos)
            except Exception as erro:
                console.print(Text(f"Falha ao conectar no banco de destino: {erro}", style="bold red"))
                raise typer.Exit(code=1)
            if erros:
                for erro in erros:
                    console.print(Text(f"  Erro: {erro}", style="bold red"))
                raise typer.Exit(code=1)
            console.print(Text(
                f"{len(comandos)} comando(s) aplicado(s) com sucesso no banco de destino.",
                style="bold green",
            ))

    if env_path is not None and env_path.exists():
        drivers = {adapter_origem.driver, adapter_destino.driver}
        setup_uv_environment(project_dir, drivers=drivers)

        gerar_comando_dagster(project_dir)

        console.print(Rule(style="dim blue"))
        subir_dagster = questionary.select(
            "Deseja subir o servidor Dagster agora?",
            choices=[
                "Sim, subir agora",
                "Não, depois",
            ],
            style=custom_style,
            qmark="",
        ).ask()
        if subir_dagster is None:
            cancelar()
        if subir_dagster.startswith("Sim"):
            _subir_servidor_dagster(project_dir)


@app.command()
def ddl(
    directory: str = typer.Option(".", "--dir", "-d", help="Diretório do projeto conduto (padrão: atual)"),
    output: str = typer.Option(None, "--output", "-o", help="Salva o DDL em um arquivo .sql"),
    apply: bool = typer.Option(None, "--apply/--no-apply", help="Executa o DDL no banco de destino (sem perguntar)"),
):
    """Converte os schemas YAML em DDL e cria as tabelas no banco de destino."""
    project_dir = Path(directory)
    try:
        credenciais, tipo = credenciais_destino(project_dir)
        tabelas = carregar_tabelas(project_dir)
    except Exception as erro:
        console.print(Text(f"Falha ao ler o projeto: {erro}", style="bold red"))
        raise typer.Exit(code=1)

    if not tabelas:
        console.print(Text("Nenhum schema YAML encontrado para gerar DDL.", style="bold red"))
        raise typer.Exit(code=1)

    if apply is None:
        escolha = questionary.select(
            "Deseja aplicar o DDL no banco de destino agora?",
            choices=[
                "Aplicar agora no banco de destino",
                "Apenas gerar o DDL (aplicar depois)",
            ],
            style=custom_style,
            qmark="",
        ).ask()
        if escolha is None:
            cancelar()
        aplicar = escolha.startswith("Aplicar")
    else:
        aplicar = apply

    texto_ddl = gerar_ddl(tabelas, tipo)

    if output:
        destino = Path(output)
        if not destino.is_absolute():
            destino = project_dir / destino
        destino.write_text(texto_ddl, encoding="utf-8")
        console.print(Text(f"DDL salvo em: {destino}", style="bold green"))
    else:
        console.print(texto_ddl, markup=False)

    if aplicar:
        console.print(Rule(style="dim blue"))
        console.print(Text("Aplicando DDL no banco de destino...", style="bold cyan"))
        comandos = dividir_statement(texto_ddl)
        try:
            erros = executar_ddl(tipo, credenciais, comandos)
        except Exception as erro:
            console.print(Text(f"Falha ao conectar no banco de destino: {erro}", style="bold red"))
            raise typer.Exit(code=1)
        if erros:
            for erro in erros:
                console.print(Text(f"  Erro: {erro}", style="bold red"))
            raise typer.Exit(code=1)
        console.print(Text(
            f"{len(comandos)} comando(s) aplicado(s) com sucesso no banco de destino.",
            style="bold green",
        ))


@app.command()
def schedules(
    directory: str = typer.Option(".", "--dir", "-d", help="Diretório do projeto conduto (padrão: atual)"),
):
    """Gera/atualiza os schedules dos schemas e o código Dagster padrão."""
    project_dir = Path(directory)
    try:
        project_name = nome_projeto_projeto(project_dir)
    except Exception as erro:
        console.print(Text(f"Falha ao ler o projeto: {erro}", style="bold red"))
        raise typer.Exit(code=1)
    gerar_schedules_automaticos(project_dir, project_name)
    if not garantir_config_dagster(project_dir):
        console.print(Text("Falha ao configurar o pyproject.toml para o dagster dev.", style="bold red"))
        raise typer.Exit(code=1)


@app.command()
def dagster(
    directory: str = typer.Option(".", "--dir", "-d", help="Diretório do projeto conduto (padrão: atual)"),
):
    """Sobe o servidor Dagster do projeto."""
    project_dir = Path(directory)
    if not (project_dir / "pyproject.toml").exists():
        console.print(Text(f"Nenhum projeto uv encontrado em: {project_dir}", style="bold red"))
        raise typer.Exit(code=1)
    _subir_servidor_dagster(project_dir)


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


@app.command()
def inferir(
    directory: str = typer.Option(".", "--dir", "-d", help="Diretório do projeto conduto (padrão: atual)"),
    tabela: Optional[str] = typer.Option(None, "--tabela", "-t", help="Nome da tabela para inferir (padrão: todas sem colunas)"),
):
    """Infere as colunas das tabelas do banco de origem nos schemas do projeto."""
    project_dir = Path(directory)
    try:
        inferidas = inferir_colunas(project_dir, tabela)
    except Exception as erro:
        console.print(Text(f"Falha ao inferir colunas: {erro}", style="bold red"))
        raise typer.Exit(code=1)
    if not inferidas:
        raise typer.Exit(code=1)
    console.print(Text(
        f"{len(inferidas)} tabela(s) inferida(s). Rode 'conduto schedules' para gerar os schedules e o código Dagster.",
        style="bold green",
    ))


if __name__ == "__main__":
    app()
