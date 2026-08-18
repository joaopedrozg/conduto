# conduto

**O duto que leva seus dados da origem ao destino.**

CLI para criar projetos de migração/ELT de dados: gera o `.env` com as credenciais dos bancos, o manifesto `main.yml`, os schemas YAML das tabelas e configura o ambiente com `uv` (`pyyaml`, `jinja2`, `polars`, `dagster`, `dagster-webserver`).

**Repositório:** [github.com/joaopedrozg/conduto](https://github.com/joaopedrozg/conduto)

## Funcionalidades

- Scaffold completo de projeto ELT em um único comando
- Fluxo interativo para configurar bancos de origem e destino (PostgreSQL, MySQL, SQL Server)
- Geração do `.env` com as credenciais das duas pontas do duto
- Manifesto `main.yml` com a ordem de dependência das tabelas
- Schemas YAML de exemplo (clientes, pedidos e produtos) com PK, FK, `unique` e `default`
- Ambiente Python gerenciado por `uv` com `pyyaml`, `jinja2`, `polars`, `dagster` e `dagster-webserver`
- Adapta-se automaticamente a um projeto uv existente (gera direto no projeto atual, sem subpasta nem `uv init`)
- Adapters de conexão com defaults por SGBD (porta, banco e usuário)
- Teste de conexão antes de gerar o projeto (com opção de digitar novamente ou seguir mesmo assim)
- Navegação pelos bancos e schemas do servidor — sem precisar digitar o nome do banco
- Opção de criar banco e schema no destino direto pelo fluxo interativo
- Geração automática de schemas a partir do banco de origem: lista tabelas e colunas, infere tipos, PK, FK, unique e default
- Ordenação do `main.yml` por dependência (pais antes de filhos)
- Gerenciamento automático de schedules: infere colunas de atualização incremental, cria um schedule padrão de hora em hora por tabela e um schedule para o modelo geral
- Geração de código Dagster padrão que segue a chave `schedule` de cada schema (`cron`, `mode`, `incremental_column`, `full_load` e `truncate`)
- Comando `conduto schedules` para (re)gerar os schedules e o código Dagster de um projeto existente
- Credenciais visíveis no prompt durante o preenchimento — só vão para o `.env`
- Instalação da lib oficial do SGBD escolhido (`psycopg[binary]`, `pymysql`, `pyodbc`)
- Download/instalação automática do ODBC Driver for SQL Server (Windows, Linux e macOS)
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

1. SGBD de origem (PostgreSQL, MySQL ou SQL Server) — os defaults de porta e usuário mudam conforme o SGBD
2. Credenciais do servidor de origem (host, porta, usuário e senha) — sem precisar digitar o banco
3. Teste de conexão — se falhar, escolha entre digitar novamente ou continuar mesmo assim
4. Lista de bancos do servidor de origem — escolha um
5. Lista de schemas do banco escolhido — escolha um
6. SGBD de destino
7. Credenciais de destino, com o mesmo fluxo — e com opção de **criar um banco e/ou schema novo**
8. Como configurar os schemas: **gerar automaticamente** a partir do banco de origem (tabelas, colunas e tipos inferidos) ou **configurar manualmente** (gera os exemplos)
9. Gerenciamento de schedules — pergunta se você quer gerar automaticamente o schedule de cada tabela (padrão: hora em hora) e o código Dagster correspondente
10. Servidor Dagster — pergunta se você quer subir o servidor agora (`uv run dagster dev`) e gera os scripts `run_dagster.ps1`/`run_dagster.sh`

**Dentro de um projeto uv?** Se o diretório atual já tem `pyproject.toml` (por exemplo, após `uv add conduto`), o conduto se adapta: gera `.env`, `main.yml` e `schemas/` direto no projeto atual e adiciona só as dependências que faltam — sem criar subpasta nem rodar `uv init`. **Dentro de um projeto uv?** Se o diretório atual já tem `pyproject.toml` (por exemplo, após `uv add conduto`), o conduto se adapta: gera `.env`, `main.yml` e `schemas/` direto no projeto atual e adiciona só as dependências que faltam — sem criar subpasta nem rodar `uv init`. Nesse caso, use `uv run conduto init` (o nome do projeto vira opcional).

### Geração automática de schemas

Depois de testar as duas conexões, o conduto pergunta como você quer configurar os schemas das tabelas:

- **Gerar automaticamente**: o conduto lista as tabelas do banco de origem, permite buscar por nome e marcar/desmarcar quais incluir, lê as colunas (tipos, PK, FK, unique, default e nullable) e gera os `schemas/*.yml` e o `main.yml` na ordem de dependência (pais antes de filhos).
- **Configurar manualmente**: mantém o comportamento atual e gera os três schemas de exemplo (clientes, pedidos e produtos) para você editar.

### DDL para o banco de destino

Depois de gerar os schemas, o `conduto ddl` converte tudo em `CREATE TABLE` para o banco de destino. Antes de gerar, ele pergunta se você quer **aplicar agora** no banco de destino ou **apenas gerar o DDL** para aplicar depois. No `conduto init` (modo **gerar automaticamente**), a mesma pergunta aparece ao final da geração dos schemas:

```bash
# pergunta se quer aplicar agora ou só gerar
conduto ddl

# salva o DDL em um arquivo .sql (aplicação fica para depois)
conduto ddl --output ddl.sql

# aplica direto no banco de destino (cria o schema se necessário), sem perguntar
conduto ddl --apply

# apenas gera o DDL, sem perguntar
conduto ddl --no-apply
```

As flags `--apply` e `--no-apply` pulam a pergunta interativa (útil para scripts). O comando lê o `.env` (credenciais de destino), o `main.yml` (ordem de dependência) e os `schemas/*.yml`, traduzindo tipos e funções (ex.: `gen_random_uuid()`, `clock_timestamp()`) para o SGBD de destino (PostgreSQL, MySQL ou SQL Server). Por padrão roda no diretório atual; use `--dir caminho/do/projeto` para outro diretório.

### Inferindo colunas de tabelas novas

Para adicionar uma tabela nova ao projeto, crie o schema com apenas o nome
(ou adicione o caminho no `main.yml`) e deixe as colunas para o conduto:

```yaml
# schemas/minha_tabela.yml
table: minha_tabela
```

```bash
# infere as colunas de todos os schemas sem colunas e registra no main.yml
conduto inferir

# ou infere/atualiza uma tabela específica
conduto inferir --tabela minha_tabela
```

O comando lê as credenciais de origem do `.env`, consulta o banco (tipos, PK,
FK, unique, default e nullable) e escreve as `columns:` no schema, preservando
o que já existir (description, schedule etc.). Depois rode `conduto schedules`
para gerar o schedule e o código Dagster da tabela nova.

### Schedules e Dagster

Ao final do `conduto init`, o conduto pergunta se você quer **gerenciar os schedules automaticamente**. Se sim:

- Mapeia as tabelas e tenta inferir a coluna de atualização incremental (watermark): prioriza colunas como `updated_at`/`atualizado_em`, depois `created_at`/`criado_em` e, por fim, qualquer coluna temporal
- Cria um schedule padrão de hora em hora (`0 * * * *`) para cada tabela, gravado na chave `schedule` do schema YAML — edite à vontade:

```yaml
schedule:
  cron: "0 * * * *"
  mode: incremental        # incremental (usa incremental_column) ou full
  incremental_column: updated_at
  full_load: false          # true força uma carga completa na próxima execução
  truncate: false           # true limpa a tabela de destino antes de carregar
```

- Adiciona o schedule do **modelo geral** no `main.yml` (executa todas as tabelas na ordem de dependência)
- Gera o pacote `conduto_dagster/` com os assets e schedules, além do `definitions.py` na raiz — para rodar, é só executar `uv run dagster dev`
- Adiciona o bloco `[tool.dagster]` no `pyproject.toml` apontando para as definições — o `dagster dev` (versões recentes) exige esse bloco ou um argumento `-m`/`-f` para localizar o código

O código Dagster lê o `main.yml` e os `schemas/*.yml` em tempo de execução: alterar a chave `schedule` de um schema muda o asset/schedule sem precisar regenerar nada. Tabelas com FK viram dependências de assets (pais antes de filhos).

Para regenerar depois (por exemplo, após adicionar uma tabela nova):

```bash
# na raiz do projeto
conduto schedules

# apontando para outro diretório
conduto schedules --dir caminho/do/projeto
```

Os valores já editados nos YAMLs são preservados na regeneração — só as chaves ausentes recebem o padrão.

### Subindo o servidor Dagster

Ao final do `conduto init`, o conduto também pergunta se você quer **subir o servidor Dagster agora** e gera comandos prontos no projeto:

```bash
# na raiz do projeto
uv run dagster dev

# ou pelos scripts gerados
.\run_dagster.ps1      # Windows
./run_dagster.sh        # Linux/macOS

# ou direto pelo conduto
conduto dagster
conduto dagster --dir caminho/do/projeto
```

O servidor abre em http://localhost:3000 — pressione `Ctrl+C` para encerrar. O `dagster dev` exige o pacote `dagster-webserver`; o conduto o instala junto com as demais dependências e, se faltar num projeto já existente, instala automaticamente antes de subir o servidor (`uv add dagster-webserver`).

Enquanto o servidor inicializa, o conduto mostra um status animado ("Aguardando o servidor Dagster iniciar...") e avisa quando ele estiver no ar — nada de tela parada sem sinal de progresso. Se o código `conduto_dagster/` ainda não existir no projeto, ele é gerado na hora a partir do `main.yml` e dos `schemas/*.yml`, e o bloco `[tool.dagster]` é adicionado ao `pyproject.toml` automaticamente.

### Driver ODBC do SQL Server

O `pyodbc` precisa do driver nativo instalado no sistema. Se a conexão com SQL Server falhar por falta de driver, o `conduto init` oferece a opção **Instalar driver automaticamente**. As credenciais já digitadas ficam guardadas só em memória e, depois da instalação, o teste de conexão é reexecutado sozinho — você não precisa digitá-las novamente. Também dá para instalar direto, sem passar pelo fluxo interativo:

```bash
conduto install-sqlserver-driver
```

Esse comando funciona em Windows (winget ou MSI), Linux (apt) e macOS (Homebrew). No Windows, existe ainda um script standalone que baixa o instalador oficial — útil para instalação offline ou para automatizar fora do conduto:

Durante a instalação no Windows, se o terminal não estiver como administrador, o conduto abre a janela de permissão (UAC) na frente para você confirmar. Se houver um reinício pendente no sistema, a instalação é bloqueada com um aviso claro até você reiniciar o Windows. O download e a instalação rodam em segundo plano (sem abrir janela do PowerShell) — só a confirmação do UAC aparece.

```powershell
# só baixa o MSI
.\scripts\install-sqlserver-odbc.ps1 -DownloadOnly -OutFile .\msodbcsql18.msi

# baixa e instala (winget ou MSI; se precisar de administrador, o UAC abre na frente)
.\scripts\install-sqlserver-odbc.ps1
```

Versões suportadas: 18 (padrão) e 17 (`-Version 17`). Documentação oficial: [Download ODBC Driver for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server).

## O que é gerado

```text
meu_projeto/
├── .env
├── main.yml
├── run_dagster.ps1 / run_dagster.sh   # comandos para subir o Dagster
├── definitions.py            # ponto de entrada do dagster dev (com schedules)
├── conduto_dagster/          # código Dagster padrão (com schedules)
│   ├── __init__.py
│   ├── etl.py
│   └── definitions.py
├── schemas/
│   ├── clientes.yml
│   ├── pedidos.yml
│   └── produtos.yml
└── ambiente uv (pyyaml, jinja2, polars, dagster, dagster-webserver)
```

> Fora de um projeto uv, essa estrutura é criada dentro de `meu_projeto/`. Dentro de um projeto uv já existente, os arquivos são gerados no diretório atual. O projeto é inicializado **sem pasta `src/`** (`uv init --bare`) — scripts e código Dagster ficam na raiz.

### `.env` — credenciais

Guarda as credenciais de origem e destino em variáveis `DB_ORIGEM_*` e `DB_DESTINO_*`:

```bash
DB_ORIGEM_TYPE=postgresql
DB_ORIGEM_HOST=localhost
DB_ORIGEM_PORT=5432
DB_ORIGEM_NAME=postgres
DB_ORIGEM_SCHEMA=public
DB_ORIGEM_USER=postgres
DB_ORIGEM_PASSWORD=postgres

DB_DESTINO_TYPE=postgresql
DB_DESTINO_HOST=localhost
DB_DESTINO_PORT=5432
DB_DESTINO_NAME=postgres
DB_DESTINO_SCHEMA=public
DB_DESTINO_USER=postgres
DB_DESTINO_PASSWORD=postgres
```

Para cargas pesadas no PostgreSQL (ex.: Supabase), o destino pode estourar o
`statement_timeout` do servidor durante o `COPY`. Para evitar isso:

- Use o **session pooler** (porta `5432`) ou a conexão direta; o transaction
  pooler (`6543`) não permite ajustar timeouts de sessão.
- Defina `DB_DESTINO_STATEMENT_TIMEOUT` no `.env` (em milissegundos; `0`
  desativa o limite). O pipeline executa `SET statement_timeout` ao conectar.

> **Importante:** o `.env` contém credenciais e não deve ser versionado.

### `main.yml` — manifesto

Define a versão do projeto e a lista de schemas na ordem correta de dependência:

```yaml
version: "1.0"
project: meu_projeto

# Schedule do modelo geral (todas as tabelas, na ordem de dependência)
schedule:
  cron: "0 * * * *"

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
schedule:
  cron: "0 * * * *"
  mode: incremental
  incremental_column: criado_em
  full_load: false
  truncate: false
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
uv init --no-readme --bare   # sem pasta src/
uv add pyyaml jinja2 polars dagster dagster-webserver
```

O projeto é inicializado sem a pasta `src/`, pois os scripts e o código Dagster ficam na raiz. E também a lib oficial do SGBD escolhido: `psycopg[binary]` (PostgreSQL), `pymysql` (MySQL) ou `pyodbc` (SQL Server).

## Como funciona

1. `cli.py` faz as perguntas de origem e destino e monta o contexto
2. `env_render` renderiza o template do `.env`
3. Se você escolheu gerar automaticamente, `database/introspect.py` lê tabelas e colunas do banco de origem e `schemas/schemas_auto.py` gera os schemas e o `main.yml`; caso contrário, `schemas_render` renderiza os exemplos em `schemas/`
4. Se você optou por gerenciar schedules, `schedules/schedules_auto.py` infere colunas de atualização incremental, grava a chave `schedule` nos schemas e no `main.yml`, e `schedules/dagster_render.py` gera o código Dagster padrão
5. `setup_uv_environment` roda `uv init` (se necessário) e `uv add` das dependências

## Próximos passos

1. Revise os schemas em `schemas/` (na geração automática eles já refletem o banco de origem)
2. Revise o `.env` com as credenciais corretas de origem e destino
3. Revise os schedules em cada schema (`cron`, `mode`, `incremental_column`, `full_load`, `truncate`) e o schedule do modelo geral no `main.yml`
4. Suba o servidor Dagster: `uv run dagster dev`, `run_dagster.ps1` (Windows), `run_dagster.sh` (Linux/macOS) ou `conduto dagster` — assets e schedules já vêm montados a partir dos YAMLs

## Desenvolvimento

```bash
uv sync
uv build
uv publish
```

### Publicar uma vers?o nova (autom?tico)

No GitHub, em **Actions ? Release ? Run workflow**, escolha o tipo de bump (`patch`, `minor` ou `major`). O workflow bumpa a vers?o no `pyproject.toml` e `uv.lock`, builda, publica no PyPI (usando o secret `UV_PUBLISH_TOKEN`) e cria a tag `vX.Y.Z` ? sem precisar mexer em vers?o na m?o.

## Licença

MIT
