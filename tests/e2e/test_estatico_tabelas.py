"""Tabelas de "Ver tabela" já no HTML do build (src/estatico/tabelas.py) iguais às do script.

Monta o site com o build_site.sh numa pasta temporária, serve essa pasta e compara, tabela por
tabela, o innerHTML sem JavaScript (o que o buscador e quem lê sem script recebem) com o innerHTML
depois que o script desenhou a visão padrão (página sem hash, "reduzir movimento"). Os dois saem da
serialização do navegador, então as entidades não atrapalham. Também confere que o script trocou
cada tabela (não ficou a do build por falha do script), a versão de celular da tabela de rotas e,
em outras visões (grupo, período, produto, ano), as funções do módulo contra o script.

    RADAR_E2E_LIBS=/caminho/com/chart.umd.min.js/e/anime.umd.min.js python -m pytest tests/e2e

Sem o Playwright ou sem RADAR_E2E_LIBS, o teste é pulado (como no CI).
"""

import functools
import http.server
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
LIBS = os.environ.get("RADAR_E2E_LIBS")
if not LIBS:
    pytest.skip("defina RADAR_E2E_LIBS com chart.umd.min.js e anime.umd.min.js", allow_module_level=True)

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from src.estatico import tabelas as T  # noqa: E402
from src.estatico import tabelas_notas as N  # noqa: E402

CHROMIUM = os.environ.get("RADAR_E2E_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
TABELAS = ["tabela-toneladas", "tabela-origens", "tabela-hhi", "tabela-fluxos", "tabela-portos", "tabela-rotas", "tabela-precos",
           "tabela-frete", "tabela-nutrientes", "tabela-bm", "tabela-troca"]
NOTAS = ["nota-toneladas", "nota-origens", "nota-hhi", "nota-portos", "nota-rotas", "nota-precos", "nota-frete", "nota-nutrientes",
         "nota-teores", "nota-bm", "nota-spread", "nota-brl", "nota-troca"]
TEXTOS = ["titulo-frete-rotas", "nota-frete-rotas", "fonte-rodape", *NOTAS]
SECOES = ["secao-nutrientes", "secao-bm", "secao-troca", "secao-rotas", "rodape-bm"]
# Guarda o conteúdo do build de cada caixa antes do script (para ver se ele o trocou).
GUARDAR = """
window.__estaticos = {};
document.addEventListener("DOMContentLoaded", () => {
  for (const id of %s) window.__estaticos[id] = document.getElementById(id)?.firstChild ?? null;
});
""" % TABELAS
TROCADAS = "(ids) => ids.filter((id) => document.getElementById(id).firstChild === window.__estaticos[id])"
INNER = "(ids) => Object.fromEntries(ids.map((id) => [id, document.getElementById(id).innerHTML]))"
CLASSES = "(ids) => Object.fromEntries(ids.map((id) => [id, document.getElementById(id).className]))"
NORMALIZAR = "(h) => { const d = document.createElement('div'); d.innerHTML = h; return d.innerHTML; }"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("site") / "site"
    r = subprocess.run(["bash", str(RAIZ / "build_site.sh"), str(pasta)], capture_output=True, text=True, cwd=RAIZ, timeout=300)
    assert r.returncode == 0, r.stderr
    manipulador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(pasta))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), manipulador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{srv.server_address[1]}/", "pasta": pasta}
    srv.shutdown()


@pytest.fixture(scope="module")
def navegador():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROMIUM if Path(CHROMIUM).exists() else None)
        yield b
        b.close()


def _rede(rota):
    """Só o servidor local; o Chart.js e o anime.js vêm das cópias locais; o resto (Turnstile) cai."""
    url = rota.request.url
    if url.startswith("http://127.0.0.1"):
        return rota.continue_()
    for nome, arquivo in (("chart.js", "chart.umd.min.js"), ("animejs", "anime.umd.min.js")):
        if "cdn.jsdelivr.net" in url and nome in url:
            return rota.fulfill(path=str(Path(LIBS) / arquivo), content_type="application/javascript", headers={"Access-Control-Allow-Origin": "*"})
    return rota.abort()


def _sem_js(navegador, site, largura=1280):
    ctx = navegador.new_context(viewport={"width": largura, "height": 900}, java_script_enabled=False)
    pg = ctx.new_page()
    pg.route("**/*", _rede)
    pg.goto(site["url"])
    return ctx, pg


def _com_js(navegador, site, largura=1280, tema="light", hash_="", fluxos=True):
    ctx = navegador.new_context(viewport={"width": largura, "height": 900}, color_scheme=tema, reduced_motion="reduce")
    pg = ctx.new_page()
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" and "net::ERR_FAILED" not in m.text else None)
    pg.add_init_script(GUARDAR)
    pg.route("**/*", _rede)
    pg.goto(site["url"] + hash_)
    pg.wait_for_function("!!(window.radarDados && window.Chart)", timeout=30_000)
    if fluxos:
        # a tabela do mapa só é montada quando o mapa aparece na tela
        pg.evaluate("document.getElementById('fluxos').scrollIntoView({block: 'start'})")
        pg.wait_for_function("document.getElementById('tabela-fluxos').firstChild !== window.__estaticos['tabela-fluxos']", timeout=30_000)
    pg.wait_for_timeout(300)
    return ctx, pg, erros


@pytest.fixture(scope="module")
def estatico(navegador, site):
    ctx, pg = _sem_js(navegador, site)
    saida = {"tabelas": pg.evaluate(INNER, TABELAS), "textos": pg.evaluate(INNER, TEXTOS), "secoes": pg.evaluate(CLASSES, SECOES)}
    ctx.close()
    return saida


def test_build_traz_todas_as_tabelas_e_as_secoes_a_vista(estatico):
    for id_, html in estatico["tabelas"].items():
        assert html.startswith("<table>") and "</tbody></table>" in html, id_
        assert "<tbody><tr>" in html, f"{id_} sem linhas"
    assert estatico["textos"]["titulo-frete-rotas"].startswith("Frete por rota · ")
    assert estatico["textos"]["nota-frete-rotas"].startswith("Só rotas com volume relevante")
    assert all(estatico["textos"][id_] for id_ in NOTAS)
    assert estatico["textos"]["fonte-rodape"] == "Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet); BCB/PTAX"
    assert all("oculto" not in c for c in estatico["secoes"].values()), estatico["secoes"]


def test_tabelas_do_build_iguais_as_do_script_na_visao_padrao(navegador, site, estatico):
    ctx, pg, erros = _com_js(navegador, site)
    assert pg.evaluate("location.hash").startswith("#grupo=TOTAL&")
    assert pg.evaluate(TROCADAS, TABELAS) == []  # o script redesenhou todas
    depois = pg.evaluate(INNER, TABELAS)
    for id_ in TABELAS:
        assert depois[id_] == estatico["tabelas"][id_], id_
    assert pg.evaluate(INNER, TEXTOS) == estatico["textos"]
    assert pg.evaluate(CLASSES, SECOES) == estatico["secoes"]
    assert erros == []
    ctx.close()


def test_tema_escuro_so_muda_a_cor_da_barra_do_frete(navegador, site, estatico):
    ctx, pg, erros = _com_js(navegador, site, tema="dark", fluxos=False)
    depois = pg.evaluate(INNER, TABELAS)
    sem_cor = lambda h: re.sub(r"background: rgba\([^)]*\)", "background: X", h)  # noqa: E731
    for id_ in TABELAS:
        assert sem_cor(depois[id_]) == sem_cor(estatico["tabelas"][id_]), id_
    assert depois["tabela-rotas"] != estatico["tabelas"]["tabela-rotas"]  # a cor do tema escuro
    assert erros == []
    ctx.close()


def test_no_celular_o_script_troca_as_tabelas_e_a_de_rotas_vira_a_versao_curta(navegador, site, estatico):
    ctx, pg, erros = _com_js(navegador, site, largura=390)
    assert pg.evaluate(TROCADAS, TABELAS) == []
    depois = pg.evaluate(INNER, TABELAS)
    for id_ in TABELAS:
        if id_ != "tabela-rotas":
            assert depois[id_] == estatico["tabelas"][id_], id_
    cabecalho = pg.evaluate("[...document.querySelectorAll('#tabela-rotas th')].map((t) => t.textContent)")
    assert cabecalho[:2] == ["Origem", "URF"] and "#" not in cabecalho and "" not in cabecalho
    assert pg.evaluate("document.querySelectorAll('#tabela-rotas .barra').length") == 0
    assert pg.evaluate("document.querySelectorAll('#tabela-rotas tbody tr').length") == estatico["tabelas"]["tabela-rotas"].count("<tr>") - 1
    assert pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    assert erros == []
    ctx.close()


VISOES = [
    ("#grupo=K", T.Visao("K", None, None)),
    ("#grupo=P&de=2020-01&ate=2023-12", T.Visao("P", "2020-01", "2023-12")),
    ("#grupo=N&de=2026-01", T.Visao("N", "2026-01", None)),
    ("#grupo=NPK&de=2016-03&ate=2017-02", T.Visao("NPK", "2016-03", "2017-02")),
    ("#grupo=TOTAL&bm=tsp&de=2018-06&ate=2021-05", T.Visao("TOTAL", "2018-06", "2021-05", bm="tsp")),
    ("#grupo=P&bm=dap", T.Visao("P", None, None, bm="dap")),
]


@pytest.mark.parametrize("hash_,visao", VISOES, ids=[h for h, _ in VISOES])
def test_funcoes_do_modulo_iguais_ao_script_em_outras_visoes(navegador, site, hash_, visao):
    """As mesmas funções do build, noutras visões: a tradução do script vale para além da padrão."""
    ctx, pg, erros = _com_js(navegador, site, hash_=hash_, fluxos=False)
    dados = json.loads((site["pasta"] / "dashboard.json").read_text(encoding="utf-8"))
    p = dados["mensal"]["periodos"]
    v = T.Visao(visao.grupo, visao.de or p[0], visao.ate or p[-1], bm=visao.bm)
    css = (site["pasta"] / "assets" / "radar.css").read_text(encoding="utf-8")
    cor = T.cor_do_tema_claro(css, "--g-total" if v.grupo == "TOTAL" else f"--g-{v.grupo.lower()}")
    esperado = T.tabelas(dados, v, cor)
    esperado.pop("tabela-fluxos")  # o mapa tem filtro próprio (ano), conferido abaixo
    depois = pg.evaluate(INNER, list(esperado))
    for id_, html in esperado.items():
        assert depois[id_] == pg.evaluate(NORMALIZAR, html), id_
    rot = T.rotas(dados, v, cor)
    assert pg.evaluate("document.getElementById('titulo-frete-rotas').textContent") == rot.titulo
    assert pg.evaluate("document.getElementById('nota-frete-rotas').textContent") == rot.nota
    assert pg.evaluate("(ids) => Object.fromEntries(ids.map((id) => [id, document.getElementById(id).textContent]))", NOTAS) == N.notas(dados, v)
    # ano escolhido no diagrama de rotas
    pg.select_option("#filtro-ano-rotas", "2019")
    v.ano_rotas = 2019
    assert pg.evaluate("document.getElementById('tabela-rotas').innerHTML") == pg.evaluate(NORMALIZAR, T.rotas(dados, v, cor).html)
    assert erros == []
    ctx.close()


@pytest.mark.parametrize("hash_,ano,grupo", [("#grupo=K&ano=2026", 2026, "K"), ("#ano=2019", 2019, "TOTAL"), ("#grupo=NPK&ano=2015", 2015, "NPK")])
def test_tabela_do_mapa_igual_ao_fluxos_js_em_outros_anos(navegador, site, hash_, ano, grupo):
    ctx, pg, erros = _com_js(navegador, site, hash_=hash_)
    dados = json.loads((site["pasta"] / "dashboard.json").read_text(encoding="utf-8"))
    assert pg.evaluate("document.getElementById('tabela-fluxos').innerHTML") == pg.evaluate(NORMALIZAR, T.fluxos(dados, ano, grupo))
    assert erros == []
    ctx.close()
