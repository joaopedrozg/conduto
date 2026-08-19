import platform
import subprocess
from typing import Optional
from pathlib import Path

import typer

from conduto.database.adapters import ADAPTERS, eh_administrador, instalar_driver_sqlserver, testar_conexao
from conduto.database.admin import (
    criar_banco,
    criar_schema,
    listar_bancos,
    listar_schemas,
    schema_padrao_sgbd,
)
from conduto.database.particularidades import PARTICULARIDADES
from conduto.ddl.ddl_render import (
    carregar_tabelas,
    credenciais_destino,
    dividir_statement,
    executar_ddl,
    gerar_ddl,
)
from conduto.docs.docs_server import servir as servir_docs
from conduto.env.env_render import env_render
from conduto.i18n import definir_idioma, detectar_idioma, t
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
from conduto.ui import (
    CORES,
    aplicar_ajustes,
    aviso,
    banner,
    carregando,
    console,
    erro,
    info,
    neutro,
    painel,
    pedir,
    pedir_senha,
    selecionar,
    separador,
    sucesso,
)

aplicar_ajustes()
definir_idioma(detectar_idioma())

app = typer.Typer(help=t("Conduto: o duto que leva seus dados da origem ao destino."))


@app.callback()
def _opcoes_globais(
    lang: Optional[str] = typer.Option(None, "--lang", help=t("Idioma da interface (pt ou en)")),
):
    """Conduto: o duto que leva seus dados da origem ao destino."""
    if lang:
        definir_idioma(lang)


def cancelar():
    console.print(aviso("Operação cancelada."))
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
    """Aguarda o servidor Dagster responder enquanto mostra um spinner moderno.

    Devolve True se o servidor subiu (ou o tempo esgotou com o processo vivo) e
    False se o processo encerrou antes de ficar pronto.
    """
    import time
    import urllib.request

    inicio = time.monotonic()
    with carregando("Aguardando o servidor Dagster iniciar..."):
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
    console.print(separador())
    with carregando("Verificando dagster-webserver..."):
        tem_webserver = _dagster_webserver_instalado(project_dir)
    if not tem_webserver:
        console.print(aviso(
            "dagster-webserver não encontrado — instalando automaticamente..."
        ))
        with carregando("Instalando dagster-webserver..."):
            resultado = subprocess.run(
                ["uv", "add", "dagster-webserver"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        if resultado.returncode != 0:
            console.print(erro(
                "Falha ao instalar dagster-webserver. Rode manualmente: uv add dagster-webserver"
            ))
            raise typer.Exit(code=1)

    if not garantir_codigo_dagster(project_dir):
        console.print(erro(
            "Não foi possível preparar o código Dagster do projeto (main.yml ausente?)."
        ))
        raise typer.Exit(code=1)
    if not garantir_config_dagster(project_dir):
        console.print(erro(
            "Não foi possível configurar o pyproject.toml (bloco [tool.dagster])."
        ))
        raise typer.Exit(code=1)

    console.print(info("Subindo o servidor Dagster..."))
    console.print(neutro("Acesse http://localhost:3000 — pressione Ctrl+C para encerrar."))
    try:
        processo = subprocess.Popen(["uv", "run", "dagster", "dev"], cwd=project_dir)
        if not _aguardar_dagster_responder(processo):
            console.print(erro(
                "O servidor Dagster encerrou antes de ficar pronto. Veja os erros acima."
            ))
            raise typer.Exit(code=1)
        console.print(sucesso(
            "Servidor Dagster no ar em http://localhost:3000 — pressione Ctrl+C para encerrar."
        ))
        processo.wait()
    except KeyboardInterrupt:
        console.print(aviso("Servidor Dagster encerrado."))


def _mostrar_particularidades(adapter) -> None:
    """Exibe as particularidades que o conduto aplica automaticamente no SGBD."""
    particulares = PARTICULARIDADES.get(adapter.tipo)
    if particulares is None or not particulares.notas:
        return
    console.print(painel(
        t("Particularidades do {nome} aplicadas automaticamente", nome=adapter.nome),
        "\n".join(f"  \u2022 {t(nota)}" for nota in particulares.notas),
        cor=CORES["info"],
    ))


def coletar_credenciais(
    rotulo: str, permitir_criar: bool = False, mostrar_particularidades: bool = False
):
    while True:
        console.print(separador())
        sgbd = selecionar("Selecione o SGBD de {rotulo}:", ADAPTERS.keys(), rotulo=rotulo)
        if sgbd is None:
            cancelar()
        adapter = ADAPTERS[sgbd]

        console.print(separador())
        console.print(aviso(
            "Credenciais do servidor de {rotulo} ({nome})",
            rotulo=rotulo,
            nome=adapter.nome,
        ))

        credenciais = {
            "tipo": adapter.tipo,
            "host": pedir("HOST:", padrao=adapter.host_padrao),
            "port": pedir("PORT:", padrao=adapter.porta_padrao),
            "user": pedir("USERNAME:", padrao=adapter.usuario_padrao),
            "password": pedir_senha("PASSWORD:", padrao=adapter.senha_padrao),
        }

        conectado = False
        continuar_mesmo_assim = False
        opcao_digitar = t("Digitar novamente")
        opcao_continuar = t("Continuar mesmo assim")
        opcao_instalar = t("Instalar driver automaticamente")
        while True:
            with carregando("Testando conexão com {nome}...", nome=adapter.nome):
                ok, erro_conexao = testar_conexao(adapter, credenciais)
            if ok:
                conectado = True
                console.print(sucesso(
                    "Conexão com {nome} ({rotulo}) testada com sucesso!",
                    nome=adapter.nome,
                    rotulo=rotulo,
                ))
                break

            console.print(erro(
                "Falha ao conectar em {nome}: {erro}",
                nome=adapter.nome,
                erro=erro_conexao,
            ))
            opcoes = [opcao_digitar, opcao_continuar]
            if adapter.tipo == "sqlserver" and "driver ODBC" in erro_conexao:
                opcoes.insert(0, opcao_instalar)
            escolha = selecionar("O que deseja fazer?", opcoes)

            if escolha is None:
                cancelar()
            if escolha == opcao_digitar:
                break
            if escolha == opcao_continuar:
                continuar_mesmo_assim = True
                break

            if platform.system() == "Windows" and not eh_administrador():
                console.print(painel(
                    "Permissão de administrador",
                    t(
                        "A instalação exige permissão de administrador do Windows.\n"
                        "Uma janela de confirmação (UAC) vai aparecer na frente — clique em \"Sim\".\n"
                        "O download e a instalação rodam em segundo plano, sem abrir janela do PowerShell."
                    ),
                    cor=CORES["aviso"],
                ))
            ok_instalacao, mensagem = instalar_driver_sqlserver()
            if ok_instalacao:
                console.print(sucesso(mensagem))
                console.print(info(
                    "Driver instalado. Testando a conexão novamente com as credenciais já informadas..."
                ))
            else:
                console.print(erro(mensagem))

        if not conectado and not continuar_mesmo_assim:
            continue  # "Digitar novamente": recomeça do SGBD

        if conectado:
            banco = _escolher_banco(adapter, credenciais, rotulo, permitir_criar)
            credenciais["database"] = banco
            if adapter.tipo in ("mysql", "clickhouse", "deltalake"):
                credenciais["schema"] = banco
            else:
                credenciais["schema"] = _escolher_schema(adapter, credenciais, rotulo, permitir_criar)
        else:
            # continua mesmo sem conexão: banco/schema digitados manualmente
            banco = pedir("DATABASE:", padrao=adapter.banco_padrao)
            credenciais["database"] = banco
            credenciais["schema"] = schema_padrao_sgbd(adapter, credenciais)

        if mostrar_particularidades:
            _mostrar_particularidades(adapter)

        return credenciais, adapter


def _escolher_banco(adapter, credenciais: dict, rotulo: str, permitir_criar: bool) -> str:
    opcao_criar = t("Criar novo banco...")
    while True:
        try:
            with carregando("Listando bancos de {nome}...", nome=adapter.nome):
                bancos = listar_bancos(adapter, credenciais)
        except Exception as exc:
            console.print(erro("Falha ao listar bancos: {erro}", erro=exc))
            return pedir("DATABASE:", padrao=adapter.banco_padrao)

        opcoes = list(bancos)
        if permitir_criar:
            opcoes.append(opcao_criar)
        escolha = selecionar("Selecione o banco de dados de {rotulo}:", opcoes, rotulo=rotulo)
        if escolha is None:
            cancelar()
        if escolha != opcao_criar:
            return escolha

        nome = pedir("Nome do novo banco:")
        if not nome or not nome.strip():
            continue
        nome = nome.strip()
        try:
            criar_banco(adapter, credenciais, nome)
            console.print(sucesso("Banco '{nome}' criado com sucesso!", nome=nome))
            return nome
        except Exception as exc:
            console.print(erro("Falha ao criar o banco: {erro}", erro=exc))


def _escolher_schema(adapter, credenciais: dict, rotulo: str, permitir_criar: bool) -> str:
    opcao_criar = t("Criar novo schema...")
    while True:
        try:
            with carregando("Listando schemas de {nome}...", nome=adapter.nome):
                schemas = listar_schemas(adapter, credenciais)
        except Exception as exc:
            console.print(erro("Falha ao listar schemas: {erro}", erro=exc))
            return schema_padrao_sgbd(adapter, credenciais)

        opcoes = list(schemas)
        if permitir_criar:
            opcoes.append(opcao_criar)
        escolha = selecionar("Selecione o schema de {rotulo}:", opcoes, rotulo=rotulo)
        if escolha is None:
            cancelar()
        if escolha != opcao_criar:
            return escolha

        nome = pedir("Nome do novo schema:")
        if not nome or not nome.strip():
            continue
        nome = nome.strip()
        try:
            criar_schema(adapter, credenciais, nome)
            console.print(sucesso("Schema '{nome}' criado com sucesso!", nome=nome))
            return nome
        except Exception as exc:
            console.print(erro("Falha ao criar o schema: {erro}", erro=exc))


@app.command(help=t("Cria/adapta o projeto ELT: .env, main.yml, schemas/ e ambiente uv."))
def init(
    project_name: str = typer.Argument(None, help=t("Nome do projeto (opcional se já estiver em um projeto uv)")),
):
    cwd = Path.cwd()
    em_projeto_uv = (cwd / "pyproject.toml").exists()

    if em_projeto_uv:
        project_dir = cwd
        nome_projeto = project_name or cwd.name
        console.print(banner(
            "Bem vindo ao Conduto!",
            subtitulo="Projeto uv detectado! Adaptando a estrutura ao projeto atual.",
        ))
    else:
        if project_name is None:
            console.print(erro("Informe um nome de projeto: conduto init meu_projeto"))
            raise typer.Exit(code=1)
        project_dir = cwd / project_name
        nome_projeto = project_name
        console.print(banner(
            "Bem vindo ao Conduto!",
            subtitulo="Vamos criar um novo projeto chamado: ",
            nome=nome_projeto,
        ))

    origem, adapter_origem = coletar_credenciais(t("origem"))
    destino, adapter_destino = coletar_credenciais(
        t("destino"), permitir_criar=True, mostrar_particularidades=True
    )

    console.print(separador())
    opcao_auto = t("Gerar automaticamente a partir do banco de origem")
    opcao_manual = t("Configurar manualmente (gerar exemplos)")
    modo_schemas = selecionar("Como deseja configurar os schemas das tabelas?", [opcao_auto, opcao_manual])
    if modo_schemas is None:
        cancelar()
    gerar_automatico = modo_schemas == opcao_auto

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
        except Exception as exc:
            console.print(erro("Falha na geração automática: {erro}", erro=exc))
            gerou = False
        if not gerou:
            console.print(aviso("Gerando os schemas de exemplo (configuração manual)."))
            schemas_render(project_dir, context)
    else:
        schemas_render(project_dir, context)

    console.print(separador())
    opcao_sim_schedules = t("Sim, gerar schedules e código Dagster padrão")
    opcao_nao = t("Não, deixar para depois")
    gerenciar_schedules = selecionar(
        "Deseja gerenciar os schedules automaticamente?",
        [opcao_sim_schedules, opcao_nao],
    )
    if gerenciar_schedules is None:
        cancelar()
    if gerenciar_schedules == opcao_sim_schedules:
        gerar_schedules_automaticos(project_dir, nome_projeto)

    if gerar_automatico and gerou:
        opcao_aplicar = t("Aplicar agora no banco de destino")
        opcao_apenas = t("Apenas gerar o DDL (aplicar depois)")
        aplicar_ddl = selecionar(
            "Deseja aplicar o DDL no banco de destino agora?",
            [opcao_aplicar, opcao_apenas],
        )
        if aplicar_ddl is None:
            cancelar()
        if aplicar_ddl == opcao_aplicar:
            tabelas_ddl = carregar_tabelas(project_dir)
            texto_ddl = gerar_ddl(tabelas_ddl, adapter_destino.tipo)
            comandos = dividir_statement(texto_ddl)
            console.print(separador())
            console.print(info("Aplicando DDL no banco de destino..."))
            try:
                erros = executar_ddl(adapter_destino.tipo, destino, comandos)
            except Exception as exc:
                console.print(erro("Falha ao conectar no banco de destino: {erro}", erro=exc))
                raise typer.Exit(code=1)
            if erros:
                for exc in erros:
                    console.print(erro("  Erro: {erro}", erro=exc))
                raise typer.Exit(code=1)
            console.print(sucesso(
                "{qtd} comando(s) aplicado(s) com sucesso no banco de destino.",
                qtd=len(comandos),
            ))

    if env_path is not None and env_path.exists():
        drivers = {adapter_origem.driver, adapter_destino.driver}
        setup_uv_environment(project_dir, drivers=drivers)

        gerar_comando_dagster(project_dir)

        console.print(separador())
        opcao_subir = t("Sim, subir agora")
        subir_dagster = selecionar("Deseja subir o servidor Dagster agora?", [opcao_subir, opcao_nao])
        if subir_dagster is None:
            cancelar()
        if subir_dagster == opcao_subir:
            _subir_servidor_dagster(project_dir)


@app.command(help=t("Converte os schemas YAML em DDL e cria as tabelas no banco de destino."))
def ddl(
    directory: str = typer.Option(".", "--dir", "-d", help=t("Diretório do projeto conduto (padrão: atual)")),
    output: str = typer.Option(None, "--output", "-o", help=t("Salva o DDL em um arquivo .sql")),
    apply: bool = typer.Option(None, "--apply/--no-apply", help=t("Executa o DDL no banco de destino (sem perguntar)")),
):
    """Converte os schemas YAML em DDL e cria as tabelas no banco de destino."""
    project_dir = Path(directory)
    try:
        credenciais, tipo = credenciais_destino(project_dir)
        tabelas = carregar_tabelas(project_dir)
    except Exception as exc:
        console.print(erro("Falha ao ler o projeto: {erro}", erro=exc))
        raise typer.Exit(code=1)

    if not tabelas:
        console.print(erro("Nenhum schema YAML encontrado para gerar DDL."))
        raise typer.Exit(code=1)

    if apply is None:
        opcao_aplicar = t("Aplicar agora no banco de destino")
        opcao_apenas = t("Apenas gerar o DDL (aplicar depois)")
        escolha = selecionar(
            "Deseja aplicar o DDL no banco de destino agora?",
            [opcao_aplicar, opcao_apenas],
        )
        if escolha is None:
            cancelar()
        aplicar = escolha == opcao_aplicar
    else:
        aplicar = apply

    texto_ddl = gerar_ddl(tabelas, tipo)

    if output:
        destino = Path(output)
        if not destino.is_absolute():
            destino = project_dir / destino
        destino.write_text(texto_ddl, encoding="utf-8")
        console.print(sucesso("DDL salvo em: {destino}", destino=destino))
    else:
        console.print(texto_ddl, markup=False)

    if aplicar:
        console.print(separador())
        with carregando("Aplicando DDL no banco de destino..."):
            comandos = dividir_statement(texto_ddl)
            try:
                erros = executar_ddl(tipo, credenciais, comandos)
            except Exception as exc:
                console.print(erro("Falha ao conectar no banco de destino: {erro}", erro=exc))
                raise typer.Exit(code=1)
        if erros:
            for exc in erros:
                console.print(erro("  Erro: {erro}", erro=exc))
            raise typer.Exit(code=1)
        console.print(sucesso(
            "{qtd} comando(s) aplicado(s) com sucesso no banco de destino.",
            qtd=len(comandos),
        ))


@app.command(help=t("Gera/atualiza os schedules dos schemas e o código Dagster padrão."))
def schedules(
    directory: str = typer.Option(".", "--dir", "-d", help=t("Diretório do projeto conduto (padrão: atual)")),
):
    """Gera/atualiza os schedules dos schemas e o código Dagster padrão."""
    project_dir = Path(directory)
    try:
        project_name = nome_projeto_projeto(project_dir)
    except Exception as exc:
        console.print(erro("Falha ao ler o projeto: {erro}", erro=exc))
        raise typer.Exit(code=1)
    gerar_schedules_automaticos(project_dir, project_name)
    if not garantir_config_dagster(project_dir):
        console.print(erro("Falha ao configurar o pyproject.toml para o dagster dev."))
        raise typer.Exit(code=1)


@app.command(help=t("Sobe o servidor Dagster do projeto."))
def dagster(
    directory: str = typer.Option(".", "--dir", "-d", help=t("Diretório do projeto conduto (padrão: atual)")),
):
    """Sobe o servidor Dagster do projeto."""
    project_dir = Path(directory)
    if not (project_dir / "pyproject.toml").exists():
        console.print(erro("Nenhum projeto uv encontrado em: {projeto}", projeto=project_dir))
        raise typer.Exit(code=1)
    _subir_servidor_dagster(project_dir)


@app.command(help=t("Baixa e instala o ODBC Driver for SQL Server automaticamente."))
def install_sqlserver_driver():
    """Baixa e instala o ODBC Driver for SQL Server automaticamente."""
    with carregando("Instalando o ODBC Driver for SQL Server..."):
        ok, mensagem = instalar_driver_sqlserver()
    if ok:
        console.print(sucesso(mensagem))
    else:
        console.print(erro(mensagem))
        raise typer.Exit(code=1)


@app.command()
def build():
    """
    Build the project.
    """
    console.print(info("Compilando o projeto..."))
    # Add logic to build the project here


@app.command(help=t("Infere as colunas das tabelas do banco de origem nos schemas do projeto."))
def inferir(
    directory: str = typer.Option(".", "--dir", "-d", help=t("Diretório do projeto conduto (padrão: atual)")),
    tabela: Optional[str] = typer.Option(None, "--tabela", "-t", help=t("Nome da tabela para inferir (padrão: todas sem colunas)")),
):
    """Infere as colunas das tabelas do banco de origem nos schemas do projeto."""
    project_dir = Path(directory)
    try:
        inferidas = inferir_colunas(project_dir, tabela)
    except Exception as exc:
        console.print(erro("Falha ao inferir colunas: {erro}", erro=exc))
        raise typer.Exit(code=1)
    if not inferidas:
        raise typer.Exit(code=1)
    console.print(sucesso(
        "{qtd} tabela(s) inferida(s). Rode 'conduto schedules' para gerar os schedules e o código Dagster.",
        qtd=len(inferidas),
    ))


@app.command(help=t("Sobe um servidor web com a documentação da estrutura do projeto."))
def docs(
    directory: str = typer.Option(".", "--dir", "-d", help=t("Diretório do projeto conduto (padrão: atual)")),
    host: str = typer.Option("127.0.0.1", "--host", help=t("Endereço IP em que o servidor escuta")),
    port: int = typer.Option(8000, "--port", "-p", help=t("Porta inicial do servidor (usa a próxima livre se ocupada)")),
    open_browser: bool = typer.Option(True, "--open/--no-open", help=t("Abre o navegador automaticamente")),
):
    """Sobe um servidor web com a documentação da estrutura do projeto."""
    project_dir = Path(directory)
    if not project_dir.exists():
        console.print(erro("Diretório não encontrado: {projeto}", projeto=project_dir))
        raise typer.Exit(code=1)
    try:
        servir_docs(project_dir, host=host, port=port, abrir_navegador=open_browser)
    except RuntimeError as exc:
        console.print(erro("Falha ao subir o servidor de documentação: {erro}", erro=exc))
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
