"""Introspecção do banco de origem para geração automática de schemas YAML."""

from typing import Any, Dict, List, Optional

from conduto.database.adapters import Adapter, conectar_mysql, conectar_postgres, conectar_sqlserver


def listar_tabelas(adapter: Adapter, credenciais: dict) -> List[Dict[str, str]]:
    """Lista as tabelas (schema + nome) do banco de origem."""
    if adapter.tipo == "postgresql":
        return _listar_tabelas_postgres(credenciais)
    if adapter.tipo == "mysql":
        return _listar_tabelas_mysql(credenciais)
    if adapter.tipo == "sqlserver":
        return _listar_tabelas_sqlserver(credenciais)
    raise ValueError(f"Adapter desconhecido: {adapter.tipo}")


def descrever_tabela(adapter: Adapter, credenciais: dict, schema: str, table: str) -> Dict[str, Any]:
    """Descreve as colunas de uma tabela (tipos, PK, FK, unique, default, nullable)."""
    if adapter.tipo == "postgresql":
        return _descrever_tabela_postgres(credenciais, schema, table)
    if adapter.tipo == "mysql":
        return _descrever_tabela_mysql(credenciais, schema, table)
    if adapter.tipo == "sqlserver":
        return _descrever_tabela_sqlserver(credenciais, schema, table)
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
    if t in ("text", "tinytext", "mediumtext", "longtext", "ntext"):
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
    if t in ("int", "integer", "int4", "serial", "serial4", "mediumint"):
        return "integer"
    if t in ("bigint", "int8", "bigserial", "serial8"):
        return "bigint"
    if t in ("smallint", "int2"):
        return "smallint"
    if t in ("tinyint", "int1"):
        return "tinyint"
    if t in ("boolean", "bool"):
        return "boolean"
    if t == "bit":
        return "boolean"
    if t in ("timestamp without time zone", "timestamp", "datetime", "datetime2", "smalldatetime"):
        return "timestamp"
    if t in ("timestamp with time zone", "timestamptz", "datetimeoffset"):
        return "timestamptz"
    if t == "date":
        return "date"
    if t in ("time", "time without time zone"):
        return "time"
    if t in ("time with time zone", "timetz"):
        return "timetz"
    if t in ("double precision", "double", "float8"):
        return "double"
    if t in ("real", "float", "float4"):
        return "float"
    if t in ("uuid", "uniqueidentifier"):
        return "uuid"
    if t in ("json", "jsonb"):
        return "json"
    if t in ("bytea", "blob", "tinyblob", "mediumblob", "longblob",
             "binary", "varbinary", "image"):
        return "binary"
    if t == "enum":
        return "enum"
    if t == "xml":
        return "xml"
    return t


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


def _descrever_tabela_postgres(credenciais: dict, schema: str, table: str) -> Dict[str, Any]:
    conn = conectar_postgres(credenciais)
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


def _descrever_tabela_mysql(credenciais: dict, schema: str, table: str) -> Dict[str, Any]:
    conn = conectar_mysql(credenciais)
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


def _descrever_tabela_sqlserver(credenciais: dict, schema: str, table: str) -> Dict[str, Any]:
    conn = conectar_sqlserver(credenciais)
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
