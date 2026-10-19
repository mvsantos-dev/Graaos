"""Páginas estáticas dos boletins: boletim/AAAA-MM/ (uma por mês dos dados) e boletim/ (o arquivo).

Tudo sai do dashboard.json do site: as frases-modelo usam o pacote de fatos do boletim
(src.boletim.montar_fatos, com a troca montada do próprio dashboard.json por troca_do_painel), os
cartões do Resumo as contas do script do dashboard (dados.kpis) e as tabelas os mesmos blocos que o
painel desenha. O texto de IA, quando existe, vem já validado de boletins/AAAA-MM.json (ou do
boletim.json do site, se for do mesmo mês) e entra escapado. Origens, portos e rotas só aparecem
quando os blocos anuais terminam no mês (o último mês dos dados e os dezembros), como no boletim.
Páginas sem JavaScript, com o radar.css e o boletim.css do site.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass

from .. import boletim as B
from . import boletins_frases as T
from . import dados as D
from . import formato as F
from . import sinais as SN
from .contexto import REPOSITORIO, URL_BASE, Contexto, ErroEstatico, Pagina, esc

PASTA = "boletim"
COR_TEMA = "#2B36D9"
LICENCA_DADOS = "https://creativecommons.org/licenses/by/4.0/"
COMEX_STAT = "https://comexstat.mdic.gov.br/"
IMAGEM_ALT = "Graaos · Fertilizantes: mapa-múndi em pontos com as rotas das maiores origens das importações brasileiras de fertilizantes"
ORDEM_FONTES = [B.FONTE, B.FONTE_PINK, B.FONTE_PTAX]
CORES_GRUPO = {"N": "--g-n", "P": "--g-p", "K": "--g-k", "NPK": "--g-npk", "TOTAL": "--g-total"}
# Tema salvo no painel (localStorage "tema"): só o escolhe, sem botão; sem JavaScript vale o do sistema.
SCRIPT_TEMA = '<script>try{var t=localStorage.getItem("tema");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}</script>'


@dataclass
class Mes:
    periodo: str
    fatos: B.Fatos
    kpis: dict
    texto: dict | None  # texto de IA do mês (já validado na geração), ou None

    @property
    def caminho(self) -> str:
        return f"{PASTA}/{self.periodo}/"

    @property
    def url(self) -> str:
        return URL_BASE + self.caminho

    @property
    def nome(self) -> str:
        return F.rotulo_mes_longo(self.periodo)

    @property
    def titulo(self) -> str:
        return f"Importação de fertilizantes em {self.nome} | Graaos"


def gerar(ctx: Contexto) -> None:
    """Grava boletim/AAAA-MM/index.html de cada mês e boletim/index.html, acrescenta todas em
    ctx.paginas e liga o último mês e o arquivo no lead do bloco Boletim da home."""
    periodos = ctx.periodos
    if not periodos:
        raise ErroEstatico("dashboard.json sem meses: não há boletim para gerar")
    troca = B.troca_do_painel(ctx.dados)
    meses = []
    for p in periodos:
        try:
            fatos = B.montar_fatos(ctx.dados, troca, p)
        except (B.ErroBoletim, KeyError, IndexError, TypeError, ValueError) as e:
            raise ErroEstatico(f"pacote de fatos de {p}: {e}") from e
        meses.append(Mes(p, fatos, D.kpis(ctx.dados, "TOTAL", p), _texto_do_mes(ctx, p)))
    cabeca = _links_da_home(ctx.html)
    for i, mes in enumerate(meses):
        ctx.escrever(f"{mes.caminho}index.html", _pagina_mes(ctx, meses, i, cabeca))
        ctx.paginas.append(Pagina(mes.caminho, ctx.atualizado))
    ctx.escrever(f"{PASTA}/index.html", _pagina_arquivo(ctx, meses, cabeca))
    ctx.paginas.append(Pagina(f"{PASTA}/", ctx.atualizado))
    ultimo = meses[-1]
    ctx.preencher("link-boletim-pagina", f' Leia o <a href="{ultimo.caminho}">boletim de {esc(ultimo.nome)}</a> ou o <a href="{PASTA}/">arquivo de todos os meses</a>.')


# --- Texto de IA de cada mês ------------------------------------------------------------------


def _texto_valido(b, periodo: str) -> bool:
    return (isinstance(b, dict) and b.get("mes") == periodo and isinstance(b.get("titulo"), str) and b["titulo"].strip() != ""
            and isinstance(b.get("lead"), str) and isinstance(b.get("paragrafos"), list) and len(b["paragrafos"]) > 0
            and all(isinstance(x, str) and x.strip() for x in b["paragrafos"]))


def _texto_do_mes(ctx: Contexto, periodo: str) -> dict | None:
    """O boletim.json do site quando é deste mês (o mesmo do card da home), senão
    boletins/AAAA-MM.json do repositório. Texto do modo --mock nunca entra numa página."""
    candidatos = []
    if ctx.boletim.get("mes") == periodo and _texto_valido(ctx.boletim, periodo):
        candidatos.append(ctx.boletim)
    arquivo = ctx.raiz / "boletins" / f"{periodo}.json"
    if arquivo.is_file():
        try:
            b = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ErroEstatico(f"boletins/{periodo}.json inválido: {e}") from e
        if not _texto_valido(b, periodo):
            raise ErroEstatico(f"boletins/{periodo}.json sem mes {periodo}, titulo, lead ou paragrafos")
        candidatos.append(b)
    for b in candidatos:
        if b.get("mock"):
            print(f"build_site.sh: aviso: o texto de {periodo} é do modo --mock e fica fora da página", file=sys.stderr)
            continue
        return b
    return None


# --- Peças comuns das páginas -----------------------------------------------------------------


def _links_da_home(pagina: str) -> list[str]:
    """Ícones e manifesto do <head> da home, para as páginas dos boletins usarem os mesmos (com o
    caminho relativo corrigido em _cabeca)."""
    head = pagina.split("</head>", 1)[0]
    return re.findall(r'<link\b[^>]*\brel="(?:icon|shortcut icon|apple-touch-icon|manifest|mask-icon)"[^>]*>', head)


def _relativo(link: str, prefixo: str) -> str:
    def trocar(m: re.Match) -> str:
        href = m.group(2)
        if re.match(r"(?:[a-z][a-z0-9+.-]*:|/|#)", href, re.IGNORECASE):
            return m.group(0)
        return f'{m.group(1)}{prefixo}{href}"'
    return re.sub(r'(\shref=")([^"]*)"', trocar, link)


def _jsonld(grafo: list[dict]) -> str:
    texto = json.dumps({"@context": "https://schema.org", "@graph": grafo}, ensure_ascii=False, separators=(",", ":"))
    return '<script type="application/ld+json">\n' + texto.replace("</", "<\\/") + "\n</script>"


def _trilha_jsonld(url: str, itens: list[tuple[str, str]]) -> dict:
    return {
        "@type": "BreadcrumbList", "@id": url + "#trilha",
        "itemListElement": [{"@type": "ListItem", "position": i, "name": nome, "item": link} for i, (nome, link) in enumerate(itens, 1)],
    }


def _cabeca(ctx: Contexto, *, titulo: str, descricao: str, url: str, prefixo: str, og_tipo: str, jsonld: str, extras: str = "", icones: list[str]) -> str:
    imagem = URL_BASE + "preview.png"
    metas = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(titulo)}</title>",
        f'<meta name="description" content="{esc(descricao)}">',
        f'<link rel="canonical" href="{esc(url)}">',
        '<meta name="color-scheme" content="light dark">',
        f'<meta name="theme-color" content="{COR_TEMA}">',
        *([f'<meta name="atualizado" content="{esc(ctx.atualizado)}">'] if ctx.atualizado else []),
        f'<meta property="og:type" content="{og_tipo}">',
        '<meta property="og:site_name" content="Graaos">',
        '<meta property="og:locale" content="pt_BR">',
        f'<meta property="og:title" content="{esc(titulo)}">',
        f'<meta property="og:description" content="{esc(descricao)}">',
        f'<meta property="og:url" content="{esc(url)}">',
        f'<meta property="og:image" content="{imagem}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:image:alt" content="{esc(IMAGEM_ALT)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{esc(titulo)}">',
        f'<meta name="twitter:description" content="{esc(descricao)}">',
        f'<meta name="twitter:image" content="{imagem}">',
        f'<meta name="twitter:image:alt" content="{esc(IMAGEM_ALT)}">',
        *(_relativo(link, prefixo) for link in icones),
        extras,
        f'<link rel="preload" href="{prefixo}assets/fontes/inter-tight-latin-300-normal.woff2" as="font" type="font/woff2" crossorigin>',
        f'<link rel="preload" href="{prefixo}assets/fontes/jetbrains-mono-latin-400-normal.woff2" as="font" type="font/woff2" crossorigin>',
        f'<link rel="stylesheet" href="{prefixo}assets/radar.css">',
        f'<link rel="stylesheet" href="{prefixo}assets/boletim.css">',
        SCRIPT_TEMA,
        jsonld,
    ]
    return "\n".join(m for m in metas if m)


def _barra(prefixo: str, no_arquivo: bool) -> str:
    atual = ' aria-current="page"' if no_arquivo else ' aria-current="true"'
    return (
        '<a class="pular" href="#conteudo">Pular para o conteúdo</a>\n'
        '<div class="fundo-pontos" aria-hidden="true"></div>\n'
        '<header class="barra-topo">\n'
        f'  <a class="marca" href="{prefixo}"><strong>Graaos</strong><span>Fertilizantes</span></a>\n'
        '  <nav class="nav-pilula" aria-label="Navegação do site">\n'
        f'    <a href="{prefixo}">Painel</a>\n'
        f'    <a href="{prefixo}{PASTA}/"{atual}>Boletins</a>\n'
        f'    <a class="nav-alertas" href="{prefixo}#lista-espera">Receber alertas</a>\n'
        "  </nav>\n"
        "</header>"
    )


def _trilha(itens: list[tuple[str, str | None]]) -> str:
    lis = "".join(f'<li><a href="{href}">{esc(nome)}</a></li>' if href else f'<li aria-current="page">{esc(nome)}</li>' for nome, href in itens)
    return f'<nav class="trilha" aria-label="Você está em"><ol>{lis}</ol></nav>'


def _rodape(ctx: Contexto, fontes: list[str]) -> str:
    datas = [f"Dados de {F.rotulo_mes(ctx.primeiro_mes)} a {F.rotulo_mes(ctx.ultimo_mes)}"]
    if ctx.atualizado:
        a = ctx.atualizado
        datas.append(f"atualizado em {a[8:10]}/{a[5:7]}/{a[:4]}")
    return (
        '<footer class="rodape">\n'
        f'  <span class="fonte">Fonte: {esc("; ".join(fontes))}</span>\n'
        f"  <span>{esc(' · '.join(datas))}</span>\n"
        "  <span>Fontes tipográficas Inter Tight e JetBrains Mono (SIL OFL 1.1).</span>\n"
        "  <span><strong>Graaos</strong> — hub de inteligência de mercado do agro e da logística, com dados públicos. Este é o módulo Fertilizantes.</span>\n"
        f'  <span>Código aberto (MIT) · dados CC BY 4.0: <a href="{REPOSITORIO}">github.com/mvsantos-dev/graaos</a></span>\n'
        "</footer>"
    )


def _documento(cabeca: str, corpo: str) -> str:
    return f'<!doctype html>\n<html lang="pt-BR">\n<head>\n{cabeca}\n</head>\n<body class="pagina-boletim">\n{corpo}\n</body>\n</html>\n'


def _tabela(colunas: list[tuple[str, bool]], linhas: list[list[str]], classes: list[str] | None = None) -> str:
    """Como o tabela() do script: th/td com a classe "num" nas colunas numéricas."""
    num = ' class="num"'
    th = "".join(f"<th{num if n else ''}>{esc(t)}</th>" for t, n in colunas)
    trs = []
    for k, linha in enumerate(linhas):
        classe = f' class="{classes[k]}"' if classes and classes[k] else ""
        tds = "".join(f"<td{num if colunas[i][1] else ''}>{esc(v)}</td>" for i, v in enumerate(linha))
        trs.append(f"<tr{classe}>{tds}</tr>")
    return f'<div class="rolagem"><table><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


def _frase(texto: str) -> str:
    """Frase-modelo escapada, com o "US$" preso ao número (não quebra a linha entre os dois)."""
    return esc(texto).replace("US$ ", "US$ ")


def _kpi(rotulo: str, valor: str, delta: str, ponto: str | None = None) -> str:
    """O mesmo cartão do script (tile/valorAnimado): rótulo, valor num span.numero e delta."""
    marca = f'<span class="ponto" style="background: var({ponto})"></span>' if ponto else ""
    classe = "rotulo titulo-produto" if ponto else "rotulo"
    return (f'<div class="kpi"><div class="{classe}">{marca}{esc(rotulo)}</div>'
            f'<div class="valor"><span class="numero">{esc(valor)}</span></div><div class="delta">{esc(delta)}</div></div>')


def _fontes(texto: dict | None) -> list[str]:
    """Comex Stat sempre (volumes, preços e a soja da troca); as do texto de IA, quando ele as cita."""
    citadas = {B.FONTE} | {x.strip() for x in str((texto or {}).get("fonte") or "").split(";") if x.strip()}
    return [f for f in ORDEM_FONTES if f in citadas]


# --- Página do mês ----------------------------------------------------------------------------


def _ano_ate_o_mes(dados: dict, periodo: str) -> bool:
    """Os blocos anuais (origens, URFs, rotas) cobrem todos os meses do ano nos dados: só descrevem
    o acumulado até o mês quando o ano termina nele (a mesma regra do pacote de fatos)."""
    anual, ano = dados["anual"], int(periodo[:4])
    return ano in anual["anos"] and anual["n_meses"][anual["anos"].index(ano)] == int(periodo[5:7])


def _rotulo_ano(dados: dict, ano: int) -> str:
    """(rotuloAno) "2026 (jan–set)" num ano parcial."""
    anual = dados["anual"]
    n = anual["n_meses"][anual["anos"].index(ano)] if ano in anual["anos"] else 0
    return f"{ano} (jan–{F.MESES[n - 1]})" if 0 < n < 12 else str(ano)


def _cartao_texto(mes: Mes) -> str:
    """O boletim escrito por IA, como no card da home (desenharBoletim), mas já aberto."""
    b = mes.texto
    data = b.get("gerado_em") if isinstance(b.get("gerado_em"), str) and re.match(r"\d{4}-\d{2}-\d{2}", b.get("gerado_em")) else None
    detalhes = ", ".join(x for x in (f"modelo {b['modelo']}" if isinstance(b.get("modelo"), str) and b["modelo"] else None,
                                       f"gerado em {data[8:10]}/{data[5:7]}/{data[:4]}" if data else None) if x)
    nota = f"{b['nota']} " if isinstance(b.get("nota"), str) and b["nota"] else ""
    rodape = f"{nota}{b.get('rodape') or B.RODAPE} Fonte: {b.get('fonte') or B.FONTE}.{f' ({detalhes})' if detalhes else ''}"
    links = ""
    if isinstance(b.get("arquivo"), str) and re.fullmatch(r"boletins/\d{4}-\d{2}\.md", b["arquivo"]):
        links = f'<div class="links"><a href="{REPOSITORIO}/blob/main/{b["arquivo"]}">Boletim com os números citados</a></div>'
    paragrafos = "".join(f"<p>{esc(p)}</p>" for p in b["paragrafos"])
    return (
        '<section class="cartao grade boletim" aria-labelledby="t-texto">\n<div>\n'
        f'<p class="sobretitulo">Boletim do mês · {esc(b.get("mes_referencia") or mes.nome)}</p>\n'
        f'<h2 class="titulo-cartao" id="t-texto">{esc(b["titulo"])}</h2>\n'
        f'<p class="lead">{esc(b["lead"])}</p>\n'
        f'<div class="texto">{paragrafos}</div>\n'
        f'<p class="rodape-boletim">{esc(rodape)}</p>\n{links}\n'
        "</div>\n</section>"
    )


def _cartao_kpis(mes: Mes) -> str:
    k = mes.kpis
    blocos = "".join(
        f'<div class="kpi-bloco"><h3>{esc(titulo)}</h3><div class="kpi-linha">{"".join(_kpi(c["rotulo"], c["valor"], c["delta"]) for c in cartoes)}</div></div>'
        for titulo, cartoes in ((k["titulo_mes"], k["mes"]), (k["titulo_acumulado"], k["acumulado"]))
    )
    destaques = T.frase_precos(mes.fatos)
    return (
        '<section class="cartao kpis grade" aria-labelledby="t-kpis">\n<div>\n'
        f'<div class="cabecalho"><h2 class="titulo-cartao" id="t-kpis">{esc(k["titulo"])}</h2><p class="nota">{esc(k["nota"])}</p></div>\n'
        f"{blocos}\n"
        + (f'<p class="destaques">{_frase(destaques)}</p>\n' if destaques else "")
        + '<dl class="termos" aria-label="O que querem dizer FOB e CIF">'
        "<div><dt>FOB</dt><dd>preço da carga no porto de embarque, sem frete nem seguro internacionais</dd></div>"
        "<div><dt>CIF</dt><dd>preço posto no porto brasileiro: FOB mais frete e seguro</dd></div>"
        "<div><dt>Frete no CIF</dt><dd>quanto do CIF é frete internacional</dd></div>"
        '<div><dt>Outros termos</dt><dd><a href="../../#glossario">no glossário</a></dd></div>'
        "</dl>\n</div>\n</section>"
    )


def _cartao_grupos(ctx: Contexto, mes: Mes) -> str:
    p = ctx.periodos
    i = p.index(mes.periodo)
    anterior = T.mes_anterior(mes.periodo)
    i_ant = p.index(anterior) if anterior in p else None
    total = D.metricas(ctx.dados, "TOTAL", [i])
    linhas, classes = [], []
    for g in [*F.GRUPOS, "TOTAL"]:
        m = D.metricas(ctx.dados, g, [i])
        ant = D.metricas(ctx.dados, g, [i_ant]) if i_ant is not None else None
        nome = F.NOMES[g] if g == "TOTAL" else f"{g} · {F.NOMES[g]}"
        linhas.append([
            nome, F.fmt0(m["t"]), *([F.variacao(F.variacao_pct(m["t"], ant["t"]))] if ant else []),
            F.pct(100 * m["t"] / total["t"] if total["t"] > 0 else None),
            F.TRACO if F.nulo(m["preco_fob"]) else F.fmt0(m["preco_fob"]),
            F.TRACO if F.nulo(m["preco_cif"]) else F.fmt0(m["preco_cif"]),
            F.pct(m["frete_cif"]),
        ])
        classes.append("total" if g == "TOTAL" else "")
    # Sem o mesmo mês do ano anterior nos dados (o primeiro ano), sem a coluna de variação.
    colunas = [("Grupo", False), ("Toneladas", True), *([(f"Var. t vs {F.rotulo_mes(anterior)}", True)] if i_ant is not None else []),
               ("Share", True), ("FOB US$/t", True), ("CIF US$/t", True), ("Frete no CIF", True)]
    sobre = f"; variação sobre {F.rotulo_mes(anterior)}" if i_ant is not None else ""
    ordem = sorted((g.lower() for g in F.GRUPOS), key=lambda k: -(ctx.dados["mensal"][k.upper()]["t"][i] or 0))
    frase = T.frase_grupos(mes.fatos, ordem)
    return (
        '<section class="cartao grade" aria-labelledby="t-grupos">\n<div>\n'
        f'<h2 class="titulo-cartao" id="t-grupos">Por grupo de nutriente · {esc(F.rotulo_mes(mes.periodo))}</h2>\n'
        f'<p class="nota">Toneladas, share do mês e preços médios (valor ÷ toneladas){esc(sobre)}</p>\n'
        + (f'<p class="resumo-grafico">{_frase(frase)}</p>\n' if frase else "")
        + _tabela(colunas, linhas, classes)
        + "\n</div>\n</section>"
    )


def _cartao_origens(ctx: Contexto, meses: list[Mes], i: int) -> str:
    mes = meses[i]
    ano = int(mes.periodo[:4])
    if not _ano_ate_o_mes(ctx.dados, mes.periodo):
        # Os blocos anuais vão além deste mês: aponta para a página que os traz.
        alvo = next((m for m in meses if m.periodo == f"{ano}-12"), meses[-1] if meses[-1].periodo[:4] == str(ano) else None)
        if alvo is None:
            return ""
        return (f'<p class="nota-boletim">Origens, portos e rotas saem por ano: os de {esc(_rotulo_ano(ctx.dados, ano))} estão no '
                f'<a href="../{alvo.periodo}/">boletim de {esc(alvo.nome)}</a>.</p>')
    k = str(ano)
    rotulo = _rotulo_ano(ctx.dados, ano)
    m = int(mes.periodo[5:7])
    base = str(ano - 1) if m == 12 else f"jan/{ano - 1}" if m == 1 else f"jan–{F.MESES[m - 1]}/{ano - 1}"  # mesmos meses do ano anterior
    tem_ant = ano - 1 in ctx.dados["anual"]["anos"]  # no primeiro ano não há variação
    var_cols = [("Var. t", True), ("Var. share", True)] if tem_ant else []
    var = (lambda r: [F.variacao(r[4]), F.variacao(r[5], " p.p.")]) if tem_ant else (lambda r: [])
    partes = []
    origens = [r for r in (ctx.dados["origens"]["dados"].get(k, {}).get("TOTAL") or []) if r[1] != "Outros"][:5]
    if origens:
        partes.append('<div><h3 class="subtitulo">Maiores origens</h3>' + _tabela(
            [("País", False), ("Toneladas", True), ("Share", True), *var_cols],
            [[r[1], F.fmt0(r[2]), F.pct(r[3]), *var(r)] for r in origens]) + "</div>")
    portos = [r for r in (ctx.dados["urfs"]["dados"].get(k, {}).get("TOTAL") or []) if r[1] != "Outros"][:5]
    if portos:
        partes.append('<div><h3 class="subtitulo">Maiores URFs (portos)</h3>' + _tabela(
            [("URF", False), ("Toneladas", True), ("Share", True), *var_cols],
            [[F.nome_urf(r[1]), F.fmt0(r[2]), F.pct(r[3]), *var(r)] for r in portos]) + "</div>")
    bloco_rotas = ((ctx.dados.get("rotas") or {}).get("dados", {}).get(k, {}) or {}).get("TOTAL") or {}
    rotas = (bloco_rotas.get("rotas") or [])[:5]
    tabela_rotas = ""
    if rotas:
        corte = bloco_rotas.get("corte_t")
        nota = f'<p class="nota">Rotas com pelo menos {esc(F.fmt0(corte))} t no período; frete médio por tonelada de cada rota</p>' if corte is not None else ""
        tabela_rotas = ('<h3 class="subtitulo">Maiores rotas (país de origem → URF)</h3>' + nota + _tabela(
            [("Origem", False), ("URF", False), ("Toneladas", True), ("Share", True), ("Frete US$/t", True)],
            [[r[0] or F.TRACO, F.nome_curto_urf(r[2]) if r[2] else F.TRACO, F.fmt0(r[3]), F.pct(r[4]), F.TRACO if F.nulo(r[5]) else F.fmt0(r[5])] for r in rotas]))
    if not partes and not tabela_rotas:
        return ""
    frase = T.frase_origens(mes.fatos)
    return (
        '<section class="cartao grade" aria-labelledby="t-origens">\n<div>\n'
        f'<h2 class="titulo-cartao" id="t-origens">Origens, portos e rotas · {esc(rotulo)}</h2>\n'
        f'<p class="nota">Todos os grupos, acumulado do ano; share nas toneladas{esc(" e variação sobre " + base if tem_ant else "")}</p>\n'
        + (f'<p class="resumo-grafico">{_frase(frase)}</p>\n' if frase else "")
        + (f'<div class="tabelas-boletim">{"".join(partes)}</div>\n' if partes else "")
        + tabela_rotas
        + "\n</div>\n</section>"
    )


def _cartao_troca(ctx: Contexto, mes: Mes) -> str:
    tr = ctx.dados.get("troca")
    if not tr or mes.periodo not in tr["periodos"]:
        return ""
    j = tr["periodos"].index(mes.periodo)
    f = mes.fatos
    cartoes = []
    for prod in T.PRODUTOS_TROCA:
        d = tr["produtos"][prod]
        cor = CORES_GRUPO.get(d.get("grupo"), "--g-total")
        rotulo = f"{d['nome']} · {F.rotulo_mes(mes.periodo)}"
        if f"troca_{prod}_ultimo" in f:
            cartoes.append(_kpi(rotulo, T.valor(f, f"troca_{prod}_ultimo"), T.delta_troca(f, prod), cor))
        else:
            sem = "sem importação" if F.nulo(d["t"][j]) or d["t"][j] == 0 else "sem preço da soja"
            cartoes.append(_kpi(rotulo, sem, "relação de troca no porto indisponível no mês", cor))
    frase, nota = T.frase_troca(f), T.nota_troca(f)
    return (
        '<section class="cartao grade" aria-labelledby="t-troca">\n<div>\n'
        f'<h2 class="titulo-cartao" id="t-troca">Relação de troca no porto · {esc(F.rotulo_mes(mes.periodo))}</h2>\n'
        '<p class="nota">Toneladas de soja exportada que pagam 1 t de fertilizante importado no mesmo mês</p>\n'
        '<p class="ressalva"><strong>No porto, não na fazenda.</strong> Toneladas de soja exportada (preço FOB) que pagam 1 t de'
        " fertilizante importado (preço CIF) no mesmo mês. Não é o preço ao produtor: ficam de fora o frete interno, impostos,"
        " margens e prêmios.</p>\n"
        + (f'<p class="resumo-grafico">{_frase(frase)}</p>\n' if frase else "")
        + f'<div class="kpi-linha produtos">{"".join(cartoes)}</div>\n'
        + (f'<p class="nota nota-troca">{_frase(nota)}</p>\n' if nota else "")
        + "</div>\n</section>"
    )


def _navegacao(meses: list[Mes], i: int) -> str:
    anterior = meses[i - 1] if i > 0 else None
    proximo = meses[i + 1] if i + 1 < len(meses) else None
    itens = []
    itens.append(f'<a class="anterior" rel="prev" href="../{anterior.periodo}/"><span class="rotulo">← Mês anterior</span>{esc(anterior.nome)}</a>'
                 if anterior else '<span class="anterior vazio"></span>')
    itens.append('<a class="arquivo" href="../"><span class="rotulo">Arquivo</span>Todos os boletins</a>')
    itens.append(f'<a class="proximo" rel="next" href="../{proximo.periodo}/"><span class="rotulo">Próximo mês →</span>{esc(proximo.nome)}</a>'
                 if proximo else '<a class="proximo" href="../../#boletim"><span class="rotulo">Painel →</span>Ver no painel</a>')
    return f'<nav class="meses-boletim" aria-label="Outros meses">{"".join(itens)}</nav>'


def _pagina_mes(ctx: Contexto, meses: list[Mes], i: int, icones: list[str]) -> str:
    mes = meses[i]
    f = mes.fatos
    sinais = SN.documento(ctx)  # o bloco "Sinais do mês", do data/sinais.json
    tem_origens = _ano_ate_o_mes(ctx.dados, mes.periodo) and "lider_total_ano" in f
    descricao = T.descricao(f, tem_origens)
    trilha = [("Graaos · Fertilizantes", URL_BASE), ("Boletins", URL_BASE + f"{PASTA}/"), (mes.nome, mes.url)]
    pagina = {
        "@type": "WebPage", "@id": mes.url + "#pagina", "url": mes.url, "name": mes.titulo, "description": descricao,
        "inLanguage": "pt-BR", "isPartOf": {"@id": URL_BASE + "#website"}, "publisher": {"@id": URL_BASE + "#organization"},
        "breadcrumb": {"@id": mes.url + "#trilha"}, "temporalCoverage": mes.periodo, "license": LICENCA_DADOS,
        "isBasedOn": COMEX_STAT, "primaryImageOfPage": {"@type": "ImageObject", "url": URL_BASE + "preview.png"},
    }
    if ctx.atualizado:
        pagina["dateModified"] = ctx.atualizado
    extras = "\n".join(x for x in (
        f'<link rel="prev" href="../{meses[i - 1].periodo}/">' if i > 0 else "",
        f'<link rel="next" href="../{meses[i + 1].periodo}/">' if i + 1 < len(meses) else "",
    ) if x)
    cabeca = _cabeca(ctx, titulo=mes.titulo, descricao=descricao, url=mes.url, prefixo="../../", og_tipo="article",
                     jsonld=_jsonld([pagina, _trilha_jsonld(mes.url, trilha)]), extras=extras, icones=icones)
    corpo = "\n".join(x for x in (
        _barra("../../", no_arquivo=False),
        '<div class="pagina">\n<main id="conteudo">',
        _trilha([("Graaos · Fertilizantes", "../../"), ("Boletins", "../"), (mes.nome, None)]),
        '<section class="bloco" aria-labelledby="titulo-pagina">',
        '<header class="bloco-cabecalho">'
        f'<p class="kicker">Boletim mensal · {esc(F.rotulo_mes(mes.periodo))}</p>'
        f'<h1 class="titulo-bloco" id="titulo-pagina">Importação de fertilizantes em {esc(mes.nome)}</h1>'
        f'<p class="bloco-lead">{_frase(T.lead(f))}</p>'
        "</header>",
        _cartao_texto(mes) if mes.texto else "",
        SN.bloco_boletim(sinais, mes.periodo, SN.ids_da_home(ctx)),
        _cartao_kpis(mes),
        _cartao_grupos(ctx, mes),
        _cartao_origens(ctx, meses, i),
        _cartao_troca(ctx, mes),
        "</section>",
        _navegacao(meses, i),
        "</main>",
        _rodape(ctx, [f for f in ORDEM_FONTES if f in {*_fontes(mes.texto), *SN.fontes(SN.do_mes(sinais, mes.periodo))}]),
        "</div>",
    ) if x)
    return _documento(cabeca, corpo)


# --- Arquivo ----------------------------------------------------------------------------------


def _pagina_arquivo(ctx: Contexto, meses: list[Mes], icones: list[str]) -> str:
    url = URL_BASE + f"{PASTA}/"
    titulo = "Boletins mensais de importação de fertilizantes | Graaos"
    inicio, fim = F.rotulo_mes(meses[0].periodo), F.rotulo_mes(meses[-1].periodo)
    descricao = (f"Um boletim por mês, de {inicio} a {fim}: importações brasileiras de fertilizantes (N, P, K e NPK), preços,"
                 " origens, portos e relação de troca com a soja, com dados públicos.")
    if len(descricao) > T.MAX_DESCRICAO:
        descricao = f"Um boletim por mês, de {inicio} a {fim}: importações brasileiras de fertilizantes, preços, origens e relação de troca."
    trilha = [("Graaos · Fertilizantes", URL_BASE), ("Boletins", url)]
    pagina = {
        "@type": "CollectionPage", "@id": url + "#pagina", "url": url, "name": titulo, "description": descricao,
        "inLanguage": "pt-BR", "isPartOf": {"@id": URL_BASE + "#website"}, "publisher": {"@id": URL_BASE + "#organization"},
        "breadcrumb": {"@id": url + "#trilha"}, "temporalCoverage": f"{meses[0].periodo}/{meses[-1].periodo}", "license": LICENCA_DADOS,
        "isBasedOn": COMEX_STAT, "primaryImageOfPage": {"@type": "ImageObject", "url": URL_BASE + "preview.png"},
    }
    if ctx.atualizado:
        pagina["dateModified"] = ctx.atualizado
    cabeca = _cabeca(ctx, titulo=titulo, descricao=descricao, url=url, prefixo="../", og_tipo="website",
                     jsonld=_jsonld([pagina, _trilha_jsonld(url, trilha)]), icones=icones)

    ultimo = meses[-1]
    destaque = (
        '<section class="cartao grade boletim" aria-labelledby="t-ultimo">\n<div>\n'
        f'<p class="sobretitulo">Último boletim · {esc(F.rotulo_mes(ultimo.periodo))}</p>\n'
        f'<h2 class="titulo-cartao" id="t-ultimo"><a href="{ultimo.periodo}/">Importação de fertilizantes em {esc(ultimo.nome)}</a></h2>\n'
        f'<p class="lead">{_frase(T.lead(ultimo.fatos))}</p>\n'
        "</div>\n</section>"
    )
    anos = []
    por_ano: dict[str, list[Mes]] = {}
    for m in meses:
        por_ano.setdefault(m.periodo[:4], []).append(m)
    for n, ano in enumerate(sorted(por_ano, reverse=True)):
        lista = por_ano[ano]
        fim_ano = lista[-1].fatos
        total = T.valor(fim_ano, "t_total_ytd")
        rotulo = _rotulo_ano(ctx.dados, int(ano))
        nota = f"{total} {'em ' + ano if rotulo == ano else 'de ' + T.valor(fim_ano, 'periodo_ytd')}" if total else ""
        itens = "".join(
            f'<li><a href="{m.periodo}/">{esc(m.nome)}</a>' + ('<span class="selo">com texto</span>' if m.texto else "")
            + f'<span class="resumo">{esc(T.resumo_curto(m.fatos))}</span></li>'
            for m in reversed(lista)
        )
        # Os dois anos mais recentes abertos; os outros fechados (os links continuam no HTML).
        anos.append(
            f'<section class="cartao grade ano-boletins" aria-labelledby="t-ano-{ano}">\n<details{" open" if n < 2 else ""}>\n'
            f'<summary class="cabecalho-ano"><h2 class="titulo-cartao" id="t-ano-{ano}">{esc(rotulo)}</h2>'
            + (f'<span class="nota">{esc(nota)}</span>' if nota else "")
            + f'</summary>\n<ol class="lista-meses">{itens}</ol>\n</details>\n</section>'
        )
    corpo = "\n".join((
        _barra("../", no_arquivo=True),
        '<div class="pagina">\n<main id="conteudo">',
        _trilha([("Graaos · Fertilizantes", "../"), ("Boletins", None)]),
        '<section class="bloco" aria-labelledby="titulo-pagina">',
        '<header class="bloco-cabecalho">'
        f'<p class="kicker">Boletins · {esc(inicio)} a {esc(fim)}</p>'
        '<h1 class="titulo-bloco" id="titulo-pagina">Boletins mensais</h1>'
        '<p class="bloco-lead">Uma página por mês com as importações brasileiras de fertilizantes: volumes, preços, relação de'
        " troca no porto e, no último mês de cada ano e no mais recente, origens, portos e rotas. Números calculados pelo programa"
        " a partir dos dados públicos; nos meses com boletim escrito por IA, o texto vem junto.</p>"
        "</header>",
        destaque,
        *anos,
        "</section>",
        "</main>",
        _rodape(ctx, [B.FONTE]),
        "</div>",
    ))
    return _documento(cabeca, corpo)
