"""Testes do helper de drivers (extras por SGBD)."""

import importlib
import sys

import pytest

from conduto.database.drivers import (
    MODULOS_POR_SGBD,
    drivers_faltantes,
    extra_do_driver,
    importar_driver,
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
