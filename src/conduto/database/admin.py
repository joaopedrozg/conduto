"""Opera\u00e7\u00f5es de cat\u00e1logo: listar/criar bancos e schemas dos SGBDs suportados."""

import re
from pathlib import Path

from conduto.database.adapters import (
    Adapter,
    conectar_clickhouse,
    conectar_duckdb,
    conectar_mysql,
    conectar_postgres,
    conectar_sqlserver,
    delta_cliente_s3,
    delta_eh_s3,
)

_IDENTIFICADOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validar_identificador(nome: str, tipo: str) -> None:
    if not nome or not _IDENTIFICADOR.match(nome):
        raise ValueError(f"'{nome}' n\u00e3o \u00e9 um nome v\u00e1lido para {tipo}.")


def schema_padrao_sgbd(adapter: Adapter, credenciais: dict) -> str:
    """Schema padr\u00e3o do SGBD (public, dbo, main ou o pr\u00f3prio banco)."""
    if adapter.tipo in ("mysql", "clickhouse", "deltalake"):
        return credenciais.get("database") or adapter.banco_padrao
    if adapter.tipo == "duckdb":
        return "main"
    if adapter.tipo == "sqlserver":
        return "dbo"
    return "public"


def listar_bancos(adapter: Adapter, credenciais: dict) -> list:
    if adapter.tipo == "postgresql":
        return _listar_bancos_postgres(credenciais)
    if adapter.tipo == "mysql":
        return _listar_bancos_mysql(credenciais)
    if adapter.tipo == "sqlserver":
        return _listar_bancos_sqlserver(credenciais)
    if adapter.tipo == "clickhouse":
        return _listar_bancos_clickhouse(credenciais)
    if adapter.tipo == "duckdb":
        return _listar_bancos_duckdb(credenciais)
    if adapter.tipo == "deltalake":
        return _listar_bancos_deltalake(credenciais)
    raise ValueError(f"Adapter desconhecido: {adapter.tipo}")


def criar_banco(adapter: Adapter, credenciais: dict, nome: str) -> None:
    _validar_identificador(nome, "banco")
    if adapter.tipo == "postgresql":
        _criar_banco_postgres(credenciais, nome)
    elif adapter.tipo == "mysql":
        _criar_banco_mysql(credenciais, nome)
    elif adapter.tipo == "sqlserver":
        _criar_banco_sqlserver(credenciais, nome)
    elif adapter.tipo == "clickhouse":
        _criar_banco_clickhouse(credenciais, nome)
    elif adapter.tipo == "duckdb":
        _criar_banco_duckdb(credenciais, nome)
    elif adapter.tipo == "deltalake":
        _criar_banco_deltalake(credenciais, nome)
    else:
        raise ValueError(f"Adapter desconhecido: {adapter.tipo}")


def listar_schemas(adapter: Adapter, credenciais: dict) -> list:
    if adapter.tipo == "postgresql":
        return _listar_schemas_postgres(credenciais)
    if adapter.tipo == "mysql":
        return [credenciais.get("database") or "mysql"]
    if adapter.tipo == "sqlserver":
        return _listar_schemas_sqlserver(credenciais)
    if adapter.tipo == "clickhouse":
        return _listar_schemas_clickhouse(credenciais)
    if adapter.tipo == "duckdb":
        return _listar_schemas_duckdb(credenciais)
    if adapter.tipo == "deltalake":
        return _listar_schemas_deltalake(credenciais)
    raise ValueError(f"Adapter desconhecido: {adapter.tipo}")


def criar_schema(adapter: Adapter, credenciais: dict, nome: str) -> None:
    if adapter.tipo == "mysql":
        raise ValueError("No MySQL o schema \u00e9 o pr\u00f3prio banco; crie um banco.")
    if adapter.tipo in ("clickhouse", "deltalake"):
        raise ValueError("No ClickHouse/Delta Lake o schema \u00e9 o pr\u00f3prio banco; crie um banco.")
    _validar_identificador(nome, "schema")
    if adapter.tipo == "postgresql":
        _criar_schema_postgres(credenciais, nome)
    elif adapter.tipo == "sqlserver":
        _criar_schema_sqlserver(credenciais, nome)
    elif adapter.tipo == "duckdb":
        _criar_schema_duckdb(credenciais, nome)
    else:
        raise ValueError(f"Adapter desconhecido: {adapter.tipo}")


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------

def _listar_bancos_postgres(credenciais: dict) -> list:
    conn = conectar_postgres(credenciais, database="postgres")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname"
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _criar_banco_postgres(credenciais: dict, nome: str) -> None:
    from psycopg import sql

    conn = conectar_postgres(credenciais, database="postgres")
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nome)))
    finally:
        conn.close()


def _listar_schemas_postgres(credenciais: dict) -> list:
    conn = conectar_postgres(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
                  AND schema_name NOT LIKE 'pg\\_%'
                ORDER BY schema_name
                """
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _criar_schema_postgres(credenciais: dict, nome: str) -> None:
    from psycopg import sql

    conn = conectar_postgres(credenciais)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(nome)))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------------

def _listar_bancos_mysql(credenciais: dict) -> list:
    conn = conectar_mysql(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW DATABASES")
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _criar_banco_mysql(credenciais: dict, nome: str) -> None:
    conn = conectar_mysql(credenciais)
    try:
        conn.autocommit(True)
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE `{nome}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# SQL Server
# ---------------------------------------------------------------------------

def _listar_bancos_sqlserver(credenciais: dict) -> list:
    conn = conectar_sqlserver(credenciais, database="master")
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sys.databases WHERE database_id > 4 ORDER BY name")
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _criar_banco_sqlserver(credenciais: dict, nome: str) -> None:
    conn = conectar_sqlserver(credenciais, database="master")
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE [{nome}]")
    finally:
        conn.close()


def _listar_schemas_sqlserver(credenciais: dict) -> list:
    conn = conectar_sqlserver(credenciais)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sys.schemas WHERE schema_id = 1 OR schema_id > 16383 ORDER BY name"
        )
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _criar_schema_sqlserver(credenciais: dict, nome: str) -> None:
    conn = conectar_sqlserver(credenciais)
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(f"CREATE SCHEMA [{nome}]")
    finally:
        conn.close()
# ---------------------------------------------------------------------------
# ClickHouse
# ---------------------------------------------------------------------------

def _listar_bancos_clickhouse(credenciais: dict) -> list:
    conn = conectar_clickhouse(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT name FROM system.databases
                WHERE name NOT IN ('system', 'INFORMATION_SCHEMA', 'information_schema')
                ORDER BY name
                """
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _criar_banco_clickhouse(credenciais: dict, nome: str) -> None:
    conn = conectar_clickhouse(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{nome}`")
    finally:
        conn.close()


def _listar_schemas_clickhouse(credenciais: dict) -> list:
    return [credenciais.get("database") or "default"]


# ---------------------------------------------------------------------------
# DuckDB
# ---------------------------------------------------------------------------

def _listar_bancos_duckdb(credenciais: dict) -> list:
    caminho = credenciais.get("database") or credenciais.get("host") or ""
    return [Path(str(caminho)).name or "duckdb"]


def _criar_banco_duckdb(credenciais: dict, nome: str) -> None:
    import duckdb

    caminho = credenciais.get("host") or ""
    if not caminho or str(caminho).strip() in (":memory:", "memory", ""):
        raise ValueError("Defina o caminho do arquivo .duckdb em HOST para criar um novo banco.")
    nome_arquivo = nome if nome.lower().endswith(".duckdb") else f"{nome}.duckdb"
    alvo = Path(caminho).parent / nome_arquivo
    alvo.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(alvo))
    conn.close()


def _listar_schemas_duckdb(credenciais: dict) -> list:
    conn = conectar_duckdb(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT schema_name FROM information_schema.schemata
                WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
                ORDER BY schema_name
                """
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _criar_schema_duckdb(credenciais: dict, nome: str) -> None:
    conn = conectar_duckdb(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{nome}"')
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Delta Lake
# ---------------------------------------------------------------------------

def _listar_bancos_deltalake(credenciais: dict) -> list:
    host = credenciais.get("host") or ""
    if delta_eh_s3(host):
        cliente = delta_cliente_s3(credenciais)
        return [b["Name"] for b in cliente.list_buckets().get("Buckets", [])]
    caminho = Path(host)
    return [caminho.name or "."] if caminho.exists() else ["."]


def _criar_banco_deltalake(credenciais: dict, nome: str) -> None:
    host = credenciais.get("host") or ""
    if delta_eh_s3(host):
        cliente = delta_cliente_s3(credenciais)
        cliente.create_bucket(Bucket=nome)
        return
    alvo = Path(host) / nome if nome != "." else Path(host)
    alvo.mkdir(parents=True, exist_ok=True)


def _listar_schemas_deltalake(credenciais: dict) -> list:
    return [credenciais.get("database") or credenciais.get("schema") or "deltalake"]
