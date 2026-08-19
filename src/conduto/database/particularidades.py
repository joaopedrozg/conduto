from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class ParticularidadesSGBD:
    """Particularidades de um SGBD suportado pelo conduto.

    Centraliza como o conduto deve se comportar para cada SGBD: se o
    schema do projeto é um banco ou um schema de verdade, quais
    constraints existem no CREATE TABLE, defaults de engine/order by
    (ClickHouse), chaves extras aceitas no schema YAML e notas exibidas
    no fluxo do CLI e na documentação.
    """

    tipo: str
    nome: str
    # database (banco == schema) ou schema (schema de verdade)
    schema_recurso: str
    # Constraints suportadas no CREATE TABLE
    suporta_pk: bool = True
    suporta_unique: bool = True
    suporta_fk: bool = True
    # ClickHouse: engine padrão e ORDER BY obrigatório do MergeTree
    engine_padrao: str | None = None
    requer_order_by: bool = False
    # Chaves extras aceitas no schema YAML por tabela
    chaves_tabela: Tuple[str, ...] = ()
    # Criação de banco/schema no fluxo do CLI
    suporta_criar_banco: bool = True
    suporta_criar_schema: bool = True
    # Notas exibidas no fluxo do CLI/docs (chaves de i18n em pt)
    notas: Tuple[str, ...] = ()


PARTICULARIDADES: Dict[str, ParticularidadesSGBD] = {
    'postgresql': ParticularidadesSGBD(
        tipo='postgresql',
        nome='PostgreSQL',
        schema_recurso='schema',
        notas=('Schema explícito (padrão: public).',),
    ),
    'mysql': ParticularidadesSGBD(
        tipo='mysql',
        nome='MySQL',
        schema_recurso='database',
        notas=('No MySQL o schema é o próprio banco.',),
    ),
    'sqlserver': ParticularidadesSGBD(
        tipo='sqlserver',
        nome='SQL Server',
        schema_recurso='schema',
        notas=('Schema explícito (padrão: dbo).',),
    ),
    'clickhouse': ParticularidadesSGBD(
        tipo='clickhouse',
        nome='ClickHouse',
        schema_recurso='database',
        suporta_pk=False,
        suporta_unique=False,
        suporta_fk=False,
        engine_padrao='MergeTree',
        requer_order_by=True,
        chaves_tabela=('engine', 'order_by', 'partition_by'),
        suporta_criar_schema=False,
        notas=(
            'Engine padrão: MergeTree (chave engine no schema para trocar).',
            'Sem constraints de PK/FK/unique: a chave primária vira o ORDER BY do MergeTree.',
            'Chaves por tabela: engine, order_by e partition_by.',
        ),
    ),
    'duckdb': ParticularidadesSGBD(
        tipo='duckdb',
        nome='DuckDB',
        schema_recurso='schema',
        notas=('Schema explícito (padrão: main).',),
    ),
    'deltalake': ParticularidadesSGBD(
        tipo='deltalake',
        nome='Delta Lake',
        schema_recurso='database',
        suporta_pk=False,
        suporta_unique=False,
        suporta_fk=False,
        suporta_criar_schema=False,
        notas=('Sem constraints de PK/FK/unique no CREATE TABLE (Delta Lake).',),
    ),
}


def particularidades_sgbd(tipo: str) -> ParticularidadesSGBD:
    """Devolve as particularidades do SGBD (levanta erro se não mapeado)."""
    try:
        return PARTICULARIDADES[tipo]
    except KeyError:
        raise ValueError(
            f'Tipo de SGBD sem particularidades mapeadas: {tipo!r}'
        ) from None
