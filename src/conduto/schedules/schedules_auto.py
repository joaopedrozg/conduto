"""Geração automática de schedules: inferência incremental e chave ``schedule`` nos schemas."""

from pathlib import Path
from typing import Any
from typing import Any, Dict, List, Optional

import yaml
from rich.console import Console
from rich.table import Table
from rich.text import Text

from conduto.schedules.dagster_render import gerar_dagster

console = Console()

CRON_PADRAO = "0 * * * *"

# Nomes priorizados para inferir a coluna de atualização incremental (watermark).
NOMES_ATUALIZACAO = (
    "updated_at", "updatedat", "updated", "update_timestamp", "last_updated",
    "lastupdate", "last_modified", "modified_at", "modified",
    "atualizado_em", "alterado_em", "data_atualizacao", "data_alteracao",
    "ultima_atualizacao", "dt_atualizacao", "dt_update",
)

NOMES_CRIACAO = (
    "created_at", "created", "create_timestamp", "inserted_at", "inserted",
    "criado_em", "data_criacao", "createddate", "dt_criacao", "data_inclusao",
    "data_pedido", "data", "date",
)

TIPOS_TEMPORAIS = ("timestamp", "timestamptz", "date", "time", "timetz", "datetime")


def inferir_coluna_incremental(colunas: List[Dict[str, Any]]) -> Optional[str]:
    """Tenta inferir a coluna usada como marcador de água (watermark).

    Prioridade: nomes de atualização, depois nomes de criação e, por fim,
    qualquer coluna de tipo temporal.
    """
    por_nome = {c["name"].lower(): c["name"] for c in colunas}
    for candidato in (*NOMES_ATUALIZACAO, *NOMES_CRIACAO):
        if candidato in por_nome:
            return por_nome[candidato]
    for coluna in colunas:
        tipo = (coluna.get("type") or "").lower()
        if any(tipo.startswith(t) for t in TIPOS_TEMPORAIS):
            return coluna["name"]
    return None


def schedule_padrao(colunas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Schedule padrão: hora em hora; incremental se houver coluna de watermark."""
    coluna = inferir_coluna_incremental(colunas)
    schedule: Dict[str, Any] = {
        "cron": CRON_PADRAO,
        "mode": "incremental" if coluna else "full",
        "full_load": False,
        "truncate": False,
    }
    if coluna:
        schedule["incremental_column"] = coluna
    return schedule


def schedule_geral_padrao() -> Dict[str, Any]:
    """Schedule padrão do modelo geral (todas as tabelas, em ordem)."""
    return {"cron": CRON_PADRAO}


def _completar_schedule(existente: Any, colunas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Preenche apenas as chaves ausentes, preservando o que o usuário já editou."""
    novo = dict(schedule_padrao(colunas))
    if isinstance(existente, dict):
        for chave, valor in existente.items():
            if valor is not None:
                novo[chave] = valor
    if novo.get("mode") == "incremental" and not novo.get("incremental_column"):
        coluna = inferir_coluna_incremental(colunas)
        if coluna:
            novo["incremental_column"] = coluna
    return novo


def _completar_schedule_geral(existente: Any) -> Dict[str, Any]:
    """Preenche o schedule geral do main.yml preservando edições do usuário."""
    novo = dict(schedule_geral_padrao())
    if isinstance(existente, dict):
        for chave, valor in existente.items():
            if valor is not None:
                novo[chave] = valor
    return novo


def _dump_yaml(dados: Dict[str, Any]) -> str:
    return yaml.dump(dados, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _reordenar(dados: Dict[str, Any], ordem: List[str]) -> Dict[str, Any]:
    """Move as chaves da lista para o início, preservando a ordem das demais."""
    novo: Dict[str, Any] = {}
    for chave in ordem:
        if chave in dados:
            novo[chave] = dados[chave]
    for chave, valor in dados.items():
        if chave not in ordem:
            novo[chave] = valor
    return novo


def aplicar_schedules(project_dir: Path) -> List[Dict[str, Any]]:
    """Adiciona a chave ``schedule`` em cada schema e o schedule geral no main.yml.

    Devolve a lista de tabelas com os schedules aplicados (table, path, schedule).
    """
    project_dir = Path(project_dir)
    main_path = project_dir / "main.yml"
    if not main_path.exists():
        raise FileNotFoundError(f"main.yml não encontrado em: {main_path}")

    dados = yaml.safe_load(main_path.read_text(encoding="utf-8")) or {}
    resultado: List[Dict[str, Any]] = []

    for item in dados.get("tables", []):
        caminho = project_dir / item["path"]
        if not caminho.exists():
            continue
        schema = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
        if not schema.get("table") or not schema.get("columns"):
            continue
        schema["schedule"] = _completar_schedule(schema.get("schedule"), schema["columns"])
        schema = _reordenar(schema, ["table", "schema", "description", "schedule"])
        caminho.write_text(_dump_yaml(schema), encoding="utf-8")
        resultado.append({
            "table": schema["table"],
            "path": item["path"],
            "schedule": schema["schedule"],
        })

    dados["schedule"] = _completar_schedule_geral(dados.get("schedule"))
    dados = _reordenar(dados, ["version", "project", "schedule"])
    main_path.write_text(_dump_yaml(dados), encoding="utf-8")
    return resultado


def nome_projeto(project_dir: Path) -> str:
    """Lê o nome do projeto do main.yml (fallback: nome da pasta)."""
    main_path = Path(project_dir) / "main.yml"
    if main_path.exists():
        dados = yaml.safe_load(main_path.read_text(encoding="utf-8")) or {}
        if dados.get("project"):
            return str(dados["project"])
    return Path(project_dir).name


def _mostrar_resumo(tabelas: List[Dict[str, Any]]) -> None:
    tabela = Table(
        title="Schedules aplicados",
        border_style="dim blue",
        header_style="bold cyan",
        pad_edge=False,
    )
    tabela.add_column("Tabela", style="bold white", no_wrap=True, min_width=16)
    tabela.add_column("Cron", style="yellow")
    tabela.add_column("Modo", style="green")
    tabela.add_column("Incremental", style="cyan")
    tabela.add_column("Full load", style="white")
    tabela.add_column("Truncate", style="white")
    for t in tabelas:
        s = t["schedule"]
        tabela.add_row(
            t["table"],
            s.get("cron", ""),
            s.get("mode", ""),
            s.get("incremental_column") or "-",
            "sim" if s.get("full_load") else "não",
            "sim" if s.get("truncate") else "não",
        )
    console.print(tabela)


def gerar_schedules_automaticos(project_dir: Path, project_name: str) -> List[Dict[str, Any]]:
    """Aplica/infere os schedules nos schemas e gera o código Dagster padrão."""
    tabelas = aplicar_schedules(Path(project_dir))
    gerar_dagster(Path(project_dir), project_name)
    console.print(Text("Schedules e código Dagster gerados com sucesso!", style="bold green"))
    _mostrar_resumo(tabelas)
    return tabelas


def garantir_codigo_dagster(project_dir: Path) -> bool:
    """Garante que o projeto tem o código Dagster (conduto_dagster/) gerado.

    Se o código não existir, gera a partir do main.yml e dos schemas/*.yml,
    com o mesmo comportamento do comando ``conduto schedules``. Devolve True
    quando o projeto fica pronto para subir o Dagster.
    """
    project_dir = Path(project_dir)
    if (project_dir / "conduto_dagster" / "definitions.py").exists():
        return True
    if not (project_dir / "main.yml").exists():
        return False
    console.print(Text(
        "Código Dagster não encontrado — gerando a partir dos schemas...",
        style="bold yellow",
    ))
    try:
        gerar_schedules_automaticos(project_dir, nome_projeto(project_dir))
        return True
    except Exception as erro:
        console.print(Text(f"Falha ao gerar o código Dagster: {erro}", style="bold red"))
        return False
