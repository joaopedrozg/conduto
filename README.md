# conduto

**O duto que leva seus dados da origem ao destino.**

CLI para criar projetos de migração/ELT de dados: gera o `.env` com as credenciais dos bancos, o manifesto `main.yml`, os schemas YAML das tabelas e configura o ambiente com `uv` (`pyyaml`, `jinja2`, `polars`, `dagster`).

**Repositório:** [github.com/joaopedrozg/conduto](https://github.com/joaopedrozg/conduto)

## Funcionalidades

- Scaffold completo de projeto ELT em um único comando
- Fluxo interativo para configurar bancos de origem e destino (PostgreSQL, MySQL, SQL Server)
- Geração do `.env` com as credenciais das duas pontas do duto
- Manifesto `main.yml` com a ordem de dependência das tabelas
- Schemas YAML de exemplo (clientes, pedidos e produtos) com PK, FK, `unique` e `default`
- Ambiente Python gerenciado por `uv` com `pyyaml`, `jinja2`, `polars` e `dagster`
- Adapta-se automaticamente a um projeto uv existente (gera direto no projeto atual, sem subpasta nem `uv init`)
- Feedback visual com `rich` e `questionary`

## Instalação

```bash
pip install conduto
```

Ou, para usar sem sujar o ambiente atual:

```bash
uv tool install conduto
```

## Uso

Crie um novo projeto de migração:

```bash
conduto init meu_projeto
```

O comando pergunta interativamente:

1. SGBD de origem (PostgreSQL, MySQL ou SQL Server)
2. Credenciais de origem (host, porta, banco, usuário e senha)
3. SGBD de destino
4. Credenciais de destino

**Dentro de um projeto uv?** Se o diretório atual já tem `pyproject.toml` (por exemplo, após `uv add conduto`), o conduto se adapta: gera `.env`, `main.yml` e `schemas/` direto no projeto atual e adiciona só as dependências que faltam — sem criar subpasta nem rodar `uv init`. Nesse caso, use `uv run conduto init` (o nome do projeto vira opcional).

## O que é gerado

```text
meu_projeto/
├── .env
├── main.yml
├── schemas/
│   ├── clientes.yml
│   ├── pedidos.yml
│   └── produtos.yml
└── ambiente uv (pyyaml, jinja2, polars, dagster)
```

> Fora de um projeto uv, essa estrutura é criada dentro de `meu_projeto/`. Dentro de um projeto uv já existente, os arquivos são gerados no diretório atual.

### `.env` — credenciais

Guarda as credenciais de origem e destino em variáveis `DB_ORIGEM_*` e `DB_DESTINO_*`:

```bash
DB_ORIGEM_HOST=localhost
DB_ORIGEM_PORT=5432
DB_ORIGEM_NAME=postgres
DB_ORIGEM_USER=postgres
DB_ORIGEM_PASSWORD=postgres

DB_DESTINO_HOST=localhost
DB_DESTINO_PORT=5432
DB_DESTINO_NAME=postgres
DB_DESTINO_USER=postgres
DB_DESTINO_PASSWORD=postgres
```

> **Importante:** o `.env` contém credenciais e não deve ser versionado.

### `main.yml` — manifesto

Define a versão do projeto e a lista de schemas na ordem correta de dependência:

```yaml
version: "1.0"
project: meu_projeto

tables:
  - path: "schemas/clientes.yml"
  - path: "schemas/pedidos.yml"
  - path: "schemas/produtos.yml"
```

### `schemas/*.yml` — tabelas

Schemas YAML que descrevem as tabelas: tipos, chave primária, foreign keys, `unique` e `default`.

```yaml
table: clientes
schema: public
description: "Tabela de cadastro de clientes"
columns:
  - name: id
    type: integer
    primary_key: true
    nullable: false
  - name: nome
    type: varchar(255)
    nullable: false
```

Os três exemplos cobrem padrões comuns de modelagem:

| Schema | O que demonstra |
| --- | --- |
| `clientes.yml` | chave primária, coluna `unique` e `default` com `CURRENT_TIMESTAMP` |
| `pedidos.yml` | chave estrangeira com `foreign_key: clientes(id)` |
| `produtos.yml` | tipos `numeric` e `boolean`, colunas opcionais (`nullable: true`) |

### Ambiente `uv`

Se ainda não existir `pyproject.toml`, o conduto inicializa o projeto e instala as dependências do pipeline:

```bash
uv init --no-readme
uv add pyyaml jinja2 polars dagster
```

## Como funciona

1. `cli.py` faz as perguntas de origem e destino e monta o contexto
2. `env_render` renderiza o template do `.env`
3. `schemas_render` renderiza o `main.yml` e os schemas em `schemas/`
4. `setup_uv_environment` roda `uv init` (se necessário) e `uv add` das dependências

## Próximos passos

1. Ajuste os schemas em `schemas/` às suas tabelas reais
2. Revise o `.env` com as credenciais corretas de origem e destino
3. Escreva suas definições Dagster (assets/jobs) dentro do projeto
4. Rode e itere com `uv run dagster dev` (o Dagster já vem instalado)

## Desenvolvimento

```bash
uv sync
uv build
uv publish
```

## Licença

MIT
