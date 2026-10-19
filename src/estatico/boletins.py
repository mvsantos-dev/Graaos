"""Páginas estáticas dos boletins: boletim/AAAA-MM/ (uma por mês) e boletim/ (o arquivo)."""

from __future__ import annotations

from .contexto import Contexto


def gerar(ctx: Contexto) -> None:
    """A preencher: grava as páginas e acrescenta cada uma em ctx.paginas."""
