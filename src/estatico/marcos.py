"""Marcos de mercado (data/eventos.yml): os eventos no index.html, para o script desenhar a linha vertical nos gráficos dos produtos citados.

Os eventos vão como JSON dentro do <script type="application/json" id="marcos-dados"> (o script
os lê sem outra requisição). Arquivo inválido é erro de build; sem o arquivo, nenhum marco.
"""

from __future__ import annotations

import json
import sys

from .. import eventos as E
from .contexto import Contexto, ErroEstatico

ID = "marcos-dados"


def para_pagina(eventos: list[dict]) -> list[dict]:
    """O que o script usa de cada evento: {data, titulo, fonte_url, dominio, produtos}."""
    return [{**e, "dominio": E.dominio(e["fonte_url"])} for e in eventos]


def json_inline(dados) -> str:
    """JSON para dentro de um <script>: sem "<", ">", "&" nem "/" literais (nada de "</script>",
    "<!--" nem um "assets/" que o versionador dos assets tomaria por referência) e sem os
    separadores de linha que quebram o JavaScript antigo."""
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    for c, escape in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), ("/", "\\/"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        texto = texto.replace(c, escape)
    return texto


def gerar(ctx: Contexto) -> None:
    arquivo = ctx.raiz / E.ARQUIVO
    if arquivo.is_file():
        try:
            eventos = E.ler(arquivo, nome=E.ARQUIVO)
        except E.ErroEventos as e:
            raise ErroEstatico(str(e)) from e
    else:
        print(f"build_site.sh: aviso: sem {E.ARQUIVO}, os gráficos ficam sem marcos de mercado", file=sys.stderr)
        eventos = []
    ctx.preencher(ID, json_inline(para_pagina(eventos)))
