"""Servidor web com a documenta\u00e7\u00e3o da estrutura do projeto conduto.

O comando ``conduto docs`` coleta a estrutura do projeto atual (schemas,
schedules, conex\u00f5es, DDL, ambiente e \u00e1rvore de arquivos) e sobe um
servidor HTTP local com uma p\u00e1gina de documenta\u00e7\u00e3o naveg\u00e1vel.
"""

import re
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import yaml
from jinja2 import Environment, FileSystemLoader

from conduto.database.adapters import ADAPTERS
from conduto.database.particularidades import PARTICULARIDADES
from conduto.ddl.ddl_render import carregar_tabelas, credenciais_destino, gerar_ddl
from conduto.ui import aviso, console, erro, info, neutro, separador

# Diret\u00f3rios e sufixos que ficam de fora da documenta\u00e7\u00e3o.
_DIRETORIOS_IGNORADOS = {
    ".git", ".venv", "__pycache__", "dist", "build", ".mypy_cache",
    ".ruff_cache", ".pytest_cache", ".idea", ".vscode", "node_modules",
}
_SUFIXOS_IGNORADOS = {".pyc", ".pyo"}

_CHAVES_SENSIVEIS = ("password", "senha", "token", "secret", "api_key", "apikey")

COMANDOS_CONDUTO = [
    ("conduto --version", "Exibe a versão instalada do conduto."),
    ("conduto init [nome]", "Cria/adapta o projeto ELT: .env, main.yml, schemas/ e ambiente uv."),
    ("conduto schedules", "(Re)gera os schedules e o c\u00f3digo Dagster a partir dos schemas."),
    ("conduto ddl", "Gera (e opcionalmente aplica) o DDL das tabelas no banco de destino."),
    ("conduto inferir", "Infere as colunas das tabelas de origem nos schemas do projeto."),
    ("conduto dagster", "Sobe o servidor Dagster do projeto."),
    ("conduto docs", "Sobe este servidor de documenta\u00e7\u00e3o da estrutura do projeto."),
]


def _ler_texto(caminho: Path) -> str:
    try:
        return caminho.read_text(encoding="utf-8")
    except Exception:
        return ""


def _campo_pyproject(texto: str, chave: str) -> str:
    """Extrai um campo simples ``chave = "valor"`` do pyproject.toml."""
    padrao = rf'^\s*{re.escape(chave)}\s*=\s*"([^"]*)"'
    resultado = re.search(padrao, texto, re.MULTILINE)
    return resultado.group(1) if resultado else ""


def _lista_pyproject(texto: str, chave: str) -> List[str]:
    """Extrai uma lista ``chave = [ "item", ... ]`` do pyproject.toml."""
    padrao = rf'^\s*{re.escape(chave)}\s*=\s*\[(.*?)\]'
    resultado = re.search(padrao, texto, re.DOTALL | re.MULTILINE)
    if not resultado:
        return []
    return re.findall(r'"([^"]+)"', resultado.group(1))




def _ler_pyproject(project_dir: Path) -> Optional[Dict[str, Any]]:
    arquivo = project_dir / "pyproject.toml"
    if not arquivo.exists():
        return None
    texto = _ler_texto(arquivo)

    opcionais: Dict[str, List[str]] = {}
    secao = re.search(r"\[project\.optional-dependencies\](.*?)(?:\n\[|$)", texto, re.DOTALL)
    if secao:
        for grupo in re.finditer(
            r"^\s*([\w.\-]+)\s*=\s*\[(.*?)\]", secao.group(1), re.DOTALL | re.MULTILINE
        ):
            opcionais[grupo.group(1)] = re.findall(r'"([^"]+)"', grupo.group(2))

    return {
        "nome": _campo_pyproject(texto, "name"),
        "versao": _campo_pyproject(texto, "version"),
        "descricao": _campo_pyproject(texto, "description"),
        "licenca": _campo_pyproject(texto, "license"),
        "requer_python": _campo_pyproject(texto, "requires-python"),
        "dependencias": _lista_pyproject(texto, "dependencies"),
        "opcionais": opcionais,
    }


def _ler_env(project_dir: Path) -> List[Dict[str, str]]:
    """L\u00ea o .env e devolve as vari\u00e1veis (valores sens\u00edveis mascarados)."""
    arquivo = project_dir / ".env"
    if not arquivo.exists():
        return []
    variaveis: List[Dict[str, str]] = []
    for linha in _ler_texto(arquivo).splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave, valor = chave.strip(), valor.strip()
        sensivel = any(s in chave.lower() for s in _CHAVES_SENSIVEIS)
        variaveis.append({
            "chave": chave,
            "valor": "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" if sensivel and valor else valor,
            "sensivel": sensivel,
            "definida": bool(valor),
        })
    return variaveis


def _ler_conexoes(env: List[Dict[str, str]]) -> Dict[str, Optional[Dict[str, Any]]]:
    valores = {v["chave"]: v["valor"] for v in env}

    def montar(prefixo: str) -> Optional[Dict[str, Any]]:
        tipo = valores.get(f"{prefixo}_TYPE")
        if not tipo:
            return None
        adapter = ADAPTERS.get(tipo)
        return {
            "tipo": tipo,
            "nome": adapter.nome if adapter else tipo,
            "host": valores.get(f"{prefixo}_HOST", ""),
            "port": valores.get(f"{prefixo}_PORT", ""),
            "database": valores.get(f"{prefixo}_NAME", ""),
            "schema": valores.get(f"{prefixo}_SCHEMA", ""),
            "user": valores.get(f"{prefixo}_USER", ""),
            "senha_definida": bool(valores.get(f"{prefixo}_PASSWORD")),
        }

    return {"origem": montar("DB_ORIGEM"), "destino": montar("DB_DESTINO")}


def _montar_arvore(project_dir: Path) -> Dict[str, Any]:
    """Monta a \u00e1rvore de arquivos do projeto (sem segredos/cache/build)."""

    def percorrer(caminho: Path, relativo: Path) -> Optional[Dict[str, Any]]:
        nome = caminho.name
        if caminho.is_dir():
            if nome in _DIRETORIOS_IGNORADOS or nome.endswith(".egg-info"):
                return None
            filhos = []
            for item in sorted(caminho.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                nodo = percorrer(item, relativo / item.name)
                if nodo:
                    filhos.append(nodo)
            return {"nome": nome, "caminho": str(relativo), "tipo": "dir", "filhos": filhos}
        if caminho.suffix in _SUFIXOS_IGNORADOS:
            return None
        return {"nome": nome, "caminho": str(relativo), "tipo": "file", "filhos": []}

    return percorrer(project_dir, Path("."))


def _enriquecer_tabela(tabela: Dict[str, Any], project_dir: Path) -> Dict[str, Any]:
    tabela = dict(tabela)
    colunas = []
    for coluna in tabela.get("columns", []):
        coluna = dict(coluna)
        coluna["chave_primaria"] = bool(coluna.get("primary_key"))
        coluna["unica"] = bool(coluna.get("unique"))
        coluna["nao_nula"] = coluna.get("nullable") is False
        fk = coluna.get("foreign_key")
        if isinstance(fk, str) and fk:
            if "(" in fk and fk.endswith(")"):
                ref_tabela, _, ref_coluna = fk.partition("(")
                coluna["fk_tabela"] = ref_tabela.strip()
                coluna["fk_coluna"] = ref_coluna.rstrip(")").strip()
            else:
                coluna["fk_tabela"] = fk
                coluna["fk_coluna"] = ""
        colunas.append(coluna)

    tabela["colunas"] = colunas
    tabela["qtd_colunas"] = len(colunas)
    tabela["chaves_primarias"] = [c["name"] for c in colunas if c["chave_primaria"]]
    tabela["chaves_estrangeiras"] = [c for c in colunas if c.get("fk_tabela")]
    tabela["unicas"] = [c["name"] for c in colunas if c["unica"]]
    tabela["slug"] = re.sub(r"[^\w\-]+", "-", str(tabela.get("table", ""))).strip("-").lower() or "tabela"
    tabela["yaml"] = _ler_texto(project_dir / str(tabela.get("path", "")))
    tabela["schedule"] = tabela.get("schedule") or {}
    return tabela


def _resumo_schedules(dados: Dict[str, Any]) -> Dict[str, Any]:
    main = dados.get("main") or {}
    lista = []
    for tabela in dados["tabelas"]:
        schedule = tabela["schedule"]
        lista.append({
            "tabela": tabela["table"],
            "slug": tabela["slug"],
            "cron": schedule.get("cron", ""),
            "mode": schedule.get("mode", ""),
            "incremental_column": schedule.get("incremental_column") or "",
            "full_load": bool(schedule.get("full_load")),
            "truncate": bool(schedule.get("truncate")),
        })
    return {"geral": main.get("schedule") or {}, "tabelas": lista}


def _resumo_particularidades() -> List[Dict[str, Any]]:
    """Lista as particularidades de cada SGBD para a página de docs."""
    return [
        {
            "tipo": p.tipo,
            "nome": p.nome,
            "schema_recurso": p.schema_recurso,
            "suporta_pk": p.suporta_pk,
            "suporta_unique": p.suporta_unique,
            "suporta_fk": p.suporta_fk,
            "engine_padrao": p.engine_padrao or "",
            "requer_order_by": p.requer_order_by,
            "chaves_tabela": list(p.chaves_tabela),
            "notas": list(p.notas),
        }
        for p in PARTICULARIDADES.values()
    ]


def coletar_dados(project_dir: Path) -> Dict[str, Any]:
    """Coleta todas as informa\u00e7\u00f5es usadas na p\u00e1gina de documenta\u00e7\u00e3o."""
    project_dir = Path(project_dir)
    pyproject = _ler_pyproject(project_dir)

    main_path = project_dir / "main.yml"
    main = None
    if main_path.exists():
        main = yaml.safe_load(_ler_texto(main_path)) or {}

    tabelas_origem = carregar_tabelas(project_dir)
    tabelas = [_enriquecer_tabela(t, project_dir) for t in tabelas_origem]

    env = _ler_env(project_dir)
    conexoes = _ler_conexoes(env)

    ddl = None
    try:
        _, tipo = credenciais_destino(project_dir)
        ddl = {"tipo": tipo, "texto": gerar_ddl(tabelas_origem, tipo)}
    except Exception:
        ddl = None

    dados = {
        "projeto": {
            "nome": (pyproject or {}).get("nome") or (main or {}).get("project") or project_dir.name,
            "versao": (pyproject or {}).get("versao") or (main or {}).get("version") or "\u2014",
            "descricao": (pyproject or {}).get("descricao") or "",
            "licenca": (pyproject or {}).get("licenca") or "",
            "requer_python": (pyproject or {}).get("requer_python") or "",
            "pasta": str(project_dir.resolve()),
        },
        "arvore": _montar_arvore(project_dir),
        "env": env,
        "conexoes": conexoes,
        "particularidades": _resumo_particularidades(),
        "main": main,
        "tabelas": tabelas,
        "total_colunas": sum(t["qtd_colunas"] for t in tabelas),
        "ddl": ddl,
        "dependencias": (pyproject or {}).get("dependencias") or [],
        "opcionais": (pyproject or {}).get("opcionais") or {},
        "comandos": COMANDOS_CONDUTO,
        "readme": _ler_texto(project_dir / "README.md"),
    }
    dados["schedules"] = _resumo_schedules(dados)
    return dados


def renderizar_html(dados: Dict[str, Any]) -> bytes:
    """Renderiza a p\u00e1gina HTML completa a partir dos dados coletados."""
    templates_dir = Path(__file__).resolve().parent.parent / "templates" / "docs"
    ambiente = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)
    template = ambiente.get_template("index.html.jinja")
    return template.render(**dados).encode("utf-8")


def servir(
    project_dir: Path,
    host: str = "127.0.0.1",
    port: int = 8000,
    abrir_navegador: bool = True,
) -> None:
    """Sobe o servidor HTTP com a documenta\u00e7\u00e3o e bloqueia at\u00e9 Ctrl+C."""
    project_dir = Path(project_dir)
    dados = coletar_dados(project_dir)
    pagina = renderizar_html(dados)

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            caminho = urlsplit(self.path).path
            if caminho in ("/", "/index.html"):
                corpo = pagina
                tipo = "text/html; charset=utf-8"
            elif caminho == "/robots.txt":
                corpo = b"User-agent: *\nDisallow: /\n"
                tipo = "text/plain; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, formato, *args):
            return

    servidor = None
    porta_efetiva = port
    for tentativa in range(port, port + 10):
        try:
            servidor = ThreadingHTTPServer((host, tentativa), _Handler)
            porta_efetiva = tentativa
            break
        except OSError:
            continue
    if servidor is None:
        console.print(erro(
            "Não foi possível subir o servidor na porta {port} (e nas 9 seguintes).",
            port=port,
        ))
        raise RuntimeError(f"Portas {port}-{port + 9} ocupadas")

    url = f"http://{host}:{porta_efetiva}/"
    console.print(separador())
    console.print(info("Documentação de {nome}", nome=dados["projeto"]["nome"]))
    console.print(neutro("Acesse: {url}", url=url))
    console.print(neutro("Pressione Ctrl+C para encerrar o servidor."))
    if abrir_navegador:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        console.print()
        console.print(aviso("Servidor de documentação encerrado."))
    finally:
        servidor.server_close()
