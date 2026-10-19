"""Sinais do mês (data/sinais.json): os cards logo depois do hero, o feed /sinais.xml e os sinais das páginas dos boletins.

Os sinais são os do data/sinais.json (src/sinais.py, regras fixas em Python, sem IA), conferidos
contra o dashboard.json do site: um arquivo velho ou fora do formato derruba o build. Sem o
arquivo (uma cópia do site fora do repositório), saem do próprio dashboard.json, com o mesmo
resultado. Nada aqui calcula sinal nem escreve número à mão: as frases são as do src/sinais.py, as
minilinhas usam as mesmas séries (src.sinais.series) e as regras do texto vêm do campo "limites".

- Home (#sinais, estática, sem JavaScript): até MAX_CARTOES cards do último mês, os fortes
  primeiro e, dentro do nível, pelo tamanho do desvio; cada um com o nível em texto, a frase, a
  minilinha dos últimos MESES_LINHA meses (CIF em US$/t, a troca ou as toneladas, conforme o
  sinal) e o link para o gráfico do produto. Mês sem sinal: uma linha dizendo isso.
- /sinais.xml: Atom 1.0, uma entrada por mês com sinais (do mais novo, até MESES_FEED meses).
- boletim/AAAA-MM/: o bloco "Sinais do mês" com todos os sinais do mês (bloco_boletim).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from xml.sax.saxutils import escape as esc_xml

from .. import config
from .. import sinais as S
from . import formato as F
from .contexto import REPOSITORIO, URL_BASE, Contexto, ErroEstatico, esc

ARQUIVO = config.SINAIS_JSON.relative_to(config.RAIZ).as_posix()  # data/sinais.json
FEED = "sinais.xml"
MAX_CARTOES = 6  # cards na home (o resto fica na página do boletim do mês)
MESES_LINHA = 24  # meses da minilinha
MESES_FEED = 24  # meses do feed
TAG = "tag:radar.graaos.cloud,2026:sinais"  # id do feed; cada entrada acrescenta /AAAA-MM
NIVEL = {"forte": "Forte", "atencao": "Atenção"}
LINK_ANCORA = {  # texto do link de cada âncora (o destino, para o link fazer sentido fora do card)
    "#secao-bm": "Ver Brasil x mercado internacional",
    "#secao-nutrientes": "Ver o custo por nutriente",
    "#precos": "Ver os preços",
    "#troca": "Ver a relação de troca",
    "#grafico-enxofre": "Ver o gráfico do enxofre",
    "#grafico-rocha": "Ver o gráfico da rocha",
}
RESSALVA_TROCA = "A troca é no porto, em t de soja exportada por t de fertilizante importado. Não é o preço ao produtor."
RESSALVA_PINK = "A Pink Sheet é referência de outro lugar e de outro momento de contrato, não um preço do Brasil."
# minilinha: viewBox e margem interna (o SVG escala com a largura do card)
LARGURA, ALTURA, MARGEM = 240, 56, 4


# --- Documento ---------------------------------------------------------------------------------


def _carregar(ctx: Contexto) -> dict:
    calculado = S.gerar(ctx.dados)
    arquivo = ctx.raiz / ARQUIVO
    if not arquivo.is_file():
        print(f"build_site.sh: aviso: sem {ARQUIVO}; os sinais do site saem do dashboard.json", file=sys.stderr)
        return calculado
    try:
        doc = S.ler(arquivo)
    except (OSError, ValueError, KeyError, TypeError) as e:  # ErroSinais é ValueError
        raise ErroEstatico(f"{ARQUIVO} inválido: {e}") from e
    if doc["periodo"] != calculado["periodo"] or doc["sinais"] != calculado["sinais"]:
        raise ErroEstatico(f"{ARQUIVO} não é o que sai do dashboard.json (rode python -m src.sinais)")
    return doc


def documento(ctx: Contexto) -> dict:
    """O data/sinais.json do build (lido e conferido uma vez; as páginas dos boletins usam o mesmo)."""
    doc = ctx.__dict__.get("_sinais")
    if doc is None:
        doc = ctx.__dict__["_sinais"] = _carregar(ctx)
    return doc


def ordenar(sinais: list[dict]) -> list[dict]:
    """Os fortes primeiro e, no mesmo nível, o maior desvio (|variacao_pct|); empate na ordem do arquivo."""
    return sorted(sinais, key=lambda s: (S.NIVEIS.index(s["nivel"]), -abs(s["comparacao"]["variacao_pct"])))


def do_mes(doc: dict, mes: str) -> list[dict]:
    return ordenar(S.sinais_do_mes(doc, mes))


# --- Textos ------------------------------------------------------------------------------------


def _frase(texto: str) -> str:
    """Escapada e com o "US$" preso ao número, como nas páginas dos boletins."""
    return esc(texto).replace("US$ ", "US$\u00a0")


def _pct(v: float) -> str:
    return f"{F.numero(v, 0, 1)}%"


def _minuscula(nome: str) -> str:
    """O nome no meio da frase: "Rocha fosfática" vira "rocha fosfática"; sigla (KCl, MAP) fica como está."""
    return nome[:1].lower() + nome[1:] if nome[1:2].islower() else nome


def rotulo_tipo(sinal: dict) -> str:
    c, tipo = sinal["comparacao"], sinal["tipo"]
    if tipo == "media_12m":
        return f"Média de {c['janela_meses']} meses"
    if tipo == "variacao_3m":
        return f"Variação em {c['janela_meses']} meses"
    if tipo == "recorde":
        return "Recorde da série"
    if tipo == "internacional":
        return "Internacional na frente"
    if tipo == "troca_p90":
        return f"Troca acima do percentil {F.numero(c['percentil'], 0, 1)}"
    if tipo == "ritmo_importacao":
        return "Ritmo de importação"
    raise ErroEstatico(f"tipo de sinal desconhecido: {tipo!r}")


def _fortes(sinais: list[dict]) -> str:
    n, k = len(sinais), sum(s["nivel"] == "forte" for s in sinais)
    if n == 1:
        return "forte" if k else "de atenção"
    return "nenhum forte" if k == 0 else "todos fortes" if k == n else "1 forte" if k == 1 else f"{k} fortes"


def _n(sinais: list[dict]) -> str:
    return "1 sinal" if len(sinais) == 1 else f"{len(sinais)} sinais"


def contagem(sinais: list[dict], nome_mes: str | None = None) -> str:
    """A contagem do mês: "9 sinais, 5 fortes" ou, com o mês, "9 sinais em setembro de 2026, 5 fortes" ("1 sinal, forte")."""
    return f"{_n(sinais)}{f' em {nome_mes}' if nome_mes else ''}, {_fortes(sinais)}"


def _maiuscula(texto: str) -> str:
    return texto[:1].upper() + texto[1:]


def fontes(sinais: list[dict]) -> list[str]:
    """Comex Stat sempre (preço, toneladas e a soja da troca); o Banco Mundial quando um sinal usa a Pink Sheet."""
    saida = ["Comex Stat/MDIC"]
    if any(s["tipo"] == "internacional" for s in sinais):
        saida.append("Banco Mundial (Pink Sheet)")
    return saida


def ressalvas(sinais: list[dict]) -> list[str]:
    """As ressalvas que os sinais mostrados pedem: a troca no porto e a Pink Sheet."""
    saida = []
    if any(s["tipo"] == "troca_p90" for s in sinais):
        saida.append(RESSALVA_TROCA)
    if any(s["tipo"] == "internacional" for s in sinais):
        saida.append(RESSALVA_PINK)
    return saida


def regras(doc: dict) -> list[str]:
    """As regras em pt-BR, com os limites do campo "limites" do sinais.json."""
    L = doc["limites"]
    m, v, r, i, t, ri = (L[k] for k in ("media_12m", "variacao_3m", "recorde", "internacional", "troca_p90", "ritmo_importacao"))
    proprios: dict[float, list[str]] = {}
    for chave, vol in L["volume_min_t_produto"].items():
        nome = (doc["produtos"].get(chave) or {}).get("nome") or S.PRODUTOS.get(chave, (chave,))[0]
        proprios.setdefault(vol, []).append(_minuscula(nome))
    excecoes = "; ".join(f"{' e '.join(nomes)}: {F.toneladas(vol)}" for vol, nomes in proprios.items())
    return [
        f"Média: CIF do mês {_pct(m['limite_pct'])} ou mais acima ou abaixo da média dos {m['meses']} meses anteriores"
        f" (forte a partir de {_pct(m['forte_pct'])}).",
        f"Variação: CIF {_pct(v['limite_pct'])} ou mais acima ou abaixo do de {v['meses']} meses antes"
        f" (forte a partir de {_pct(v['forte_pct'])}).",
        f"Recorde: CIF acima do maior ou abaixo do menor da série, depois de {r['min_meses_validos']} meses de histórico"
        f" (forte se passa o recorde anterior por {_pct(r['forte_pct'])} ou mais).",
        f"Internacional na frente: a Pink Sheet do produto andou {_pct(i['limite_pct'])} ou mais em {i['meses']} meses e o CIF"
        f" do Brasil não acompanhou (forte a partir de {_pct(i['forte_pct'])}); o MAP usa o DAP. {RESSALVA_PINK}",
        f"Troca: relação de troca no porto acima do percentil {F.numero(t['percentil'], 0, 1)} da série"
        f" (forte acima do percentil {F.numero(t['forte_percentil'], 0, 1)}). {RESSALVA_TROCA}",
        f"Ritmo de importação: toneladas do mês {_pct(ri['limite_pct'])} ou mais acima ou abaixo das do mesmo mês do ano"
        f" anterior (forte a partir de {_pct(ri['forte_pct'])}).",
        f"Contra o ruído: preço só nos meses com pelo menos {F.toneladas(L['volume_min_t'])} do produto"
        + (f" ({excecoes})" if excecoes else "") + "; os outros ficam fora das médias, dos recordes e das comparações.",
    ]


# --- Minilinha ---------------------------------------------------------------------------------


@dataclass
class Linha:
    """O que a minilinha de um sinal desenha, já recortado nos últimos MESES_LINHA meses."""

    meses: list[str]
    valores: list  # a série do sinal (None = sem ponto: mês sem o volume mínimo ou sem dado)
    extra: list | None = None  # a Pink Sheet, no sinal internacional (tracejada)
    referencia: float | None = None  # linha horizontal tracejada (média, recorde anterior, percentil)
    ref_de: int = 0
    ref_ate: int = 0
    marca: int | None = None  # o mês da comparação (círculo vazio)
    legenda: str = ""


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float("inf"), float("-inf"))


def linha(serie: S.Serie, periodos: list[str], sinal: dict) -> Linha:
    """Os valores da minilinha do sinal: a série que a regra usou, nos meses que ela aceita."""
    i = periodos.index(sinal["mes"])
    ini = max(0, i - MESES_LINHA + 1)
    idx = range(ini, i + 1)
    tipo, c = sinal["tipo"], sinal["comparacao"]
    if tipo == "troca_p90":
        valores = [serie.troca[j] if serie.troca_valida(j) else None for j in idx]
        base = "Troca no porto, t de soja por t"
    elif tipo == "ritmo_importacao":
        valores = [serie.t[j] if _num(serie.t[j]) else None for j in idx]
        base = "Toneladas importadas por mês"
    else:
        valores = [serie.cif[j] if serie.valido(j) else None for j in idx]
        base = "CIF do Brasil e Pink Sheet (tracejada), em US$/t" if tipo == "internacional" else "CIF em US$/t"
    meses = periodos[ini: i + 1]
    lin = Linha(meses, valores)
    pos = {p: k for k, p in enumerate(meses)}
    nota = ""
    if tipo == "internacional" and serie.pink is not None:
        lin.extra = [serie.pink[j] if _num(serie.pink[j]) and serie.pink[j] > 0 else None for j in idx]
        if c.get("proxy") and c.get("pink_serie"):
            nota = f"; Pink Sheet do {c['pink_serie']}"
    elif tipo == "media_12m":
        lin.referencia, lin.ref_de, lin.ref_ate = c["valor"], max(0, len(meses) - 1 - c["janela_meses"]), len(meses) - 2
        nota = f"; tracejado: média dos {c['janela_meses']} meses anteriores"
    elif tipo == "recorde":
        lin.referencia, lin.ref_de, lin.ref_ate = c["valor"], 0, len(meses) - 1
        nota = f"; tracejado: recorde anterior ({F.rotulo_mes(c['mes'])})"
    elif tipo == "troca_p90":
        lin.referencia, lin.ref_de, lin.ref_ate = c["valor"], 0, len(meses) - 1
        nota = f"; tracejado: percentil {F.numero(c['percentil'], 0, 1)} da série"
    elif tipo in ("variacao_3m", "ritmo_importacao") and c.get("mes") in pos:
        lin.marca = pos[c["mes"]]
        nota = f"; círculo: {F.rotulo_mes(c['mes'])}"
    vazios = "; vazios: meses sem o volume mínimo" if tipo != "ritmo_importacao" and any(v is None for v in valores) else ""
    lin.legenda = f"{base}, {F.rotulo_mes(meses[0])} a {F.rotulo_mes(meses[-1])}{nota}{vazios}"
    return lin


def _c(v: float) -> str:
    return f"{v:.1f}"


def svg(lin: Linha) -> str:
    """A minilinha em SVG (aria-hidden: a frase do card é o texto): cores pelo CSS (currentColor)."""
    pontos = [v for v in [*lin.valores, *(lin.extra or [])] if v is not None]
    if not any(v is not None for v in lin.valores):
        return ""
    if lin.referencia is not None:
        pontos.append(lin.referencia)
    lo, hi = min(pontos), max(pontos)
    n = len(lin.valores)

    def x(k: int) -> float:
        return MARGEM + (LARGURA - 2 * MARGEM) * (k / (n - 1) if n > 1 else 0.5)

    def y(v: float) -> float:
        return MARGEM + (ALTURA - 2 * MARGEM) * (0.5 if hi == lo else (hi - v) / (hi - lo))

    def trechos(valores: list) -> list[list[int]]:
        saida, atual = [], []
        for k, v in enumerate(valores):
            if v is None:
                if atual:
                    saida.append(atual)
                atual = []
            else:
                atual.append(k)
        return saida + ([atual] if atual else [])

    def caminho(valores: list) -> str:
        partes = []
        for t in trechos(valores):
            partes.append(f"M{_c(x(t[0]))} {_c(y(valores[t[0]]))}" + ("h0" if len(t) == 1 else "".join(f"L{_c(x(k))} {_c(y(valores[k]))}" for k in t[1:])))
        return "".join(partes)

    def area(valores: list) -> str:
        fundo = _c(ALTURA - MARGEM)
        return "".join(
            f"M{_c(x(t[0]))} {fundo}" + "".join(f"L{_c(x(k))} {_c(y(valores[k]))}" for k in t) + f"L{_c(x(t[-1]))} {fundo}Z"
            for t in trechos(valores) if len(t) > 1
        )

    partes = [f'<svg class="sinal-linha" viewBox="0 0 {LARGURA} {ALTURA}" aria-hidden="true" focusable="false">']
    if area(lin.valores):
        partes.append(f'<path class="area" d="{area(lin.valores)}"/>')
    if lin.referencia is not None and lin.ref_ate >= lin.ref_de:
        partes.append(f'<path class="referencia" d="M{_c(x(lin.ref_de))} {_c(y(lin.referencia))}H{_c(x(lin.ref_ate))}"/>')
    if lin.extra and any(v is not None for v in lin.extra):
        partes.append(f'<path class="extra" d="{caminho(lin.extra)}"/>')
    partes.append(f'<path class="serie" d="{caminho(lin.valores)}"/>')
    if lin.marca is not None and lin.valores[lin.marca] is not None:
        partes.append(f'<circle class="marca" cx="{_c(x(lin.marca))}" cy="{_c(y(lin.valores[lin.marca]))}" r="2.6"/>')
    if lin.valores[-1] is not None:
        partes.append(f'<circle class="fim" cx="{_c(x(n - 1))}" cy="{_c(y(lin.valores[-1]))}" r="3"/>')
    partes.append("</svg>")
    return "".join(partes)


# --- Home: seção "Sinais do mês" ---------------------------------------------------------------


def ids_da_pagina(pagina: str) -> set[str]:
    """Os ids do HTML (para só ligar um card a uma âncora que existe)."""
    return set(re.findall(r'\sid="([^"]+)"', pagina))


def ids_da_home(ctx: Contexto) -> set[str]:
    """ids_da_pagina(ctx.html), calculado de novo só se o index.html mudou (as páginas dos boletins pedem um por mês)."""
    guardado = ctx.__dict__.get("_ids")
    if guardado is None or guardado[0] is not ctx.html:
        guardado = ctx.__dict__["_ids"] = (ctx.html, ids_da_pagina(ctx.html))
    return guardado[1]


def cartao(sinal: dict, k: int, lin: Linha | None, ids: set[str]) -> str:
    nivel = sinal["nivel"]
    ancora = sinal["ancora"]
    if ancora[1:] in ids:
        texto = LINK_ANCORA.get(ancora, "Ver no gráfico")
        link = f'<a class="sinal-link" href="{esc(ancora)}" data-secao="{esc(ancora[1:])}" aria-describedby="sinal-frase-{k}">{esc(texto)}</a>'
    else:
        print(f"build_site.sh: aviso: a âncora {ancora} não existe no index.html; o card de {sinal['id']} fica sem link", file=sys.stderr)
        link = ""
    desenho = svg(lin) if lin else ""
    legenda = f'<p class="sinal-legenda">{esc(lin.legenda)}</p>' if desenho else ""
    return (
        f'<li class="cartao sinal" data-nivel="{esc(nivel)}">'
        f'<p class="sinal-topo"><span class="sinal-nivel">{esc(NIVEL[nivel])}</span><span class="sinal-tipo">{esc(rotulo_tipo(sinal))}</span></p>'
        f'<p class="sinal-frase" id="sinal-frase-{k}">{_frase(sinal["frase"])}</p>'
        f"{desenho}{legenda}{link}</li>"
    )


def secao(ctx: Contexto, doc: dict) -> tuple[str, str]:
    """(lead, corpo) da seção #sinais da home, para o último mês dos dados."""
    mes = doc["periodo"]["fim"]
    todos = do_mes(doc, mes)
    mostrados = todos[:MAX_CARTOES]
    nome_mes = F.rotulo_mes_longo(mes)
    lead = (f"Alertas automáticos de {nome_mes} para os {len(doc['produtos'])} produtos acompanhados: preço CIF, relação de"
            " troca no porto e ritmo de importação, por regras fixas do programa, sem IA. Os fortes vêm primeiro.")
    series = S.series(ctx.dados, doc["limites"])
    periodos = ctx.periodos
    ids = ids_da_pagina(ctx.html)
    pagina_mes = f"boletim/{mes}/#sinais"
    partes = []
    if mostrados:
        cards = "".join(
            cartao(s, k, linha(series[s["produto"]], periodos, s) if s["produto"] in series else None, ids)
            for k, s in enumerate(mostrados, 1)
        )
        partes.append(f'<ol class="sinais-lista">{cards}</ol>')
        if len(todos) > len(mostrados):
            resumo = f"Os {len(mostrados)} principais dos {_n(todos)} de {nome_mes} ({_fortes(todos)})."
            mais = f'<a href="{pagina_mes}">Ver todos na página do boletim</a>'
        else:
            resumo = f"{_maiuscula(contagem(todos, nome_mes))}."
            mais = f'<a href="{pagina_mes}">Ver no boletim do mês</a>'
    else:
        partes.append(f'<p class="sinais-vazio">Nenhum sinal de preço ou de volume em {esc(nome_mes)}: nenhum produto passou dos limites das regras.</p>')
        resumo, mais = "", f'<a href="{pagina_mes}">Ver o boletim do mês</a>'
    feed = f'<a href="{FEED}" type="application/atom+xml">Assinar o feed (Atom)</a>'
    dados = f'<a href="{REPOSITORIO}/blob/main/{ARQUIVO}">Histórico em JSON</a>'
    ressalva = " ".join(ressalvas(mostrados))
    partes.append(
        '<div class="sinais-rodape">'
        f'<p class="sinais-contagem">{esc(resumo)}{" " if resumo else ""}{mais} · {feed} · {dados}</p>'
        + (f'<p class="nota">{esc(ressalva)}</p>' if ressalva else "")
        + '<details class="sinais-regras"><summary>Como os sinais são calculados</summary>'
        f'<ul class="lista-metodo">{"".join(f"<li>{esc(r)}</li>" for r in regras(doc))}</ul></details>'
        f'<p class="nota">Fonte: {esc(doc["fonte"])}.</p>'
        "</div>"
    )
    return lead, "".join(partes)


def _mostrar_secao(ctx: Contexto) -> None:
    """Tira o hidden da seção (no index.html sem build, ela fica escondida e vazia)."""
    m = ctx._tag_com_id("sinais")
    tag = m.group(0)
    nova = re.sub(r"\shidden(?=[\s>])", "", tag, count=1)
    ctx.html = ctx.html[: m.start()] + nova + ctx.html[m.end():]


# --- Feed Atom ---------------------------------------------------------------------------------


def _mes_seguinte(mes: str) -> str:
    ano, m = int(mes[:4]), int(mes[5:7])
    return f"{ano + m // 12:04d}-{m % 12 + 1:02d}"


def _atr(v: str) -> str:
    return esc_xml(v, {'"': "&quot;"})


def feed(ctx: Contexto, doc: dict) -> str:
    """Atom 1.0 (RFC 4287): uma entrada por mês com sinais, do mais novo para o mais antigo.

    A entrada de cada mês tem id estável (TAG/AAAA-MM) e data do primeiro dia depois do mês (a
    mesma a cada build); o feed, a da última atualização dos dados, se for mais nova."""
    meses = [p for p in reversed(ctx.periodos[-MESES_FEED:]) if S.sinais_do_mes(doc, p)]
    entradas = []
    for mes in meses:
        lista = do_mes(doc, mes)
        nome = F.rotulo_mes_longo(mes)
        itens = "".join(f"<li><strong>{esc(NIVEL[s['nivel']])}</strong> · {esc(s['frase'])}</li>" for s in lista)
        notas = " ".join([*ressalvas(lista), f"Fonte: {'; '.join(fontes(lista))}."])
        conteudo = f"<ul>{itens}</ul><p>{esc(notas)}</p>"
        url = f"{URL_BASE}boletim/{mes}/#sinais"
        titulo = f"Sinais de {nome}: {contagem(lista)}"
        entradas.append(
            "  <entry>\n"
            f"    <id>{TAG}/{mes}</id>\n"
            f"    <title>{esc_xml(titulo)}</title>\n"
            f'    <link rel="alternate" type="text/html" href="{_atr(url)}"/>\n'
            f"    <updated>{_mes_seguinte(mes)}-01T00:00:00Z</updated>\n"
            f"    <summary>{esc_xml('; '.join(s['frase'] for s in lista))}</summary>\n"
            f'    <content type="html">{esc_xml(conteudo)}</content>\n'
            "  </entry>\n"
        )
    datas = [f"{_mes_seguinte(meses[0])}-01T00:00:00Z"] if meses else [f"{_mes_seguinte(doc['periodo']['fim'])}-01T00:00:00Z"]
    if ctx.atualizado:
        datas.append(f"{ctx.atualizado}T00:00:00Z")
    direitos = f"Dados tratados sob CC BY 4.0: Graaos (github.com/mvsantos-dev/graaos). Fonte: {doc['fonte']}."
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="pt-BR">\n'
        f"  <id>{TAG}</id>\n"
        "  <title>Graaos · Fertilizantes: sinais do mês</title>\n"
        "  <subtitle>Sinais automáticos de preço e de volume das importações brasileiras de fertilizantes e dos insumos do"
        " fósforo, por regras fixas, sem IA.</subtitle>\n"
        f"  <updated>{max(datas)}</updated>\n"
        f'  <link rel="self" type="application/atom+xml" href="{URL_BASE}{FEED}"/>\n'
        f'  <link rel="alternate" type="text/html" href="{URL_BASE}#sinais"/>\n'
        f"  <author><name>Graaos</name><uri>{REPOSITORIO}</uri></author>\n"
        f"  <icon>{URL_BASE}favicon-192.png</icon>\n"
        f"  <rights>{esc_xml(direitos)}</rights>\n"
        + "".join(entradas)
        + "</feed>\n"
    )


# --- Páginas dos boletins ----------------------------------------------------------------------


def bloco_boletim(doc: dict, mes: str, ids: set[str] | None = None, prefixo: str = "../../") -> str:
    """O cartão "Sinais do mês" (id="sinais") da página boletim/AAAA-MM/: todos os sinais do mês,
    com o nível e o link para o gráfico na home (só para a âncora que existe nela, em `ids`)."""
    lista = do_mes(doc, mes)
    nome = F.rotulo_mes_longo(mes)
    if lista:
        itens = "".join(
            f'<li data-nivel="{esc(s["nivel"])}"><span class="sinal-nivel">{esc(NIVEL[s["nivel"]])}</span>'
            f'<span class="sinal-frase">{_frase(s["frase"])}</span>'
            + (f'<a href="{prefixo}{esc(s["ancora"])}">no painel</a>' if ids is None or s["ancora"][1:] in ids else "")
            + "</li>"
            for s in lista
        )
        ordem = " Os fortes vêm primeiro." if 0 < sum(s["nivel"] == "forte" for s in lista) < len(lista) else ""
        corpo = (f'<p class="resumo-grafico">{esc(_maiuscula(contagem(lista, nome)))}.{ordem}</p>\n'
                 f'<ol class="lista-sinais">{itens}</ol>\n')
        notas = [*ressalvas(lista), f"Fonte: {'; '.join(fontes(lista))}."]
    else:
        corpo = f'<p class="sinais-vazio">Nenhum sinal de preço ou de volume em {esc(nome)}.</p>\n'
        notas = ["Fonte: Comex Stat/MDIC."]
    return (
        '<section class="cartao grade sinais-boletim" id="sinais" aria-labelledby="t-sinais">\n<div>\n'
        f'<h2 class="titulo-cartao" id="t-sinais">Sinais do mês · {esc(F.rotulo_mes(mes))}</h2>\n'
        f'<p class="nota">Regras fixas do programa sobre os dados do mês, sem IA. <a href="{prefixo}#sinais">Como são calculados</a></p>\n'
        f"{corpo}"
        f'<p class="nota">{esc(" ".join(notas))}</p>\n'
        "</div>\n</section>"
    )


# --- Etapa do build ----------------------------------------------------------------------------


def gerar(ctx: Contexto) -> None:
    doc = documento(ctx)
    lead, corpo = secao(ctx, doc)
    ctx.preencher("sinais-lead", esc(lead))
    ctx.preencher("sinais-corpo", corpo)
    _mostrar_secao(ctx)
    ctx.escrever(FEED, feed(ctx, doc))
