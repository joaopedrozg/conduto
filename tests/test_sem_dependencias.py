"""Garantia de que o projeto gerado não cria dependência entre as tabelas.

O problema relatado: com FK virando constraint e virando ``deps`` no Dagster,
carregar uma tabela só exigia que a que ela referenciava também existisse /
fosse materializada antes — e falhava. Em ambiente analítico isso não faz
sentido: qualquer tabela tem de ser carga isolada.

Aqui se prova, camada por caminho, que a ``foreign_key`` declarada nos schemas
não vira nada:

- **DDL**: nenhuma ``FOREIGN KEY`` no ``CREATE TABLE``, nos 6 destinos;
- **Dagster**: nenhum ``deps`` no ``@asset`` (testado importando o módulo de
  verdade com um stub do Dagster, não só conferindo texto);
- **manifesto**: ``main.yml`` não é reordenado por topologia de FK;
- **docs**: deixa de anunciar suporte a FK, que não existe mais.

A própria ``foreign_key`` continua gravada no YAML — documentação do modelo,
conforme decidido.
"""

import dataclasses
import importlib
import sys
import types
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml
from jinja2 import Template

from conduto.database.particularidades import PARTICULARIDADES
from conduto.ddl.ddl_render import gerar_ddl, gerar_ddl_tabela
from conduto.docs.docs_server import _resumo_particularidades
from conduto.schemas.schemas_auto import gerar_arquivos


RAIZ = Path(__file__).resolve().parents[1]
TEMPLATES_DAGSTER = RAIZ / "src" / "conduto" / "templates" / "dagster"
TEMPLATE_DOCS = RAIZ / "src" / "conduto" / "templates" / "docs" / "index.html.jinja"

DESTINOS = ["postgresql", "mysql", "sqlserver", "clickhouse", "duckdb", "deltalake"]
# Destinos que aceitam constraints no CREATE TABLE (suporta_pk/suporta_unique).
COM_CONSTRAINTS = ["postgresql", "mysql", "sqlserver", "duckdb"]


def _tabela_pedidos() -> Dict[str, Any]:
    """Tabela com DUAS FK declaradas, mais PK e unique — o caso mais completo."""
    return {
        "table": "pedidos",
        "schema": "public",
        "source_schema": "public",
        "columns": [
            {"name": "id", "type": "integer", "primary_key": True, "nullable": False},
            {"name": "cliente_id", "type": "integer", "foreign_key": "clientes(id)"},
            {
                "name": "fornecedor_id",
                "type": "integer",
                "foreign_key": "public.fornecedores(id)",
            },
            {"name": "codigo", "type": "varchar", "unique": True},
            {"name": "valor", "type": "numeric(10,2)"},
        ],
    }


def _tabela_clientes() -> Dict[str, Any]:
    return {
        "table": "clientes",
        "schema": "public",
        "source_schema": "public",
        "columns": [
            {"name": "id", "type": "integer", "primary_key": True, "nullable": False},
            {"name": "nome", "type": "varchar(255)"},
        ],
    }


def _descricoes() -> List[Dict[str, Any]]:
    """pedidos ANTES de clientes: com ordenação topológica viraria o contrário."""
    return [_tabela_pedidos(), _tabela_clientes()]


# ---------------------------------------------------------------------------
# 1. DDL: nenhuma FOREIGN KEY em nenhum destino
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sgbd", DESTINOS)
def test_ddl_nao_tem_foreign_key(sgbd: str):
    ddl = gerar_ddl_tabela(_tabela_pedidos(), sgbd)

    assert "FOREIGN KEY" not in ddl
    assert "REFERENCES" not in ddl
    # nem o nome da constraint que antes era gerada
    assert "fk_pedidos_cliente_id" not in ddl
    assert "fk_pedidos_fornecedor_id" not in ddl


@pytest.mark.parametrize("sgbd", DESTINOS)
def test_gerar_ddl_completo_tambem_nao_tem_foreign_key(sgbd: str):
    ddl = gerar_ddl([_tabela_pedidos(), _tabela_clientes()], sgbd)

    assert "FOREIGN KEY" not in ddl
    assert "REFERENCES" not in ddl


@pytest.mark.parametrize("sgbd", DESTINOS)
def test_coluna_com_fk_continua_sendo_gerada(sgbd: str):
    """A constraint some, mas a coluna que declara a FK fica."""
    ddl = gerar_ddl_tabela(_tabela_pedidos(), sgbd)

    assert "cliente_id" in ddl
    assert "fornecedor_id" in ddl


@pytest.mark.parametrize("sgbd", COM_CONSTRAINTS)
def test_remover_fk_preserva_pk_e_unique(sgbd: str):
    """Não regressão: só a FK foi removida, PK e unique continuam."""
    ddl = gerar_ddl_tabela(_tabela_pedidos(), sgbd)

    assert "PRIMARY KEY" in ddl
    assert "UNIQUE" in ddl


@pytest.mark.parametrize("sgbd", DESTINOS)
def test_particularidades_deste_destino_continua_coerente(sgbd: str):
    """O SGBD continua declarando suporte a PK/unique como antes da remoção."""
    p = PARTICULARIDADES[sgbd]
    ddl = gerar_ddl_tabela(_tabela_pedidos(), sgbd)

    if p.suporta_pk:
        assert "PRIMARY KEY" in ddl
    if p.suporta_unique:
        assert "UNIQUE" in ddl


def test_mecanica_de_fk_foi_removida_do_renderizador():
    """A função que emitia a constraint nem existe mais — não é só não chamada."""
    from conduto.ddl import ddl_render

    assert not hasattr(ddl_render, "_linha_foreign_key")
    assert not hasattr(ddl_render, "_FK_RE")


# ---------------------------------------------------------------------------
# 2. Manifesto: main.yml não é reordenado por topologia
# ---------------------------------------------------------------------------


def test_main_yml_mantem_a_ordem_recebida(tmp_path: Path):
    """pedidos vem primeiro e referencia clientes: a ordenação antiga inverteria."""
    gerar_arquivos(tmp_path, "proj", _descricoes())

    main = yaml.safe_load((tmp_path / "main.yml").read_text(encoding="utf-8"))
    assert [item["path"] for item in main["tables"]] == [
        "schemas/pedidos.yml",
        "schemas/clientes.yml",
    ]


def test_comentario_do_main_yml_nao_menciona_dependencia(tmp_path: Path):
    gerar_arquivos(tmp_path, "proj", _descricoes())

    texto = (tmp_path / "main.yml").read_text(encoding="utf-8")
    assert "dependência" not in texto
    assert "pais antes de filhos" not in texto


def test_ordenacao_por_dependencia_foi_removida():
    from conduto.schemas import schemas_auto

    assert not hasattr(schemas_auto, "_ordenar_por_dependencia")


def test_ordenacao_por_dependencia_fica_fora_do_comportamento_do_gerador(tmp_path: Path):
    """Mesmo com FK formando ordem clara, o gerador não reordena nada."""
    # inverte a ordem: clientes primeiro, pedidos depois — deve permanecer
    gerar_arquivos(tmp_path, "proj", [_tabela_clientes(), _tabela_pedidos()])

    main = yaml.safe_load((tmp_path / "main.yml").read_text(encoding="utf-8"))
    assert [item["path"] for item in main["tables"]] == [
        "schemas/clientes.yml",
        "schemas/pedidos.yml",
    ]


# ---------------------------------------------------------------------------
# 3. foreign_key continua como documentação (decisão mantida)
# ---------------------------------------------------------------------------


def test_foreign_key_continua_gravada_no_yaml(tmp_path: Path):
    gerar_arquivos(tmp_path, "proj", _descricoes())

    texto = (tmp_path / "schemas" / "pedidos.yml").read_text(encoding="utf-8")
    assert "foreign_key: clientes(id)" in texto
    assert "foreign_key: public.fornecedores(id)" in texto


def test_source_schema_continua_gravado_junto_com_a_fk(tmp_path: Path):
    """A documentação da origem não foi pega no fogo da remoção."""
    gerar_arquivos(tmp_path, "proj", _descricoes())

    texto = (tmp_path / "schemas" / "pedidos.yml").read_text(encoding="utf-8")
    assert "source_schema: public" in texto


# ---------------------------------------------------------------------------
# 4. Templates Dagster: nenhuma mecânica de dependência
# ---------------------------------------------------------------------------


def _ler_template_dagster(nome: str) -> str:
    return (TEMPLATES_DAGSTER / "conduto_dagster" / nome).read_text(encoding="utf-8")


def test_template_etl_nao_monta_dependencias():
    texto = _ler_template_dagster("etl.py.jinja")

    assert "_dependencias" not in texto
    assert 'tabela["deps"]' not in texto


def test_template_definitions_nao_passa_deps():
    texto = _ler_template_dagster("definitions.py.jinja")

    assert "deps=" not in texto
    assert 'get("deps"' not in texto


def test_template_definitions_explica_a_independencia():
    """A ausência de deps é intencional e documentada no próprio template."""
    texto = _ler_template_dagster("definitions.py.jinja")

    assert "Sem ``deps``" in texto


# ---------------------------------------------------------------------------
# 5. Dagster de verdade: importar o definitions e inspecionar o @asset
# ---------------------------------------------------------------------------


def _renderizar_pacote(project_dir: Path) -> None:
    """Renderiza o pacote conduto_dagster/ como o ``gerar_dagster`` faria."""
    pacote = project_dir / "conduto_dagster"
    pacote.mkdir(parents=True, exist_ok=True)
    for nome in ("__init__.py", "etl.py", "definitions.py"):
        origem = TEMPLATES_DAGSTER / "conduto_dagster" / f"{nome}.jinja"
        conteudo = Template(origem.read_text(encoding="utf-8")).render(
            project_name="proj"
        )
        (pacote / nome).write_text(conteudo, encoding="utf-8")


def _stub_dagster(chamadas_asset: List[Dict[str, Any]]) -> types.ModuleType:
    """Módulo falso do Dagster que grava os kwargs recebidos por @asset."""
    modulo = types.ModuleType("dagster")

    def asset(**kwargs):
        chamadas_asset.append(kwargs)

        def _decora(funcao):
            return funcao

        return _decora

    modulo.asset = asset
    modulo.AssetKey = lambda *a, **k: ("AssetKey", a)
    modulo.AssetSelection = types.SimpleNamespace(assets=lambda *a, **k: ("sel", a))
    modulo.define_asset_job = lambda *a, **k: ("job", a, k)
    modulo.ScheduleDefinition = lambda **k: ("schedule", k)
    modulo.Definitions = lambda **k: ("defs", k)
    return modulo


def _esvaziar_cache_pacote() -> None:
    for nome in list(sys.modules):
        if nome == "conduto_dagster" or nome.startswith("conduto_dagster."):
            del sys.modules[nome]


@pytest.fixture()
def projeto_dagster(tmp_path: Path):
    """Projeto gerado de verdade (gerar_arquivos + templates) e importado."""
    gerar_arquivos(tmp_path, "proj", _descricoes())
    _renderizar_pacote(tmp_path)

    chamadas_asset: List[Dict[str, Any]] = []
    _esvaziar_cache_pacote()
    sys.modules["dagster"] = _stub_dagster(chamadas_asset)
    sys.path.insert(0, str(tmp_path))
    try:
        modulo = importlib.import_module("conduto_dagster.definitions")
        yield types.SimpleNamespace(
            modulo=modulo,
            chamadas_asset=chamadas_asset,
            project_dir=tmp_path,
        )
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("dagster", None)
        _esvaziar_cache_pacote()


def test_definitions_importa_e_cria_assets(projeto_dagster):
    """Precondição: o resto só tem sentido se os assets foram criados mesmo."""
    assert len(projeto_dagster.modulo.TABELAS) == 2
    assert len(projeto_dagster.chamadas_asset) == 2


def test_nenhum_asset_recebe_deps(projeto_dagster):
    """O núcleo do bug: @asset sem deps == qualquer tabela roda isolada."""
    nomes = []
    for kwargs in projeto_dagster.chamadas_asset:
        assert "deps" not in kwargs, f"@asset recebeu deps: {kwargs}"
        nomes.append(kwargs.get("name"))

    assert sorted(nomes) == ["clientes", "pedidos"]


def test_ler_tabelas_nao_injeta_chave_deps(projeto_dagster):
    """ler_tabelas devolve as tabelas lidas do YAML, sem montar grafo."""
    tabelas = projeto_dagster.modulo.TABELAS
    assert {t["table"] for t in tabelas} == {"pedidos", "clientes"}

    for tabela in tabelas:
        assert "deps" not in tabela


def test_defs_do_modulo_nao_carrega_dependencia_entre_assets(projeto_dagster):
    """O Definitions final é montado só com assets e schedules soltos."""
    defs = projeto_dagster.modulo.defs
    tipo, conteudo = defs
    assert tipo == "defs"
    assert set(conteudo) == {"assets", "schedules"}
    assert len(conteudo["assets"]) == 2


def test_as_duas_tabelas_sao_assets_independentes(projeto_dagster):
    """Nomes dos assets batem com as tabelas: nenhuma ficou de fora."""
    nomes = {kwargs["name"] for kwargs in projeto_dagster.chamadas_asset}
    nomes_tabelas = {t["table"] for t in projeto_dagster.modulo.TABELAS}
    assert nomes == nomes_tabelas


# ---------------------------------------------------------------------------
# 6. Docs: deixa de anunciar suporte a FK
# ---------------------------------------------------------------------------


def test_particularidades_nao_tem_mais_o_campo_suporta_fk():
    campos = {f.name for f in dataclasses.fields(PARTICULARIDADES["postgresql"])}
    assert "suporta_fk" not in campos


def test_resumo_de_particularidades_nao_expoe_suporta_fk():
    for item in _resumo_particularidades():
        assert "suporta_fk" not in item


def test_template_de_docs_nao_tem_a_coluna_suporta_fk():
    texto = TEMPLATE_DOCS.read_text(encoding="utf-8")
    assert "suporta_fk" not in texto


def test_docs_continuam_exibindo_a_fk_de_cada_tabela():
    """A coluna ``Foreign key`` por coluna (documentação) continua de pé."""
    texto = TEMPLATE_DOCS.read_text(encoding="utf-8")
    assert "<th>Foreign key</th>" in texto


# ---------------------------------------------------------------------------
# 7. Templates de exemplo: nada de ordem de dependência no projeto gerado
# ---------------------------------------------------------------------------


def test_nenhum_schema_de_exemplo_promete_ordem_de_dependencia():
    """Varredura: o manifesto e os schemas de exemplo também não prometem ordem."""
    diretorio = RAIZ / "src" / "conduto" / "templates" / "schemas"
    arquivos = sorted(diretorio.glob("*.jinja"))
    assert arquivos, "nenhum template de schema encontrado"

    for arquivo in arquivos:
        texto = arquivo.read_text(encoding="utf-8")
        assert "ordem de dependência" not in texto, arquivo.name
        assert "antes de pedidos" not in texto, arquivo.name


def test_exemplo_de_pedidos_continua_documentando_a_fk():
    """A decisão de manter a FK como documentação vale também no exemplo."""
    texto = (
        RAIZ / "src" / "conduto" / "templates" / "schemas" / "pedidos-example.yml.jinja"
    ).read_text(encoding="utf-8")

    assert "foreign_key: clientes(id)" in texto
