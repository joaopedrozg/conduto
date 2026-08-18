"""Inferencia de colunas para schemas novos a partir do banco de origem."""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from conduto.database.adapters import ADAPTERS
from conduto.database.admin import schema_padrao_sgbd
from conduto.database.introspect import descrever_tabela
from conduto.ddl.ddl_render import ler_env
from conduto.ui import aviso, console, erro, progresso, tabela

ORDEM_SCHEMA = ["table", "schema", "description", "schedule"]
ORDEM_MAIN = ["version", "project", "schedule"]


def _dump_yaml(dados: Dict[str, Any]) -> str:
    return yaml.dump(dados, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _reordenar(dados: Dict[str, Any], ordem: List[str]) -> Dict[str, Any]:
    """Move as chaves da lista para o inicio, preservando a ordem das demais."""
    novo: Dict[str, Any] = {}
    for chave in ordem:
        if chave in dados:
            novo[chave] = dados[chave]
    for chave, valor in dados.items():
        if chave not in ordem:
            novo[chave] = valor
    return novo


def _ler_schema(arquivo: Optional[Path]) -> Dict[str, Any]:
    if arquivo is None or not arquivo.exists():
        return {}
    return yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}


def _credenciais_origem(env: Dict[str, str]):
    """Devolve o adapter, as credenciais e o schema de origem a partir do .env."""
    tipo = env["DB_ORIGEM_TYPE"]
    adapter = next((a for a in ADAPTERS.values() if a.tipo == tipo), None)
    if adapter is None:
        raise ValueError(f"Tipo de SGBD de origem nao suportado no .env: {tipo!r}")
    credenciais = {
        "tipo": tipo,
        "host": env.get("DB_ORIGEM_HOST", adapter.host_padrao),
        "port": env.get("DB_ORIGEM_PORT", adapter.porta_padrao),
        "database": env.get("DB_ORIGEM_NAME", adapter.banco_padrao),
        "user": env.get("DB_ORIGEM_USER", adapter.usuario_padrao),
        "password": env.get("DB_ORIGEM_PASSWORD", adapter.senha_padrao),
    }
    schema = env.get("DB_ORIGEM_SCHEMA") or schema_padrao_sgbd(adapter, credenciais)
    return adapter, credenciais, schema


def _candidatas(project_dir: Path, tabela_alvo: Optional[str]) -> List[Dict[str, Any]]:
    """Lista as tabelas que precisam de inferencia (sem colunas no schema)."""
    main_path = project_dir / "main.yml"
    caminhos: List[str] = []
    if main_path.exists():
        dados_main = _ler_schema(main_path)
        caminhos = [
            item["path"]
            for item in dados_main.get("tables", [])
            if isinstance(item, dict) and item.get("path")
        ]

    schemas_dir = project_dir / "schemas"
    arquivos = {
        p.relative_to(project_dir).as_posix(): p
        for p in schemas_dir.glob("*.yml")
    } if schemas_dir.exists() else {}

    if tabela_alvo:
        return [{
            "table": tabela_alvo,
            "path": f"schemas/{tabela_alvo}.yml",
            "dados": _ler_schema(arquivos.get(f"schemas/{tabela_alvo}.yml")),
        }]

    alvos: List[Dict[str, Any]] = []
    vistos = set()

    for caminho in caminhos:
        arquivo = project_dir / caminho
        if arquivo.exists():
            dados = _ler_schema(arquivo)
            if dados.get("table") and not dados.get("columns"):
                alvos.append({"table": dados["table"], "path": caminho, "dados": dados})
                vistos.add(caminho)
        else:
            alvos.append({"table": Path(caminho).stem, "path": caminho, "dados": None})

    for caminho, arquivo in sorted(arquivos.items()):
        if caminho in vistos:
            continue
        dados = _ler_schema(arquivo)
        if dados.get("table") and not dados.get("columns"):
            alvos.append({"table": dados["table"], "path": caminho, "dados": dados})

    return alvos


def _registrar_no_main(project_dir: Path, caminho: str) -> None:
    main_path = project_dir / "main.yml"
    dados = _ler_schema(main_path) if main_path.exists() else {}
    tabelas = dados.setdefault("tables", [])
    if not any(isinstance(i, dict) and i.get("path") == caminho for i in tabelas):
        tabelas.append({"path": caminho})
    dados = _reordenar(dados, ORDEM_MAIN)
    main_path.write_text(_dump_yaml(dados), encoding="utf-8")


def _mostrar_resumo(inferidas: List[Dict[str, Any]]) -> None:
    grade = tabela(
        "Colunas inferidas",
        [
            ("Tabela", "titulo"),
            ("Colunas", "sucesso"),
            ("Arquivo", "detalhe"),
        ],
        ((item["table"], str(item["columns"]), item["path"]) for item in inferidas),
    )
    console.print(grade)


def inferir_colunas(project_dir: Path, tabela_alvo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Infere as colunas das tabelas da origem e atualiza os schemas YAML.

    Se ``tabela_alvo`` for informado, infere (ou re-infere) somente essa tabela.
    Caso contrario, infere todos os schemas que ainda nao tem colunas:
    arquivos do main.yml, caminhos do main.yml sem arquivo e schemas/*.yml
    fora do main.yml. Devolve o resumo das tabelas inferidas.
    """
    project_dir = Path(project_dir)
    env = ler_env(project_dir)
    adapter, credenciais, schema_origem = _credenciais_origem(env)
    schema_destino = env.get("DB_DESTINO_SCHEMA") or "public"

    alvos = _candidatas(project_dir, tabela_alvo)
    if not alvos:
        console.print(aviso("Nenhum schema sem colunas encontrado."))
        return []

    inferidas: List[Dict[str, Any]] = []
    with progresso(len(alvos), "Inferindo colunas das tabelas...") as (barra, tarefa):
        for alvo in alvos:
            nome = alvo["table"]
            try:
                descricao = descrever_tabela(adapter, credenciais, schema_origem, nome)
            except Exception as exc:
                console.print(erro("Falha ao inferir {nome}: {erro}", nome=nome, erro=exc))
                barra.advance(tarefa)
                continue
            if not descricao.get("columns"):
                console.print(aviso("Tabela {nome} nao retornou colunas; pulando.", nome=nome))
                barra.advance(tarefa)
                continue

            dados = dict(alvo["dados"] or {})
            dados["table"] = descricao["table"]
            dados["schema"] = dados.get("schema") or schema_destino
            dados["description"] = dados.get("description") or f"Tabela {nome}"
            dados["columns"] = descricao["columns"]
            dados = _reordenar(dados, ORDEM_SCHEMA)

            caminho = project_dir / alvo["path"]
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_text(_dump_yaml(dados), encoding="utf-8")
            _registrar_no_main(project_dir, alvo["path"])
            inferidas.append({
                "table": nome,
                "path": alvo["path"],
                "columns": len(dados["columns"]),
            })
            barra.advance(tarefa)

    if inferidas:
        _mostrar_resumo(inferidas)
    return inferidas
