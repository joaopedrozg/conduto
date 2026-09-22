"""Testes do helper de drivers (extras por SGBD)."""

import importlib
import shutil
import sys

import pytest

from conduto.database import drivers as drivers_mod
from conduto.database.drivers import (
    MODULOS_POR_SGBD,
    _REQ_POR_MODULO,
    drivers_faltantes,
    extra_do_driver,
    importar_driver,
    instalar_drivers,
    requisicoes_pendentes,
)


def test_extra_do_driver_conhece_todos_os_sgbd():
    assert extra_do_driver("psycopg") == "postgresql"
    assert extra_do_driver("pymysql") == "mysql"
    assert extra_do_driver("pyodbc") == "sqlserver"
    assert extra_do_driver("clickhouse_connect") == "clickhouse"
    assert extra_do_driver("duckdb") == "duckdb"
    # deltalake usa tres modulos, todos no mesmo extra
    for modulo in ("deltalake", "pyarrow", "boto3"):
        assert extra_do_driver(modulo) == "deltalake"


def test_extra_desconhecido_cai_no_all():
    assert extra_do_driver("qualquer_coisa") == "all"


def test_modulos_por_sgbd_tem_os_seis_sgbds():
    assert set(MODULOS_POR_SGBD) == {
        "postgresql",
        "mysql",
        "sqlserver",
        "clickhouse",
        "duckdb",
        "deltalake",
    }
    # deltalake e o unico que precisa de mais de um modulo
    assert len(MODULOS_POR_SGBD["deltalake"]) == 3


def test_drivers_faltantes_sgbd_desconhecido():
    assert drivers_faltantes("inexistente") == ()


def test_drivers_faltantes_vs_instalados():
    """Cada SGBD reporta como faltante exatamente o que nao esta no ambiente."""
    for tipo, modulos in MODULOS_POR_SGBD.items():
        faltando = drivers_faltantes(tipo)
        for modulo in modulos:
            try:
                importlib.import_module(modulo)
                instalado = True
            except ImportError:
                instalado = False
            assert (modulo in faltando) != instalado, f"{tipo}/{modulo}"


def test_importar_driver_modulo_instalado():
    # yaml e dependencia base do conduto: sempre presente
    assert importar_driver("yaml") is not None


def test_importar_driver_ausente_mostra_extra(monkeypatch):
    """Modulo inexistente vira um RuntimeError apontando o extra a instalar."""
    # garante que o modulo realmente nao exista neste ambiente
    monkeypatch.delitem(sys.modules, "modulo_que_nao_existe_conduto", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        importar_driver("modulo_que_nao_existe_conduto")

    mensagem = str(excinfo.value)
    assert "modulo_que_nao_existe_conduto" in mensagem
    assert "pip install" in mensagem
    assert 'conduto[all]' in mensagem


def test_importar_driver_erro_interno_e_repassado(tmp_path, monkeypatch):
    """ModuleNotFoundError vindo de DENTRO de um modulo existente (outra
    dependencia que faltou) nao pode virar a mensagem de extra."""
    pacote = tmp_path / "pacote_zumbi_conduto"
    pacote.mkdir()
    (pacote / "__init__.py").write_text(
        "import dependencia_que_nao_existe_conduto\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(ModuleNotFoundError) as excinfo:
        importar_driver("pacote_zumbi_conduto")

    # o erro original (da dependencia interna) chega intacto
    assert excinfo.value.name == "dependencia_que_nao_existe_conduto"
    assert "pip install" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# requisicoes_pendentes / instalar_drivers
# ---------------------------------------------------------------------------


def test_requisicoes_pendentes_usa_nome_pip():
    """O requisito pip difere do modulo em dois casos: psycopg[binary] e
    clickhouse-connect (modulo com sublinhado, pacote com hifen)."""
    assert _REQ_POR_MODULO["psycopg"] == "psycopg[binary]"
    assert _REQ_POR_MODULO["clickhouse_connect"] == "clickhouse-connect"
    # todo modulo tem requisito mapeado
    for modulos in MODULOS_POR_SGBD.values():
        for modulo in modulos:
            assert modulo in _REQ_POR_MODULO, modulo


def test_requisicoes_pendentes_sgbd_desconhecido():
    assert requisicoes_pendentes("inexistente") == []


def test_requisicoes_pendentes_reflete_o_ambiente():
    """So pede instalar o que realmente falta neste ambiente."""
    for tipo in MODULOS_POR_SGBD:
        pendentes = requisicoes_pendentes(tipo)
        assert len(pendentes) == len(drivers_faltantes(tipo))


def test_instalar_drivers_nada_pendente(monkeypatch):
    """Com tudo instalado, nao roda nenhum comando e devolve sucesso."""
    monkeypatch.setattr(drivers_mod, "_rodar", lambda comando: pytest.fail(
        "nao deveria instalar nada"
    ))
    ok, mensagem = instalar_drivers("postgresql")
    assert ok is True
    assert "já estão instaladas" in mensagem


def test_instalar_drivers_sgbd_desconhecido(monkeypatch):
    monkeypatch.setattr(drivers_mod, "_rodar", lambda comando: pytest.fail(
        "sgbd desconhecido nao tem o que instalar"
    ))
    ok, mensagem = instalar_drivers("nao_existe")
    assert ok is True


def _com_pip(monkeypatch, disponivel: bool):
    """Fixa a disponibilidade do pip: venvs do uv nao o trazem, entao o teste
    nao pode depender do ambiente real."""
    real_find_spec = importlib.util.find_spec

    def _find_spec(nome):
        if nome == "pip":
            return object() if disponivel else None
        return real_find_spec(nome)

    monkeypatch.setattr(importlib.util, "find_spec", _find_spec)


def test_candidatos_instalacao_prefere_uv_depois_pip(monkeypatch):
    """uv cobre ambientes gerados por uv (uvx nao tem pip); pip cobre o resto."""
    monkeypatch.setattr(shutil, "which", lambda nome: "/usr/bin/uv")
    _com_pip(monkeypatch, disponivel=True)

    candidatos = drivers_mod._candidatos_instalacao(["pyodbc"])

    assert candidatos[0][:3] == ["/usr/bin/uv", "pip", "install"]
    # o uv aponta para o interpretador em uso, senao instalaria noutro lugar
    assert sys.executable in candidatos[0]
    assert candidatos[1][:3] == [sys.executable, "-m", "pip"]


def test_candidatos_instalacao_com_uv_sem_pip_so_uv(monkeypatch):
    """venv do uv: so o uv, ja que `python -m pip` falharia por nao existir."""
    monkeypatch.setattr(shutil, "which", lambda nome: "/usr/bin/uv")
    _com_pip(monkeypatch, disponivel=False)

    candidatos = drivers_mod._candidatos_instalacao(["pyodbc"])

    assert len(candidatos) == 1
    assert candidatos[0][0] == "/usr/bin/uv"


def test_candidatos_instalacao_sem_uv_so_pip(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda nome: None)
    _com_pip(monkeypatch, disponivel=True)

    candidatos = drivers_mod._candidatos_instalacao(["pyodbc"])

    assert len(candidatos) == 1
    assert candidatos[0][:3] == [sys.executable, "-m", "pip"]


def test_candidatos_instalacao_sem_uv_nem_pip(monkeypatch):
    """Nenhum instalador disponivel: nao ha o que tentar."""
    monkeypatch.setattr(shutil, "which", lambda nome: None)
    _com_pip(monkeypatch, disponivel=False)
    assert drivers_mod._candidatos_instalacao(["pyodbc"]) == []


def test_instalar_drivers_sem_instalador_fica_claro(monkeypatch):
    monkeypatch.setattr(
        drivers_mod, "_candidatos_instalacao", lambda reqs, quebrar_sistema=False: []
    )
    monkeypatch.setattr(drivers_mod, "gerenciado_pelo_sistema", lambda: False)
    monkeypatch.setattr(drivers_mod, "requisicoes_pendentes", lambda tipo: ["pyodbc"])
    ok, mensagem = instalar_drivers("sqlserver")
    assert ok is False
    assert "pip install pyodbc" in mensagem


def test_instalar_drivers_sucesso_no_primeiro_comando(monkeypatch):
    chamados = []

    def _rodar_ok(comando):
        chamados.append(comando)
        return "", False

    monkeypatch.setattr(drivers_mod, "requisicoes_pendentes", lambda tipo: ["pyodbc"])
    monkeypatch.setattr(
        drivers_mod,
        "_candidatos_instalacao",
        lambda reqs, quebrar_sistema=False: [["fake-uv"], ["fake-pip"]],
    )
    monkeypatch.setattr(drivers_mod, "_rodar", _rodar_ok)

    ok, mensagem = instalar_drivers("sqlserver")
    assert ok is True
    assert len(chamados) == 1  # para no sucesso, nao tenta o proximo
    assert "pyodbc" in mensagem


def test_instalar_drivers_falla_nos_dois_mostra_o_erro_e_o_comando(monkeypatch):
    """Se os dois instaladores falham, a mensagem junta o ultimo erro e o
    comando manual — nada de falha silenciosa."""
    respostas = iter([("uv deu ruim", True), ("pip deu ruim", True)])
    monkeypatch.setattr(drivers_mod, "requisicoes_pendentes", lambda tipo: ["pyodbc"])
    monkeypatch.setattr(
        drivers_mod,
        "_candidatos_instalacao",
        lambda reqs, quebrar_sistema=False: [["fake-uv"], ["fake-pip"]],
    )
    monkeypatch.setattr(drivers_mod, "_rodar", lambda comando: next(respostas))

    ok, mensagem = instalar_drivers("sqlserver")
    assert ok is False
    assert "pip deu ruim" in mensagem  # o ultimo erro e o que importa
    assert "pip install pyodbc" in mensagem  # sempre diz o que fazer na mao


def test_resumir_corta_saida_longa():
    longa = "x" * 1000
    resumo = drivers_mod._resumir(longa, limite=100)
    assert len(resumo) < 120
    assert resumo.startswith("...")
    # disse algo util quando o instalador nao deu nada
    assert drivers_mod._resumir("") == "sem saída"


def test_rodar_comando_inexistente_nao_levanta(monkeypatch):
    """_rodar nunca joga excecao: o fluxo do CLI depende do tupla (saida, falhou)."""
    saida, falhou = drivers_mod._rodar(["/bin/comando_que_nao_existe_zumbi_123"])
    assert falhou is True
    assert isinstance(saida, str) and saida


# ---------------------------------------------------------------------------
# PEP 668: Linux (Debian/Ubuntu, Fedora, Arch) e Homebrew barram pip fora de venv
# ---------------------------------------------------------------------------


def test_gerenciado_pelo_sistema_nunca_dentro_de_venv(monkeypatch, tmp_path):
    """Dentro de venv o stdlib pode apontar para o sistema, onde o marker
    EXISTE — mas a instalacao funciona. Checar so o arquivo daria falso
    positivo no ambiente correto, entao 'em venv' vence."""
    monkeypatch.setattr(drivers_mod, "em_venv", lambda: True)
    marcador = tmp_path / "EXTERNALLY-MANAGED"
    marcador.write_text("[externally-managed]\n")
    monkeypatch.setattr(
        drivers_mod.sysconfig, "get_path", lambda nome: str(tmp_path)
    )
    assert drivers_mod.gerenciado_pelo_sistema() is False


def test_gerenciado_pelo_sistema_fora_de_venv_com_marker(monkeypatch, tmp_path):
    """O caso do Ubuntu: Python do sistema com o marker do PEP 668."""
    (tmp_path / "EXTERNALLY-MANAGED").write_text("[externally-managed]\n")
    monkeypatch.setattr(drivers_mod, "em_venv", lambda: False)
    monkeypatch.setattr(drivers_mod.sysconfig, "get_path", lambda nome: str(tmp_path))
    assert drivers_mod.gerenciado_pelo_sistema() is True


def test_gerenciado_pelo_sistema_fora_de_venv_sem_marker(monkeypatch, tmp_path):
    """Windows (python.org) e venv sem marker: pip instalou direto, sem flag."""
    monkeypatch.setattr(drivers_mod, "em_venv", lambda: False)
    monkeypatch.setattr(drivers_mod.sysconfig, "get_path", lambda nome: str(tmp_path))
    assert drivers_mod.gerenciado_pelo_sistema() is False


def test_candidatos_bloqueados_sob_pep668_sem_autorizacao(monkeypatch):
    """Sem autorizar --break-system-packages, nao tenta: pip e uv recusariam
    com um mural de texto da distribuicao. Lista vazia vira mensagem clara."""
    monkeypatch.setattr(drivers_mod, "gerenciado_pelo_sistema", lambda: True)
    monkeypatch.setattr(shutil, "which", lambda nome: "/usr/bin/uv")
    _com_pip(monkeypatch, disponivel=True)

    assert drivers_mod._candidatos_instalacao(["pyodbc"]) == []


def test_candidatos_com_break_system_packages_quando_autorizado(monkeypatch):
    monkeypatch.setattr(drivers_mod, "gerenciado_pelo_sistema", lambda: True)
    monkeypatch.setattr(shutil, "which", lambda nome: "/usr/bin/uv")
    _com_pip(monkeypatch, disponivel=True)

    candidatos = drivers_mod._candidatos_instalacao(
        ["pyodbc"], quebrar_sistema=True
    )

    assert len(candidatos) == 2
    for comando in candidatos:
        assert "--break-system-packages" in comando
    # as requisicoes ficam no fim, depois das flags
    assert candidatos[0][-1] == "pyodbc"


def test_candidatos_sem_flag_quando_nao_gerenciado(monkeypatch):
    """PEP 668 inativo: --break-system-packages seria ruido desnecessario."""
    monkeypatch.setattr(drivers_mod, "gerenciado_pelo_sistema", lambda: False)
    monkeypatch.setattr(shutil, "which", lambda nome: "/usr/bin/uv")
    _com_pip(monkeypatch, disponivel=True)

    candidatos = drivers_mod._candidatos_instalacao(["pyodbc"], quebrar_sistema=True)

    for comando in candidatos:
        assert "--break-system-packages" not in comando


def test_instalar_drivers_sob_pep668_sem_autorizacao_explica(monkeypatch):
    """A mensagem tem que apontar as saidas reais (uvx/venv/flag) em vez de
    repassar o mural de erro da distribuicao."""
    monkeypatch.setattr(drivers_mod, "requisicoes_pendentes", lambda tipo: ["pyodbc"])
    monkeypatch.setattr(drivers_mod, "gerenciado_pelo_sistema", lambda: True)
    monkeypatch.setattr(
        drivers_mod, "_rodar", lambda comando: pytest.fail("nao deveria rodar nada")
    )

    ok, mensagem = instalar_drivers("sqlserver")

    assert ok is False
    assert "PEP 668" in mensagem
    assert "uvx" in mensagem  # o caminho que funciona sem mexer no sistema
    assert "--break-system-packages" in mensagem  # o caminho arriscado


def test_em_venv_espelha_o_interpretador():
    """Sanidade: a funcao reflete o ambiente real (venv do projeto = True)."""
    assert drivers_mod.em_venv() == (sys.prefix != sys.base_prefix)
