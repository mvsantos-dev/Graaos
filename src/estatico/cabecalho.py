"""Indexação: JSON-LD no index.html, robots.txt, sitemap.xml, 404.html, llms.txt, _headers e a
versão (?v=) dos arquivos de assets/ em todas as páginas. Roda por último, depois que as outras
etapas gravaram as páginas e as acrescentaram em ctx.paginas.

Nenhum número escrito à mão: o período vem do dashboard.json (meta.periodo), a data de atualização
do build (--atualizado) e a lista de arquivos de dados do que existe em data/ na hora do build.
"""

from __future__ import annotations

import json
import re
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape as esc_xml

from . import formato
from .cabecalho_versao import versionar
from .contexto import REPOSITORIO, URL_BASE, Contexto, ErroEstatico, esc

REPO_RAW = "https://raw.githubusercontent.com/mvsantos-dev/Graaos/main/"
LICENCA_DADOS = "https://creativecommons.org/licenses/by/4.0/"
CREDITO = "Graaos (github.com/mvsantos-dev/graaos)"
FONTES = "Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet); BCB/PTAX."
ID_SITE = URL_BASE + "#website"
ID_ORG = URL_BASE + "#organization"
ID_DATASET = URL_BASE + "#dataset"
ICONES = {"favicon-32.png": 32, "favicon-192.png": 192, "favicon-512.png": 512, "apple-touch-icon.png": 180}  # lado em px
LOGO = "favicon-512.png"
DESCRICAO = (
    "Importações de fertilizantes no Brasil (N, P, K e NPK): origens, portos, preços e relação de troca "
    "com a soja no porto. Dados públicos e código aberto."
)
# Cache-Control (Cloudflare Workers static assets; o _headers não é servido como arquivo).
CACHE_LONGO = "public, max-age=31536000, immutable"
CACHE_CURTO = "public, max-age=0, must-revalidate"
CACHE_ICONES = "public, max-age=86400"
TIPOS = {".csv": "text/csv", ".parquet": "application/vnd.apache.parquet", ".json": "application/json"}


def gerar(ctx: Contexto) -> None:
    conferir_icones(ctx)
    ctx.escrever("404.html", pagina_404(ctx))
    ctx.inserir_antes("</head>", json_ld_html(ctx))
    ctx.escrever("robots.txt", robots())
    ctx.escrever("sitemap.xml", sitemap(ctx))
    ctx.escrever("llms.txt", llms(ctx))
    ctx.escrever("_headers", headers(ctx))
    versionar(ctx)  # por último: depois de todo HTML gravado


def tamanho_png(arquivo: Path) -> tuple[int, int]:
    """(largura, altura) do cabeçalho IHDR de um PNG."""
    cabeca = arquivo.read_bytes()[:24]
    if len(cabeca) < 24 or cabeca[:8] != b"\x89PNG\r\n\x1a\n" or cabeca[12:16] != b"IHDR":
        raise ErroEstatico(f"{arquivo.name} não é um PNG")
    return struct.unpack(">II", cabeca[16:24])


def conferir_icones(ctx: Contexto) -> None:
    """Os ícones de dashboard/ (copiados para a raiz do site) existem, no tamanho certo, e o manifest os lista."""
    for arquivo, lado in ICONES.items():
        if not (ctx.site / arquivo).is_file():
            raise ErroEstatico(f"falta {arquivo} no site (vem de dashboard/)")
        if tamanho_png(ctx.site / arquivo) != (lado, lado):
            raise ErroEstatico(f"{arquivo} não tem {lado}x{lado} px")
    try:
        manifest = json.loads((ctx.site / "site.webmanifest").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ErroEstatico(f"site.webmanifest ausente ou inválido: {e}") from e
    for icone in manifest.get("icons", []):
        lado = ICONES.get(icone.get("src"))
        if lado is None or icone.get("sizes") != f"{lado}x{lado}":
            raise ErroEstatico(f"site.webmanifest: ícone {icone.get('src')!r} não confere com os arquivos")
    if not manifest.get("icons"):
        raise ErroEstatico("site.webmanifest sem ícones")


# --- JSON-LD --------------------------------------------------------------------------------
def _periodo(ctx: Contexto) -> tuple[str, str]:
    return formato.rotulo_mes_longo(ctx.primeiro_mes), formato.rotulo_mes_longo(ctx.ultimo_mes)


def arquivos_de_dados(raiz: Path) -> list[Path]:
    """Os CSV e Parquet de data/ que estão no repositório (git ls-files; sem git, os que estão na pasta),
    porque os links apontam para o GitHub: arquivo local fora do Git daria 404."""
    try:
        r = subprocess.run(["git", "-C", str(raiz), "ls-files", "-z", "--", "data"], capture_output=True, timeout=30)
        rastreados = [raiz / n for n in r.stdout.decode("utf-8").split("\0") if n] if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        rastreados = None
    if rastreados is None:
        rastreados = list((raiz / "data").rglob("*")) if (raiz / "data").is_dir() else []
    return sorted(p for p in rastreados if p.suffix in (".csv", ".parquet") and p.is_file())


def distribuicao(ctx: Contexto) -> list[dict]:
    """Os CSV e Parquet de data/ que estão no repositório, mais o dashboard.json do site."""
    arquivos = arquivos_de_dados(ctx.raiz)
    # tabelas analíticas primeiro, depois as de referência e os dados brutos
    arquivos.sort(key=lambda p: (0 if p.parent.name == "processed" else 2 if p.suffix == ".parquet" else 1, str(p)))
    itens = [
        {
            "@type": "DataDownload",
            "name": p.relative_to(ctx.raiz).as_posix(),
            "contentUrl": REPO_RAW + p.relative_to(ctx.raiz).as_posix(),
            "encodingFormat": TIPOS[p.suffix],
        }
        for p in arquivos
    ]
    itens.insert(
        sum(1 for p in arquivos if p.parent.name == "processed"),
        {
            "@type": "DataDownload",
            "name": "dashboard.json",
            "description": "Todos os números do site, num arquivo só.",
            "contentUrl": URL_BASE + "dashboard.json",
            "encodingFormat": "application/json",
        },
    )
    return itens


def _variavel(nome: str, unidade: str, descricao: str) -> dict:
    return {"@type": "PropertyValue", "name": nome, "unitText": unidade, "description": descricao}


def json_ld(ctx: Contexto) -> dict:
    inicio, fim = _periodo(ctx)
    organizacao = {"@id": ID_ORG}
    dataset = {
        "@type": "Dataset",
        "@id": ID_DATASET,
        "name": "Importação de fertilizantes no Brasil: volumes, origens, portos, preços e relação de troca",
        "alternateName": "Graaos · Fertilizantes",
        "description": (
            "Importações brasileiras de fertilizantes minerais e químicos (nitrogenados, fosfatados, potássicos e "
            f"compostos NPK), mês a mês, de {inicio} a {fim}: toneladas, valor FOB e CIF em dólares, frete e preço "
            "médio por tonelada, por produto (NCM), país de origem, UF de destino e URF (a unidade da Receita onde "
            "a carga é desembaraçada, na prática o porto de chegada). Inclui a relação de troca com a soja em grão "
            "exportada (no porto, não é o preço ao produtor), a comparação com os preços internacionais da Pink "
            "Sheet do Banco Mundial (o spread não é ágio: o benchmark é de outro lugar e de outro momento de "
            "contrato) e o CIF em reais pela PTAX média do mês. Dados tratados pelo Graaos a partir de dados "
            f"públicos oficiais; os dados de origem seguem as licenças das fontes. {FONTES}"
        ),
        "url": URL_BASE,
        "inLanguage": "pt-BR",
        "isAccessibleForFree": True,
        "license": LICENCA_DADOS,
        "creditText": CREDITO,
        "creator": organizacao,
        "publisher": organizacao,
        "temporalCoverage": f"{ctx.primeiro_mes}/{ctx.ultimo_mes}",
        "spatialCoverage": {"@type": "Country", "name": "Brasil", "sameAs": "https://www.wikidata.org/wiki/Q155"},
        "keywords": [
            "importação de fertilizantes", "fertilizantes", "adubos", "nitrogenados", "fosfatados", "potássicos",
            "NPK", "ureia", "cloreto de potássio", "MAP", "comércio exterior", "portos", "frete",
            "relação de troca", "soja", "Comex Stat", "Pink Sheet", "PTAX", "Brasil",
        ],
        "variableMeasured": [
            _variavel("Toneladas importadas", "t", "Peso líquido importado, em toneladas, por mês, produto (NCM), país de origem, UF de destino e URF."),
            _variavel("Valor FOB", "US$", "Valor da carga embarcada no porto de origem. Não inclui o frete nem o seguro internacionais."),
            _variavel("Valor CIF", "US$", "Valor da carga posta no porto brasileiro: FOB mais frete e seguro internacionais. Não inclui impostos, taxas portuárias, frete interno nem margens."),
            _variavel("Frete internacional por tonelada", "US$/t", "Frete internacional ÷ toneladas, por grupo, país de origem e rota (país de origem → URF)."),
            _variavel("Preço médio por tonelada", "US$/t", "Valor importado (FOB ou CIF) ÷ toneladas: a média ponderada pelo peso, e não o preço de um contrato."),
            _variavel(
                "Relação de troca",
                "t de soja por t de fertilizante",
                "Toneladas de soja em grão exportada que pagam uma tonelada de fertilizante importado no mesmo mês, no porto "
                "(preço CIF do KCl, da ureia e do MAP ÷ preço FOB da soja). Não é o preço ao produtor.",
            ),
        ],
        "distribution": distribuicao(ctx),
        "isBasedOn": [
            {
                "@type": "Dataset",
                "name": "Comex Stat: estatísticas de comércio exterior do Brasil",
                "description": "Dados abertos de comércio exterior do MDIC: importações e exportações por NCM, país, UF, via e URF, com valor FOB, peso, CIF, frete e seguro.",
                "url": "https://comexstat.mdic.gov.br/",
                "publisher": {"@type": "GovernmentOrganization", "name": "Ministério do Desenvolvimento, Indústria, Comércio e Serviços (MDIC)"},
            },
            {
                "@type": "Dataset",
                "name": "World Bank Commodity Price Data (The Pink Sheet)",
                "description": "Preços mensais de commodities do Banco Mundial; aqui, os de fertilizantes (ureia, DAP, TSP, cloreto de potássio e rocha fosfática), em US$/t nominais.",
                "url": "https://www.worldbank.org/en/research/commodity-markets",
                "license": LICENCA_DADOS,
                "publisher": {"@type": "Organization", "name": "Banco Mundial"},
            },
            {
                "@type": "Dataset",
                "name": "PTAX de venda, média mensal (SGS 3698)",
                "description": "Taxa de câmbio de referência do Banco Central do Brasil para o dólar americano (venda, média mensal), do Sistema Gerenciador de Séries Temporais.",
                "url": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.3698/dados?formato=json",
                "license": "https://opendatacommons.org/licenses/odbl/",
                "publisher": {"@type": "GovernmentOrganization", "name": "Banco Central do Brasil"},
            },
        ],
    }
    if ctx.atualizado:
        dataset["dateModified"] = ctx.atualizado
    largura, altura = tamanho_png(ctx.site / LOGO)
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": ID_SITE,
                "url": URL_BASE,
                "name": "Graaos",
                "alternateName": "Graaos · Fertilizantes",
                "description": DESCRICAO,
                "inLanguage": "pt-BR",
                "publisher": organizacao,
            },
            {
                "@type": "Organization",
                "@id": ID_ORG,
                "name": "Graaos",
                "url": URL_BASE,
                "description": "Hub de inteligência de mercado do agro e da logística, com dados públicos e código aberto.",
                "logo": {"@type": "ImageObject", "url": URL_BASE + LOGO, "contentUrl": URL_BASE + LOGO, "width": largura, "height": altura},
                "sameAs": [REPOSITORIO],
            },
            dataset,
        ],
    }


def json_ld_html(ctx: Contexto) -> str:
    texto = json.dumps(json_ld(ctx), ensure_ascii=False, separators=(",", ":"))
    texto = texto.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")  # nada fecha o <script>
    return f'<script type="application/ld+json">{texto}</script>\n'


# --- robots.txt e sitemap.xml ---------------------------------------------------------------
def robots() -> str:
    return f"User-agent: *\nAllow: /\n\nSitemap: {URL_BASE}sitemap.xml\n"


def _arquivo_da_pagina(ctx: Contexto, caminho: str) -> Path:
    if caminho == "" or caminho.endswith("/"):
        return ctx.site / caminho / "index.html"
    return ctx.site / caminho


def sitemap(ctx: Contexto) -> str:
    vistos: set[str] = set()
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for pagina in ctx.paginas:
        if pagina.caminho in vistos:
            raise ErroEstatico(f"sitemap: página repetida {pagina.caminho!r}")
        vistos.add(pagina.caminho)
        if pagina.caminho.startswith("/") or not _arquivo_da_pagina(ctx, pagina.caminho).is_file():
            raise ErroEstatico(f"sitemap: a página {pagina.caminho!r} não existe no site")
        lastmod = pagina.lastmod or ctx.atualizado
        if lastmod is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", lastmod):
            raise ErroEstatico(f"sitemap: lastmod inválido em {pagina.caminho!r}: {lastmod!r}")
        mod = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        linhas.append(f"  <url><loc>{esc_xml(pagina.url)}</loc>{mod}</url>")
    linhas.append("</urlset>")
    texto = "\n".join(linhas) + "\n"
    ET.fromstring(texto.encode("utf-8"))  # XML válido ou exceção
    return texto


# --- 404.html -------------------------------------------------------------------------------
_TOKENS = ("hero-fundo", "hero-brilho", "hero-texto", "hero-texto-2", "chip-fundo", "chip-texto", "fonte", "mono")
_FONTES_404 = ("inter-tight-latin-300-normal.woff2", "inter-tight-latin-400-normal.woff2", "inter-tight-latin-600-normal.woff2", "jetbrains-mono-latin-400-normal.woff2")


def _bloco_css(css: str, seletor: str) -> str:
    i = css.find(seletor + " {")
    if i < 0:
        raise ErroEstatico(f"404.html: não achei {seletor} no radar.css")
    return css[i : css.index("}", i)]


def _tokens(bloco: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"--([\w-]+):\s*([^;]+);", bloco)}


def css_404(ctx: Contexto) -> str:
    """Os tokens (claro e escuro) e as fontes do radar.css, para o 404 ter o visual do site sem depender
    do caminho: a página é servida em qualquer endereço que não existe."""
    radar = (ctx.site / "assets" / "radar.css").read_text(encoding="utf-8")
    claro, escuro = _tokens(_bloco_css(radar, ":root")), _tokens(_bloco_css(radar, ':root[data-theme="dark"]'))
    faltam = [t for t in _TOKENS if t not in claro]
    if faltam:
        raise ErroEstatico(f"404.html: o radar.css não tem os tokens {', '.join(faltam)}")
    fontes = [r for r in re.findall(r"@font-face\s*\{[^}]*\}", radar) if any(f in r for f in _FONTES_404)]
    if len(fontes) != len(_FONTES_404):
        raise ErroEstatico("404.html: não achei as fontes no radar.css")
    # caminho a partir da raiz: o 404 aparece em qualquer profundidade (no espelho do GitHub Pages, em
    # /Graaos/, as fontes não carregam e fica a fonte do sistema)
    fontes = [re.sub(r"url\((['\"]?)fontes/", r"url(\1/assets/fontes/", r) for r in fontes]
    var = lambda d: " ".join(f"--{t}: {d[t]};" for t in _TOKENS if t in d)  # noqa: E731
    return "\n".join(
        fontes
        + [
            f":root {{ color-scheme: light dark; {var(claro)} }}",
            f"@media (prefers-color-scheme: dark) {{ :root {{ {var(escuro)} }} }}",
            "* { box-sizing: border-box; }",
            "html { background: var(--hero-fundo); }",
            "body { margin: 0; min-height: 100vh; min-height: 100svh; display: grid; color: var(--hero-texto);"
            " background: radial-gradient(60% 70% at 72% 46%, var(--hero-brilho), transparent 70%), var(--hero-fundo);"
            " font: 400 14px/1.45 var(--fonte); -webkit-text-size-adjust: 100%; }",
            "main { width: 100%; max-width: 1360px; margin: 0 auto; padding: 32px 40px; display: grid; grid-template-rows: auto 1fr auto; gap: 24px; }",
            ".marca { justify-self: start; display: grid; gap: 2px; color: inherit; text-decoration: none; line-height: 1.05; }",
            ".marca strong { font: 600 15px/1.05 var(--fonte); letter-spacing: -0.01em; }",
            ".marca span { font: 400 11px/1.1 var(--mono); color: var(--hero-texto-2); }",
            ".texto { align-self: center; max-width: 680px; }",
            ".kicker { display: flex; align-items: center; gap: 9px; margin: 0; color: var(--hero-texto-2); font: 400 12px/1.4 var(--mono); letter-spacing: 0.01em; }",
            '.kicker::before { content: ""; flex: none; width: 7px; height: 7px; background: currentColor; }',
            "h1 { margin: 18px 0 0; font: 300 clamp(46px, 6.6vw, 104px)/0.96 var(--fonte); letter-spacing: -0.04em; text-wrap: balance; }",
            ".lead { margin: 22px 0 0; max-width: 33em; color: var(--hero-texto-2); font: 400 15px/1.55 var(--fonte); }",
            ".botoes { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 26px; }",
            ".botao { display: inline-flex; align-items: center; min-height: 40px; padding: 0 14px; border: 1px solid rgba(255, 255, 255, 0.55);"
            " border-radius: 1px; color: inherit; font: 400 12.5px/1 var(--mono); text-decoration: none; transition: background-color 0.25s; }",
            ".botao:hover { background: rgba(255, 255, 255, 0.12); }",
            ".botao.principal { background: var(--chip-fundo); color: var(--chip-texto); border-color: var(--chip-fundo); }",
            ".botao.principal:hover { background: var(--chip-fundo); filter: brightness(1.04); }",
            "a:focus-visible { outline: 2px solid var(--hero-texto); outline-offset: 2px; }",
            "footer { color: var(--hero-texto-2); font: 400 11px/1.5 var(--mono); }",
            "footer a { color: inherit; text-underline-offset: 2px; }",
            "@media (max-width: 560px) { main { padding: 24px 16px; } .botao { flex: 1 1 100%; justify-content: center; } }",
            "@media (prefers-reduced-motion: reduce) { .botao { transition: none; } }",
        ]
    )


def pagina_404(ctx: Contexto) -> str:
    """Página de endereço inexistente (a Cloudflare a serve com status 404: wrangler.jsonc,
    not_found_handling). Links absolutos, porque ela aparece em qualquer caminho."""
    favicon = re.search(r'<link rel="icon" href="(data:image/svg\+xml,[^"]+)"', ctx.html)
    if not favicon:
        raise ErroEstatico("404.html: não achei o favicon SVG no index.html")
    botoes = [f'<a class="botao principal" href="{URL_BASE}">Ir para a página inicial</a>']
    if (ctx.site / "boletim" / "index.html").is_file():
        botoes.append(f'<a class="botao" href="{URL_BASE}boletim/">Ver os boletins mensais</a>')
    botoes_html = "\n      ".join(botoes)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Página não encontrada | Graaos</title>
<meta name="robots" content="noindex">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#2B36D9">
<link rel="icon" href="{favicon.group(1)}" type="image/svg+xml">
<style>
{css_404(ctx)}
</style>
</head>
<body>
<main>
  <a class="marca" href="{URL_BASE}"><strong>Graaos</strong><span>Fertilizantes</span></a>
  <div class="texto">
    <p class="kicker">Erro 404</p>
    <h1>Página não encontrada</h1>
    <p class="lead">Este endereço não existe ou mudou de lugar. As importações de fertilizantes do Brasil, com origens, portos, preços e relação de troca com a soja no porto, estão na página inicial.</p>
    <div class="botoes">
      {botoes_html}
    </div>
  </div>
  <footer><strong>Graaos</strong> — hub de inteligência de mercado do agro e da logística, com dados públicos. Código aberto (MIT) · dados CC BY 4.0: <a href="{esc(REPOSITORIO)}">github.com/mvsantos-dev/graaos</a></footer>
</main>
</body>
</html>
"""


# --- llms.txt -------------------------------------------------------------------------------
def _ultimo_boletim(ctx: Contexto) -> str | None:
    meses = sorted(p.caminho for p in ctx.paginas if re.fullmatch(r"boletim/\d{4}-\d{2}/", p.caminho))
    return meses[-1] if meses else None


def llms(ctx: Contexto) -> str:
    """llms.txt (llmstxt.org): o que é o Graaos, as fontes e onde ficam os dados abertos."""
    inicio, fim = _periodo(ctx)
    arvore = REPOSITORIO + "/tree/main/"
    linhas = [
        "# Graaos · Fertilizantes",
        "",
        f"> Importações brasileiras de fertilizantes (nitrogenados, fosfatados, potássicos e NPK), mês a mês, de {inicio} "
        f"a {fim}, só com dados públicos oficiais: volumes, países de origem, portos (URF), rotas e frete, preços FOB e CIF, "
        "comparação com a Pink Sheet do Banco Mundial e relação de troca com a soja no porto.",
        "",
        "O Graaos é um hub de inteligência de mercado do agro e da logística, com dados públicos e código aberto. "
        "Fertilizantes é o primeiro módulo; logística portuária e grãos estão planejados. Os dados se atualizam todo mês.",
        "",
        "Ao citar os números:",
        "",
        "- A relação de troca (toneladas de soja exportada que pagam uma tonelada de fertilizante importado) e o custo por "
        "nutriente são no porto, não o preço ao produtor.",
        "- O spread entre o preço do Brasil e a Pink Sheet não é ágio: o benchmark é de outro lugar e de outro momento de contrato.",
        "- A UF do Comex Stat na importação é a UF de destino da mercadoria, não a do importador nem a do porto.",
        "- Preço implícito = valor ÷ toneladas (média ponderada pelo peso), não o preço de um contrato.",
        f"- Dados tratados sob CC BY 4.0, com o crédito \"{CREDITO}\"; os dados de origem seguem as licenças das fontes.",
        "",
        FONTES,
        "",
        "## Site",
        "",
        f"- [Dashboard]({URL_BASE}): volumes, origens, mapa de fluxos, portos e rotas, preços, Brasil x mercado internacional, relação de troca e método",
    ]
    if (ctx.site / "boletim" / "index.html").is_file():
        linhas.append(f"- [Boletins mensais]({URL_BASE}boletim/): uma página por mês, com os números do mês")
    ultimo = _ultimo_boletim(ctx)
    if ultimo:
        linhas.append(f"- [Último boletim]({URL_BASE}{ultimo}): {formato.rotulo_mes_longo(ultimo[8:15])}")
    if (ctx.site / "sinais.xml").is_file():
        linhas.append(f"- [Sinais do mês (feed Atom)]({URL_BASE}sinais.xml): alertas automáticos de preço e de volume por produto, um item por mês, por regras fixas (sem IA)")
    linhas += [
        "",
        "## Dados abertos",
        "",
        f"- [dashboard.json]({URL_BASE}dashboard.json): todos os números do site, num arquivo JSON",
    ]
    pastas = (
        ("data/processed", "Tabelas analíticas (CSV)", "preços, shares por origem, porto e UF de destino, HHI, rotas e frete, relação de troca, custo por nutriente e benchmark"),
        ("data/raw", "Importações (Parquet, um arquivo por ano)", "país de origem, NCM, UF de destino, via e URF, com FOB, kg, CIF, frete e seguro"),
        ("data/raw_soja", "Exportação de soja em grão (Parquet, um arquivo por ano)", "FOB e kg, para a relação de troca"),
        ("data/raw_benchmark", "Pink Sheet (CSV)", "preços internacionais de fertilizantes do Banco Mundial, em US$/t"),
        ("data/raw_cambio", "PTAX (CSV)", "PTAX de venda, média mensal"),
    )
    for pasta, titulo, descricao in pastas:
        if (ctx.raiz / pasta).is_dir():
            linhas.append(f"- [{titulo}]({arvore}{pasta}): {descricao}")
    if (ctx.raiz / "data" / "sinais.json").is_file():
        linhas.append(f"- [Sinais (JSON)]({REPOSITORIO}/blob/main/data/sinais.json): histórico de todos os sinais de preço e de volume, num formato estável (README)")
    linhas += [
        f"- [Código e método]({REPOSITORIO}): pipeline em Python, README com o método e as limitações (código MIT)",
        "",
        "## Fontes",
        "",
        "- [Comex Stat/MDIC](https://comexstat.mdic.gov.br/): importações e exportações do Brasil; dados abertos do MDIC",
        "- [Banco Mundial, Pink Sheet](https://www.worldbank.org/en/research/commodity-markets): preços internacionais de commodities; CC BY 4.0",
        "- [BCB, PTAX (SGS 3698)](https://api.bcb.gov.br/dados/serie/bcdata.sgs.3698/dados?formato=json): câmbio de referência; ODbL",
        "",
        "## Optional",
        "",
        f"- [Licença dos dados tratados]({REPOSITORIO}/blob/main/data/LICENSE): CC BY 4.0",
        f"- [Sitemap]({URL_BASE}sitemap.xml)",
    ]
    return "\n".join(linhas) + "\n"


# --- _headers -------------------------------------------------------------------------------
def headers(ctx: Contexto) -> str:
    """Cache na Cloudflare. Regras sem sobreposição: se duas casam com o mesmo endereço, a Cloudflare
    junta os valores do mesmo cabeçalho com vírgula."""
    curtos = ["/", "/index.html"]
    curtos += sorted(f"/{p.name}" for p in ctx.site.glob("*.json"))
    curtos += sorted({f"/{p.caminho.split('/', 1)[0]}/*" for p in ctx.paginas if "/" in p.caminho})
    curtos += ["/sinais.xml"] if (ctx.site / "sinais.xml").is_file() else []  # feed: revalida a cada leitura, como as páginas
    linhas = [
        "# Gerado pelo build (src/estatico/cabecalho.py). Cloudflare Workers static assets: não é servido.",
        "# assets/: um ano, immutable, porque toda referência leva ?v=<hash do arquivo> (o build falha se",
        "# alguma ficar sem ou apontar para arquivo que não existe; um 404 em assets/ só vem de ?v= antigo).",
        "# Páginas e JSON: o navegador guarda, mas revalida a cada uso (ETag; 304 sem corpo), para nunca",
        "# juntar HTML novo com dado velho, ou o contrário, depois da atualização mensal. Ícones: um dia.",
        "/assets/*",
        f"  Cache-Control: {CACHE_LONGO}",
    ]
    for regra in curtos:
        linhas += [regra, f"  Cache-Control: {CACHE_CURTO}"]
    for icone in ("/favicon-*", "/apple-touch-icon.png"):
        linhas += [icone, f"  Cache-Control: {CACHE_ICONES}"]
    if sum(linha.startswith("/") for linha in linhas) > 100:  # limite da Cloudflare
        raise ErroEstatico("_headers com mais de 100 regras")
    return "\n".join(linhas) + "\n"
