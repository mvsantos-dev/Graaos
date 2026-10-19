"""Cenários de navegador da volta ao lugar da leitura (só em desenvolvimento): ao recarregar no meio
da página, o trecho que estava no topo da tela volta para o mesmo lugar, embora o HTML do build
(conteúdo estático) e o redesenho do script tenham alturas diferentes. Uma visita nova começa no
topo, e rolar antes do primeiro desenho cancela a volta.

Monta o site com o build_site.sh numa pasta temporária e serve essa pasta, como no deploy:

    RADAR_E2E_LIBS=/caminho/com/chart.umd.min.js/e/anime.umd.min.js python -m pytest tests/e2e

Sem o Playwright ou sem RADAR_E2E_LIBS, o teste é pulado (como no CI).
"""

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
TOPO = "(id) => Math.round(document.getElementById(id).getBoundingClientRect().top)"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("rolagem") / "site"
    subprocess.run(["bash", str(RAIZ / "build_site.sh"), str(pasta)], check=True, capture_output=True)
    manipulador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(pasta))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), manipulador)
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


def _pagina(navegador, site, largura, altura, reduzido):
    ctx = navegador.new_context(viewport={"width": largura, "height": altura}, reduced_motion="reduce" if reduzido else "no-preference")
    pg = ctx.new_page()
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.route("https://cdn.jsdelivr.net/**", _cdn)
    pg.route("https://challenges.cloudflare.com/**", lambda r: r.abort())
    pg.goto(site)
    pg.wait_for_function("window.radarDados", timeout=30_000)
    pg.wait_for_timeout(1200)
    return ctx, pg, erros


@pytest.mark.parametrize("reduzido", [False, True], ids=["movimento", "sem-movimento"])
@pytest.mark.parametrize(("largura", "altura"), [(1440, 900), (390, 844)], ids=["desktop", "celular"])
def test_recarregar_no_meio_volta_ao_mesmo_trecho(navegador, site, largura, altura, reduzido):
    ctx, pg, erros = _pagina(navegador, site, largura, altura, reduzido)
    for alvo in ("grafico-portos", "grafico-precos", "grafico-troca", "t-metodo"):
        pg.evaluate(f"document.getElementById('{alvo}').scrollIntoView({{block: 'center'}})")
        pg.wait_for_timeout(900)
        antes = pg.evaluate(TOPO, alvo)
        pg.reload()
        pg.wait_for_function("window.radarDados", timeout=30_000)
        pg.wait_for_timeout(2200)
        assert abs(pg.evaluate(TOPO, alvo) - antes) <= 2, f"{alvo}: o trecho lido volta ao mesmo lugar da tela"
    assert erros == []
    ctx.close()


def test_visita_nova_comeca_no_topo_e_rolar_cancela_a_volta(navegador, site):
    ctx, pg, erros = _pagina(navegador, site, 1440, 900, False)
    pg.evaluate("document.getElementById('grafico-troca').scrollIntoView({block: 'center'})")
    pg.wait_for_timeout(600)
    pg.goto(site)  # navegação nova, não recarga: nada a restaurar
    pg.wait_for_function("window.radarDados", timeout=30_000)
    pg.wait_for_timeout(1800)
    assert pg.evaluate("scrollY") == 0
    # recarga, mas quem lê rola antes do primeiro desenho: a página não puxa de volta
    pg.evaluate("document.getElementById('grafico-precos').scrollIntoView({block: 'center'})")
    pg.wait_for_timeout(600)
    pg.reload(wait_until="commit")
    pg.wait_for_selector("footer.rodape")
    pg.mouse.wheel(0, -600)
    pg.wait_for_function("window.radarDados", timeout=30_000)
    pg.wait_for_timeout(2200)
    longe = pg.evaluate("Math.abs(document.getElementById('grafico-precos').getBoundingClientRect().top - innerHeight / 2)")
    assert longe > 300, "a rolagem de quem lê vale mais que a volta ao lugar salvo"
    assert erros == []
    ctx.close()


def test_sem_javascript_o_navegador_restaura_sozinho(navegador, site):
    """Sem o script, o HTML do build já tem a altura final das tabelas e frases: a restauração
    automática do navegador basta (o script só troca para "manual" quando roda)."""
    ctx = navegador.new_context(viewport={"width": 1440, "height": 900}, java_script_enabled=False)
    pg = ctx.new_page()
    pg.goto(site)
    pg.evaluate("document.getElementById('grafico-troca').scrollIntoView({block: 'center'})")
    antes = pg.evaluate(TOPO, "grafico-troca")
    pg.reload()
    pg.wait_for_timeout(800)
    assert abs(pg.evaluate(TOPO, "grafico-troca") - antes) <= 2
    ctx.close()
