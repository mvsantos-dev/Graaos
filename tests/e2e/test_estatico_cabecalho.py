"""Cenários de navegador do site MONTADO (build_site.sh): fontes com ?v= baixadas uma vez só, preload
sem desperdício, nenhum 404 de arquivo do site, JSON-LD e manifest legíveis e a página 404.

O servidor imita o not_found_handling "404-page" da Cloudflare (wrangler.jsonc): endereço que não
existe recebe o 404.html da raiz, com status 404. Pulado sem Playwright ou sem RADAR_E2E_LIBS.
"""

import collections
import functools
import http.server
import os
import subprocess
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
LIBS = os.environ.get("RADAR_E2E_LIBS")
if not LIBS:
    pytest.skip("defina RADAR_E2E_LIBS com chart.umd.min.js e anime.umd.min.js", allow_module_level=True)

RAIZ = Path(__file__).resolve().parents[2]
CHROMIUM = os.environ.get("RADAR_E2E_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    saida = tmp_path_factory.mktemp("site-montado") / "site"
    r = subprocess.run(["bash", str(RAIZ / "build_site.sh"), str(saida)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return saida


@pytest.fixture(scope="module")
def servidor(site):
    class Manipulador(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send_error(self, code, message=None, explain=None):  # 404.html da raiz, como a Cloudflare
            if code != 404:
                return super().send_error(code, message, explain)
            corpo = (site / "404.html").read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Manipulador, directory=str(site)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
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


@pytest.mark.parametrize(("largura", "altura"), [(390, 844), (1440, 900)], ids=["celular", "desktop"])
def test_fontes_uma_vez_so_e_nenhum_arquivo_faltando(navegador, servidor, largura, altura):
    ctx = navegador.new_context(viewport={"width": largura, "height": altura}, is_mobile=largura < 800, has_touch=largura < 800)
    pg = ctx.new_page()
    pedidos, falhas, avisos = [], [], []
    pg.on("request", lambda r: r.url.startswith(servidor) and pedidos.append((r.resource_type, r.url[len(servidor):])))
    pg.on("response", lambda r: r.url.startswith(servidor) and r.status >= 400 and falhas.append((r.status, r.url)))
    pg.on("console", lambda m: avisos.append(m.text) if m.type in ("warning", "error") else None)
    pg.route("https://cdn.jsdelivr.net/**", _cdn)
    pg.route("https://challenges.cloudflare.com/**", lambda r: r.abort())
    try:
        pg.goto(servidor)
        pg.wait_for_function("window.radarDados", timeout=30_000)
        pg.wait_for_timeout(4000)  # o Chromium avisa de preload sem uso depois de uns segundos
        pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        pg.wait_for_timeout(1500)
        fontes = [u for t, u in pedidos if t == "font"]
        assert fontes, "nenhuma fonte baixada"
        assert all("?v=" in u for u in fontes), fontes
        por_arquivo = collections.Counter(u.split("?")[0] for u in fontes)
        assert all(n == 1 for n in por_arquivo.values()), por_arquivo  # preload e @font-face com a mesma URL
        assert all("?v=" in u for t, u in pedidos if u.startswith("assets/")), pedidos
        assert not falhas, falhas
        assert not [a for a in avisos if "preload" in a], avisos
        # as fontes da primeira tela chegam pelo preload, antes do CSS pedir
        primeiras = [u.split("?")[0].rsplit("/", 1)[-1] for t, u in pedidos[:6] if t == "font"]
        assert {"inter-tight-latin-300-normal.woff2", "inter-tight-latin-400-normal.woff2", "jetbrains-mono-latin-400-normal.woff2"} <= set(primeiras)
        # JSON-LD e manifest legíveis no navegador; ícones do manifest existem
        tipos = pg.evaluate("""() => JSON.parse(document.querySelector('script[type="application/ld+json"]').textContent)['@graph'].map(n => n['@type'])""")
        assert tipos == ["WebSite", "Organization", "Dataset"]
        estados = pg.evaluate(
            """async () => { const m = await (await fetch(document.querySelector('link[rel=manifest]').href)).json();
              const icones = [...m.icons.map(i => new URL(i.src, document.querySelector('link[rel=manifest]').href).href),
                ...[...document.querySelectorAll('link[rel~=icon], link[rel=apple-touch-icon]')].map(l => l.href).filter(h => !h.startsWith('data:'))];
              return Promise.all(icones.map(async h => (await fetch(h)).status)); }"""
        )
        assert estados and all(s == 200 for s in estados), estados
    finally:
        ctx.close()


@pytest.mark.parametrize("tema", ["light", "dark"])
def test_pagina_404_em_qualquer_caminho(navegador, servidor, tema):
    ctx = navegador.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, color_scheme=tema)
    pg = ctx.new_page()
    try:
        resposta = pg.goto(servidor + "boletim/1999-01/nada/")
        assert resposta.status == 404
        pg.wait_for_load_state("networkidle")
        assert pg.title() == "Página não encontrada | Graaos"
        info = pg.evaluate(
            """() => ({fontes: [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family + ' ' + f.weight),
              largura: document.scrollingElement.scrollWidth, tela: document.documentElement.clientWidth,
              home: [...document.querySelectorAll('a')].some(a => a.href === 'https://radar.graaos.cloud/'),
              fundo: getComputedStyle(document.body).backgroundColor})"""
        )
        assert "Inter Tight 300" in info["fontes"], info  # fonte do site, achada a partir da raiz
        assert info["largura"] <= info["tela"] and info["home"]
        assert info["fundo"] in ("rgb(43, 52, 209)", "rgb(7, 11, 36)"), info  # hero: cobalto no claro, marinho no escuro
    finally:
        ctx.close()
