"""Opera\u00e7\u00f5es de cat\u00e1logo: listar/criar bancos e schemas dos SGBDs suportados."""

import re

from conduto.database.adapters import (
    Adapter,
    conectar_mysql,
    conectar_postgres,
    conectar_sqlserver,
)

_IDENTIFICADOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validar_identificador(nome: str, tipo: str) -> None:
    if not nome or not _IDENTIFICADOR.match(nome):
        raise ValueError(f"'{nome}' n\u00e3o \u00e9 um nome v\u00e1lido para {tipo}.")


def schema_padrao_sgbd(adapter: Adapter, credenciais: dict) -> str:
    """Schema padr\u00e3o do SGBD (public, dbo ou o pr\u00f3prio banco no MySQL)."""
    if adapter.tipo == "mysql":
        return credenciais.get("database") or "mysql"
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
    raise ValueError(f"Adapter desconhecido: {adapter.tipo}")


def criar_banco(adapter: Adapter, credenciais: dict, nome: str) -> None:
    _validar_identificador(nome, "banco")
    if adapter.tipo == "postgresql":
        _criar_banco_postgres(credenciais, nome)
    elif adapter.tipo == "mysql":
        _criar_banco_mysql(credenciais, nome)
    elif adapter.tipo == "sqlserver":
        _criar_banco_sqlserver(credenciais, nome)
    else:
        raise ValueError(f"Adapter desconhecido: {adapter.tipo}")


def listar_schemas(adapter: Adapter, credenciais: dict) -> list:
    if adapter.tipo == "postgresql":
        return _listar_schemas_postgres(credenciais)
    if adapter.tipo == "mysql":
        return [credenciais.get("database") or "mysql"]
    if adapter.tipo == "sqlserver":
        return _listar_schemas_sqlserver(credenciais)
    raise ValueError(f"Adapter desconhecido: {adapter.tipo}")


def criar_schema(adapter: Adapter, credenciais: dict, nome: str) -> None:
    if adapter.tipo == "mysql":
        raise ValueError("No MySQL o schema \u00e9 o pr\u00f3prio banco; crie um banco.")
    _validar_identificador(nome, "schema")
    if adapter.tipo == "postgresql":
        _criar_schema_postgres(credenciais, nome)
    elif adapter.tipo == "sqlserver":
        _criar_schema_sqlserver(credenciais, nome)
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