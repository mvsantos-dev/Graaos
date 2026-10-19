"""Testes do cabeçalho e da indexação do site (src/estatico/cabecalho.py e cabecalho_versao.py).

Monta o site com o build_site.sh (sem rede) e confere o <head> do index.html, o JSON-LD, os ícones,
o manifest, robots.txt, sitemap.xml, 404.html, llms.txt, _headers e a versão (?v=) de toda
referência a assets/.
"""

import hashlib
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src.estatico import cabecalho, formato
from src.estatico.cabecalho_versao import Conferente, Versionador, conferir, versionar
from src.estatico.contexto import REPOSITORIO, URL_BASE, Contexto, ErroEstatico, Pagina

RAIZ = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="precisa de bash")


@pytest.fixture(scope="module")
def site(tmp_path_factory) -> Path:
    saida = tmp_path_factory.mktemp("cabecalho") / "site"
    r = subprocess.run(["bash", str(RAIZ / "build_site.sh"), str(saida)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return saida


@pytest.fixture(scope="module")
def dados() -> dict:
    return json.loads((RAIZ / "data" / "processed" / "dashboard.json").read_text(encoding="utf-8"))


class _Cabeca(HTMLParser):
    """title, meta e link do <head>."""

    def __init__(self):
        super().__init__()
        self.titulo, self.metas, self.links, self._no_titulo, self._na_cabeca = "", [], [], False, True

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "body":
            self._na_cabeca = False
        if not self._na_cabeca:
            return
        if tag == "title":
            self._no_titulo = True
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "link":
            self.links.append(a)

    def handle_endtag(self, tag):
        if tag == "title":
            self._no_titulo = False

    def handle_data(self, data):
        if self._no_titulo:
            self.titulo += data

    def meta(self, chave: str) -> str:
        achados = [m["content"] for m in self.metas if m.get("name") == chave or m.get("property") == chave]
        assert len(achados) == 1, chave
        return achados[0]

    def link(self, rel: str, **filtro) -> list[dict]:
        return [ln for ln in self.links if rel in (ln.get("rel") or "").split() and all(ln.get(k) == v for k, v in filtro.items())]


def _cabeca(html: str) -> _Cabeca:
    c = _Cabeca()
    c.feed(html)
    return c


def _json_ld(html: str) -> dict:
    blocos = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert len(blocos) == 1
    return json.loads(blocos[0])


def _no(grafo: dict, tipo: str) -> dict:
    achados = [n for n in grafo["@graph"] if n["@type"] == tipo]
    assert len(achados) == 1, tipo
    return achados[0]


def _png(caminho: Path) -> tuple[int, int]:
    cabeca = caminho.read_bytes()[:24]
    assert cabeca[:8] == b"\x89PNG\r\n\x1a\n"
    return int.from_bytes(cabeca[16:20], "big"), int.from_bytes(cabeca[20:24], "big")


def _h(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()[:10]


# --- <head> -------------------------------------------------------------------------------
def test_titulo_descricao_e_open_graph(site):
    c = _cabeca((site / "index.html").read_text(encoding="utf-8"))
    assert c.titulo == "Importação de fertilizantes no Brasil | Graaos"
    assert len(c.titulo) <= 60
    descricao = c.meta("description")
    assert len(descricao) <= 155
    for termo in ("N, P, K e NPK", "origens", "portos", "preços", "relação de troca", "soja", "no porto", "Dados públicos", "código aberto"):
        assert termo in descricao, termo
    assert not re.search(r"\d", descricao), "nenhum número escrito à mão na descrição"
    assert c.meta("og:title") == c.meta("twitter:title") == c.titulo
    for chave in ("og:description", "twitter:description"):
        texto = c.meta(chave)
        assert "Importação de fertilizantes no Brasil" in texto and "no porto" in texto
        assert texto.endswith("Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet); BCB/PTAX.")
        assert not re.search(r"\b(19|20)\d\d\b", texto), "período escrito à mão"
    assert c.meta("og:url") == URL_BASE


def test_canonical_tema_icones_e_manifest(site):
    c = _cabeca((site / "index.html").read_text(encoding="utf-8"))
    assert [ln["href"] for ln in c.link("canonical")] == [URL_BASE]
    assert c.meta("theme-color") == "#2B36D9"
    assert c.link("icon", type="image/svg+xml")[0]["href"].startswith("data:image/svg+xml,")
    tamanhos = {"32x32": 32, "192x192": 192}
    for sizes, lado in tamanhos.items():
        (icone,) = c.link("icon", sizes=sizes)
        assert icone["type"] == "image/png"
        assert _png(site / icone["href"]) == (lado, lado)
    (toque,) = c.link("apple-touch-icon")
    assert _png(site / toque["href"]) == (180, 180)
    (manifest,) = c.link("manifest")
    m = json.loads((site / manifest["href"]).read_text(encoding="utf-8"))
    assert m["name"] and m["short_name"] and m["start_url"] and m["display"] in ("browser", "standalone")
    assert m["theme_color"] == c.meta("theme-color")
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", m["background_color"])
    lados = set()
    for icone in m["icons"]:
        largura, altura = _png(site / icone["src"])
        assert icone["sizes"] == f"{largura}x{altura}" and icone["type"] == "image/png"
        lados.add(largura)
    assert {192, 512} <= lados


def test_preload_das_fontes_usa_a_mesma_url_do_css(site):
    html = (site / "index.html").read_text(encoding="utf-8")
    c = _cabeca(html)
    preloads = c.link("preload", **{"as": "font"})
    assert preloads, "sem preload de fontes"
    css = (site / "assets" / "radar.css").read_text(encoding="utf-8")
    urls_css = {(site / "assets" / u).resolve().relative_to(site).as_posix() + "?" + q for u, q in re.findall(r'url\("(fontes/[^"?]+)\?([^"]+)"\)', css)}
    for p in preloads:
        assert p["type"] == "font/woff2" and "crossorigin" in p
        caminho, _, query = p["href"].partition("?")
        assert f"{caminho}?{query}" in urls_css, p["href"]  # mesma URL: a fonte baixa uma vez
        assert query == f"v={_h(site / caminho)}"
    nomes = {p["href"].split("?")[0].rsplit("/", 1)[-1] for p in preloads}
    # as da primeira tela (título 300, texto 400, menu e botões em mono 400), sem a 500 do mono
    assert {"inter-tight-latin-300-normal.woff2", "inter-tight-latin-400-normal.woff2", "jetbrains-mono-latin-400-normal.woff2"} <= nomes
    assert "jetbrains-mono-latin-500-normal.woff2" not in nomes
    (marca,) = [p for p in preloads if "600" in p["href"]]
    assert marca.get("media") == "(min-width: 821px)"  # a marca some até 820 px (radar.css)


# --- JSON-LD ------------------------------------------------------------------------------
def test_json_ld_website_e_organizacao(site):
    grafo = _json_ld((site / "index.html").read_text(encoding="utf-8"))
    assert grafo["@context"] == "https://schema.org"
    web, org = _no(grafo, "WebSite"), _no(grafo, "Organization")
    assert web["@id"] == URL_BASE + "#website" and web["url"] == URL_BASE and web["inLanguage"] == "pt-BR"
    assert web["publisher"] == {"@id": org["@id"]} and org["@id"] == URL_BASE + "#organization"
    assert org["name"] == "Graaos" and org["url"] == URL_BASE
    assert REPOSITORIO in org["sameAs"]
    logo = org["logo"]
    assert logo["url"].startswith(URL_BASE)
    assert _png(site / logo["url"][len(URL_BASE):]) == (logo["width"], logo["height"])
    assert logo["width"] >= 112  # mínimo do Google para logo


def test_json_ld_dataset_com_valores_dos_dados(site, dados):
    html = (site / "index.html").read_text(encoding="utf-8")
    ds = _no(_json_ld(html), "Dataset")
    for campo in ("name", "description", "license", "creator", "temporalCoverage", "spatialCoverage", "variableMeasured", "distribution", "isBasedOn", "keywords"):
        assert ds.get(campo), campo
    assert 50 <= len(ds["description"]) <= 5000  # limites do Google
    periodo = dados["meta"]["periodo"]
    assert ds["temporalCoverage"] == f"{periodo['inicio']}/{periodo['fim']}"
    assert formato.rotulo_mes_longo(periodo["inicio"]) in ds["description"]
    assert formato.rotulo_mes_longo(periodo["fim"]) in ds["description"]
    assert "Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet); BCB/PTAX." in ds["description"]
    assert "no porto" in ds["description"] and "não é ágio" in ds["description"]
    assert ds["license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert ds["creator"] == {"@id": URL_BASE + "#organization"}
    assert ds["spatialCoverage"]["@type"] == "Country" and ds["spatialCoverage"]["name"] == "Brasil"
    assert ds["inLanguage"] == "pt-BR"
    atualizado = _cabeca(html).meta("atualizado")
    assert ds.get("dateModified") == (atualizado or None)
    variaveis = " | ".join(v["name"] for v in ds["variableMeasured"])
    for termo in ("Toneladas", "FOB", "CIF", "Frete", "Relação de troca"):
        assert termo in variaveis, termo
    assert all(v["@type"] == "PropertyValue" and v["unitText"] and v["description"] for v in ds["variableMeasured"])
    (troca,) = [v for v in ds["variableMeasured"] if v["name"] == "Relação de troca"]
    assert "no porto" in troca["description"] and "Não é o preço ao produtor" in troca["description"]
    fontes = " | ".join(f["name"] + " " + f["url"] for f in ds["isBasedOn"])
    for termo in ("Comex Stat", "Pink Sheet", "3698", "comexstat.mdic.gov.br", "worldbank.org", "bcb.gov.br"):
        assert termo in fontes, termo
    assert all(f["@type"] == "Dataset" and len(f["description"]) >= 50 for f in ds["isBasedOn"])


def test_json_ld_distribuicao_aponta_para_os_arquivos_do_repositorio(site):
    ds = _no(_json_ld((site / "index.html").read_text(encoding="utf-8")), "Dataset")
    urls = {d["contentUrl"]: d for d in ds["distribution"]}
    assert all(d["@type"] == "DataDownload" and d["encodingFormat"] for d in ds["distribution"])
    assert urls[URL_BASE + "dashboard.json"]["encodingFormat"] == "application/json"
    rastreados = subprocess.run(["git", "-C", str(RAIZ), "ls-files", "--", "data"], capture_output=True, text=True)
    if rastreados.returncode != 0:
        pytest.skip("sem git")
    esperados = [n for n in rastreados.stdout.splitlines() if n.endswith((".csv", ".parquet"))]
    assert any(n.startswith("data/processed/") for n in esperados) and any(n.endswith(".parquet") for n in esperados)
    for nome in esperados:
        d = urls[cabecalho.REPO_RAW + nome]
        assert d["encodingFormat"] == ("text/csv" if nome.endswith(".csv") else "application/vnd.apache.parquet")
    assert len(ds["distribution"]) == len(esperados) + 1


def test_json_ld_nao_fecha_o_script(monkeypatch):
    valor = {"a": "</script><!-- x & y >"}
    monkeypatch.setattr(cabecalho, "json_ld", lambda ctx: valor)
    html = cabecalho.json_ld_html(None)
    assert html.count("</script>") == 1 and "<!--" not in html and "&" not in html
    assert json.loads(re.search(r'json">(.*)</script>', html).group(1)) == valor


# --- robots, sitemap, llms, 404 -----------------------------------------------------------
def test_robots_e_sitemap_com_todas_as_paginas(site):
    robots = (site / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots and "Allow: /" in robots and "Disallow" not in robots
    assert f"Sitemap: {URL_BASE}sitemap.xml" in robots
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    raiz = ET.parse(site / "sitemap.xml").getroot()
    urls = {u.find("s:loc", ns).text: u.find("s:lastmod", ns) for u in raiz.findall("s:url", ns)}
    assert URL_BASE in urls
    # toda página HTML do site (menos o 404) está no sitemap, e só elas
    paginas = {URL_BASE if p.parent == site else f"{URL_BASE}{p.parent.relative_to(site).as_posix()}/" for p in site.rglob("index.html") if "assets" not in p.parts}
    assert set(urls) == paginas
    atualizado = _cabeca((site / "index.html").read_text(encoding="utf-8")).meta("atualizado")
    for lastmod in urls.values():
        if atualizado:
            assert lastmod is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", lastmod.text)
    if atualizado:
        assert urls[URL_BASE].text == atualizado


def test_llms_txt(site, dados):
    texto = (site / "llms.txt").read_text(encoding="utf-8")
    linhas = texto.splitlines()
    assert linhas[0] == "# Graaos · Fertilizantes" and linhas[2].startswith("> ")
    periodo = dados["meta"]["periodo"]
    assert formato.rotulo_mes_longo(periodo["inicio"]) in texto and formato.rotulo_mes_longo(periodo["fim"]) in texto
    for termo in (
        "Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet); BCB/PTAX.",
        URL_BASE + "dashboard.json",
        REPOSITORIO + "/tree/main/data/processed",
        "https://comexstat.mdic.gov.br/",
        "https://www.worldbank.org/en/research/commodity-markets",
        "bcdata.sgs.3698",
        "no porto, não o preço ao produtor",
        "não é ágio",
        "UF de destino",
        "CC BY 4.0",
    ):
        assert termo in texto, termo
    assert "## Dados abertos" in texto and "## Fontes" in texto
    # links no formato do llmstxt.org: - [nome](url): descrição
    assert all(re.match(r"- \[[^\]]+\]\(https://[^)]+\)", ln) for ln in linhas if ln.startswith("- [")), "link mal formado"
    if (site / "boletim" / "index.html").exists():
        assert URL_BASE + "boletim/" in texto


def test_pagina_404(site):
    html = (site / "404.html").read_text(encoding="utf-8")
    c = _cabeca(html)
    assert c.titulo == "Página não encontrada | Graaos"
    assert c.meta("robots") == "noindex"
    assert '<html lang="pt-BR">' in html
    assert f'href="{URL_BASE}"' in html  # link para a home
    # servida em qualquer caminho: nada relativo (só absoluto, a partir da raiz ou data:)
    for ref in re.findall(r'(?:href|src)="([^"]*)"|url\("([^"]*)"\)', html):
        valor = ref[0] or ref[1]
        assert valor.startswith(("https://", "/", "data:")), valor
    for fonte in re.findall(r'url\("(/assets/[^"?]+)\?v=(\w+)"\)', html):
        assert fonte[1] == _h(site / fonte[0].lstrip("/"))
    assert "<script" not in html.replace('type="application/ld+json"', "")  # sem JavaScript


# --- _headers ------------------------------------------------------------------------------
def _regras(texto: str) -> list[tuple[str, dict]]:
    regras = []
    for linha in texto.splitlines():
        assert len(linha) <= 2000
        if not linha.strip() or linha.startswith("#"):
            continue
        if not linha.startswith(" "):
            regras.append((linha, {}))
        else:
            nome, _, valor = linha.strip().partition(": ")
            regras[-1][1][nome] = valor
    return regras


def _casa(padrao: str, caminho: str) -> bool:
    return re.fullmatch(re.escape(padrao).replace(r"\*", ".*"), caminho) is not None


def test_headers_cache_longo_so_em_assets_e_sem_sobreposicao(site):
    regras = _regras((site / "_headers").read_text(encoding="utf-8"))
    assert 0 < len(regras) <= 100
    assert all(p.count("*") <= 1 for p, _ in regras)  # um splat por regra (Cloudflare)
    caminhos = ["/", "/index.html", "/dashboard.json", "/boletim.json", "/llms.txt", "/sitemap.xml", "/favicon-32.png"]
    caminhos += ["/" + p.relative_to(site).as_posix() for p in (site / "assets").rglob("*") if p.is_file()]
    caminhos += ["/" + p.parent.relative_to(site).as_posix() + "/" for p in site.rglob("index.html") if p.parent != site and "assets" not in p.parts]
    for caminho in caminhos:
        valores = [h["Cache-Control"] for padrao, h in regras if "Cache-Control" in h and _casa(padrao, caminho)]
        assert len(valores) <= 1, f"{caminho}: a Cloudflare juntaria {valores}"
        valor = valores[0] if valores else "public, max-age=0, must-revalidate"  # padrão da Cloudflare
        if caminho.startswith("/assets/"):
            assert valor == "public, max-age=31536000, immutable", caminho
        elif caminho.endswith((".json", ".html", "/")):
            assert "max-age=0" in valor and "must-revalidate" in valor, caminho


# --- versão dos assets ---------------------------------------------------------------------
def test_toda_referencia_a_assets_tem_a_versao_do_arquivo(site):
    html = (site / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="(assets/[^"]+)"', html)
    assert len(refs) >= 9  # css, 4 scripts, 4 preloads
    for ref in refs:
        caminho, _, query = ref.partition("?")
        assert query == f"v={_h(site / caminho)}", ref
    css = (site / "assets" / "radar.css").read_text(encoding="utf-8")
    fontes = re.findall(r'url\("(fontes/[^"?]+)(\?[^"]*)?"\)', css)
    assert fontes and all(q == f"?v={_h(site / 'assets' / f)}" for f, q in fontes)
    for js in ("fluxos.js", "mapa-hero.js"):
        texto = (site / "assets" / js).read_text(encoding="utf-8")
        assert f'fetch("assets/mapa-pontos.json?v={_h(site / "assets" / "mapa-pontos.json")}")' in texto
    # a conferência do build passa no site montado
    ctx = Contexto.carregar(site)
    assert conferir(ctx) >= len(refs) + len(fontes) + 2


# --- Versionador num site de mentira -------------------------------------------------------
def _site_falso(tmp_path: Path, index: str, arquivos: dict[str, str]) -> Contexto:
    site = tmp_path / "site"
    site.mkdir()
    for nome, texto in arquivos.items():
        (site / nome).parent.mkdir(parents=True, exist_ok=True)
        (site / nome).write_text(texto, encoding="utf-8")
    (site / "index.html").write_text(index, encoding="utf-8")
    return Contexto(site=site, dados={}, boletim={}, html=index)


def test_versionador_cobre_html_css_js_e_subpaginas(tmp_path):
    index = (
        "<!-- assets/comentario.js -->\n"
        '<link rel="stylesheet" href="assets/a.css?v=velho">\n'
        '<img srcset="assets/i.png 1x, assets/i.png 2x" src="/assets/i.png" alt="">\n'
        '<svg><use href="assets/s.svg#icone"/></svg>\n'
        '<script type="application/ld+json">{"x": "assets/nao-existe.js"}</script>\n'
        '<script>// (assets/nao-existe.js) é só comentário\nfetch("assets/d.json"); const u = `assets/d.json`;</script>\n'
        '<style>.x { background: url(assets/i.png) } .y { filter: url(#f) }</style>\n'
    )
    ctx = _site_falso(
        tmp_path,
        index,
        {
            "assets/a.css": '@font-face { src: url("fontes/f.woff2") format("woff2"); } .z { background: url(data:image/png;base64,AA==) }',
            "assets/fontes/f.woff2": "fonte",
            "assets/i.png": "png",
            "assets/s.svg": "<svg/>",
            "assets/d.json": "{}",
            "assets/b.js": 'fetch("assets/d.json")',
            "boletim/2026-09/index.html": '<link rel="stylesheet" href="../../assets/a.css">',
        },
    )
    site = ctx.site
    n = versionar(ctx)
    h = lambda nome: _h(site / nome)  # noqa: E731
    css = (site / "assets/a.css").read_text()
    assert f'url("fontes/f.woff2?v={h("assets/fontes/f.woff2")}")' in css and "url(data:image/png;base64,AA==)" in css
    assert f'href="assets/a.css?v={h("assets/a.css")}"' in ctx.html  # hash do CSS já versionado
    assert f'srcset="assets/i.png?v={h("assets/i.png")} 1x, assets/i.png?v={h("assets/i.png")} 2x"' in ctx.html
    assert f'src="/assets/i.png?v={h("assets/i.png")}"' in ctx.html
    assert f'href="assets/s.svg?v={h("assets/s.svg")}#icone"' in ctx.html
    assert "<!-- assets/comentario.js -->" in ctx.html and '{"x": "assets/nao-existe.js"}' in ctx.html
    assert "// (assets/nao-existe.js) é só comentário" in ctx.html
    assert f'fetch("assets/d.json?v={h("assets/d.json")}")' in ctx.html and f"`assets/d.json?v={h('assets/d.json')}`" in ctx.html
    assert f"url(assets/i.png?v={h('assets/i.png')})" in ctx.html and "url(#f)" in ctx.html
    assert f'fetch("assets/d.json?v={h("assets/d.json")}")' in (site / "assets/b.js").read_text()
    assert f'href="../../assets/a.css?v={h("assets/a.css")}"' in (site / "boletim/2026-09/index.html").read_text()
    assert n >= 10
    # rodar de novo não muda nada (idempotente)
    antes = ctx.html
    versionar(ctx)
    assert ctx.html == antes


@pytest.mark.parametrize(
    ("index", "arquivos", "mensagem"),
    [
        ('<script src="assets/falta.js"></script>', {}, "não existe"),
        ('<link rel="stylesheet" href="assets/a.css">', {"assets/a.css": 'body { background: url("falta.png") }'}, "não existe"),
        ('<script src="../assets/a.js"></script>', {"assets/a.js": ""}, "fora do site"),
        ("<p>x</p>", {"boletim/index.html": '<link href="assets/a.css">', "assets/a.css": ""}, "não existe"),  # caminho relativo errado na subpágina
        ('<link href="assets/a.css">', {"assets/a.css": '@import url("b.css");', "assets/b.css": '@import url("a.css");'}, "circular"),
    ],
    ids=["html-sem-arquivo", "css-sem-arquivo", "fora-do-site", "subpagina-relativa", "circular"],
)
def test_versionador_falha_em_referencia_quebrada(tmp_path, index, arquivos, mensagem):
    ctx = _site_falso(tmp_path, index, arquivos)
    with pytest.raises(ErroEstatico, match=mensagem):
        versionar(ctx)


def test_conferencia_pega_referencia_sem_versao_ou_com_hash_velho(tmp_path):
    ctx = _site_falso(tmp_path, '<script src="assets/a.js"></script>', {"assets/a.js": "1"})
    versionar(ctx)
    (ctx.site / "assets/a.js").write_text("2")  # arquivo mudou depois da versão
    with pytest.raises(ErroEstatico, match="hash|com \\?v="):
        conferir(ctx)
    ctx.html = '<script src="assets/a.js"></script>'
    with pytest.raises(ErroEstatico, match="sem versão"):
        conferir(ctx)
    assert issubclass(Conferente, Versionador)


@pytest.mark.parametrize("codigo", ['fetch("assets/" + nome);', "fetch(`assets/${nome}.json`);", "const pasta = '../assets/fontes/';"], ids=["concatenado", "template", "pasta"])
@pytest.mark.parametrize("onde", ["asset", "inline"])
def test_conferencia_recusa_caminho_de_assets_montado_no_codigo(tmp_path, codigo, onde):
    # sem o caminho inteiro numa string, o build não põe ?v= e o arquivo ficaria um ano no cache
    if onde == "asset":
        ctx = _site_falso(tmp_path, '<script src="assets/a.js"></script>', {"assets/a.js": codigo})
    else:
        ctx = _site_falso(tmp_path, f"<script>{codigo}</script>", {})
    with pytest.raises(ErroEstatico, match="montado no código"):
        versionar(ctx)


# --- sitemap e páginas ---------------------------------------------------------------------
def test_sitemap_recusa_pagina_que_nao_existe_ou_repetida(site):
    ctx = Contexto.carregar(site, "2026-10-01")
    ctx.paginas = [Pagina("", None), Pagina("boletim/1999-01/", "2026-10-01")]
    with pytest.raises(ErroEstatico, match="não existe"):
        cabecalho.sitemap(ctx)
    ctx.paginas = [Pagina("", None), Pagina("", None)]
    with pytest.raises(ErroEstatico, match="repetida"):
        cabecalho.sitemap(ctx)
    ctx.paginas = [Pagina("", "2026-1-1")]
    with pytest.raises(ErroEstatico, match="lastmod"):
        cabecalho.sitemap(ctx)
    ctx.paginas = [Pagina("", None)]
    assert "<lastmod>2026-10-01</lastmod>" in cabecalho.sitemap(ctx)  # sem lastmod próprio: a data dos dados


def test_icones_com_tamanho_errado_falham(tmp_path, site):
    copia = tmp_path / "site"
    shutil.copytree(site, copia)
    shutil.copy(copia / "favicon-32.png", copia / "favicon-192.png")
    with pytest.raises(ErroEstatico, match="favicon-192.png"):
        cabecalho.conferir_icones(Contexto.carregar(copia))
