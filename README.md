# conduto

CLI para criar projetos de migração/ELT de dados: gera o `.env` com as credenciais dos bancos, o manifesto `main.yml`, os schemas YAML das tabelas e configura o ambiente com `uv` (`pyyaml`, `jinja2`, `polars`, `dagster`).

**Repositório:** [github.com/joaopedrozg/conduto](https://github.com/joaopedrozg/conduto)

## Instalação

```bash
pip install conduto
```

## Uso

```bash
conduto init meu_projeto
```

O comando pergunta as credenciais dos bancos de origem e destino e gera a estrutura:

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

## Desenvolvimento

```bash
uv sync
uv build
uv publish
```
