# conduto

**O duto que leva seus dados da origem ao destino.**

CLI para criar projetos de migração/ELT de dados: gera o `.env` com as credenciais dos bancos, o manifesto `main.yml`, os schemas YAML das tabelas e configura o ambiente com `uv` (`pyyaml`, `jinja2`, `dagster`, `dagster-webserver`).

**Repositório:** [github.com/joaopedrozg/conduto](https://github.com/joaopedrozg/conduto)

## Funcionalidades

- Scaffold completo de projeto ELT em um único comando
- Fluxo interativo para configurar bancos de origem e destino (PostgreSQL, MySQL, SQL Server, ClickHouse, DuckDB e Delta Lake)
- Geração do `.env` com as credenciais das duas pontas do duto
- Manifesto `main.yml` com a lista das tabelas do projeto
- Schemas YAML de exemplo (clientes, pedidos e produtos) com PK, `unique` e `default` (a FK é só documentação do modelo)
- Ambiente Python gerenciado por `uv` com `pyyaml`, `jinja2`, `dagster` e `dagster-webserver`
- Adapta-se automaticamente a um projeto uv existente (gera direto no projeto atual, sem subpasta nem `uv init`)
- Adapters de conexão com defaults por SGBD (porta, banco e usuário)
- Mapa de particularidades por SGBD aplicado no fluxo do CLI e no DDL (ClickHouse: ENGINE/ORDER BY do MergeTree e sem constraints; Delta Lake: sem constraints no CREATE TABLE; MySQL: banco == schema)
- Teste de conexão antes de gerar o projeto (com opção de digitar novamente ou seguir mesmo assim)
- Navegação pelos bancos e schemas do servidor — sem precisar digitar o nome do banco
- Opção de criar banco e schema no destino direto pelo fluxo interativo
- Geração automática de schemas a partir do banco de origem: lista tabelas e colunas, infere tipos, PK, FK, unique e default
- Assets Dagster independentes: qualquer tabela é materializada sozinha, sem exigir que outra exista ou rode antes
- Gerenciamento automático de schedules: infere colunas de atualização incremental, cria um schedule padrão de hora em hora por tabela e um schedule para o modelo geral
- Geração de código Dagster padrão que segue a chave `schedule` de cada schema (`cron`, `mode`, `incremental_column`, `full_load` e `truncate`)
- Comando `conduto schedules` para (re)gerar os schedules e o código Dagster de um projeto existente
- Comando `conduto docs`: sobe um servidor web local com a documentação da estrutura do projeto (visão geral, árvore de arquivos, conexões, schemas, schedules, DDL e ambiente)
- Credenciais visíveis no prompt durante o preenchimento — só vão para o `.env`
- Instalação da lib oficial do SGBD escolhido (`psycopg[binary]`, `pymysql`, `pyodbc`) no projeto gerado — na CLI, os drivers são extras por SGBD (`conduto[all]` traz todos)
- Download/instalação automática do ODBC Driver for SQL Server (Windows, Linux e macOS)
- Feedback visual com `rich` e `questionary`: cores semânticas (sucesso, aviso, erro, info), tabelas de resumo e widgets de carregamento (spinner e barra de progresso) nas operações demoradas
- Detecção automática do idioma da máquina (português ou inglês) com override por comando (`--lang`) ou variável de ambiente (`CONDUTO_LANG`)

## Instalação

O pacote base instala só a CLI (Typer, rich, questionary, Jinja2 e PyYAML).
Os drivers de banco vêm como **extras por SGBD** — instale só o que você usa:

```bash
pip install "conduto[postgresql]"   # psycopg
pip install "conduto[mysql]"        # pymysql
pip install "conduto[sqlserver]"    # pyodbc
pip install "conduto[clickhouse]"   # clickhouse-connect
pip install "conduto[duckdb]"       # duckdb
pip install "conduto[deltalake]"    # deltalake, pyarrow e boto3

pip install "conduto[all]"          # todos os SGBD
```

O mesmo vale para `uv tool install "conduto[all]"`:

```bash
uv tool install "conduto[all]"
```

> Sem o extra, a CLI funciona normalmente (`conduto --help`, `ddl`, `schedules`,
> `docs`...). Ao escolher um SGBD cujo driver falta, o conduto pergunta se quer
> instalar na hora (via `uv` ou `pip`) e diz o comando manual se falhar. Os
> projetos gerados pelo `conduto init` seguem recebendo o driver do SGBD no
> `uv add` deles — o extra é só para o ambiente da CLI.

#### Linux: PEP 668 e o "ambiente virtual exigido"

Debian/Ubuntu, Fedora, Arch e o Homebrew no macOS marcam o Python do sistema
como *externally-managed* (PEP 668): `pip install` fora de um venv é recusado
com "create a virtual environment". Isso **não** afeta quem usa
`uvx "conduto[postgresql]"`, `uv tool` ou `pipx` — todos já rodam em venv
próprio. Só quem instalou o conduto direto no Python do sistema
(`pip install --user` ou `--break-system-packages`) esbarra nisso.

Quando acontece, o conduto detecta o marker antes de instalar e mostra as
duas saídas:

```bash
uvx "conduto[postgresql]"   # cria um venv isolado — sem mexer no sistema

pip install --break-system-packages psycopg[binary]   # só se você autorizar
```

A pergunta "Instalar mesmo assim no Python do sistema?" tem padrão **não** —
nada é quebrado sem consentimento explícito. Windows (python.org) e macOS não
gerenciados não têm o marker, então seguem direto, sem a pergunta.

### Idioma

O Conduto detecta o idioma da máquina automaticamente (português por padrão,
com suporte a inglês) e usa essa preferência em todas as mensagens, prompts,
ajudas de comando e rótulos. A detecção segue esta ordem:

1. `CONDUTO_LANG` (ex.: `CONDUTO_LANG=en conduto init`)
2. Variáveis de ambiente de locale (`LANG`, `LC_ALL`, `LC_MESSAGES`) e locale do Python
3. Idioma de interface do Windows

Para forçar um idioma em uma execução, use `--lang pt` ou `--lang en`:

```bash
conduto --lang en init meu_projeto
```

> Dica: `--lang` vale para o fluxo do comando; a tela de ajuda (`--help`) segue a
> detecção automática e pode ser forçada com `CONDUTO_LANG=en conduto --help`.

## Uso

### Fluxo rápido (passo a passo)

```bash
# 1. Cria o projeto (conexões no .env, schemas/ e main.yml)
conduto init meu_projeto

# 2. Gera e aplica o DDL das tabelas no banco de destino
conduto ddl --apply

# 3. Gera os schedules e o código Dagster
conduto schedules

# 4. Sobe o servidor Dagster (http://localhost:3000)
conduto dagster

# 5. Documentação web do projeto (http://localhost:8000)
conduto docs
```

Use `conduto --help` e `conduto [COMANDO] --help` para ver as opções de cada
comando.

Confira a versão instalada:

```bash
conduto --version
```

Crie um novo projeto de migração:

```bash
conduto init meu_projeto
```

O comando pergunta interativamente:

1. SGBD de origem (PostgreSQL, MySQL, SQL Server, ClickHouse, DuckDB ou Delta Lake) — os defaults de porta e usuário mudam conforme o SGBD
2. Credenciais do servidor de origem (host, porta, usuário e senha) — sem precisar digitar o banco
3. Teste de conexão — se falhar, escolha entre digitar novamente ou continuar mesmo assim
4. Lista de bancos do servidor de origem — escolha um
5. Lista de schemas do banco escolhido — escolha um
6. SGBD de destino
7. Credenciais de destino, com o mesmo fluxo — e com opção de **criar um banco e/ou schema novo**
8. Como configurar os schemas: **gerar automaticamente** a partir do banco de origem (tabelas, colunas e tipos inferidos) ou **configurar manualmente** (gera os exemplos)
9. Gerenciamento de schedules — pergunta se você quer gerar automaticamente o schedule de cada tabela (padrão: hora em hora) e o código Dagster correspondente
10. Servidor Dagster — pergunta se você quer subir o servidor agora (`uv run dagster dev`) e gera os scripts `run_dagster.ps1`/`run_dagster.sh`

**Dentro de um projeto uv?** Se o diretório atual já tem `pyproject.toml` (por exemplo, após `uv add conduto`), o conduto se adapta: gera `.env`, `main.yml` e `schemas/` direto no projeto atual e adiciona só as dependências que faltam — sem criar subpasta nem rodar `uv init`. Nesse caso, use `uv run conduto init` (o nome do projeto vira opcional).

### Documentação web

Sobe um servidor web local com a documentação da estrutura do projeto atual: visão geral,
árvore de arquivos, conexões do `.env` (senhas mascaradas), schemas/tabelas, schedules,
DDL e dependências.

```bash
conduto docs                    # abre http://localhost:8000
conduto docs --port 9000        # porta específica
conduto docs --no-open          # sem abrir o navegador automaticamente
```

### Geração automática de schemas

Depois de testar as duas conexões, o conduto pergunta como você quer configurar os schemas das tabelas:

- **Gerar automaticamente**: o conduto lista os schemas do banco de origem e, se houver mais de um, deixa marcar **qualquer quantidade com espaço**; só as tabelas dos schemas marcados entram na lista seguinte, onde você busca por nome e marca/desmarca quais incluir. Depois lê as colunas (tipos, PK, FK, unique, default e nullable) e gera os `schemas/*.yml` e o `main.yml`. Com um único schema (MySQL, ClickHouse, Delta Lake) a primeira pergunta não aparece.
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

As flags `--apply` e `--no-apply` pulam a pergunta interativa (útil para scripts). O comando lê o `.env` (credenciais de destino), o `main.yml` e os `schemas/*.yml`, traduzindo tipos e funções (ex.: `gen_random_uuid()`, `clock_timestamp()`) para o SGBD de destino (PostgreSQL, MySQL, SQL Server, ClickHouse, DuckDB ou Delta Lake). Por padrão roda no diretório atual; use `--dir caminho/do/projeto` para outro diretório.

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

- Adiciona o schedule do **modelo geral** no `main.yml` (executa todas as tabelas na ordem do `main.yml`)
- Gera o pacote `conduto_dagster/` com os assets e schedules, além do `definitions.py` na raiz — para rodar, é só executar `uv run dagster dev`
- Adiciona o bloco `[tool.dagster]` no `pyproject.toml` apontando para as definições — o `dagster dev` (versões recentes) exige esse bloco ou um argumento `-m`/`-f` para localizar o código

O código Dagster lê o `main.yml` e os `schemas/*.yml` em tempo de execução: alterar a chave `schedule` de um schema muda o asset/schedule sem precisar regenerar nada. Não há dependências entre assets: a `foreign_key` de cada schema é só documentação do modelo e nunca vira `deps` no Dagster nem `FOREIGN KEY` no destino — qualquer tabela pode ser materializada isoladamente, mesmo que a que ela referencia ainda não exista.

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
└── ambiente uv (pyyaml, jinja2, dagster, dagster-webserver)
```

> Fora de um projeto uv, essa estrutura é criada dentro de `meu_projeto/`. Dentro de um projeto uv já existente, os arquivos são gerados no diretório atual. O projeto é inicializado **sem pasta `src/`** (`uv init --bare`) — scripts e código Dagster ficam na raiz.

### `.env` — credenciais

Guarda as credenciais de origem e destino em variáveis `DB_ORIGEM_*` e `DB_DESTINO_*`:

> `DB_ORIGEM_SCHEMA` é o schema de origem **padrão** — o ETL só usa quando o schema da tabela não está no `source_schema` dela. Com tabelas em schemas diferentes da origem, cada uma leva o seu no YAML.

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

Para ajustar o tamanho do lote da carga (linhas por lote; padrão `20000`),
defina `CONDUTO_LOTE` no `.env`:

```bash
CONDUTO_LOTE=50000
```

> **Importante:** o `.env` contém credenciais e não deve ser versionado.

### `main.yml` — manifesto

Define a versão do projeto e a lista de schemas do projeto:

```yaml
version: "1.0"
project: meu_projeto

# Schedule do modelo geral (todas as tabelas, na ordem do manifesto)
schedule:
  cron: "0 * * * *"

tables:
  - path: "schemas/clientes.yml"
  - path: "schemas/pedidos.yml"
  - path: "schemas/produtos.yml"
```

### `schemas/*.yml` — tabelas

Schemas YAML que descrevem as tabelas: tipos, chave primária, foreign keys, `unique` e `default`.

Duas chaves de schema, com funções diferentes:

| Chave | Qual schema é |
| --- | --- |
| `schema` | o do **destino** — é o que o `conduto ddl` usa no `CREATE TABLE` |
| `source_schema` | o da **origem** — é de onde o ETL lê a tabela na hora da carga |

A de origem é gravada por tabela justamente porque uma tabela pode morar num schema e a outra em outro (SQL Server tem `Person`, `HumanResources`, `dbo`...). Sem ela o ETL leria tudo a partir do `DB_ORIGEM_SCHEMA` único do `.env` e falharia com `Invalid object name`. Em projetos antigos, sem a chave, o `DB_ORIGEM_SCHEMA` continua valendo como fallback.

```yaml
table: clientes
schema: public
source_schema: public
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
| `pedidos.yml` | chave estrangeira `foreign_key: clientes(id)` — só documentação |
| `produtos.yml` | tipos `numeric` e `boolean`, colunas opcionais (`nullable: true`) |

#### Sem dependências entre tabelas

O `foreign_key` é **só documentação do modelo** — nenhuma parte do projeto o transforma em restrição:

- o `conduto ddl` **não** emite `FOREIGN KEY` no `CREATE TABLE`, em nenhum SGBD de destino;
- o código Dagster **não** cria `deps` entre assets;
- o `main.yml` **não** é reordenado por topologia de FK.

Em ambiente analítico é exatamente o que se quer: se `pedidos` referencia `clientes`, você ainda carrega `pedidos` sozinha, sem precisar que `clientes` exista ou tenha sido materializada antes. A integridade referencial fica com quem escreve na origem; aqui o que importa é conseguir ler qualquer tabela isoladamente.

#### Tipos customizados

Tipos que não são de todos os SGBD — `ltree`, `citext`, `hstore`, `tsvector`, `inet`, `cidr`, `geometry`, `interval`, `hierarchyid`, `year`, arrays do PostgreSQL etc. — têm uma regra por destino: o tipo é mantido onde existe nativamente (PostgreSQL, e `geometry`/`hierarchyid` no SQL Server) e degrada para texto aceito pelo destino nos demais (`text`/`nvarchar(max)`/`String`/`varchar`/`string`). Assim o `CREATE TABLE` nunca falha por causa do tipo.

Quando a regra não é a que você quer, declare o equivalente na própria coluna com `types:` — ele vence qualquer tabela:

```yaml
columns:
  - name: localizacao
    type: geometry            # regra padrão por destino
    types:                    # override: só para os destinos listados
      mysql: point
      deltalake: binary
```

Se um tipo não tiver regra nenhuma, ele passa como está e o conduto avisa — é sinal de que vale declarar um `types:`.

### Ambiente `uv`

Se ainda não existir `pyproject.toml`, o conduto inicializa o projeto e instala as dependências do pipeline:

```bash
uv init --no-readme --bare   # sem pasta src/
uv add pyyaml jinja2 dagster dagster-webserver
```

O projeto é inicializado sem a pasta `src/`, pois os scripts e o código Dagster ficam na raiz. E também a lib oficial do SGBD escolhido: `psycopg[binary]` (PostgreSQL), `pymysql` (MySQL) ou `pyodbc` (SQL Server). Essa dependência é do **projeto gerado**, não da CLI — na CLI os drivers são extras (`pip install "conduto[all]"`).

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
uv sync --all-extras   # instala o projeto + drivers de todos os SGBD + dev (pytest)
uv run pytest -q       # roda os testes
uv build
uv publish
```

### Publicar uma versão nova (automático)

Todo merge/push para a `main` dispara o workflow `Publish to PyPI`, que faz o
bump de versão, o build e o publish automáticos:

- A versão é calculada a partir da **última versão publicada no PyPI**: bump
  `patch` sobre ela (ex.: última `0.1.9` → publica `0.1.10`). Se o PR já
  bumpou a versão no `pyproject.toml` (maior que a última publicada), ela é
  publicada direto.
- O bump é aplicado só no working tree do workflow — não é commitado na `main`
  (o ruleset exige PR para push direto), então a versão do `pyproject.toml`
  pode ficar atrás da versão publicada.
- Após o publish é criada a tag `vX.Y.Z`.

Para release manual (`patch`, `minor` ou `major`), use **Actions → Publish to
PyPI → Run workflow** e escolha o tipo de bump.

### Performance da carga

O ETL gerado usa `COPY` para carregar no PostgreSQL:

- **Origem e destino PostgreSQL**: streaming direto `COPY (SELECT ...) TO STDOUT`
  para `COPY ... FROM STDIN` — o Python só repassa bytes, sem conversão linha a
  linha. É o caminho mais rápido possível para o Postgres.
- **Outras origens para PostgreSQL**: leitura em lotes (`fetchmany`) com escrita
  via `COPY FROM STDIN` em blocos pré-serializados (um `write()` por lote).

Ajustes disponíveis no `.env`:

- `CONDUTO_LOTE`: linhas por lote de cópia (padrão `20000`).
- `DB_DESTINO_STATEMENT_TIMEOUT`: timeout da carga em ms (`0` = sem limite;
  útil em servidores gerenciados como o Supabase).

Para cargas grandes, remova índices/constraints não essenciais da tabela de
destino antes da carga full e recrie depois — o `COPY` acelera muito sem eles.

## Licença

MIT
