"""Modelo de seleção: a regra de negócio das telas, sem depender de terminal.

A tela (Textual) só desenha. Quem filtra, marca, desmarca e devolve os
valores é o :class:`ModeloSelecao` — assim dá para testar a flegagem uma a
uma, a "selecionar todas" e o filtro sem abrir nenhum TUI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Sequence, Set

from conduto.tui.tema import Status

#: Modo multi-seleção (checkbox: flegar uma a uma + marcar todas).
MULTIPLA = "multipla"
#: Modo seleção única (escolha de SGBD, banco, schema, sim/não...).
UNICA = "unica"

MODOS = (MULTIPLA, UNICA)


@dataclass
class Choice:
    """Opção de uma tela de seleção.

    ``title`` é o que aparece na linha, ``value`` é o que a tela devolve,
    ``status`` dá a cor da linha (verde/âmbar/vermelho/azul/cinza) e
    ``detalhe`` é o texto ao lado do status (ex.: "12 tabelas", "já existe").
    """

    title: str
    value: Any = None
    status: Status = Status.NEUTRO
    detalhe: str = ""

    def __post_init__(self) -> None:
        # Mesma convenção de sempre: sem valor explícito, devolve o título.
        if self.value is None:
            self.value = self.title


def para_choice(item: Any) -> Choice:
    """Aceita ``Choice`` ou texto simples e devolve sempre um :class:`Choice`."""
    if isinstance(item, Choice):
        return item
    return Choice(title=str(item))


class ModeloSelecao:
    """Filtro + flegagem de uma lista de opções.

    Os índices internos são **absolutos** (posição na lista original); a
    filtragem muda só quem está visível. Assim a marcação feita antes do
    filtro continua valendo depois dele e a ordem de saída é sempre a da
    lista original.
    """

    def __init__(self, itens: Iterable[Any], modo: str = MULTIPLA) -> None:
        if modo not in MODOS:
            raise ValueError(f"Modo de seleção desconhecido: {modo}")
        self.itens: List[Choice] = [para_choice(item) for item in itens]
        self.modo = modo
        self.consulta = ""
        self._marcados: Set[int] = set()
        if modo == UNICA and self.itens:
            # Sem nada marcado o enter confirmaria "vazio"; começa na primeira.
            self._marcados = {0}

    # ------------------------------------------------------------------
    # Filtro
    # ------------------------------------------------------------------

    @property
    def consulta_normalizada(self) -> str:
        return self.consulta.strip().lower()

    def filtrar(self, consulta: str) -> None:
        """Filtra por título **ou** detalhe, sem diferenciar maiúsculas."""
        self.consulta = consulta or ""
        if self.modo == UNICA:
            self._ajustar_unica_aos_visiveis()

    @property
    def indices_visiveis(self) -> List[int]:
        """Índices (absolutos) das opções que passam no filtro atual."""
        consulta = self.consulta_normalizada
        if not consulta:
            return list(range(len(self.itens)))
        return [
            indice
            for indice, escolha in enumerate(self.itens)
            if consulta in _texto_de_busca(escolha)
        ]

    @property
    def visiveis(self) -> List[Choice]:
        """Opções que passam no filtro atual, na ordem original."""
        return [self.itens[indice] for indice in self.indices_visiveis]

    # ------------------------------------------------------------------
    # Flegagem
    # ------------------------------------------------------------------

    @property
    def marcados(self) -> Set[int]:
        """Índices (absolutos) marcados."""
        return set(self._marcados)

    def esta_marcado(self, indice: int) -> bool:
        return indice in self._marcados

    def alternar(self, indice: int) -> bool:
        """Flega/desflega uma opção (no modo único, marca só ela).

        Devolve o estado novo da opção.
        """
        if not 0 <= indice < len(self.itens):
            return False
        if self.modo == UNICA:
            self._marcados = {indice}
            return True
        if indice in self._marcados:
            self._marcados.discard(indice)
            return False
        self._marcados.add(indice)
        return True

    def selecionar(self, indice: int) -> None:
        """Marca exatamente uma opção (usado pelo modo único)."""
        if 0 <= indice < len(self.itens):
            self._marcados = {indice}

    def marcar_todas(self) -> int:
        """Marca **todas as opções visíveis** (o filtro manda) e devolve o total."""
        visiveis = self.indices_visiveis
        if self.modo == UNICA:
            if visiveis:
                self._marcados = {visiveis[0]}
            return len(self._marcados)
        self._marcados.update(visiveis)
        return len(self._marcados)

    def limpar(self) -> None:
        """Desflega tudo (no modo único volta a marcar a primeira visível)."""
        if self.modo == UNICA:
            visiveis = self.indices_visiveis
            self._marcados = {visiveis[0]} if visiveis else set()
            return
        self._marcados.clear()

    @property
    def contagem(self) -> tuple:
        """``(marcadas, visíveis, total)`` — alimenta a barra de status."""
        return len(self._marcados), len(self.indices_visiveis), len(self.itens)

    @property
    def visiveis_com_atencao(self) -> int:
        """Quantas opções visíveis carregam status de atenção (âmbar/vermelho)."""
        return sum(
            1
            for indice in self.indices_visiveis
            if self.itens[indice].status in (Status.AVISO, Status.ERRO)
        )

    def selecionados(self) -> List[Any]:
        """Valores marcados, **na ordem da lista original** (não a do filtro)."""
        return [
            self.itens[indice].value
            for indice in sorted(self._marcados)
        ]

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _ajustar_unica_aos_visiveis(self) -> None:
        """No modo único a marca tem de estar sempre numa opção visível."""
        visiveis = self.indices_visiveis
        if not visiveis:
            self._marcados.clear()
            return
        if not self._marcados or not (self._marcados & set(visiveis)):
            self._marcados = {visiveis[0]}


def _texto_de_busca(escolha: Choice) -> str:
    return f"{escolha.title} {escolha.detalhe}".lower()


def valores_de(escolhas: Sequence[Any]) -> List[Any]:
    """Converte uma lista de opções nos valores que as telas devolvem."""
    return [para_choice(escolha).value for escolha in escolhas]
