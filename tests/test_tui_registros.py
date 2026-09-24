"""Registros do shell em SQLite: a saída guardada para consultar depois.

O banco destes testes é sempre um arquivo de ``tmp_path`` (a env
``CONDUTO_REGISTROS`` é fixada no conftest): nenhum teste toca o
``~/.conduto`` de quem roda. Aqui ficam a persistência, a renderização fiel
de um ``console.print`` e a poda; o lado da tela (``F3``) está em
``tests/test_tui_shell.py``.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from rich.table import Table
from rich.text import Text

from conduto.tui import registros

#: O formato do ``momento`` — ISO local, ordenável lexicograficamente.
FORMATO = "%Y-%m-%dT%H:%M:%S"


# ---------------------------------------------------------------------------
# Caminho do arquivo
# ---------------------------------------------------------------------------


def test_caminho_honra_a_env_conduto_registros(monkeypatch, tmp_path):
    alvo = tmp_path / "outro" / "registros.db"
    monkeypatch.setenv("CONDUTO_REGISTROS", str(alvo))
    assert registros.caminho() == alvo


def test_caminho_sem_env_cai_em_conduto_na_home(monkeypatch):
    monkeypatch.delenv("CONDUTO_REGISTROS", raising=False)
    assert registros.caminho() == Path.home() / ".conduto" / "registros.db"


def test_caminho_expande_o_til_da_env(monkeypatch):
    monkeypatch.setenv("CONDUTO_REGISTROS", "~/meus.db")
    assert registros.caminho() == Path.home() / "meus.db"


# ---------------------------------------------------------------------------
# Criação do schema na primeira gravação
# ---------------------------------------------------------------------------


def test_primeira_gravacao_cria_diretorio_banco_e_indice(monkeypatch, tmp_path):
    arquivo = tmp_path / "bem" / "fundo" / "registros.db"
    monkeypatch.setenv("CONDUTO_REGISTROS", str(arquivo))
    registros.fechar()  # a conexão anterior apontava para outro arquivo

    assert not arquivo.exists()
    assert registros.gravar("s1", "init", None, ("oi",), {}) is not None
    assert arquivo.exists()

    # solta a conexão do módulo para inspecionar o arquivo cru
    registros.fechar()
    with sqlite3.connect(str(arquivo)) as conexao:
        colunas = {
            linha[1]
            for linha in conexao.execute("PRAGMA table_info(registros)")
        }
        indices = [
            linha[0]
            for linha in conexao.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
                " AND tbl_name='registros'"
            )
        ]
    assert {"id", "sessao", "comando", "etapa", "momento", "texto", "estilo"} <= colunas
    assert any("sessao" in nome for nome in indices)


# ---------------------------------------------------------------------------
# Roundtrip e separação por sessão
# ---------------------------------------------------------------------------


def test_gravar_e_consultar_na_ordem_em_que_foram_impressos():
    registros.gravar("sessao-a", "init", "origem_sgbd", ("primeira",), {})
    registros.gravar("sessao-a", "init", "origem_credenciais", ("segunda",), {})
    registros.gravar("sessao-b", "ddl", None, ("de outra sessao",), {})

    da_a = registros.consultar("sessao-a")
    assert [registro.texto for registro in da_a] == ["primeira", "segunda"]
    assert [registro.etapa for registro in da_a] == [
        "origem_sgbd",
        "origem_credenciais",
    ]
    # a sessão alheia não vaza para cá
    assert [registro.texto for registro in registros.consultar("sessao-b")] == [
        "de outra sessao"
    ]


def test_sessao_sem_nenhum_registro_devolve_lista_vazia():
    assert registros.consultar("nunca-existiu") == []


def test_gravar_guarda_a_etapa_o_comando_e_um_momento_iso():
    registros.gravar("s-etapa", "init", "origem_sgbd", ("linha",), {})
    registro = registros.consultar("s-etapa")[0]
    assert registro.etapa == "origem_sgbd"
    # formato ISO local: ordena lexicograficamente e cabe no visualizador
    datetime.strptime(registro.momento, FORMATO)


def test_etapa_nula_antes_do_primeiro_marcador():
    registros.gravar("s-nula", "init", None, ("ainda sem marcador",), {})
    assert registros.consultar("s-nula")[0].etapa is None


def test_consultar_respeita_o_limite_e_devolve_mais_recentes_no_fim():
    for numero in range(10):
        registros.gravar("s-limite", "init", None, (f"linha {numero}",), {})
    ultimas = registros.consultar("s-limite", limite=3)
    assert [registro.texto for registro in ultimas] == [
        "linha 7",
        "linha 8",
        "linha 9",
    ]


# ---------------------------------------------------------------------------
# Renderização fiel de um console.print
# ---------------------------------------------------------------------------


def test_renderizar_print_texto_puro_e_estilo_com_cor():
    texto, estilo = registros.renderizar_print(
        ("[bold green]OK[/bold green] mensagem",), {}
    )
    assert texto == "OK mensagem"  # sem marcas de markup
    assert "\x1b[" in estilo  # a cor fica para a tela reconverter
    assert not texto.startswith("\x1b")  # o texto de leitura é limpo


def test_renderizar_print_sem_estilo_nao_carrega_ansi_no_texto():
    texto, estilo = registros.renderizar_print(("mensagem simples",), {})
    assert texto == "mensagem simples"
    assert estilo == "mensagem simples"


def test_renderizar_print_markup_quebrado_cai_para_literal():
    # rich levanta MarkupError na tag que não fecha — o print não pode derrubar
    texto, estilo = registros.renderizar_print(
        ("[bold green]OK[/bold] quebrado",), {}
    )
    assert texto == "[bold green]OK[/bold] quebrado"
    assert estilo == texto  # sem cor: virou texto corrido


def test_renderizar_print_respeita_markup_false_do_chamador():
    texto, _estilo = registros.renderizar_print(
        ("[bold]literal[/bold]",), {"markup": False}
    )
    assert texto == "[bold]literal[/bold]"


def test_renderizar_print_text_do_rich():
    texto, estilo = registros.renderizar_print(
        (Text("falhou", style="red"),), {}
    )
    assert texto == "falhou"
    assert "\x1b[" in estilo  # o status vermelho sobrevive


def test_renderizar_print_tabela_vira_varias_linhas():
    grade = Table("coluna")
    grade.add_row("valor")
    texto, estilo = registros.renderizar_print((grade,), {})
    assert "coluna" in texto and "valor" in texto
    assert len(texto.splitlines()) > 1  # tabela é multilinha
    assert not texto.endswith("\n")  # a quebra de fim de linha foi cortada
    # mesma geometria (o estilo tem ANSI, então o texto não bate linha a linha)
    assert len(estilo.splitlines()) == len(texto.splitlines())


def test_renderizar_print_sem_argumentos_gera_linha_vazia():
    texto, estilo = registros.renderizar_print((), {})
    assert texto == ""
    assert estilo == ""


def test_renderizar_print_kwarg_desconhecido_nao_explode():
    # TypeError do rich: cai no texto corrido dos argumentos
    texto, estilo = registros.renderizar_print(("com kwarg",), {"nao_existe": 1})
    assert texto == "com kwarg"
    assert estilo == "com kwarg"


def test_renderizar_print_aceita_estilo_e_justificativa():
    texto, _estilo = registros.renderizar_print(
        ("centrado",), {"style": "bold", "justify": "center"}
    )
    assert texto.strip() == "centrado"


def test_renderizar_print_preserva_colchete_literal():
    # SQL parametrizado no log: [1] não é markup e tem de sobreviver inteiro
    texto, _estilo = registros.renderizar_print(("WHERE id = [1]",), {})
    assert texto == "WHERE id = [1]"


# ---------------------------------------------------------------------------
# Nunca quebra o comando
# ---------------------------------------------------------------------------


def test_gravar_retorna_none_com_o_banco_fora(monkeypatch):
    def _explodir():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(registros, "_conectar", _explodir)
    # um print não pode derrubar o comando: só não guarda
    assert registros.gravar("s-falha", "init", None, ("oi",), {}) is None


def test_consultar_retorna_vazio_com_o_banco_fora(monkeypatch):
    def _explodir():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(registros, "_conectar", _explodir)
    assert registros.consultar("s-falha") == []


def test_podar_retorna_zero_com_o_banco_fora(monkeypatch):
    def _explodir():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(registros, "_conectar", _explodir)
    assert registros.podar() == 0


# ---------------------------------------------------------------------------
# Poda: o arquivo não cresce para sempre
# ---------------------------------------------------------------------------


def test_podar_remove_o_antigo_e_mantem_o_recente():
    registros.gravar("sessao-velha", "init", None, ("antiga",), {})
    registros.gravar("sessao-recente", "ddl", None, ("nova",), {})

    # envelhece a linha antiga para valer (o INSERT gravou o agora)
    dez_dias_atras = (datetime.now() - timedelta(days=10)).strftime(FORMATO)
    with sqlite3.connect(str(registros.caminho())) as conexao:
        conexao.execute(
            "UPDATE registros SET momento = ? WHERE sessao = ?",
            (dez_dias_atras, "sessao-velha"),
        )
        conexao.commit()

    assert registros.podar(dias=7) == 1
    assert registros.consultar("sessao-velha") == []
    assert [registro.texto for registro in registros.consultar("sessao-recente")] == [
        "nova"
    ]


def test_podar_nao_remove_o_que_esta_dentro_do_prazo():
    registros.gravar("sessao-recente", "init", None, ("fica",), {})
    assert registros.podar(dias=7) == 0
    assert [registro.texto for registro in registros.consultar("sessao-recente")] == [
        "fica"
    ]
