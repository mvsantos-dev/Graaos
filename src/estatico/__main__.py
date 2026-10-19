"""python3 -m src.estatico PASTA_DO_SITE [--atualizado AAAA-MM-DD] (chamado pelo build_site.sh)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import boletins, cabecalho, resumo, resumo_precos, tabelas
from .contexto import Contexto, ErroEstatico, Pagina


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera o conteúdo estático do site (sem JavaScript), as páginas dos boletins e os arquivos de indexação.")
    parser.add_argument("site", type=Path, help="pasta do site montada pelo build_site.sh")
    parser.add_argument("--atualizado", help="data da última atualização dos dados (AAAA-MM-DD)")
    args = parser.parse_args(argv)
    try:
        ctx = Contexto.carregar(args.site, args.atualizado)
        ctx.paginas.append(Pagina("", ctx.atualizado))
        resumo.gerar(ctx)  # index.html: card Resumo, destaques e frases de volumes, origens, HHI, portos e rotas
        resumo_precos.gerar(ctx)  # index.html: frases de preços, frete, nutrientes, troca e benchmark
        tabelas.gerar(ctx)  # index.html: tabelas de "Ver tabela"
        boletins.gerar(ctx)  # boletim/AAAA-MM/ e boletim/ (acrescenta em ctx.paginas)
        cabecalho.gerar(ctx)  # por último: JSON-LD, sitemap de todas as páginas, versão dos assets
        ctx.gravar()
    except ErroEstatico as e:
        print(f"build_site.sh: ERRO: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
