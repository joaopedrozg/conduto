"""Geração de DDL (CREATE TABLE) a partir dos schemas YAML para o banco de destino."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from rich.console import Console

from conduto.database.adapters import (
    ADAPTERS,
    conectar_clickhouse,
    conectar_duckdb,
    conectar_mysql,
    conectar_postgres,
    conectar_sqlserver,
    delta_base,
    delta_storage_options,
)
from conduto.database.admin import schema_padrao_sgbd
from conduto.database.particularidades import PARTICULARIDADES

console = Console()


# ---------------------------------------------------------------------------
# Leitura do projeto (.env, main.yml e schemas/*.yml)
# ---------------------------------------------------------------------------


def ler_env(project_dir: Path) -> Dict[str, str]:
    """Lê o .env do projeto e devolve um dict de variáveis."""
    env_path = Path(project_dir) / ".env"
    if not env_path.exists():
        raise FileNotFoundError(
            f"Arquivo .env não encontrado em: {env_path}. Rode 'conduto init' antes."
        )
    valores: Dict[str, str] = {}
    for linha in env_path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valores[chave.strip()] = valor.strip()
    return valores


def credenciais_destino(project_dir: Path) -> Tuple[dict, str]:
    """Devolve as credenciais de destino e o tipo do SGBD a partir do .env."""
    env = ler_env(project_dir)
    tipo = env.get("DB_DESTINO_TYPE")
    adapter = next((a for a in ADAPTERS.values() if a.tipo == tipo), None)
    if adapter is None:
        raise ValueError(f"Tipo de SGBD de destino não suportado no .env: {tipo!r}")

    credenciais = {
        "tipo": tipo,
        "host": env.get("DB_DESTINO_HOST", adapter.host_padrao),
        "port": env.get("DB_DESTINO_PORT", adapter.porta_padrao),
        "database": env.get("DB_DESTINO_NAME", adapter.banco_padrao),
        "user": env.get("DB_DESTINO_USER", adapter.usuario_padrao),
        "password": env.get("DB_DESTINO_PASSWORD", adapter.senha_padrao),
    }
    credenciais["schema"] = env.get("DB_DESTINO_SCHEMA") or schema_padrao_sgbd(adapter, credenciais)
    return credenciais, tipo


def carregar_tabelas(project_dir: Path) -> List[Dict[str, Any]]:
    """Lê o main.yml (ordem de dependência) e os schemas/*.yml referenciados."""
    project_dir = Path(project_dir)
    main_path = project_dir / "main.yml"
    if main_path.exists():
        dados = yaml.safe_load(main_path.read_text(encoding="utf-8")) or {}
        caminhos = [
            item["path"]
            for item in dados.get("tables", [])
            if isinstance(item, dict) and item.get("path")
        ]
    else:
        schemas_dir = project_dir / "schemas"
        if not schemas_dir.exists():
            return []
        caminhos = sorted(
            str(p.relative_to(project_dir)) for p in schemas_dir.glob("*.yml")
        )

    tabelas: List[Dict[str, Any]] = []
    for caminho in caminhos:
        arquivo = project_dir / caminho
        if not arquivo.exists():
            continue
        dados = yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}
        if not dados.get("table") or not dados.get("columns"):
            continue
        dados["path"] = caminho
        tabelas.append(dados)
    return tabelas


# ---------------------------------------------------------------------------
# Mapeamento de tipos YAML -> tipo nativo do SGBD de destino
# ---------------------------------------------------------------------------

_TIPOS_POR_SGBD: Dict[str, Dict[str, str]] = {
    "postgresql": {
        "text": "text",
        "varchar": "varchar",
        "char": "char",
        "integer": "integer",
        "int": "integer",
        "bigint": "bigint",
        "smallint": "smallint",
        "tinyint": "smallint",
        "boolean": "boolean",
        "bool": "boolean",
        "timestamp": "timestamp",
        "timestamptz": "timestamptz",
        "date": "date",
        "time": "time",
        "timetz": "timetz",
        "double": "double precision",
        "float": "real",
        "real": "real",
        "numeric": "numeric",
        "decimal": "numeric",
        "uuid": "uuid",
        "json": "json",
        "jsonb": "jsonb",
        "binary": "bytea",
        "enum": "text",
        "user-defined": "text",
        "xml": "xml",
    },
    "mysql": {
        "text": "text",
        "varchar": "varchar",
        "char": "char",
        "integer": "int",
        "int": "int",
        "bigint": "bigint",
        "smallint": "smallint",
        "tinyint": "tinyint",
        "boolean": "boolean",
        "bool": "boolean",
        "timestamp": "timestamp",
        "timestamptz": "timestamp",
        "date": "date",
        "time": "time",
        "timetz": "time",
        "double": "double",
        "float": "float",
        "real": "float",
        "numeric": "decimal",
        "decimal": "decimal",
        "uuid": "char(36)",
        "json": "json",
        "jsonb": "json",
        "binary": "blob",
        "enum": "varchar(255)",
        "user-defined": "varchar(255)",
        "xml": "text",
    },
    "sqlserver": {
        "text": "varchar(max)",
        "varchar": "varchar",
        "char": "char",
        "integer": "int",
        "int": "int",
        "bigint": "bigint",
        "smallint": "smallint",
        "tinyint": "tinyint",
        "boolean": "bit",
        "bool": "bit",
        "timestamp": "datetime2",
        "timestamptz": "datetimeoffset",
        "date": "date",
        "time": "time",
        "timetz": "time",
        "double": "float",
        "float": "real",
        "real": "real",
        "numeric": "decimal",
        "decimal": "decimal",
        "uuid": "uniqueidentifier",
        "json": "nvarchar(max)",
        "jsonb": "nvarchar(max)",
        "binary": "varbinary(max)",
        "enum": "nvarchar(255)",
        "user-defined": "nvarchar(255)",
        "xml": "xml",
    },    "clickhouse": {
        "text": "String",
        "varchar": "String",
        "char": "FixedString",
        "integer": "Int32",
        "int": "Int32",
        "bigint": "Int64",
        "smallint": "Int16",
        "tinyint": "Int8",
        "boolean": "Bool",
        "bool": "Bool",
        "timestamp": "DateTime64(3)",
        "timestamptz": "DateTime64(3)",
        "date": "Date32",
        "time": "String",
        "timetz": "String",
        "double": "Float64",
        "float": "Float32",
        "real": "Float32",
        "numeric": "Decimal",
        "decimal": "Decimal",
        "uuid": "UUID",
        "json": "JSON",
        "jsonb": "JSON",
        "binary": "String",
        "enum": "String",
        "user-defined": "String",
        "xml": "String",
    },
    "duckdb": {
        "text": "text",
        "varchar": "varchar",
        "char": "char",
        "integer": "integer",
        "int": "integer",
        "bigint": "bigint",
        "smallint": "smallint",
        "tinyint": "tinyint",
        "boolean": "boolean",
        "bool": "boolean",
        "timestamp": "timestamp",
        "timestamptz": "timestamptz",
        "date": "date",
        "time": "time",
        "timetz": "time",
        "double": "double",
        "float": "real",
        "real": "real",
        "numeric": "decimal",
        "decimal": "decimal",
        "uuid": "uuid",
        "json": "json",
        "jsonb": "json",
        "binary": "blob",
        "enum": "varchar(255)",
        "user-defined": "varchar(255)",
        "xml": "varchar(255)",
    },
    "deltalake": {
        "text": "string",
        "varchar": "string",
        "char": "string",
        "integer": "integer",
        "int": "integer",
        "bigint": "bigint",
        "smallint": "smallint",
        "tinyint": "tinyint",
        "boolean": "boolean",
        "bool": "boolean",
        "timestamp": "timestamp",
        "timestamptz": "timestamp",
        "date": "date",
        "time": "time",
        "timetz": "time",
        "double": "double",
        "float": "float",
        "real": "float",
        "numeric": "decimal",
        "decimal": "decimal",
        "uuid": "string",
        "json": "string",
        "jsonb": "string",
        "binary": "binary",
        "enum": "string",
        "user-defined": "string",
        "xml": "string",
    },
}

_VARCHAR_SEM_TAMANHO = {
    "postgresql": "text",
    "mysql": "varchar(255)",
    "sqlserver": "nvarchar(255)",
    "clickhouse": "String",
    "duckdb": "varchar",
    "deltalake": "string",
}


def mapear_tipo(tipo: str, sgbd: str) -> str:
    """Converte o tipo do schema YAML para o tipo nativo do SGBD de destino."""
    mapeamento = _TIPOS_POR_SGBD.get(sgbd, {})
    texto = tipo.strip()
    correspondencia = re.match(r"^([a-z0-9_ ]+?)\s*\((.*)\)$", texto, re.IGNORECASE)
    if correspondencia:
        base = correspondencia.group(1).strip().lower()
        if sgbd == "deltalake" and base in ("text", "varchar", "char"):
            return "string"
        novo = mapeamento.get(base)
        if novo is None:
            return texto
        if "(" in novo:
            return novo
        return f"{novo}({correspondencia.group(2)})"

    base = texto.lower()
    if sgbd == "deltalake" and base in ("text", "varchar", "char"):
        return "string"
    novo = mapeamento.get(base)
    if novo is None:
        return texto
    if base == "varchar" and novo in ("varchar", "nvarchar"):
        return _VARCHAR_SEM_TAMANHO.get(sgbd, novo)
    return novo


# ---------------------------------------------------------------------------
# Defaults: traduz funções do SGBD de origem para o SGBD de destino
# ---------------------------------------------------------------------------

_EXPRESSOES_DEFAULT: Dict[str, Dict[str, str]] = {
    "postgresql": {
        "now()": "now()",
        "current_timestamp": "CURRENT_TIMESTAMP",
        "clock_timestamp()": "clock_timestamp()",
        "gen_random_uuid()": "gen_random_uuid()",
        "getdate()": "CURRENT_TIMESTAMP",
        "newid()": "gen_random_uuid()",
        "uuid()": "gen_random_uuid()",
    },
    "mysql": {
        "now()": "NOW()",
        "current_timestamp": "CURRENT_TIMESTAMP",
        "clock_timestamp()": "CURRENT_TIMESTAMP(6)",
        "gen_random_uuid()": "UUID()",
        "getdate()": "CURRENT_TIMESTAMP",
        "newid()": "UUID()",
        "uuid()": "UUID()",
    },
    "sqlserver": {
        "now()": "GETDATE()",
        "current_timestamp": "CURRENT_TIMESTAMP",
        "clock_timestamp()": "SYSDATETIME()",
        "gen_random_uuid()": "NEWID()",
        "getdate()": "GETDATE()",
        "newid()": "NEWID()",
        "uuid()": "NEWID()",
    },    "clickhouse": {
        "now()": "now()",
        "current_timestamp": "now()",
        "clock_timestamp()": "now()",
        "gen_random_uuid()": "generateUUIDv4()",
        "getdate()": "now()",
        "newid()": "generateUUIDv4()",
        "uuid()": "generateUUIDv4()",
    },
    "duckdb": {
        "now()": "now()",
        "current_timestamp": "CURRENT_TIMESTAMP",
        "clock_timestamp()": "now()",
        "gen_random_uuid()": "gen_random_uuid()",
        "getdate()": "now()",
        "newid()": "gen_random_uuid()",
        "uuid()": "gen_random_uuid()",
    },
    "deltalake": {
        "now()": "now()",
        "current_timestamp": "CURRENT_TIMESTAMP",
        "clock_timestamp()": "now()",
        "gen_random_uuid()": "gen_random_uuid()",
        "getdate()": "now()",
        "newid()": "gen_random_uuid()",
        "uuid()": "gen_random_uuid()",
    },
}

_PALAVRAS_RESERVADAS_DEFAULT = {
    "CURRENT_TIMESTAMP",
    "CURRENT_DATE",
    "CURRENT_TIME",
    "LOCALTIME",
    "LOCALTIMESTAMP",
    "CURRENT_USER",
    "SESSION_USER",
    "SYSDATE",
    "NULL",
}


def _default_sql(valor: Any, sgbd: str) -> str:
    """Formata o default do YAML para a sintaxe do SGBD de destino."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        if sgbd == "sqlserver":
            return "1" if valor else "0"
        return "TRUE" if valor else "FALSE"
    if isinstance(valor, (int, float)):
        return str(valor)

    texto = str(valor).strip()
    if not texto:
        return ""

    funcao = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)$", texto)
    if funcao:
        chave = f"{funcao.group(1).lower()}({funcao.group(2)})"
        return _EXPRESSOES_DEFAULT.get(sgbd, {}).get(chave, texto)

    if texto.upper() in _PALAVRAS_RESERVADAS_DEFAULT:
        chave = texto.lower()
        return _EXPRESSOES_DEFAULT.get(sgbd, {}).get(chave, texto.upper())

    return "'" + texto.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Geração do DDL
# ---------------------------------------------------------------------------


def _aspas(sgbd: str, identificador: str) -> str:
    """Protege identificadores conforme o SGBD de destino."""
    if sgbd in ("mysql", "clickhouse"):
        return f"`{identificador}`"
    if sgbd == "sqlserver":
        return f"[{identificador}]"
    return f'"{identificador}"'


def _linha_coluna(coluna: Dict[str, Any], sgbd: str) -> str:
    nome = _aspas(sgbd, coluna["name"])
    tipo_sql = mapear_tipo(coluna["type"], sgbd)
    if (
        sgbd == "clickhouse"
        and coluna.get("nullable", True)
        and not coluna.get("primary_key")
        and "Nullable(" not in tipo_sql
    ):
        # No ClickHouse os tipos sao NOT NULL por padrao; colunas nullable
        # precisam do wrapper Nullable(...) para aceitar NULL na carga.
        tipo_sql = f"Nullable({tipo_sql})"
    partes = [f"  {nome} {tipo_sql}"]
    if not coluna.get("nullable", True):
        partes.append("NOT NULL")
    default = coluna.get("default")
    if default is not None and default != "":
        default_sql = _default_sql(default, sgbd)
        if (
            sgbd == "mysql"
            and tipo_sql.lower() in ("json", "text", "blob")
            and default_sql.startswith("'")
        ):
            # MySQL exige expressão entre parênteses como default de json/text/blob
            default_sql = f"({default_sql})"
        partes.append(f"DEFAULT {default_sql}")
    return " ".join(partes)


_FK_RE = re.compile(
    r"^(?:([A-Za-z_][A-Za-z0-9_]*)\.)?([A-Za-z_][A-Za-z0-9_]*)\(([A-Za-z_][A-Za-z0-9_]*)\)$"
)


def _linha_foreign_key(
    tabela: Dict[str, Any], coluna: Dict[str, Any], sgbd: str
) -> Optional[str]:
    fk = coluna.get("foreign_key")
    if not fk:
        return None
    correspondencia = _FK_RE.match(str(fk).strip())
    if not correspondencia:
        return None
    ref_schema, ref_tabela, ref_coluna = correspondencia.groups()
    schema_atual = tabela.get("schema") or "public"
    if ref_schema:
        referencia = f"{_aspas(sgbd, ref_schema)}.{_aspas(sgbd, ref_tabela)}"
    else:
        referencia = f"{_aspas(sgbd, schema_atual)}.{_aspas(sgbd, ref_tabela)}"
    nome = f"fk_{tabela['table']}_{coluna['name']}"
    return (
        f"  CONSTRAINT {_aspas(sgbd, nome)} FOREIGN KEY ({_aspas(sgbd, coluna['name'])}) "
        f"REFERENCES {referencia} ({_aspas(sgbd, ref_coluna)})"
    )


def gerar_ddl_tabela(tabela: Dict[str, Any], sgbd: str) -> str:
    """Gera o CREATE TABLE de uma tabela (com PK, unique e FKs)."""
    schema = tabela.get("schema") or "public"
    nome = tabela["table"]
    qualificado = f"{_aspas(sgbd, schema)}.{_aspas(sgbd, nome)}"

    linhas = [_linha_coluna(c, sgbd) for c in tabela.get("columns", [])]

    pks = [c["name"] for c in tabela["columns"] if c.get("primary_key")]
    particulares = PARTICULARIDADES[sgbd]
    if particulares.suporta_pk and pks:
        # Delta Lake e ClickHouse nao tem constraints no CREATE TABLE: no
        # ClickHouse a chave primaria vira o ORDER BY do MergeTree.
        nome_pk = f"pk_{nome}"
        linhas.append(
            f"  CONSTRAINT {_aspas(sgbd, nome_pk)} PRIMARY KEY "
            f"({', '.join(_aspas(sgbd, c) for c in pks)})"
        )

    if particulares.suporta_unique:
        for coluna in tabela["columns"]:
            if coluna.get("unique"):
                nome_uq = f"uq_{nome}_{coluna['name']}"
                linhas.append(
                    f"  CONSTRAINT {_aspas(sgbd, nome_uq)} UNIQUE ({_aspas(sgbd, coluna['name'])})"
                )

    if particulares.suporta_fk:
        for coluna in tabela["columns"]:
            fk = _linha_foreign_key(tabela, coluna, sgbd)
            if fk:
                linhas.append(fk)

    corpo = ",\n".join(linhas)

    if sgbd == "sqlserver":
        return (
            f"IF OBJECT_ID(N'{schema}.{nome}', N'U') IS NULL\n"
            "BEGIN\n"
            f"CREATE TABLE {qualificado} (\n{corpo}\n);\n"
            "END"
        )
    if sgbd == "clickhouse":
        engine = tabela.get("engine") or particulares.engine_padrao or "MergeTree"
        order_by = tabela.get("order_by") or pks
        if isinstance(order_by, list):
            ordem = ", ".join(_aspas(sgbd, str(c)) for c in order_by)
            ordem_sql = f"({ordem})" if ordem else "tuple()"
        else:
            ordem = str(order_by).strip()
            if ordem.startswith("(") and ordem.endswith(")"):
                ordem_sql = ordem
            else:
                ordem_sql = f"({ordem})" if ordem else "tuple()"
        partes_ddl = [
            f"CREATE TABLE IF NOT EXISTS {qualificado} (\n{corpo}\n)",
            f"ENGINE = {engine}",
            f"ORDER BY {ordem_sql}",
        ]
        if "partition_by" in particulares.chaves_tabela:
            particao = tabela.get("partition_by")
            if particao:
                partes_ddl.append(f"PARTITION BY {particao}")
        return "\n".join(partes_ddl) + ";"

    return f"CREATE TABLE IF NOT EXISTS {qualificado} (\n{corpo}\n);"



def _preambulo_schema(schema: str, sgbd: str) -> str:
    """Garante que o schema de destino exista antes de criar as tabelas."""
    particulares = PARTICULARIDADES[sgbd]
    if sgbd == "clickhouse" and particulares.suporta_criar_banco:
        return (
            f"-- Garante que o banco '{schema}' existe no ClickHouse\n"
            f"CREATE DATABASE IF NOT EXISTS {_aspas(sgbd, schema)};"
        )
    if sgbd in ("mysql", "deltalake") or not particulares.suporta_criar_schema:
        return ""
    if sgbd == "duckdb":
        return (
            f"-- Garante que o schema '{schema}' existe no DuckDB\n"
            f"CREATE SCHEMA IF NOT EXISTS {_aspas(sgbd, schema)};"
        )
    if sgbd == "sqlserver":
        return (
            f"-- Garante que o schema '{schema}' existe no SQL Server\n"
            f"IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'{schema}')\n"
            f"    EXEC(N'CREATE SCHEMA [{schema}]');"
        )
    return (
        f"-- Garante que o schema '{schema}' existe no PostgreSQL\n"
        f"CREATE SCHEMA IF NOT EXISTS {_aspas(sgbd, schema)};"
    )



def gerar_ddl(tabelas: List[Dict[str, Any]], sgbd: str) -> str:
    """Gera o DDL completo (schemas + CREATE TABLE) na ordem de dependência."""
    schemas: List[str] = []
    for tabela in tabelas:
        schema = tabela.get("schema") or "public"
        if schema not in schemas:
            schemas.append(schema)

    partes = []
    if schemas:
        partes.append(
            "-- DDL gerado pelo Conduto\n"
            f"-- Destino: {sgbd} | schema(s): {', '.join(schemas)} | tabelas: {len(tabelas)}"
        )
    for schema in schemas:
        preambulo = _preambulo_schema(schema, sgbd)
        if preambulo:
            partes.append(preambulo)
    for tabela in tabelas:
        partes.append(gerar_ddl_tabela(tabela, sgbd))
    return "\n\n".join(partes) + "\n"


# ---------------------------------------------------------------------------
# Execução no banco de destino
# ---------------------------------------------------------------------------


def dividir_statement(ddl: str) -> List[str]:
    """Divide o DDL em comandos executáveis (respeitando BEGIN...END do SQL Server)."""
    comandos: List[str] = []
    atual: List[str] = []
    profundidade = 0
    for linha in ddl.splitlines():
        limpa = linha.strip().upper()
        if limpa == "BEGIN":
            profundidade += 1
        atual.append(linha)
        if limpa == "END":
            profundidade -= 1
        if profundidade == 0 and (limpa.endswith(";") or limpa == "END"):
            comandos.append("\n".join(atual))
            atual = []
    if atual:
        comandos.append("\n".join(atual))
    return [c.strip() for c in comandos if c.strip()]


_CONEXOES = {
    "postgresql": conectar_postgres,
    "mysql": conectar_mysql,
    "sqlserver": conectar_sqlserver,
    "clickhouse": conectar_clickhouse,
    "duckdb": conectar_duckdb,
}


def executar_ddl(sgbd: str, credenciais: dict, comandos: List[str]) -> List[str]:
    """Executa os comandos DDL no banco de destino e devolve a lista de erros."""
    if sgbd == "deltalake":
        return _executar_ddl_deltalake(credenciais, comandos)
    conectar = _CONEXOES[sgbd]
    erros: List[str] = []
    conn = conectar(credenciais)
    try:
        for comando in comandos:
            try:
                with conn.cursor() as cur:
                    cur.execute(comando)
                conn.commit()
            except Exception as erro:
                primeira_linha = comando.splitlines()[0] if comando.splitlines() else comando
                erros.append(f"{primeira_linha} -> {erro}")
    finally:
        conn.close()
    return erros


# ---------------------------------------------------------------------------
# Execucao no Delta Lake (cria as tabelas Delta vazias)
# ---------------------------------------------------------------------------


def _executar_ddl_deltalake(credenciais: dict, comandos: List[str]) -> List[str]:
    """Cria as tabelas Delta a partir dos CREATE TABLE gerados pelo conduto."""
    import pyarrow as pa
    from deltalake import write_deltalake

    base = delta_base(credenciais)
    opcoes = delta_storage_options(credenciais) or None
    erros: List[str] = []
    for comando in comandos:
        try:
            tabela, campos = _parsear_create_table(comando)
            campos_arrow = [
                (nome, _tipo_arrow(tipo), nao_nulo) for nome, tipo, nao_nulo in campos
            ]
            schema_arrow = pa.schema(
                pa.field(nome, tipo, nullable=not nao_nulo)
                for nome, tipo, nao_nulo in campos_arrow
            )
            vazia = pa.Table.from_batches([], schema=schema_arrow)
            write_deltalake(
                f"{base}/{tabela}",
                vazia,
                mode="overwrite",
                schema_mode="overwrite",
                storage_options=opcoes,
            )
        except Exception as erro:
            primeira_linha = comando.splitlines()[0] if comando.splitlines() else comando
            erros.append(f"{primeira_linha} -> {erro}")
    return erros


def _parsear_create_table(comando: str):
    """Extrai (tabela, [(coluna, tipo, not_null)]) de um CREATE TABLE do conduto."""
    correspondencia = re.search(
        r"CREATE TABLE (?:IF NOT EXISTS )?\"([^\"]+)\"\.\"([^\"]+)\"\s*\((.*)\)\s*;?\s*$",
        comando,
        re.DOTALL,
    )
    if not correspondencia:
        raise ValueError("CREATE TABLE nao reconhecido (use o DDL gerado pelo conduto).")
    tabela = correspondencia.group(2)
    corpo = correspondencia.group(3)
    campos = []
    for linha in corpo.splitlines():
        trecho = linha.strip().rstrip(",").strip()
        if not trecho:
            continue
        if trecho.upper().startswith(("CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN")):
            continue
        coluna = re.match(r'^\"([^\"]+)\"\s+(.+)$', trecho)
        if not coluna:
            continue
        nome = coluna.group(1)
        resto = coluna.group(2)
        nao_nulo = False
        if re.search(r"\s+NOT\s+NULL\b", resto, re.IGNORECASE):
            nao_nulo = True
            resto = re.sub(r"\s+NOT\s+NULL\b.*$", "", resto, flags=re.IGNORECASE)
        resto = re.sub(r"\s+DEFAULT\s+.*$", "", resto, flags=re.IGNORECASE)
        campos.append((nome, resto.strip(), nao_nulo))
    return tabela, campos


def _tipo_arrow(tipo: str):
    """Mapeia o tipo do DDL do conduto para pyarrow (criacao de tabela Delta)."""
    import pyarrow as pa

    t = tipo.strip().lower()
    if t in ("text", "varchar", "char", "string", "uuid", "json", "enum", "xml"):
        return pa.string()
    if t in ("integer", "int"):
        return pa.int32()
    if t in ("bigint", "long"):
        return pa.int64()
    if t == "smallint":
        return pa.int16()
    if t == "tinyint":
        return pa.int8()
    if t in ("boolean", "bool"):
        return pa.bool_()
    if t == "timestamp":
        return pa.timestamp("us")
    if t == "date":
        return pa.date32()
    if t == "time":
        return pa.time64("us")
    if t == "double":
        return pa.float64()
    if t in ("float", "real"):
        return pa.float32()
    if t in ("binary", "blob", "bytea"):
        return pa.binary()
    m = re.match(r"^(numeric|decimal)\((\d+),\s*(\d+)\)$", t)
    if m:
        return pa.decimal128(int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(numeric|decimal)\((\d+)\)$", t)
    if m:
        return pa.decimal128(int(m.group(2)), 0)
    raise ValueError(f"Tipo nao mapeado para Delta: {tipo}")
