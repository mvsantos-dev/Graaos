"""Páginas dos boletins no navegador (só em desenvolvimento): o site montado pelo build_site.sh,
servido em localhost, como um robô de busca ou um leitor sem JavaScript o vê.

Roda com Playwright e Chromium; sem o Playwright, o teste é pulado (como no CI). As páginas dos
boletins não usam bibliotecas do CDN, e qualquer pedido para fora de localhost é abortado.
"""

import functools
import http.server
import os
import subprocess
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

RAIZ = Path(__file__).resolve().parents[2]
CHROMIUM = os.environ.get("RADAR_E2E_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
ESTOURO = "() => document.scrollingElement.scrollWidth - document.documentElement.clientWidth"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    saida = tmp_path_factory.mktemp("site") / "site"
    subprocess.run(["bash", str(RAIZ / "build_site.sh"), str(saida)], cwd=RAIZ, check=True, capture_output=True, text=True)
    manipulador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(saida))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), manipulador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ultimo = sorted(p.name for p in (saida / "boletim").iterdir() if p.is_dir())[-1]
    yield f"http://127.0.0.1:{srv.server_address[1]}/", ultimo
    srv.shutdown()


@pytest.fixture(scope="module")
def navegador():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROMIUM if Path(CHROMIUM).exists() else None)
        yield b
        b.close()


def _abrir(navegador, largura, tema, js=False):
    ctx = navegador.new_context(viewport={"width": largura, "height": 900}, color_scheme=tema, java_script_enabled=js,
                                is_mobile=largura < 800, has_touch=largura < 800)
    pg = ctx.new_page()
    falhas = []
    pg.route("**/*", lambda rota: rota.continue_() if rota.request.url.startswith("http://127.0.0.1") else rota.abort())
    pg.on("response", lambda r: r.status >= 400 and falhas.append(f"{r.status} {r.url}"))
    pg.on("requestfailed", lambda r: falhas.append(f"falhou {r.url}"))
    return ctx, pg, falhas


@pytest.mark.parametrize("largura", [360, 390, 430, 1440])
@pytest.mark.parametrize("tema", ["light", "dark"])
def test_paginas_sem_javascript_sem_estouro_e_com_fontes_do_site(navegador, site, largura, tema):
    base, ultimo = site
    ctx, pg, falhas = _abrir(navegador, largura, tema)
    for caminho in (f"boletim/{ultimo}/", "boletim/", "boletim/2015-01/"):
        pg.goto(base + caminho)
        pg.wait_for_load_state("networkidle")
        assert pg.evaluate(ESTOURO) <= 0, (caminho, largura)
        h1 = pg.locator("h1")
        assert h1.count() == 1 and h1.is_visible()
        assert "Inter Tight" in h1.evaluate("e => getComputedStyle(e).fontFamily")
        assert pg.evaluate("document.fonts.check('300 16px \"Inter Tight\"')")
        fundo = pg.evaluate("getComputedStyle(document.body).backgroundColor")
        assert fundo == ("rgb(7, 11, 36)" if tema == "dark" else "rgb(244, 244, 251)")
    assert falhas == []
    ctx.close()


def test_tabelas_rolam_dentro_da_caixa_no_celular(navegador, site):
    base, ultimo = site
    ctx, pg, _ = _abrir(navegador, 360, "light")
    pg.goto(base + f"boletim/{ultimo}/")
    for caixa in pg.locator(".cartao .rolagem").all():
        assert caixa.evaluate("e => e.getBoundingClientRect().right") <= 360
    ctx.close()


def test_home_sem_javascript_leva_ao_ultimo_boletim_e_ao_arquivo(navegador, site):
    base, ultimo = site
    ctx, pg, falhas = _abrir(navegador, 390, "light")
    pg.goto(base)
    link = pg.locator("#link-boletim-pagina a").first
    assert link.get_attribute("href") == f"boletim/{ultimo}/"
    link.click()
    pg.wait_for_load_state("networkidle")
    assert pg.url == base + f"boletim/{ultimo}/"
    pg.locator(".meses-boletim a.arquivo").click()
    pg.wait_for_load_state("networkidle")
    assert pg.url == base + "boletim/"
    pg.locator(".trilha a").first.click()
    assert pg.url == base
    assert falhas == []
    ctx.close()


def test_tema_escolhido_no_painel_vale_nas_paginas_dos_boletins(navegador, site):
    base, ultimo = site
    ctx, pg, _ = _abrir(navegador, 1440, "light", js=True)
    pg.add_init_script("localStorage.setItem('tema', 'dark')")
    pg.goto(base + f"boletim/{ultimo}/")
    assert pg.evaluate("document.documentElement.dataset.theme") == "dark"
    assert pg.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(7, 11, 36)"
    ctx.close()


def test_arquivo_abre_e_fecha_os_anos_sem_javascript(navegador, site):
    base, _ = site
    ctx, pg, _ = _abrir(navegador, 390, "light")
    pg.goto(base + "boletim/")
    anos = pg.locator("section.ano-boletins details")
    assert anos.count() >= 2
    assert anos.nth(0).get_attribute("open") is not None and anos.nth(anos.count() - 1).get_attribute("open") is None
    antigo = anos.nth(anos.count() - 1)
    assert not antigo.locator(".lista-meses a").first.is_visible()
    antigo.locator("summary").click()
    assert antigo.locator(".lista-meses a").first.is_visible()
    ctx.close()
