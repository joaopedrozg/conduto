"""Geração automática dos schemas YAML e do main.yml a partir do banco de origem."""

from collections import deque
from pathlib import Path
from typing import Any, Dict, List

import questionary
import typer

from conduto.database.adapters import Adapter
from conduto.database.introspect import abrir_conexao, descrever_tabela, listar_tabelas
from conduto.ui import aviso, carregando, console, erro, gerado, info, multi_selecionar, progresso

custom_style = questionary.Style([
    # Fundo preto e apenas a bolinha das opções marcadas em verde (noreverse)
    ('', 'bg:black'),
    ('pointer', 'fg:cyan bold noreverse bg:black'),
    ('highlighted', 'fg:white noreverse bg:black'),
    ('selected', 'fg:green bold noreverse bg:black'),
    ('text', 'fg:white noreverse bg:black'),
    ('instruction', 'fg:white dim noreverse bg:black'),
    ('answer', 'fg:yellow bold noreverse bg:black'),
])


def gerar_schemas_automaticos(
    project_dir, project_name: str, adapter: Adapter, credenciais: dict, schema_destino: str
) -> bool:
    """Introspecção do banco de origem + geração dos schemas e do main.yml.

    Retorna True se os schemas foram gerados automaticamente, False caso contrário.
    Os YAMLs gerados apontam para o schema de destino já escolhido/criado pelo usuário.
    """
    with carregando("Lendo tabelas do banco de origem..."):
        tabelas = listar_tabelas(adapter, credenciais)

    if not tabelas:
        console.print(aviso("Nenhuma tabela encontrada no banco de origem."))
        return False

    console.print(info("{qtd} tabela(s) encontrada(s).", qtd=len(tabelas)))
    escolhas = [
        questionary.Choice(
            # Titulo em texto puro: necessario para o filtro de busca funcionar
            title=f"{t['schema']}.{t['table']}" if t["schema"] else t["table"],
            value={"schema": t["schema"], "table": t["table"]},
        )
        for t in tabelas
    ]
    selecionadas = multi_selecionar(
        "Selecione as tabelas para gerar os schemas:",
        escolhas,
        instrucao=(
            "(setas para navegar, espaco para marcar/desmarcar, "
            "digite para filtrar, backspace limpa a busca, enter para confirmar)"
        ),
        style=custom_style,
        use_search_filter=True,
        use_jk_keys=False,
    )
    if selecionadas is None:
        console.print(aviso("Operação cancelada."))
        raise typer.Exit(code=1)

    if not selecionadas:
        console.print(aviso("Nenhuma tabela selecionada."))
        return False

    descricoes: List[Dict[str, Any]] = []
    conexao = abrir_conexao(adapter, credenciais)
    try:
        with progresso(len(selecionadas), "Lendo colunas das tabelas selecionadas...") as (barra, tarefa):
            for sel in selecionadas:
                try:
                    descricao = descrever_tabela(
                        adapter, credenciais, sel["schema"], sel["table"], conexao=conexao
                    )
                except Exception as exc:
                    console.print(erro(
                        "Falha ao ler a tabela {tabela}: {erro}",
                        tabela=sel["table"],
                        erro=exc,
                    ))
                    barra.advance(tarefa)
                    continue
                if not descricao["columns"]:
                    console.print(aviso(
                        "Atenção: tabela {tabela} não retornou colunas; pulando.",
                        tabela=sel["table"],
                    ))
                    barra.advance(tarefa)
                    continue
                descricao["schema"] = schema_destino
                descricoes.append(descricao)
                barra.advance(tarefa)
    finally:
        if conexao is not None:
            conexao.close()

    if not descricoes:
        console.print(erro("Não foi possível gerar schemas a partir do banco de origem."))
        return False

    gerar_arquivos(Path(project_dir), project_name, descricoes)
    return True


def gerar_arquivos(project_dir: Path, project_name: str, descricoes: List[Dict[str, Any]]) -> Path:
    """Escreve os schemas em schemas/ e o main.yml na ordem de dependência."""
    descricoes = _ordenar_por_dependencia(descricoes)

    schemas_dir = project_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)

    for descricao in descricoes:
        caminho = schemas_dir / f"{descricao['table']}.yml"
        caminho.write_text(_yaml_schema(descricao), encoding="utf-8")
        console.print(gerado(caminho))

    main_path = project_dir / "main.yml"
    main_path.write_text(
        _yaml_main(project_name, [d["table"] for d in descricoes]), encoding="utf-8"
    )
    console.print(gerado(main_path))
    return main_path


def _yaml_schema(tabela: Dict[str, Any]) -> str:
    linhas = [
        f"table: {tabela['table']}",
        f"schema: {tabela['schema']}",
        f"description: \"Tabela {tabela['table']}\"",
    ]
    for chave in ("engine", "order_by", "partition_by"):
        if tabela.get(chave):
            linhas.append(f"{chave}: {_valor_yaml_seguro(str(tabela[chave]))}")
    linhas.append("columns:")
    for coluna in tabela["columns"]:
        linhas.append(f"  - name: {coluna['name']}")
        linhas.append(f"    type: {coluna['type']}")
        if coluna.get("primary_key"):
            linhas.append("    primary_key: true")
        linhas.append(f"    nullable: {'true' if coluna.get('nullable', True) else 'false'}")
        if coluna.get("unique"):
            linhas.append("    unique: true")
        if coluna.get("default"):
            linhas.append(f"    default: {_valor_yaml_seguro(coluna['default'])}")
        if coluna.get("foreign_key"):
            linhas.append(f"    foreign_key: {coluna['foreign_key']}")
    return "\n".join(linhas) + "\n"


def _yaml_main(project_name: str, tabelas: List[str]) -> str:
    linhas = [
        'version: "1.0"',
        f"project: {project_name}",
        "",
        "# Tabelas na ordem de dependência (pais antes de filhos)",
        "tables:",
    ]
    for tabela in tabelas:
        linhas.append(f'  - path: "schemas/{tabela}.yml"')
    return "\n".join(linhas) + "\n"


def _valor_yaml_seguro(valor: str) -> str:
    """Mantém valores simples sem aspas e protege os que quebrariam o YAML."""
    if not valor:
        return valor
    if valor[0] in "\"'":
        return valor
    if (": " in valor or " #" in valor or valor[0] in "-?:,[]{}#&*!|>'\"%@`"):
        return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return valor


def _ordenar_por_dependencia(tabelas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ordena as tabelas para que dependências (FK) venham antes dos dependentes."""
    nomes = [t["table"] for t in tabelas]
    pos = {nome: i for i, nome in enumerate(nomes)}

    grau = {nome: 0 for nome in nomes}
    filhos = {nome: [] for nome in nomes}
    for tabela in tabelas:
        for coluna in tabela["columns"]:
            fk = coluna.get("foreign_key")
            if not fk:
                continue
            ref = fk.split("(", 1)[0].rsplit(".", 1)[-1]
            if ref not in pos or ref == tabela["table"]:
                continue
            grau[tabela["table"]] += 1
            filhos[ref].append(tabela["table"])

    fila = deque(nome for nome in nomes if grau[nome] == 0)
    ordenados = []
    while fila:
        nome = fila.popleft()
        ordenados.append(nome)
        for filho in filhos[nome]:
            grau[filho] -= 1
            if grau[filho] == 0:
                fila.append(filho)

    if len(ordenados) != len(nomes):
        # Ciclo ou dependência fora do conjunto: mantém a ordem original.
        return tabelas

    por_nome = {t["table"]: t for t in tabelas}
    return [por_nome[nome] for nome in ordenados]
