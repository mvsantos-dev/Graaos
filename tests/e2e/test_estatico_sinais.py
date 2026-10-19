"""Sinais do mês no navegador (só em desenvolvimento): a seção #sinais da home, o feed /sinais.xml,
o bloco das páginas dos boletins e o parágrafo de sinais no card do boletim, no site montado pelo
build_site.sh.

- A seção é HTML do build, sem JavaScript: com e sem script, o mesmo innerHTML.
- Os links dos cards vão para âncoras que existem e aparecem; o clique rola sem mexer no hash (que
  guarda os filtros).
- Sem rolagem lateral da página em 360, 390 e 1440 px, nos dois temas; no celular os cards rolam de
  lado dentro da faixa.

Roda com Playwright e Chromium; sem o Playwright ou sem RADAR_E2E_LIBS (Chart.js e anime.js locais,
porque os testes não acessam a rede), o teste é pulado (como no CI).
"""

import functools
import http.server
import json
import os
import shutil
import subprocess
import threading
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
LIBS = os.environ.get("RADAR_E2E_LIBS")
if not LIBS:
    pytest.skip("defina RADAR_E2E_LIBS com chart.umd.min.js e anime.umd.min.js", allow_module_level=True)

from src import boletim as B  # noqa: E402
from src import sinais as S  # noqa: E402
from src.estatico import sinais as ES  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
CHROMIUM = os.environ.get("RADAR_E2E_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
ESTOURO = "() => document.scrollingElement.scrollWidth - document.documentElement.clientWidth"


class _Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("estatico-sinais")
    saida = pasta / "site"
    r = subprocess.run(["bash", str(RAIZ / "build_site.sh"), str(saida)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    # um segundo site, igual, mas com o boletim do modo --mock no card (o build nunca o publica)
    assert B.main(["--mock", "--saida", str(pasta / "mock")]) == 0
    com_boletim = pasta / "com-boletim"
    shutil.copytree(saida, com_boletim)
    shutil.copy(pasta / "mock" / "latest.json", com_boletim / "boletim.json")
    servidores, urls = [], []
    for raiz in (saida, com_boletim):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Silencioso, directory=str(raiz)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servidores.append(srv)
        urls.append(f"http://127.0.0.1:{srv.server_address[1]}/")
    yield {"url": urls[0], "url_boletim": urls[1], "pasta": saida, "doc": S.ler(), "mock": json.loads((pasta / "mock" / "latest.json").read_text(encoding="utf-8"))}
    for srv in servidores:
        srv.shutdown()


@pytest.fixture(scope="module")
def navegador():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROMIUM if Path(CHROMIUM).exists() else None)
        yield b
        b.close()


def _cdn(rota):
    for nome, arquivo in (("chart.js", "chart.umd.min.js"), ("animejs", "anime.umd.min.js")):
        if nome in rota.request.url:
            return rota.fulfill(path=str(Path(LIBS) / arquivo), content_type="application/javascript", headers={"Access-Control-Allow-Origin": "*"})
    return rota.abort()


def _abrir(navegador, url, largura=1440, js=True, tema="light", movimento=False, altura=900):
    ctx = navegador.new_context(viewport={"width": largura, "height": altura}, java_script_enabled=js, color_scheme=tema,
                                reduced_motion="no-preference" if movimento else "reduce", is_mobile=largura < 800, has_touch=largura < 800)
    pg = ctx.new_page()
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" and "404" not in m.text else None)
    pg.route("https://cdn.jsdelivr.net/**", _cdn)
    pg.route("https://challenges.cloudflare.com/**", lambda rota: rota.abort())
    pg.goto(url)
    if js and "boletim/" not in url:
        pg.wait_for_function("!!(window.radarDados && window.Chart)", timeout=30_000)
        pg.wait_for_timeout(300)
    return ctx, pg, erros


def test_secao_igual_com_e_sem_javascript(navegador, site):
    ctx, pg, _ = _abrir(navegador, site["url"], js=False)
    sem = pg.evaluate("document.getElementById('sinais').innerHTML")
    assert pg.locator("#sinais").is_visible() and pg.locator("#sinais .sinal-frase, #sinais .sinais-vazio").first.is_visible()
    # logo depois do hero, antes dos filtros
    ordem = pg.evaluate("""() => { const y = (s) => document.querySelector(s).getBoundingClientRect().top;
      return [y('#inicio') < y('#sinais'), y('#sinais') < y('.filtros'), document.querySelector('#inicio').getBoundingClientRect().bottom <= y('#sinais') + 1]; }""")
    assert ordem == [True, True, True]
    ctx.close()
    ctx, pg, erros = _abrir(navegador, site["url"])
    assert pg.evaluate("document.getElementById('sinais').innerHTML") == sem
    assert erros == []
    ctx.close()


def test_cards_na_ordem_do_sinais_json(navegador, site):
    doc = site["doc"]
    esperados = ES.ordenar(S.sinais_do_mes(doc, doc["periodo"]["fim"]))[: ES.MAX_CARTOES]
    ctx, pg, _ = _abrir(navegador, site["url"], js=False)
    cards = pg.evaluate("""() => [...document.querySelectorAll('#sinais .cartao.sinal')].map((c) => ({
      nivel: c.dataset.nivel, rotulo: c.querySelector('.sinal-nivel').textContent,
      frase: c.querySelector('.sinal-frase').textContent.replaceAll('\\u00a0', ' '),
      linha: !!c.querySelector('svg.sinal-linha[aria-hidden="true"]') }))""")
    esperados_frases = [s["frase"].replace("\u00a0", " ") for s in esperados]
    assert [c["frase"] for c in cards] == esperados_frases
    assert [c["nivel"] for c in cards] == [s["nivel"] for s in esperados]
    assert [c["rotulo"] for c in cards] == [ES.NIVEL[s["nivel"]] for s in esperados]  # o nível em texto
    assert all(c["linha"] for c in cards)
    ctx.close()


def test_links_dos_cards_vao_para_ancoras_que_existem_e_aparecem(navegador, site):
    ctx, pg, _ = _abrir(navegador, site["url"], js=False)
    alvos = pg.evaluate("""() => [...document.querySelectorAll('#sinais a[href^="#"]')].map((a) => {
      const id = a.getAttribute('href').slice(1), el = document.getElementById(id);
      return [id, !!el, !!el && el.getClientRects().length > 0, a.dataset.secao === id]; })""")
    assert alvos, "nenhum link de card"
    for id_, existe, aparece, secao in alvos:
        assert existe and aparece and secao, id_
    # os outros links: página do boletim do mês, feed e o histórico no repositório
    hrefs = pg.evaluate("[...document.querySelectorAll('#sinais a:not([href^=\"#\"])')].map((a) => a.getAttribute('href'))")
    locais = [h for h in hrefs if not h.startswith("https://")]
    assert "sinais.xml" in locais and any(h.startswith("boletim/") and h.endswith("/#sinais") for h in locais)
    for h in locais:
        with urllib.request.urlopen(site["url"] + h.split("#")[0]) as r:
            assert r.status == 200, h
    ctx.close()
    # com o script: o clique rola até o alvo sem trocar o hash (que guarda os filtros)
    ctx, pg, erros = _abrir(navegador, site["url"])
    hash_antes = pg.evaluate("location.hash")
    link = pg.locator("#sinais a.sinal-link").first
    alvo = link.get_attribute("data-secao")
    link.click()
    pg.wait_for_timeout(600)
    assert pg.evaluate("location.hash") == hash_antes
    topo = pg.evaluate(f"document.getElementById('{alvo}').getBoundingClientRect().top")
    assert 0 <= topo <= 200, (alvo, topo)
    assert erros == []
    ctx.close()


@pytest.mark.parametrize("largura", [360, 390, 1440])
@pytest.mark.parametrize("tema", ["light", "dark"])
def test_sem_rolagem_lateral_e_cards_inteiros(navegador, site, largura, tema):
    ctx, pg, erros = _abrir(navegador, site["url"], largura=largura, tema=tema)
    assert pg.evaluate(ESTOURO) <= 0
    medidas = pg.evaluate("""() => { const W = document.documentElement.clientWidth, ol = document.querySelector('#sinais .sinais-lista');
      const cards = [...ol.querySelectorAll('.cartao.sinal')];
      return { W, olDireita: ol.getBoundingClientRect().right, olRola: ol.scrollWidth > ol.clientWidth + 1,
        primeiro: [cards[0].getBoundingClientRect().left, cards[0].getBoundingClientRect().right],
        cards: cards.map((c) => c.getBoundingClientRect().right), n: cards.length,
        transbordam: [...document.querySelectorAll('#sinais .sinal-frase, #sinais .sinal-legenda, #sinais .sinais-rodape p')]
          .filter((e) => e.scrollWidth > e.clientWidth + 1).length }; }""")
    assert medidas["olDireita"] <= medidas["W"] + 0.5
    assert 0 <= medidas["primeiro"][0] and medidas["primeiro"][1] <= medidas["W"] + 0.5  # o primeiro card inteiro na tela
    assert medidas["transbordam"] == 0
    if largura >= 800:
        assert all(r <= medidas["W"] + 0.5 for r in medidas["cards"]) and not medidas["olRola"]
    elif medidas["n"] > 1:
        assert medidas["olRola"]  # no celular, os outros cards na faixa que rola de lado
    assert erros == []
    ctx.close()


@pytest.mark.parametrize("tema, superficie, linha", [("light", "rgb(255, 255, 255)", "rgb(43, 52, 209)"), ("dark", "rgb(14, 20, 54)", "rgb(166, 173, 255)")])
def test_cores_dos_dois_temas(navegador, site, tema, superficie, linha):
    ctx, pg, _ = _abrir(navegador, site["url"], js=False, tema=tema)
    cores = pg.evaluate("""() => { const c = document.querySelector('#sinais .cartao.sinal'), s = getComputedStyle;
      const forte = document.querySelector('#sinais [data-nivel="forte"] .sinal-nivel'), atencao = document.querySelector('#sinais [data-nivel="atencao"] .sinal-nivel');
      return { fundo: s(c).backgroundColor, linha: s(c.querySelector('svg.sinal-linha path.serie')).stroke,
        forte: forte && [s(forte).color, s(forte).backgroundColor], atencao: atencao && s(atencao).backgroundColor }; }""")
    assert cores["fundo"] == superficie and cores["linha"] == linha
    if cores["forte"]:
        assert cores["forte"] == ["rgb(255, 255, 255)", "rgb(43, 52, 209)"]  # selo cheio, texto branco (8,4:1)
    if cores["atencao"]:
        assert cores["atencao"] == "rgba(0, 0, 0, 0)"  # selo vazado: o nível não depende só da cor
    ctx.close()


@pytest.mark.parametrize("largura", [390, 1440])
def test_entrada_dos_cards_com_movimento(navegador, site, largura):
    ctx, pg, erros = _abrir(navegador, site["url"], largura=largura, movimento=True)
    assert pg.evaluate("document.documentElement.classList.contains('movimento')")
    pg.evaluate("document.getElementById('sinais').scrollIntoView({block: 'start'})")
    pg.wait_for_timeout(1800)
    visiveis = pg.evaluate("""() => { const W = document.documentElement.clientWidth, H = innerHeight;
      return [...document.querySelectorAll('#sinais .cartao.sinal')].filter((c) => { const r = c.getBoundingClientRect();
        return r.left < W && r.right > 0 && r.top < H && r.bottom > 0; }).map((c) => getComputedStyle(c).opacity); }""")
    assert visiveis and all(o == "1" for o in visiveis), visiveis
    if largura < 800:  # o último card da faixa entra quando a faixa rola até ele
        pg.evaluate("document.querySelector('#sinais .sinais-lista').scrollLeft = 1e6")
        pg.wait_for_timeout(1800)
        assert pg.evaluate("getComputedStyle([...document.querySelectorAll('#sinais .cartao.sinal')].at(-1)).opacity") == "1"
    assert erros == []
    ctx.close()


def test_feed_atom_servido_e_ligado_no_head(navegador, site):
    with urllib.request.urlopen(site["url"] + "sinais.xml") as r:
        assert r.status == 200
        feed = ET.fromstring(r.read())
    assert feed.tag == "{http://www.w3.org/2005/Atom}feed" and feed.findall("{http://www.w3.org/2005/Atom}entry")
    ctx, pg, _ = _abrir(navegador, site["url"], js=False)
    assert pg.evaluate("document.querySelector('link[rel=alternate][type=\"application/atom+xml\"]').getAttribute('href')") == "sinais.xml"
    ctx.close()


@pytest.mark.parametrize("largura", [360, 1440])
def test_pagina_do_boletim_tem_os_sinais_do_mes(navegador, site, largura):
    doc = site["doc"]
    ultimo = doc["periodo"]["fim"]
    ctx, pg, falhas = _abrir(navegador, site["url"] + f"boletim/{ultimo}/", largura=largura, js=False)
    pg.wait_for_load_state("networkidle")
    assert pg.locator("#sinais").is_visible() and pg.evaluate(ESTOURO) <= 0
    frases = pg.evaluate("[...document.querySelectorAll('#sinais .lista-sinais .sinal-frase')].map((e) => e.textContent)")
    assert frases == [s["frase"].replace("US$ ", "US$\u00a0") for s in ES.do_mes(doc, ultimo)]
    for href in pg.evaluate("[...document.querySelectorAll('#sinais a')].map((a) => a.getAttribute('href'))"):
        assert href.startswith("../../#")
    # o link do feed da home leva à página do mês, na âncora do bloco
    pg.goto(site["url"] + f"boletim/{ultimo}/#sinais")
    assert pg.evaluate("document.getElementById('sinais').getBoundingClientRect().top") < 200
    ctx.close()


def test_card_do_boletim_mostra_o_paragrafo_de_sinais(navegador, site):
    mock = site["mock"]
    ctx, pg, erros = _abrir(navegador, site["url_boletim"])
    pg.wait_for_function("!document.getElementById('secao-boletim').classList.contains('oculto')", timeout=10_000)
    texto = pg.evaluate("""() => { const t = document.getElementById('texto-boletim');
      return { titulo: t.querySelector('h4.sinais-boletim')?.textContent, ultimo: t.lastElementChild.textContent,
        paragrafos: [...t.querySelectorAll('p')].length,
        link: [...document.querySelectorAll('#links-boletim a')].map((a) => [a.textContent, a.getAttribute('href')]) }; }""")
    assert texto["titulo"] == "Sinais do mês" and texto["ultimo"] == mock["sinais"]["paragrafo"]
    assert texto["paragrafos"] == len(mock["paragrafos"]) + 1  # o texto da IA inteiro, mais o parágrafo dos sinais
    assert ["Sinais do mês", f"boletim/{mock['mes']}/#sinais"] in texto["link"]
    assert erros == []
    ctx.close()
