# conduto

> **O duto que leva seus dados da origem ao destino.**

🇺🇸 [English](https://github.com/joaopedrozg/conduto/blob/main/README.en.md) · 🇧🇷 **Português (BR)**

[![PyPI](https://img.shields.io/pypi/v/conduto?label=pypi)](https://pypi.org/project/conduto/)
![Python](https://img.shields.io/pypi/pyversions/conduto)
![Licença](https://img.shields.io/pypi/l/conduto)
![CI](https://github.com/joaopedrozg/conduto/actions/workflows/ci.yml/badge.svg)

`conduto` é uma CLI que monta um **projeto ELT completo em um único comando**: credenciais das duas pontas no `.env`, schemas YAML das tabelas, DDL no banco de destino e código Dagster (assets + schedules) pronto para rodar.

**Para que serve:** você tem dados num banco e precisa mantê-los sincronizados em outro. Sem o conduto, isso significa escrever à mão driver, credenciais, mapeamento de tipos entre SGBD, `CREATE TABLE` no destino, leitura incremental por watermark, agendamento e orquestração. Com o conduto, você responde um wizard e recebe um projeto que carrega os dados — com carga incremental ou completa, agendada, e uma interface para disparar e acompanhar cada tabela.

- **Origem e destino:** PostgreSQL, MySQL, SQL Server, ClickHouse, DuckDB e Delta Lake
- **Orquestração:** Dagster (assets independentes, schedules por tabela, interface web)
- **Instalação:** `pip install "conduto[postgresql]"` (drivers por SGBD)
- **Código:** [github.com/joaopedrozg/conduto](https://github.com/joaopedrozg/conduto) · **Issues:** [abrir uma issue](https://github.com/joaopedrozg/conduto/issues)

---

## Sumário

1. [Instalação](#instalação)
2. [Comece aqui](#comece-aqui)
3. [Os comandos](#os-comandos)
4. [O wizard interativo](#o-wizard-interativo)
5. [O que é gerado](#o-que-é-gerado)
6. [Como os dados são carregados](#como-os-dados-são-carregados)
7. [Referência de configuração](#referência-de-configuração)
8. [Bancos suportados](#bancos-suportados)
9. [Desenvolvimento](#desenvolvimento)

---

## Instalação

O pacote base instala só a CLI (Typer, Rich, Textual, Jinja2 e PyYAML). Os drivers de banco vêm como **extras por SGBD** — instale só o que você usa:

```bash
pip install "conduto[postgresql]"   # psycopg
pip install "conduto[mysql]"        # pymysql
pip install "conduto[sqlserver]"    # pyodbc
pip install "conduto[clickhouse]"   # clickhouse-connect
pip install "conduto[duckdb]"       # duckdb
pip install "conduto[deltalake]"    # deltalake, pyarrow e boto3

pip install "conduto[all]"          # todos os SGBD
```

O mesmo vale para o `uv`:

```bash
uv tool install "conduto[all]"

# ou executa sem instalar de vez
uvx --from "conduto[postgresql]" conduto init meu_projeto
```

Requisitos: **Python 3.10+** (o pacote declara suporte a 3.10–3.14) e o [`uv`](https://docs.astral.sh/uv/) no PATH — o conduto usa ele para montar o ambiente do projeto gerado.

> Sem o extra, a CLI funciona normalmente (`conduto --help`, `ddl`, `schedules`, `docs`...). Ao escolher um SGBD cujo driver falta, o conduto pergunta se quer instalar na hora (via `uv` ou `pip`) e diz o comando manual se falhar. Os projetos gerados pelo `conduto init` recebem o driver do SGBD no `uv add` deles — o extra é só para o ambiente da CLI.

### Linux: PEP 668 e o "ambiente virtual exigido"

Debian/Ubuntu, Fedora, Arch e o Homebrew no macOS marcam o Python do sistema como *externally-managed* (PEP 668): `pip install` fora de um venv é recusado. Isso **não** afeta quem usa `uvx`, `uv tool` ou `pipx` — todos já rodam em venv próprio.

Quando acontece, o conduto detecta o marker antes de instalar e mostra as duas saídas:

```bash
uvx --from "conduto[postgresql]" conduto   # venv isolado, sem mexer no sistema

pip install --break-system-packages psycopg[binary]   # só se você autorizar
```

A pergunta "Instalar mesmo assim no Python do sistema?" tem padrão **não** — nada é quebrado sem consentimento explícito.

---

## Comece aqui

```bash
# 1. Cria o projeto: conexões no .env, schemas/ e main.yml
conduto init meu_projeto

# 2. Gera o DDL das tabelas e aplica no banco de destino
conduto ddl --apply

# 3. Gera os schedules e o código Dagster
conduto schedules

# 4. Sobe o servidor Dagster (http://localhost:3000)
conduto dagster

# 5. Documentação web do projeto (http://localhost:8000)
conduto docs
```

Confira a versão e a ajuda:

```bash
conduto --version
conduto --help
conduto [COMANDO] --help
```

### O que o `conduto init` pergunta

O fluxo é interativo e guiado — você não precisa digitar nomes de banco ou de tabela na mão:

1. **SGBD de origem** — os defaults de porta e usuário mudam conforme o SGBD
2. **Credenciais de origem** — host, porta, usuário e senha
3. **Teste de conexão** — se falhar, você digita de novo ou segue mesmo assim
4. **Bancos do servidor de origem** — o conduto lista e você escolhe
5. **SGBD de destino e credenciais** — mesmo fluxo, mais a escolha do **schema de destino** (com opção de criar banco/schema novo)
6. **Modo dos schemas** — gerar automaticamente (você flega os schemas de origem e as tabelas) ou configurar manualmente (gera três exemplos para você editar)
7. **Schedules** — se quer gerar automaticamente o schedule de cada tabela (padrão: hora em hora) e o código Dagster
8. **Servidor Dagster** — se quer subir agora e gerar os scripts `run_dagster.ps1` / `run_dagster.sh`

**Dentro de um projeto uv existente?** Se o diretório atual já tem `pyproject.toml` (por exemplo, depois de `uv add conduto`), o conduto se adapta: gera `.env`, `main.yml` e `schemas/` direto no projeto atual e adiciona só as dependências que faltam — sem subpasta e sem `uv init`. Nesse caso use `uv run conduto init` (o nome do projeto fica opcional).

### Gerando os schemas automaticamente

Depois de testar as duas conexões, no modo **gerar automaticamente** o conduto:

- lista os schemas do banco de origem e abre uma tela de seleção com **filtro de busca** — você flega qualquer quantidade com `espaço`, todas as visíveis com `a` (**Selecionar todas**) e limpa com `l`;
- mostra, em seguida, as tabelas dos schemas marcados, com a mesma tela de busca e marcação — tabelas que já têm `schemas/<tabela>.yml` aparecem em âmbar com "já existe" (regenerar sobrescreve);
- lê as colunas do banco (tipos, PK, FK, unique, default, nullable) e escreve os `schemas/*.yml` e o `main.yml`.

A marcação que você fez é **o que define o schema de origem de cada tabela** — nenhum outro prompt de schema aparece depois disso. No modo **manual**, o conduto pergunta o schema de origem uma única vez e gera os exemplos `clientes`, `pedidos` e `produtos`.

### Adicionando uma tabela nova

Crie o schema só com o nome (ou adicione o caminho no `main.yml`) e deixe as colunas para o conduto:

```yaml
# schemas/minha_tabela.yml
table: minha_tabela
```

```bash
conduto inferir                      # infere todas as tabelas sem colunas
conduto inferir --tabela minha_tabela
conduto schedules                    # gera schedule e código Dagster da nova
```

O comando lê as credenciais de origem do `.env`, consulta o banco e escreve as `columns:` preservando o que já existir (description, schedule etc.).

---

## Os comandos

| Comando | O que faz | Opções principais |
| --- | --- | --- |
| `conduto init [NOME]` | Cria/atualiza o projeto: `.env`, `schemas/`, `main.yml`, ambiente uv, schedules e código Dagster | — |
| `conduto ddl` | Converte os schemas YAML em `CREATE TABLE` para o destino | `--apply` / `--no-apply`, `--output arquivo.sql`, `--dir` |
| `conduto schedules` | (Re)gera os schedules dos schemas e o código Dagster | `--dir` |
| `conduto dagster` | Sobe o servidor Dagster do projeto (http://localhost:3000) | `--dir` |
| `conduto docs` | Sobe a documentação web do projeto (http://localhost:8000) | `--port`, `--host`, `--no-open`, `--dir` |
| `conduto inferir` | Infere as colunas das tabelas no banco de origem | `--tabela`, `--dir` |
| `conduto install-sqlserver-driver` | Baixa e instala o ODBC Driver for SQL Server (Windows, Linux, macOS) | — |
| `conduto --help` | Ajuda geral; `conduto [COMANDO] --help` mostra as opções de cada um | — |

Flags globais: `--lang pt|en` (idioma da execução) e `--version`.

### Exemplos de uso

```bash
# só gerar o DDL em arquivo, sem tocar no banco
conduto ddl --no-apply --output ddl.sql

# aplicar direto, sem perguntar (bom para script/CI)
conduto ddl --apply

# trabalhar em outro diretório
conduto schedules --dir caminho/do/projeto
conduto docs --port 9000 --no-open
```

### Documentação web

```bash
conduto docs                  # abre http://localhost:8000
conduto docs --port 9000      # porta específica
conduto docs --no-open        # sem abrir o navegador
```

A página mostra a visão geral do projeto, a árvore de arquivos, as conexões do `.env` (senhas mascaradas), as particularidades por SGBD, as tabelas com seus schemas, os schedules, o DDL gerado, o ambiente e a lista de comandos.

---

## O wizard interativo

No terminal, `conduto init` e `conduto ddl` rodam dentro de uma **tela em TUI** (Textual):

- **Menu lateral de etapas** com o estado de cada uma: atual (● azul), concluída (✓ verde), pulada (— cinza) ou pendente (○);
- **Revisão**: clicar numa etapa concluída mostra o que foi respondido ali, sem rodar o fluxo de novo;
- **Painel de log** com o que o comando está fazendo, sem piscar log velho a cada troca de etapa;
- **Registros no SQLite**: toda a saída fica em `~/.conduto/registros.db` e abre no **`F3`**, com horário, etapa e rolagem — a saída também é reproduzida no terminal quando o shell fecha;
- **Rodapé com atalhos**: `F2` alterna o menu de etapas, `F3` abre os registros, `esc` volta;
- **Cores são status**: verde = sucesso, âmbar = atenção, vermelho = erro, azul = informação, cinza = neutro;
- Widgets de carregamento (spinner e barra de progresso) nas operações demoradas, como o teste de conexão e a aplicação do DDL.

Sem terminal interativo (CI, pipe) ou com a variável `CONDUTO_SEM_TUI` definida, tudo cai no fluxo clássico de prompts numerados no terminal — mesmo comportamento, sem a tela.

---

## O que é gerado

```text
meu_projeto/
├── .env                        # credenciais de origem e destino
├── main.yml                    # manifesto: lista das tabelas + schedule geral
├── schemas/                    # um YAML por tabela
│   ├── clientes.yml
│   ├── pedidos.yml
│   └── produtos.yml
├── definitions.py              # ponto de entrada do `dagster dev`
├── conduto_dagster/            # código Dagster gerado
│   ├── __init__.py
│   ├── etl.py                  # conexão, leitura e carga das tabelas
│   └── definitions.py          # assets e schedules montados dos YAMLs
├── run_dagster.ps1             # Windows
├── run_dagster.sh              # Linux/macOS
└── pyproject.toml              # ambiente uv (pyyaml, jinja2, dagster, dagster-webserver)
```

> Fora de um projeto uv, essa estrutura é criada dentro de `meu_projeto/`. Dentro de um projeto uv já existente, os arquivos vão para o diretório atual. O projeto nasce **sem pasta `src/`** (`uv init --bare`) — scripts e código Dagster ficam na raiz.

### `.env` — credenciais

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

# Opcional: linhas por lote de carga (padrão 20000)
# CONDUTO_LOTE=50000

# Opcional (PostgreSQL): statement_timeout da carga em ms (0 = sem limite)
# DB_DESTINO_STATEMENT_TIMEOUT=0
```

`DB_ORIGEM_SCHEMA` é o schema de origem **padrão** — o ETL só usa ele quando a tabela não tem `source_schema` no próprio YAML.

> **Importante:** o `.env` contém credenciais e não deve ser versionado.

### `main.yml` — manifesto

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

```yaml
table: clientes
schema: public              # schema no DESTINO (o que o conduto ddl usa)
source_schema: public       # schema na ORIGEM (de onde o ETL lê)
description: "Tabela de cadastro de clientes"
schedule:
  cron: "0 * * * *"
  mode: incremental         # incremental ou full
  incremental_column: criado_em
  full_load: false          # true força carga completa na próxima execução
  truncate: false           # true limpa a tabela de destino antes de carregar
columns:
  - name: id
    type: integer
    primary_key: true
    nullable: false
  - name: email
    type: varchar(255)
    unique: true
  - name: criado_em
    type: timestamp
    default: CURRENT_TIMESTAMP
```

Duas chaves de schema, com funções diferentes:

| Chave | Qual schema é |
| --- | --- |
| `schema` | o do **destino** — é o que o `conduto ddl` usa no `CREATE TABLE` |
| `source_schema` | o da **origem** — é de onde o ETL lê a tabela na hora da carga |

A de origem é gravada por tabela porque uma tabela pode morar num schema e a outra em outro (`Person`, `HumanResources`, `dbo`...). Sem ela o ETL leria tudo a partir do `DB_ORIGEM_SCHEMA` do `.env` e falharia com `Invalid object name`. Em projetos antigos, sem a chave, o `DB_ORIGEM_SCHEMA` continua valendo como fallback.

Os três exemplos cobrem padrões comuns de modelagem:

| Schema | O que demonstra |
| --- | --- |
| `clientes.yml` | chave primária, coluna `unique` e `default` |
| `pedidos.yml` | chave estrangeira `foreign_key: clientes(id)` — só documentação |
| `produtos.yml` | tipos `numeric` e `boolean`, colunas opcionais (`nullable: true`) |

#### Sem dependências entre tabelas

O `foreign_key` é **só documentação do modelo** — nenhuma parte do projeto o transforma em restrição:

- o `conduto ddl` **não** emite `FOREIGN KEY` no `CREATE TABLE`, em nenhum destino;
- o código Dagster **não** cria `deps` entre assets;
- o `main.yml` **não** é reordenado por topologia de FK.

Assim, se `pedidos` referencia `clientes`, você ainda carrega `pedidos` sozinha, sem precisar que `clientes` exista ou tenha rodado antes. A integridade referencial fica com quem escreve na origem.

#### Tipos customizados

Tipos que não existem em todos os SGBD — `ltree`, `citext`, `hstore`, `tsvector`, `inet`, `geometry`, `interval`, `hierarchyid`, `year`, arrays do PostgreSQL etc. — seguem uma regra por destino: o tipo é mantido onde existe nativamente (PostgreSQL, e `geometry`/`hierarchyid` no SQL Server) e degrada para texto aceito pelo destino nos demais (`text`/`nvarchar(max)`/`String`/`varchar`/`string`). Assim o `CREATE TABLE` nunca falha por causa do tipo.

Quando a regra não é a que você quer, declare o equivalente na coluna com `types:` — ele vence a tabela de regras:

```yaml
columns:
  - name: localizacao
    type: geometry            # regra padrão por destino
    types:                    # override: só para os destinos listados
      mysql: point
      deltalake: binary
```

Se um tipo não tiver regra nenhuma, ele passa como está e o conduto avisa — sinal de que vale declarar um `types:`.

---

## Como os dados são carregados

O código Dagster gerado (`conduto_dagster/`) lê o `main.yml` e os `schemas/*.yml` **em tempo de execução**: mudar a chave `schedule` de um schema muda o asset/schedule no próximo reload, sem regenerar nada.

Cada tabela é um **asset independente**, com o modo definido no seu YAML:

| Modo | Comportamento |
| --- | --- |
| `incremental` | lê só o que é maior que o watermark (último valor da `incremental_column` no destino); sem watermark, carrega tudo |
| `full` | limpa o destino da tabela e recarrega inteira |
| `truncate: true` | limpa o destino antes de carregar, no modo que estiver |
| `full_load: true` | força uma carga completa na próxima execução mesmo no modo incremental — volte para `false` depois |

Como a carga acontece em cada destino:

- **PostgreSQL**: `COPY` — streaming direto `COPY (SELECT ...) TO STDOUT` → `COPY ... FROM STDIN` quando origem e destino são PostgreSQL (o Python só repassa bytes), e `COPY FROM STDIN` em blocos pré-serializados nas demais origens. Em tabela já populada com PK, o destino recebe **upsert** por chave primária para não estourar `UniqueViolation` na carga incremental.
- **ClickHouse**: `INSERT` nativo em lote.
- **DuckDB**: registros via Arrow + `INSERT SELECT` (o `executemany` do DuckDB é lento, uma linha por vez).
- **Delta Lake**: `write_deltalake`.
- **SQL Server / MySQL e demais**: `INSERT` em lote, com `fast_executemany` (operação em massa) no SQL Server e fallback automático se o driver recusar.

Leitura da origem sempre em **lotes** (`fetchmany`) com produtor/consumidor em thread — a memória fica estável mesmo em tabela grande.

### Rodando

```bash
# no navegador (http://localhost:3000): selecione os assets e clique em "Materializar"
uv run dagster dev

# ou pelos scripts gerados
.\run_dagster.ps1      # Windows
./run_dagster.sh       # Linux/macOS

# ou direto pelo conduto
conduto dagster
conduto dagster --dir caminho/do/projeto
```

O `dagster dev` exige o pacote `dagster-webserver`; o conduto o instala junto com as demais dependências e, se faltar num projeto existente, instala antes de subir o servidor (`uv add dagster-webserver`). Enquanto o servidor inicializa, o conduto mostra um status animado e avisa quando ele está no ar. Se o código `conduto_dagster/` ainda não existir, ele é gerado na hora e o bloco `[tool.dagster]` é adicionado ao `pyproject.toml` (versões recentes do Dagster exigem esse bloco).

### Performance da carga

- **`CONDUTO_LOTE`** no `.env`: linhas por lote de cópia (padrão `20000`). Em cargas pesadas, `50000` costuma render.
- **`DB_DESTINO_STATEMENT_TIMEOUT`** (PostgreSQL, em ms; `0` = sem limite): evita estourar o `statement_timeout` do servidor durante o `COPY`. Use o **session pooler** (porta `5432`) ou conexão direta — o transaction pooler (`6543`) não permite `SET` de sessão.
- Para cargas grandes, remova índices/constraints não essenciais da tabela de destino antes de uma carga full e recrie depois — o `COPY` acelera muito sem eles.

---

## Referência de configuração

### Variáveis de ambiente

| Variável | Onde | Efeito |
| --- | --- | --- |
| `CONDUTO_LANG` | shell | força o idioma da CLI: `pt` ou `en` (ex.: `CONDUTO_LANG=en conduto init`) |
| `CONDUTO_SEM_TUI` | shell | desliga a tela TUI e usa os prompts clássicos (útil em CI/pipe) |
| `CONDUTO_REGISTROS` | shell | caminho alternativo do SQLite dos registros do wizard (padrão `~/.conduto/registros.db`) |
| `CONDUTO_LOTE` | `.env` do projeto | linhas por lote de carga (padrão `20000`) |
| `DB_DESTINO_STATEMENT_TIMEOUT` | `.env` do projeto | `SET statement_timeout` no destino PostgreSQL, em ms (`0` = sem limite) |

### Idioma

O conduto detecta o idioma da máquina (português por padrão, com suporte a inglês) e usa essa preferência em mensagens, prompts, ajuda e rótulos. A ordem de detecção é:

1. `CONDUTO_LANG`
2. Variáveis de locale (`LANG`, `LC_ALL`, `LC_MESSAGES`) e locale do Python
3. Idioma de interface do Windows

Para forçar em uma execução: `conduto --lang en init meu_projeto`.

> `--lang` vale para o fluxo do comando; o `--help` segue a detecção automática e pode ser forçado com `CONDUTO_LANG=en conduto --help`.

### Chave `schedule` (por schema YAML)

| Chave | Valores | Padrão |
| --- | --- | --- |
| `cron` | expressão cron do agendamento | `0 * * * *` (hora em hora) |
| `mode` | `incremental` ou `full` | `full` |
| `incremental_column` | coluna usada como watermark | inferida (`updated_at`, `created_at` ou outra temporal) |
| `full_load` | `true` força carga completa na próxima execução | `false` |
| `truncate` | `true` limpa a tabela de destino antes de carregar | `false` |

O `conduto schedules` infere a coluna de atualização incremental (prioriza `updated_at`/`atualizado_em`, depois `created_at`/`criado_em` e por fim qualquer coluna temporal), grava a chave nos schemas e mantém o schedule do modelo geral no `main.yml`. Valores já editados à mão são **preservados** na regeneração — só as chaves ausentes recebem o padrão.

---

## Bancos suportados

| SGBD | Extra | Porta padrão | Usuário padrão | Banco padrão |
| --- | --- | --- | --- | --- |
| PostgreSQL | `conduto[postgresql]` | 5432 | `postgres` | `postgres` |
| MySQL | `conduto[mysql]` | 3306 | `root` | `mysql` |
| SQL Server | `conduto[sqlserver]` | 1433 | `sa` | `master` |
| ClickHouse | `conduto[clickhouse]` | 8123 | `default` | `default` |
| DuckDB | `conduto[duckdb]` | — | — | `origem.duckdb` (arquivo local) |
| Delta Lake | `conduto[deltalake]` | — | `minioadmin` | `deltalake` (storage S3/MinIO) |

Particularidades aplicadas automaticamente no fluxo do CLI e no DDL:

- **ClickHouse**: `ENGINE`/`ORDER BY` do MergeTree e sem constraints;
- **Delta Lake**: sem constraints no `CREATE TABLE`;
- **MySQL**: banco == schema;
- **SQL Server**: download e instalação automática do driver ODBC.

### Driver ODBC do SQL Server

O `pyodbc` precisa do driver nativo no sistema. Se a conexão falhar por falta dele, o `conduto init` oferece **Instalar driver automaticamente** — as credenciais digitadas ficam só em memória e o teste de conexão é reexecutado sozinho depois. Também dá para instalar direto:

```bash
conduto install-sqlserver-driver
```

Funciona em Windows (winget ou MSI), Linux (apt) e macOS (Homebrew). No Windows, se o terminal não for administrador, o conduto abre a confirmação de UAC na frente; com reinício pendente, a instalação é bloqueada até você reiniciar. Há ainda um script standalone para instalação manual/offline:

```powershell
.\scripts\install-sqlserver-odbc.ps1 -DownloadOnly -OutFile .\msodbcsql18.msi   # só baixa
.\scripts\install-sqlserver-odbc.ps1                                            # baixa e instala
```

Versões suportadas: 18 (padrão) e 17 (`-Version 17`). Documentação oficial: [Download ODBC Driver for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server).

---

## Desenvolvimento

> Este README existe também em inglês, em [`README.en.md`](https://github.com/joaopedrozg/conduto/blob/main/README.en.md). Ao editar um, atualize o outro — o PyPI mostra este arquivo (`readme = "README.md"` no `pyproject.toml`).

```bash
uv sync --all-extras   # projeto + drivers de todos os SGBD + dev (pytest)
uv run pytest -q       # testes
uv build               # empacota
```

A CI (`.github/workflows/ci.yml`) roda a cada push/PR: instala com `uv sync --all-extras`, faz smoke test do CLI, roda os testes e constrói o pacote.

### Publicar uma versão nova

Todo merge/push na `main` dispara o workflow **Publish to PyPI**, que calcula a versão a partir da última publicada no PyPI (bump `patch`; se o PR já bumpou no `pyproject.toml` maior que a publicada, usa a do arquivo), publica e cria a tag `vX.Y.Z`. O bump é aplicado só no working tree do workflow — não vai para a `main`.

Para release manual (`patch`, `minor` ou `major`): **Actions → Publish to PyPI → Run workflow** e escolha o tipo de bump.

---

## Licença

[MIT](LICENSE)
