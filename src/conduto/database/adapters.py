import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple


@dataclass(frozen=True)
class Adapter:
    nome: str
    tipo: str
    driver: str
    host_padrao: str = "localhost"
    porta_padrao: str = "5432"
    banco_padrao: str = "postgres"
    usuario_padrao: str = "postgres"
    senha_padrao: str = "postgres"


ADAPTERS: Dict[str, Adapter] = {
    "PostgreSQL": Adapter(
        nome="PostgreSQL",
        tipo="postgresql",
        driver="psycopg[binary]",
        porta_padrao="5432",
        banco_padrao="postgres",
        usuario_padrao="postgres",
        senha_padrao="postgres",
    ),
    "MySQL": Adapter(
        nome="MySQL",
        tipo="mysql",
        driver="pymysql",
        porta_padrao="3306",
        banco_padrao="mysql",
        usuario_padrao="root",
        senha_padrao="",
    ),
    "SQLServer": Adapter(
        nome="SQL Server",
        tipo="sqlserver",
        driver="pyodbc",
        porta_padrao="1433",
        banco_padrao="master",
        usuario_padrao="sa",
        senha_padrao="",
    ),
}


def conectar_postgres(credenciais: dict, database: str | None = None):
    import psycopg

    return psycopg.connect(
        host=credenciais["host"],
        port=int(credenciais["port"]),
        dbname=database or credenciais.get("database") or "postgres",
        user=credenciais["user"],
        password=credenciais["password"],
        connect_timeout=5,
    )


def conectar_mysql(credenciais: dict, database: str | None = None):
    import pymysql

    return pymysql.connect(
        host=credenciais["host"],
        port=int(credenciais["port"]),
        database=database or credenciais.get("database"),
        user=credenciais["user"],
        password=credenciais["password"],
        connect_timeout=5,
    )


def conectar_sqlserver(credenciais: dict, database: str | None = None):
    import pyodbc

    opcoes = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
    ]
    driver = next((d for d in opcoes if d in pyodbc.drivers()), None)
    if driver is None:
        raise RuntimeError(
            "Nenhum driver ODBC do SQL Server instalado. "
            "Instale: " + " ou ".join(opcoes)
        )
    return pyodbc.connect(
        f"DRIVER={{{driver}}};SERVER={credenciais['host']},{credenciais['port']};"
        f"DATABASE={database or credenciais.get('database') or 'master'};UID={credenciais['user']};"
        f"PWD={credenciais['password']};TrustServerCertificate=yes;Connection Timeout=5"
    )


def testar_conexao(adapter: Adapter, credenciais: dict) -> Tuple[bool, str]:
    if adapter.tipo == "postgresql":
        return _testar_postgres(credenciais)
    if adapter.tipo == "mysql":
        return _testar_mysql(credenciais)
    if adapter.tipo == "sqlserver":
        return _testar_sqlserver(credenciais)
    return False, f"Adapter desconhecido: {adapter.tipo}"


def instalar_driver_sqlserver() -> Tuple[bool, str]:
    sistema = platform.system()
    if sistema == "Windows":
        return _instalar_driver_windows()
    if sistema == "Linux":
        return _instalar_driver_linux()
    if sistema == "Darwin":
        return _instalar_driver_macos()
    return False, (
        f"Instalação automática não suportada em {sistema}. "
        "Instale manualmente o ODBC Driver 18 for SQL Server: "
        "https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server"
    )


def _testar_postgres(credenciais: dict) -> Tuple[bool, str]:
    try:
        conn = conectar_postgres(credenciais)
        conn.close()
        return True, "ok"
    except Exception as erro:
        mensagem = str(erro)
        if _erro_eh_dns(mensagem):
            mensagem += _dica_erro_dns(credenciais["host"])
        return False, mensagem


def _testar_mysql(credenciais: dict) -> Tuple[bool, str]:
    try:
        conn = conectar_mysql(credenciais)
        conn.close()
        return True, "ok"
    except Exception as erro:
        mensagem = str(erro)
        if _erro_eh_dns(mensagem):
            mensagem += _dica_erro_dns(credenciais["host"])
        return False, mensagem


def _testar_sqlserver(credenciais: dict) -> Tuple[bool, str]:
    try:
        conn = conectar_sqlserver(credenciais)
        conn.close()
        return True, "ok"
    except Exception as erro:
        return False, str(erro)


def eh_administrador() -> bool:
    """True se o processo atual tem privilegios de administrador no Windows."""
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _create_no_window() -> int:
    """Flag do Windows que impede a criacao de uma nova janela de console."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


_CABECALHO_MSI = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _msi_eh_valido(caminho: Path) -> bool:
    """Valida que o arquivo e um MSI (documento OLE) e nao esta vazio."""
    if not caminho.is_file() or caminho.stat().st_size == 0:
        return False
    with open(caminho, "rb") as arquivo:
        return arquivo.read(8) == _CABECALHO_MSI


def _erro_eh_dns(mensagem: str) -> bool:
    baixo = mensagem.lower()
    return (
        "getaddrinfo" in baixo
        or "11001" in baixo
        or "name or service not known" in baixo
        or "temporary failure in name resolution" in baixo
    )


def _dica_erro_dns(host: str) -> str:
    if "supabase.co" in host:
        return (
            " Dica: o host nao resolveu (so tem IPv6 e esta rede nao tem IPv6). "
            "No Supabase, use as credenciais da aba Pooler: host aws-0-<regiao>.pooler.supabase.com "
            "(porta 5432) e usuario postgres.<ref-do-projeto>."
        )
    return " Dica: o host nao resolveu no DNS. Confira o endereco e a conexao com a internet."


def _baixar_msi_odbc(url: str, destino: Path) -> Tuple[bool, str]:
    """Baixa o MSI via Python (sem abrir janela do PowerShell) e valida o arquivo."""
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.unlink(missing_ok=True)
        parcial = destino.with_name(destino.name + ".part")
        parcial.unlink(missing_ok=True)
        requisicao = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(requisicao, timeout=120) as resposta:
            with open(parcial, "wb") as saida:
                while True:
                    bloco = resposta.read(1024 * 1024)
                    if not bloco:
                        break
                    saida.write(bloco)
        parcial.replace(destino)
        if not _msi_eh_valido(destino):
            destino.unlink(missing_ok=True)
            return False, "Falha ao baixar o instalador: o arquivo baixado nao e um MSI valido."
        return True, ""
    except Exception as erro:
        return False, f"Falha ao baixar o instalador: {erro}"


def _ler_log_instalacao(log: Path) -> str:
    try:
        return log.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return log.read_text(encoding="cp1252", errors="replace")
    except OSError:
        return ""


def _tem_vc_redist_x64() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import winreg
    except Exception:
        return False
    for chave in (
        r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
        r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, chave) as reg:
                instalado, _ = winreg.QueryValueEx(reg, "Installed")
            if instalado == 1:
                return True
        except OSError:
            continue
    return False


def _dicas_falha_msi(codigo: int) -> str:
    dicas = []
    if _tem_reboot_pendente():
        dicas.append("ha um reinicio pendente no Windows (reinicie e tente novamente)")
    if codigo == 1603 and not _tem_vc_redist_x64():
        dicas.append("o Visual C++ Redistributable x64 parece nao estar instalado")
    return (" Causas comuns: " + "; ".join(dicas) + ".") if dicas else ""


def _comando_winget_elevado(pacote: str) -> str:
    argumentos = (
        "install --id {0} --silent --accept-source-agreements "
        "--accept-package-agreements --disable-interactivity"
    ).format(pacote)
    return (
        "$p = Start-Process -FilePath winget.exe -ArgumentList '"
        + argumentos.replace("'", "''")
        + "' -Verb RunAs -Wait -PassThru -WindowStyle Hidden; exit $p.ExitCode"
    )


def _comando_msi_elevado(msi: Path, log: Path) -> str:
    argumentos = (
        '/i "{0}" /quiet /norestart /l*v "{1}" IACCEPTMSODBCSQLLICENSETERMS=YES'
    ).format(msi, log)
    return (
        "$p = Start-Process -FilePath msiexec.exe -ArgumentList '"
        + argumentos.replace("'", "''")
        + "' -Verb RunAs -Wait -PassThru -WindowStyle Hidden; exit $p.ExitCode"
    )


def _tem_reboot_pendente() -> bool:
    """True se ha um reinicio pendente no Windows (bloqueia instalacoes MSI)."""
    if platform.system() != "Windows":
        return False
    try:
        import winreg
    except Exception:
        return False
    chaves = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
    )
    for chave in chaves:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, chave):
                return True
        except FileNotFoundError:
            continue
        except OSError:
            continue
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager") as reg:
            valor, _ = winreg.QueryValueEx(reg, "PendingFileRenameOperations")
            if valor:
                return True
    except Exception:
        pass
    return False


def _mensagem_erro_msi(codigo: int, log: Path | None = None) -> str:
    nomes = {
        1603: "falha geral na instalacao (1603)",
        1618: "outra instalacao em andamento (1618)",
        1619: "nao foi possivel abrir o pacote MSI (1619)",
        1625: "instalacao bloqueada pela politica do sistema (1625)",
        1925: "privilegios insuficientes (1925)",
    }
    detalhe = nomes.get(codigo, f"codigo {codigo}")
    if log and log.exists():
        linhas = [ln.strip() for ln in _ler_log_instalacao(log).splitlines() if ln.strip()]
        if linhas:
            detalhe += " | " + " | ".join(linhas[-3:])[:400]
    return detalhe


def _instalar_driver_windows() -> Tuple[bool, str]:
    if _tem_reboot_pendente():
        return False, (
            "Há um reinício pendente no Windows que bloqueia a instalação do driver. "
            "Reinicie o computador e rode a instalação novamente."
        )
    if not eh_administrador():
        return _instalar_driver_windows_uac()
    return _instalar_driver_windows_admin()


def _instalar_driver_windows_admin() -> Tuple[bool, str]:
    if shutil.which("winget"):
        for pacote in ("Microsoft.msodbcsql.18", "Microsoft.msodbcsql.17"):
            resultado = subprocess.run(
                ["winget", "install", "--id", pacote, "--silent",
                 "--accept-source-agreements", "--accept-package-agreements",
                 "--disable-interactivity"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=_create_no_window(),
            )
            if resultado.returncode == 0:
                return True, f"Driver ODBC instalado via winget ({pacote})."
        return False, (
            "Falha ao instalar via winget. Verifique o winget ou instale manualmente:\n"
            "  winget install --id Microsoft.msodbcsql.18"
        )

    url = "https://go.microsoft.com/fwlink/?linkid=2249006"
    msi = Path(tempfile.gettempdir()) / "msodbcsql18.msi"
    log = Path(tempfile.gettempdir()) / "msodbcsql_install.log"
    for tentativa in range(2):
        baixar, mensagem = _baixar_msi_odbc(url, msi)
        if not baixar:
            return False, mensagem
        instalar = subprocess.run(
            ["msiexec", "/i", str(msi), "/quiet", "/norestart",
             "/l*v", str(log), "IACCEPTMSODBCSQLLICENSETERMS=YES"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=_create_no_window(),
        )
        if instalar.returncode in (0, 3010):
            return True, "Driver ODBC 18 instalado via MSI."
        if instalar.returncode == 1603 and tentativa == 0:
            msi.unlink(missing_ok=True)
            log.unlink(missing_ok=True)
            continue
        return False, (
            "O instalador foi baixado, mas a instalação falhou: "
            f"{_mensagem_erro_msi(instalar.returncode, log)}"
            f"{_dicas_falha_msi(instalar.returncode)} Rode manualmente:\n"
            f'  msiexec /i "{msi}" /quiet IACCEPTMSODBCSQLLICENSETERMS=YES'
        )
    return False, "Falha na instalação via MSI."


def _instalar_driver_windows_uac() -> Tuple[bool, str]:
    if shutil.which("winget"):
        for pacote in ("Microsoft.msodbcsql.18", "Microsoft.msodbcsql.17"):
            resultado = subprocess.run(
                ["powershell", "-NoProfile", "-Command", _comando_winget_elevado(pacote)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=_create_no_window(),
            )
            if resultado.returncode == 0:
                return True, f"Driver ODBC instalado via winget ({pacote})."
            if resultado.returncode == 1223 or "cancel" in resultado.stderr.lower():
                return False, "A instalação foi cancelada na janela de permissão do Windows (UAC)."

    url = "https://go.microsoft.com/fwlink/?linkid=2249006"
    msi = Path(tempfile.gettempdir()) / "msodbcsql18.msi"
    log = Path(tempfile.gettempdir()) / "msodbcsql_install.log"
    for tentativa in range(2):
        baixar, mensagem = _baixar_msi_odbc(url, msi)
        if not baixar:
            return False, mensagem
        resultado = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _comando_msi_elevado(msi, log)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=_create_no_window(),
        )
        if resultado.returncode in (0, 3010):
            return True, "Driver ODBC 18 instalado via MSI (com permissão de administrador)."
        if resultado.returncode == 1223 or "cancel" in resultado.stderr.lower():
            return False, "A instalação foi cancelada na janela de permissão do Windows (UAC)."
        if resultado.returncode == 1603 and tentativa == 0:
            msi.unlink(missing_ok=True)
            log.unlink(missing_ok=True)
            continue
        return False, (
            "Não foi possível instalar com permissão de administrador: "
            f"{_mensagem_erro_msi(resultado.returncode, log)}"
            f"{_dicas_falha_msi(resultado.returncode)}"
        )
    return False, "Falha na instalação via MSI."


def _instalar_driver_linux() -> Tuple[bool, str]:
    if not shutil.which("apt-get"):
        return False, (
            "Automação suportada apenas em distribuições apt (Debian/Ubuntu). "
            "Siga o guia oficial: https://learn.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server"
        )
    sudo_ok = subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0
    if not sudo_ok:
        return False, (
            "O sudo exige senha e não pode ser automatizado sem interação. Rode manualmente:\n"
            "  curl -sSL https://packages.microsoft.com/keys/microsoft.asc | sudo tee /etc/apt/trusted.gpg.d/microsoft.asc\n"
            "  curl -sSL https://packages.microsoft.com/config/ubuntu/24.04/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list\n"
            "  sudo apt-get update\n"
            "  sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18"
        )

    url_repo = None
    for versao in ("ubuntu/24.04", "ubuntu/22.04", "ubuntu/20.04", "debian/12", "debian/11"):
        teste = subprocess.run(
            ["curl", "-fsSL", "-o", "/dev/null",
             f"https://packages.microsoft.com/config/{versao}/prod.list"],
            capture_output=True,
        )
        if teste.returncode == 0:
            url_repo = f"https://packages.microsoft.com/config/{versao}/prod.list"
            break
    if url_repo is None:
        return False, "Não foi possível detectar um repositório Microsoft apt compatível."

    comandos = [
        ["sudo", "bash", "-c", "curl -sSL https://packages.microsoft.com/keys/microsoft.asc | tee /etc/apt/trusted.gpg.d/microsoft.asc"],
        ["sudo", "bash", "-c", f"curl -sSL {url_repo} | tee /etc/apt/sources.list.d/mssql-release.list"],
        ["sudo", "apt-get", "update"],
        ["sudo", "env", "ACCEPT_EULA=Y", "apt-get", "install", "-y", "msodbcsql18"],
    ]
    for comando in comandos:
        resultado = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if resultado.returncode != 0:
            return False, f"Falha em {' '.join(comando)}: {resultado.stderr.strip()[-300:]}"
    return True, "Driver ODBC 18 instalado via apt."


def _instalar_driver_macos() -> Tuple[bool, str]:
    if not shutil.which("brew"):
        return False, (
            "Homebrew não encontrado. Siga o guia oficial: "
            "https://learn.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server"
        )
    for comando in (
        ["brew", "tap", "microsoft/mssql-release", "https://github.com/Microsoft/homebrew-mssql-release"],
        ["brew", "update"],
    ):
        resultado = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if resultado.returncode != 0:
            return False, f"Falha em {' '.join(comando)}: {resultado.stderr.strip()[-300:]}"
    ambiente = {**os.environ, "HOMEBREW_ACCEPT_EULA": "Y"}
    resultado = subprocess.run(
        ["brew", "install", "msodbcsql18"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=ambiente,
    )
    if resultado.returncode != 0:
        return False, f"Falha ao instalar msodbcsql18: {resultado.stderr.strip()[-300:]}"
    return True, "Driver ODBC 18 instalado via Homebrew."
