"""Introspecção do banco de origem para geração automática de schemas YAML."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from conduto.database.adapters import (
    Adapter,
    conectar_clickhouse,
    conectar_duckdb,
    conectar_mysql,
    conectar_postgres,
    conectar_sqlserver,
    delta_base,
    delta_cliente_s3,
    delta_eh_s3,
    delta_storage_options,
)


def listar_tabelas(adapter: Adapter, credenciais: dict) -> List[Dict[str, str]]:
    """Lista as tabelas (schema + nome) do banco de origem."""
    if adapter.tipo == "postgresql":
        return _listar_tabelas_postgres(credenciais)
    if adapter.tipo == "mysql":
        return _listar_tabelas_mysql(credenciais)
    if adapter.tipo == "sqlserver":
        return _listar_tabelas_sqlserver(credenciais)
    if adapter.tipo == "clickhouse":
        return _listar_tabelas_clickhouse(credenciais)
    if adapter.tipo == "duckdb":
        return _listar_tabelas_duckdb(credenciais)
    if adapter.tipo == "deltalake":
        return _listar_tabelas_deltalake(credenciais)
    raise ValueError(f"Adapter desconhecido: {adapter.tipo}")


_CONEXOES = {
    "postgresql": conectar_postgres,
    "mysql": conectar_mysql,
    "sqlserver": conectar_sqlserver,
    "clickhouse": conectar_clickhouse,
    "duckdb": conectar_duckdb,
}


def abrir_conexao(adapter: Adapter, credenciais: dict):
    """Abre uma conexao para reutilizar na introspect de varias tabelas.

    Delta Lake nao usa conexao e devolve None (leitura direta dos arquivos).
    """
    if adapter.tipo == "deltalake":
        return None
    return _CONEXOES[adapter.tipo](credenciais)


def descrever_tabela(
    adapter: Adapter, credenciais: dict, schema: str, table: str, conexao=None
) -> Dict[str, Any]:
    """Descreve as colunas de uma tabela (tipos, PK, FK, unique, default, nullable).

    ``conexao`` permite reutilizar uma conexao ja aberta (abrir_conexao) para
    evitar abrir uma conexao por tabela; quando omitida, abre e fecha a propria.
    """
    if adapter.tipo == "postgresql":
        return _descrever_tabela_postgres(credenciais, schema, table, conexao)
    if adapter.tipo == "mysql":
        return _descrever_tabela_mysql(credenciais, schema, table, conexao)
    if adapter.tipo == "sqlserver":
        return _descrever_tabela_sqlserver(credenciais, schema, table, conexao)
    if adapter.tipo == "clickhouse":
        return _descrever_tabela_clickhouse(credenciais, schema, table, conexao)
    if adapter.tipo == "duckdb":
        return _descrever_tabela_duckdb(credenciais, schema, table, conexao)
    if adapter.tipo == "deltalake":
        return _descrever_tabela_deltalake(credenciais, schema, table)
    raise ValueError(f"Adapter desconhecido: {adapter.tipo}")


def inferir_tipo(data_type: Optional[str], comprimento: Optional[int] = None,
                 precisao: Optional[int] = None, escala: Optional[int] = None) -> str:
    """Converte o tipo nativo do SGBD para o formato usado nos schemas YAML."""
    t = (data_type or "").strip().lower()

    if t in ("character varying", "varchar", "nvarchar", "varchar2", "nvarchar2"):
        if comprimento is None or comprimento <= 0:
            return "text"
        return f"varchar({comprimento})"
    if t in ("character", "char", "nchar", "bpchar"):
        if comprimento is None or comprimento <= 0:
            return "char"
        return f"char({comprimento})"
    if t in ("text", "tinytext", "mediumtext", "longtext", "ntext",
             "string", "utf8", "large_string", "clob"):
        return "text"
    if t in ("numeric", "decimal"):
        if precisao is not None and escala is not None and escala > 0:
            return f"numeric({precisao}, {escala})"
        if precisao is not None:
            return f"numeric({precisao})"
        return "numeric"
    if t == "money":
        return "numeric(19, 4)"
    if t == "smallmoney":
        return "numeric(10, 4)"
    if t in ("int", "integer", "int4", "int32", "serial", "serial4",
             "mediumint", "uint16"):
        return "integer"
    if t in ("bigint", "int64", "bigserial", "serial8", "int128", "int256",
             "uint32", "uint64", "uint128", "uint256", "hugeint", "uhugeint"):
        return "bigint"
    if t in ("smallint", "int2", "int16", "uint8"):
        return "smallint"
    if t in ("tinyint", "int1", "int8"):
        return "tinyint"
    if t in ("boolean", "bool"):
        return "boolean"
    if t == "bit":
        return "boolean"
    if t in ("timestamp without time zone", "timestamp", "datetime",
             "datetime2", "smalldatetime"):
        return "timestamp"
    if t in ("timestamp with time zone", "timestamptz", "datetimeoffset"):
        return "timestamptz"
    if t in ("date", "date32", "date64"):
        return "date"
    if t in ("time", "time without time zone"):
        return "time"
    if t in ("time with time zone", "timetz"):
        return "timetz"
    if t in ("double precision", "double", "float8", "float64"):
        return "double"
    if t in ("real", "float", "float4", "float32"):
        return "float"
    if t in ("uuid", "uniqueidentifier"):
        return "uuid"
    if t in ("json", "jsonb"):
        return "json"
    if t in ("bytea", "blob", "tinyblob", "mediumblob", "longblob",
             "binary", "varbinary", "image", "large_binary"):
        return "binary"
    if t in ("enum", "enum8", "enum16"):
        return "enum"
    if t == "xml":
        return "xml"

    # Tipos compostos: ClickHouse, DuckDB e Delta (Arrow)
    if t.startswith(("nullable(", "lowcardinality(")):
        interno = t.split("(", 1)[1].rsplit(")", 1)[0]
        return inferir_tipo(interno, comprimento, precisao, escala)
    if t.startswith("fixedstring("):
        numeros = _extrair_ints(t)
        return f"char({numeros[0]})" if numeros else "char"
    if t.startswith(("decimal(", "numeric(")):
        numeros = _extrair_ints(t)
        if len(numeros) >= 2:
            return f"numeric({numeros[0]}, {numeros[1]})"
        if numeros:
            return f"numeric({numeros[0]})"
        return "numeric"
    if t.startswith("datetime64"):
        return "timestamp"
    if t.startswith(("time64", "time32")):
        return "time"
    if t.startswith("timestamp["):
        return "timestamptz" if "tz=" in t else "timestamp"
    if t.startswith(("enum8", "enum16")):
        return "enum"
    return t


def _extrair_ints(texto: str) -> List[int]:
    """Extrai os inteiros de uma string (ex.: 'decimal(10, 2)' -> [10, 2])."""
    import re
    return [int(x) for x in re.findall(r"\d+", texto)]



def limpar_default(default: Optional[str], tipo_sgbd: str) -> Optional[str]:
    """Limpa o default vindo do catálogo para o formato dos schemas YAML."""
    if default is None:
        return None
    d = str(default).strip()
    if not d or d == "NULL":
        return None

    if tipo_sgbd == "postgresql":
        if d.startswith("nextval("):  # serial/identity geram nextval(...)
            return None
        if d.lower() in ("current_timestamp", "now()"):
            return "CURRENT_TIMESTAMP"
        if "::" in d:  # remove cast: 'valor'::text -> 'valor'
            d = d.split("::", 1)[0].strip()
        if len(d) >= 2 and d.startswith("'") and d.endswith("'"):
            d = d[1:-1]
    elif tipo_sgbd == "sqlserver":
        if "getdate()" in d.lower():
            return "CURRENT_TIMESTAMP"
        if d.startswith("((") and d.endswith("))"):
            d = d[1:-1]
        elif d.startswith("(") and d.endswith(")"):
            d = d[1:-1]
        if d.startswith("N'") and d.endswith("'"):
            d = d[1:]  # N'valor' -> 'valor'
        if len(d) >= 2 and d.startswith("'") and d.endswith("'"):
            d = d[1:-1]
    elif tipo_sgbd == "duckdb":
        if d.startswith("nextval("):
            return None
        if "::" in d:  # remove cast: 'x'::DATE -> 'x'
            d = d.split("::", 1)[0].strip()
        if len(d) >= 2 and d.startswith("'") and d.endswith("'"):
            d = d[1:-1]
    elif tipo_sgbd == "mysql":
        if d.lower() in ("current_timestamp", "current_timestamp()", "now()"):
            return "CURRENT_TIMESTAMP"

    return d or None


def _formatar_fk(ref_schema: Optional[str], ref_table: Optional[str],
                 ref_col: Optional[str], schema_atual: str) -> Optional[str]:
    if not ref_table or not ref_col:
        return None
    prefixo = f"{ref_schema}." if ref_schema and ref_schema != schema_atual else ""
    return f"{prefixo}{ref_table}({ref_col})"


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------

def _listar_tabelas_postgres(credenciais: dict) -> List[Dict[str, str]]:
    conn = conectar_postgres(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_type = 'BASE TABLE'
                  AND table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name
            """)
            return [{"schema": s, "table": t} for s, t in cur.fetchall()]
    finally:
        conn.close()


def _descrever_tabela_postgres(credenciais: dict, schema: str, table: str, conexao=None) -> Dict[str, Any]:
    proprio = conexao is None
    conn = conexao or conectar_postgres(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name, data_type, character_maximum_length,
                       numeric_precision, numeric_scale, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (schema, table))
            colunas_raw = cur.fetchall()

            cur.execute("""
                SELECT column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_schema = %s AND tc.table_name = %s
            """, (schema, table))
            pks = {r[0] for r in cur.fetchall()}

            cur.execute("""
                SELECT column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'UNIQUE'
                  AND tc.table_schema = %s AND tc.table_name = %s
            """, (schema, table))
            uniques = {r[0] for r in cur.fetchall()}

            cur.execute("""
                SELECT kcu.column_name, ccu.table_schema, ccu.table_name, ccu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = %s AND tc.table_name = %s
            """, (schema, table))
            fk_por_coluna = {}
            for col, ref_schema, ref_table, ref_col in cur.fetchall():
                fk_por_coluna[col] = (ref_schema, ref_table, ref_col)
    finally:
        if proprio:
            conn.close()

    colunas = []
    for nome, tipo, comprimento, precisao, escala, is_nullable, default in colunas_raw:
        colunas.append({
            "name": nome,
            "type": inferir_tipo(tipo, comprimento, precisao, escala),
            "nullable": is_nullable == "YES",
            "primary_key": nome in pks,
            "unique": nome in uniques and nome not in pks,
            "default": limpar_default(default, "postgresql"),
            "foreign_key": _formatar_fk(*fk_por_coluna.get(nome, (None, None, None)), schema),
        })
    return {"table": table, "schema": schema, "columns": colunas}


# ---------------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------------

def _listar_tabelas_mysql(credenciais: dict) -> List[Dict[str, str]]:
    conn = conectar_mysql(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT TABLE_SCHEMA, TABLE_NAME
                FROM information_schema.tables
                WHERE TABLE_TYPE = 'BASE TABLE'
                  AND TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME
            """)
            return [{"schema": r[0], "table": r[1]} for r in cur.fetchall()]
    finally:
        conn.close()


def _descrever_tabela_mysql(credenciais: dict, schema: str, table: str, conexao=None) -> Dict[str, Any]:
    proprio = conexao is None
    conn = conexao or conectar_mysql(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
                       NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE, COLUMN_DEFAULT
                FROM information_schema.columns
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
            """, (table,))
            colunas_raw = cur.fetchall()

            cur.execute("""
                SELECT COLUMN_NAME
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                  AND CONSTRAINT_NAME = 'PRIMARY'
                ORDER BY ORDINAL_POSITION
            """, (table,))
            pks = {r[0] for r in cur.fetchall()}

            cur.execute("""
                SELECT kcu.COLUMN_NAME
                FROM information_schema.TABLE_CONSTRAINTS tc
                JOIN information_schema.KEY_COLUMN_USAGE kcu
                  ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                 AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                WHERE tc.CONSTRAINT_TYPE = 'UNIQUE'
                  AND tc.TABLE_SCHEMA = DATABASE() AND tc.TABLE_NAME = %s
            """, (table,))
            uniques = {r[0] for r in cur.fetchall()}

            cur.execute("""
                SELECT COLUMN_NAME, REFERENCED_TABLE_SCHEMA,
                       REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                  AND REFERENCED_TABLE_NAME IS NOT NULL
            """, (table,))
            fk_por_coluna = {}
            for col, ref_schema, ref_table, ref_col in cur.fetchall():
                fk_por_coluna[col] = (ref_schema, ref_table, ref_col)
    finally:
        if proprio:
            conn.close()

    colunas = []
    for nome, tipo, comprimento, precisao, escala, is_nullable, default in colunas_raw:
        colunas.append({
            "name": nome,
            "type": inferir_tipo(tipo, comprimento, precisao, escala),
            "nullable": is_nullable == "YES",
            "primary_key": nome in pks,
            "unique": nome in uniques and nome not in pks,
            "default": limpar_default(default, "mysql"),
            "foreign_key": _formatar_fk(*fk_por_coluna.get(nome, (None, None, None)), schema),
        })
    return {"table": table, "schema": schema, "columns": colunas}


# ---------------------------------------------------------------------------
# SQL Server
# ---------------------------------------------------------------------------

def _listar_tabelas_sqlserver(credenciais: dict) -> List[Dict[str, str]]:
    conn = conectar_sqlserver(credenciais)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.name, t.name
            FROM sys.tables t
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE s.name NOT IN ('sys', 'INFORMATION_SCHEMA')
            ORDER BY s.name, t.name
        """)
        return [{"schema": r[0], "table": r[1]} for r in cur.fetchall()]
    finally:
        conn.close()


def _descrever_tabela_sqlserver(credenciais: dict, schema: str, table: str, conexao=None) -> Dict[str, Any]:
    proprio = conexao is None
    conn = conexao or conectar_sqlserver(credenciais)
    objeto = f"{schema}.{table}"
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.name, ty.name,
                   CASE WHEN ty.name IN ('nvarchar', 'nchar')
                        THEN c.max_length / 2 ELSE c.max_length END AS max_length,
                   c.precision, c.scale, c.is_nullable, dc.definition
            FROM sys.columns c
            JOIN sys.types ty ON c.user_type_id = ty.user_type_id
            LEFT JOIN sys.default_constraints dc ON c.default_object_id = dc.object_id
            WHERE c.object_id = OBJECT_ID(?)
            ORDER BY c.column_id
        """, (objeto,))
        colunas_raw = cur.fetchall()

        cur.execute("""
            SELECT c.name
            FROM sys.indexes i
            JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            WHERE i.object_id = OBJECT_ID(?) AND i.is_primary_key = 1
            ORDER BY ic.key_ordinal
        """, (objeto,))
        pks = {r[0] for r in cur.fetchall()}

        cur.execute("""
            SELECT c.name
            FROM sys.indexes i
            JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            WHERE i.object_id = OBJECT_ID(?) AND i.is_unique_constraint = 1
            ORDER BY ic.key_ordinal
        """, (objeto,))
        uniques = {r[0] for r in cur.fetchall()}

        cur.execute("""
            SELECT c.name,
                   OBJECT_SCHEMA_NAME(fkc.referenced_object_id),
                   OBJECT_NAME(fkc.referenced_object_id),
                   rc.name
            FROM sys.foreign_key_columns fkc
            JOIN sys.columns c ON fkc.parent_object_id = c.object_id AND fkc.parent_column_id = c.column_id
            JOIN sys.columns rc ON fkc.referenced_object_id = rc.object_id AND fkc.referenced_column_id = rc.column_id
            WHERE fkc.parent_object_id = OBJECT_ID(?)
        """, (objeto,))
        fk_por_coluna = {}
        for col, ref_schema, ref_table, ref_col in cur.fetchall():
            fk_por_coluna[col] = (ref_schema, ref_table, ref_col)
    finally:
        if proprio:
            conn.close()

    colunas = []
    for nome, tipo, comprimento, precisao, escala, is_nullable, default in colunas_raw:
        colunas.append({
            "name": nome,
            "type": inferir_tipo(tipo, comprimento, precisao, escala),
            "nullable": bool(is_nullable),
            "primary_key": nome in pks,
            "unique": nome in uniques and nome not in pks,
            "default": limpar_default(default, "sqlserver"),
            "foreign_key": _formatar_fk(*fk_por_coluna.get(nome, (None, None, None)), schema),
        })
    return {"table": table, "schema": schema, "columns": colunas}
# ---------------------------------------------------------------------------
# ClickHouse
# ---------------------------------------------------------------------------

def _listar_tabelas_clickhouse(credenciais: dict) -> List[Dict[str, str]]:
    conn = conectar_clickhouse(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT database, name
                FROM system.tables
                WHERE database = currentDatabase()
                  AND is_temporary = 0 AND engine != 'View'
                ORDER BY database, name
                """
            )
            return [{"schema": d, "table": t} for d, t in cur.fetchall()]
    finally:
        conn.close()


def _descrever_tabela_clickhouse(credenciais: dict, schema: str, table: str, conexao=None) -> Dict[str, Any]:
    proprio = conexao is None
    conn = conexao or conectar_clickhouse(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT name, type, default_expression, is_in_primary_key
                FROM system.columns
                WHERE database = %s AND table = %s
                ORDER BY position
                """,
                (schema, table),
            )
            colunas_raw = cur.fetchall()

            cur.execute(
                """
                SELECT engine, sorting_key, partition_key
                FROM system.tables
                WHERE database = %s AND name = %s
                """,
                (schema, table),
            )
            linha_tabela = cur.fetchone()
    finally:
        if proprio:
            conn.close()

    colunas = []
    for nome, tipo, default, eh_pk in colunas_raw:
        nullable = tipo.startswith("Nullable(")
        tipo_base = tipo[len("Nullable("):-1] if nullable else tipo
        colunas.append({
            "name": nome,
            "type": inferir_tipo(tipo_base),
            "nullable": nullable,
            "primary_key": bool(eh_pk),
            "unique": False,
            "default": limpar_default(default, "clickhouse"),
            "foreign_key": None,
        })
    resultado = {"table": table, "schema": schema, "columns": colunas}
    if linha_tabela:
        engine, sorting_key, partition_key = linha_tabela
        if engine:
            resultado["engine"] = engine
        if sorting_key:
            resultado["order_by"] = sorting_key
        if partition_key:
            resultado["partition_by"] = partition_key
    return resultado


# ---------------------------------------------------------------------------
# DuckDB
# ---------------------------------------------------------------------------

def _listar_tabelas_duckdb(credenciais: dict) -> List[Dict[str, str]]:
    conn = conectar_duckdb(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_type = 'BASE TABLE'
                  AND table_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY table_schema, table_name
                """
            )
            return [{"schema": s, "table": t} for s, t in cur.fetchall()]
    finally:
        conn.close()


def _descrever_tabela_duckdb(credenciais: dict, schema: str, table: str, conexao=None) -> Dict[str, Any]:
    proprio = conexao is None
    conn = conexao or conectar_duckdb(credenciais)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = ? AND table_name = ?
                ORDER BY ordinal_position
                """,
                (schema, table),
            )
            colunas_raw = cur.fetchall()

            cur.execute(
                """
                SELECT constraint_type, constraint_column_names,
                       referenced_table, referenced_column_names
                FROM duckdb_constraints()
                WHERE schema_name = ? AND table_name = ?
                """,
                (schema, table),
            )
            restricoes = cur.fetchall()
    finally:
        if proprio:
            conn.close()

    pks: set = set()
    uniques: set = set()
    fk_por_coluna: dict = {}
    for tipo, cols, ref_tabela, ref_cols in restricoes:
        if tipo == "PRIMARY KEY":
            pks.update(cols)
        elif tipo == "UNIQUE":
            uniques.update(cols)
        elif tipo == "FOREIGN KEY":
            if "." in ref_tabela:
                ref_schema, _, nome_ref = ref_tabela.partition(".")
            else:
                ref_schema, nome_ref = schema, ref_tabela
            for col, ref_col in zip(cols, ref_cols or []):
                fk_por_coluna[col] = (ref_schema, nome_ref, ref_col)

    colunas = []
    for nome, tipo, is_nullable, default in colunas_raw:
        colunas.append({
            "name": nome,
            "type": inferir_tipo(tipo),
            "nullable": is_nullable in ("YES", True),
            "primary_key": nome in pks,
            "unique": nome in uniques and nome not in pks,
            "default": limpar_default(default, "duckdb"),
            "foreign_key": _formatar_fk(*fk_por_coluna.get(nome, (None, None, None)), schema),
        })
    return {"table": table, "schema": schema, "columns": colunas}


# ---------------------------------------------------------------------------
# Delta Lake
# ---------------------------------------------------------------------------

def _listar_tabelas_deltalake(credenciais: dict) -> List[Dict[str, str]]:
    host = credenciais.get("host") or ""
    if delta_eh_s3(host):
        base = delta_base(credenciais)  # s3://bucket[/prefixo]
        if host.startswith("http"):
            bucket = base.split("://", 1)[1]
        else:
            bucket = base.split("://", 1)[1].split("/", 1)[0]
        prefixo = ""
        if "/" in base.split("://", 1)[1]:
            prefixo = base.split("://", 1)[1].split("/", 1)[1].rstrip("/") + "/"
        cliente = delta_cliente_s3(credenciais)
        resposta = cliente.list_objects_v2(Bucket=bucket, Delimiter="/", Prefix=prefixo)
        return [
            {"schema": bucket, "table": p["Prefix"].strip("/").split("/")[-1]}
            for p in resposta.get("CommonPrefixes", [])
        ]
    base = Path(host)
    if not base.exists():
        return []
    return [
        {"schema": base.name or ".", "table": p.name}
        for p in sorted(base.iterdir())
        if p.is_dir() and (p / "_delta_log").exists()
    ]


def _descrever_tabela_deltalake(credenciais: dict, schema: str, table: str) -> Dict[str, Any]:
    from deltalake import DeltaTable

    caminho = f"{delta_base(credenciais)}/{table}"
    opcoes = delta_storage_options(credenciais) or None
    tabela = DeltaTable(caminho, storage_options=opcoes)
    colunas = []
    for campo in tabela.schema().fields:
        tipo_texto = str(campo.type)
        primitivo = re.search(r'PrimitiveType\("([^"]+)"\)', tipo_texto)
        if primitivo:
            tipo_texto = primitivo.group(1)
        colunas.append({
            "name": campo.name,
            "type": inferir_tipo(tipo_texto),
            "nullable": campo.nullable,
            "primary_key": False,
            "unique": False,
            "default": None,
            "foreign_key": None,
        })
    return {"table": table, "schema": schema, "columns": colunas}
