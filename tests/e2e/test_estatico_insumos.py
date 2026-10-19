"""Seção "Insumos do fósforo" e página insumos/ no site montado pelo build_site.sh
(src/estatico/insumos.py), no navegador.

- Sem JavaScript (o que os buscadores e quem lê sem script recebem), o HTML do build é igual ao
  que o script desenha na visão padrão: mesmo innerHTML das frases, notas, item do Método e
  tabelas, e mesmos aria-labels dos seis gráficos.
- Com JavaScript, tudo acompanha o intervalo de meses (o filtro de grupo não se aplica) e, para
  cada intervalo, é o que o Python escreveria, também com meses sem dado, sem importação, sem
  benchmark e de amostra pequena (as duas versões das regras não podem divergir).
- A página insumos/ abre sem JavaScript, sem rolagem lateral e com os assets versionados.

Roda com Playwright e Chromium sobre o site montado numa pasta temporária. As bibliotecas do CDN
vêm de cópias locais, porque os testes não acessam a rede:

    RADAR_E2E_LIBS=/caminho/com/chart.umd.min.js/e/anime.umd.min.js python -m pytest tests/e2e

Sem o Playwright ou sem RADAR_E2E_LIBS, o teste é pulado (como no CI).
"""

import copy
import functools
import http.server
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
LIBS = os.environ.get("RADAR_E2E_LIBS")
if not LIBS:
    pytest.skip("defina RADAR_E2E_LIBS com chart.umd.min.js e anime.umd.min.js", allow_module_level=True)

from src.estatico import insumos as I  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
CHROMIUM = os.environ.get("RADAR_E2E_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
TEXTOS = [*I.FRASES, *I.NOTAS]
CAPTURA = """([textos, tabelas, canvas]) => ({
  html: Object.fromEntries(textos.map((id) => [id, document.getElementById(id).innerHTML])),
  texto: Object.fromEntries(textos.map((id) => [id, document.getElementById(id).textContent])),
  tabelas: Object.fromEntries(tabelas.map((id) => [id, document.getElementById(id).innerHTML])),
  rotulos: Object.fromEntries(canvas.map((id) => [id, document.getElementById(id).getAttribute("aria-label")])),
})"""
FILTRAR = "([de, ate]) => { estado.de = de; estado.ate = ate; atualizar(); }"


class _Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    saida = tmp_path_factory.mktemp("estatico-insumos") / "site"
    r = subprocess.run(["bash", str(RAIZ / "build_site.sh"), str(saida)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Silencioso, directory=str(saida)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/", json.loads((saida / "dashboard.json").read_text(encoding="utf-8"))
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


def _abrir(navegador, url, largura=1440, js=True, tema="light"):
    ctx = navegador.new_context(viewport={"width": largura, "height": 900}, java_script_enabled=js, reduced_motion="reduce", color_scheme=tema)
    pg = ctx.new_page()
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" and "404" not in m.text else None)
    pg.route("https://cdn.jsdelivr.net/**", _cdn)
    pg.route("https://challenges.cloudflare.com/**", lambda rota: rota.abort())
    pg.goto(url)
    if js:
        pg.wait_for_function("!!(window.radarDados && window.Chart)", timeout=30_000)
        pg.wait_for_timeout(400)
    return ctx, pg, erros


def _indices(dados, de, ate):
    p = dados["mensal"]["periodos"]
    return list(range(p.index(de), p.index(ate) + 1))


def _conferir(pg, dados, de, ate):
    """O que o script escreveu no intervalo é o que o Python escreveria."""
    indices = _indices(dados, de, ate)
    frases = I.frases(dados, indices)
    textos, rotulos, tabelas = {**frases, **I.notas(dados, indices)}, I.rotulos(dados, indices, frases), I.tabelas(dados, indices)
    obtido = pg.evaluate(CAPTURA, [TEXTOS, I.TABELAS, I.CANVAS])
    for id_, valor in textos.items():
        assert obtido["texto"][id_] == valor, f"{de}..{ate} #{id_}"
    for id_, valor in rotulos.items():
        assert obtido["rotulos"][id_] == valor, f"{de}..{ate} aria-label de #{id_}"
    for id_, valor in tabelas.items():
        assert obtido["tabelas"][id_] == valor, f"{de}..{ate} #{id_}"
    return obtido


@pytest.mark.parametrize("largura", [1440, 390])
def test_sem_javascript_mostra_o_mesmo_que_o_script(navegador, site, largura):
    url, _ = site
    ctx, pg, _ = _abrir(navegador, url, largura, js=False)
    estatico = pg.evaluate(CAPTURA, [TEXTOS, I.TABELAS, I.CANVAS])
    ctx.close()
    for id_ in I.FRASES:
        html = estatico["html"][id_]
        assert html.strip() and "Fonte: Comex Stat/MDIC" in html and html.endswith("."), f"#{id_} vazio ou sem a fonte no fim"
    for id_ in I.NOTAS:
        assert estatico["html"][id_].strip(), f"#{id_} vazio sem JavaScript"
    for id_, html in estatico["tabelas"].items():
        assert html.startswith("<table><thead>") and html.count("<tr>") > 12, f"#{id_} sem a tabela"
    for id_, rotulo in estatico["rotulos"].items():
        assert rotulo and "A tabela abaixo traz os valores. " in rotulo, f"aria-label de #{id_} sem a frase de resumo"
    ctx, pg, erros = _abrir(navegador, url, largura)
    assert pg.evaluate("location.hash").startswith("#grupo=TOTAL&")  # visão padrão
    dinamico = pg.evaluate(CAPTURA, [TEXTOS, I.TABELAS, I.CANVAS])
    for parte in ("html", "tabelas", "rotulos"):
        for id_, valor in estatico[parte].items():
            assert dinamico[parte][id_] == valor, f"{parte} #{id_}"
    assert pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    assert erros == []
    ctx.close()


def test_frases_do_script_iguais_as_do_python(navegador, site):
    url, dados = site
    p = dados["mensal"]["periodos"]
    pequenas = {k: [p[i] for i, x in enumerate(dados["insumos"]["produtos"][k]["amostra_pequena"]) if x] for k in ("enxofre", "rocha")}
    # o período inteiro, os últimos 12 meses, o primeiro mês (sem ano anterior), um ano no meio, e meses de amostra pequena
    # do enxofre e da rocha no fim do período (e sozinhos, sem mês comparável)
    casos = [(p[0], p[-1]), (p[-12], p[-1]), (p[0], p[0]), ("2020-01", "2022-06")]
    for mes in pequenas["enxofre"][:2] + pequenas["rocha"][:1]:
        casos += [(p[0], mes), (mes, mes)]
    ctx, pg, erros = _abrir(navegador, url)
    for de, ate in casos:
        pg.evaluate(FILTRAR, [de, ate])
        _conferir(pg, dados, de, ate)
    assert erros == []
    ctx.close()


# Casos que os dados de hoje não têm, no último mês: o mesmo dado mexido no navegador e no Python.
MEXER = """([caminhos, comparacao]) => { for (const [caminho, valor] of caminhos) { const partes = caminho.split("."); let o = dados;
  for (const k of partes) o = o[k]; o[o.length - 1] = valor; }
  if (comparacao) dados.insumos.produtos.rocha.benchmark.comparacao = comparacao; atualizar(); }"""
CASOS = {
    "sem-dado": [("insumos.produtos.enxofre.t", None), ("insumos.produtos.enxofre.cif", None), ("insumos.custo_map.custo", None),
                 ("insumos.custo_map.razao", None)],
    "sem-importacao": [("insumos.produtos.enxofre.t", 0), ("insumos.produtos.enxofre.cif", None), ("insumos.produtos.rocha.t", 0),
                       ("insumos.produtos.rocha.benchmark.spread_pct", None)],
    "sem-benchmark": [("insumos.produtos.rocha.benchmark.bm", None), ("insumos.produtos.rocha.benchmark.spread_pct", None),
                      ("insumos.produtos.rocha.benchmark.spread_usd_t", None)],
    "spread-quase-zero-e-custo-pequeno": [("insumos.produtos.rocha.benchmark.spread_pct", 0.04), ("insumos.custo_map.amostra_pequena", True)],
    "base-no-destino": [],
}


@pytest.mark.parametrize("caso", list(CASOS))
def test_casos_sem_dado_iguais_no_script_e_no_python(navegador, site, caso):
    url, dados = site
    p = dados["mensal"]["periodos"]
    comparacao = "CIF×CFR" if caso == "base-no-destino" else None  # o preço do Brasil da base vira o CIF
    mexido = copy.deepcopy(dados)
    for caminho, valor in CASOS[caso]:
        o = mexido
        for k in caminho.split("."):
            o = o[k]
        o[-1] = valor
    if comparacao:
        mexido["insumos"]["produtos"]["rocha"]["benchmark"]["comparacao"] = comparacao
    ctx, pg, erros = _abrir(navegador, url)
    pg.evaluate(MEXER, [CASOS[caso], comparacao])
    for de, ate in ((p[0], p[-1]), (p[-1], p[-1])):
        pg.evaluate(FILTRAR, [de, ate])
        _conferir(pg, mexido, de, ate)
    assert erros == []
    ctx.close()


def test_filtros_da_pagina_atualizam_a_secao_no_lugar(navegador, site):
    url, dados = site
    p = dados["mensal"]["periodos"]
    ctx, pg, erros = _abrir(navegador, url)
    padrao = _conferir(pg, dados, p[0], p[-1])
    # todos os gráficos da seção montados (como na impressão), para conferir que o filtro os atualiza no lugar
    pg.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    pg.evaluate("(ids) => { window.__insumos = Object.fromEntries(ids.map((id) => [id, Chart.getChart(id)])); }", I.CANVAS)
    assert pg.evaluate("(ids) => ids.every((id) => !!window.__insumos[id])", I.CANVAS)
    # o filtro de grupo não muda a seção
    for g in ("K", "N", "P"):
        pg.click(f"#filtro-grupo .chip[data-grupo='{g}']")
        pg.wait_for_timeout(150)
        obtido = pg.evaluate(CAPTURA, [TEXTOS, I.TABELAS, I.CANVAS])
        assert obtido["texto"] == padrao["texto"] and obtido["rotulos"] == padrao["rotulos"], g
    # o intervalo pelo preset de 12 meses e pelo seletor "Até": o mês das frases acompanha
    pg.click("#filtro-periodo .chip[data-preset='12m']")
    pg.wait_for_timeout(150)
    _conferir(pg, dados, p[-12], p[-1])
    pg.select_option("#filtro-ate", "2024-03")
    pg.wait_for_timeout(150)
    de = pg.evaluate("estado.de")
    obtido = _conferir(pg, dados, de, "2024-03")
    for id_ in ("resumo-enxofre", "resumo-enxofre-t", "resumo-rocha", "resumo-rocha-t", "resumo-custo-map", "resumo-razao-map"):
        assert "mar/2024" in obtido["texto"][id_], id_
    mesmos = pg.evaluate("(ids) => ids.filter((id) => Chart.getChart(id) !== window.__insumos[id])", I.CANVAS)
    assert mesmos == [], "trocar o período atualiza o mesmo gráfico, sem recriar"
    assert pg.evaluate("Chart.getChart('grafico-enxofre').data.labels.at(-1)") == "mar/2024"
    # as âncoras dos sinais ficam na seção
    assert pg.evaluate("['grafico-enxofre', 'grafico-rocha'].every((id) => document.getElementById(id).closest('#insumos'))")
    assert erros == []
    ctx.close()


@pytest.mark.parametrize("largura, tema", [(1440, "light"), (390, "dark")])
def test_pagina_insumos_sem_javascript(navegador, site, largura, tema):
    url, dados = site
    ctx = navegador.new_context(viewport={"width": largura, "height": 900}, java_script_enabled=False, color_scheme=tema)
    pg = ctx.new_page()
    falhas = []
    pg.on("response", lambda r: falhas.append(r.url) if r.status >= 400 else None)
    pg.goto(url + "insumos/")
    pg.wait_for_load_state("networkidle")
    assert falhas == []
    assert pg.title() == I.TITULO
    assert pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    # o CSS do site (versionado com ?v=) e o tema escuro pelo sistema
    hrefs = pg.evaluate("[...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.getAttribute('href'))")
    assert all("?v=" in h and h.startswith("../assets/") for h in hrefs) and len(hrefs) == 2
    fundo = pg.evaluate("getComputedStyle(document.body).backgroundColor")
    assert fundo != "rgba(0, 0, 0, 0)"
    frases = I.frases(dados, list(range(len(dados["mensal"]["periodos"]))))
    textos = pg.evaluate("[...document.querySelectorAll('.resumo-grafico')].map((p) => p.textContent.replaceAll('\\u00a0', ' '))")
    for frase in frases.values():
        assert frase.replace("\xa0", " ") in textos
    # links para a seção da home e para os boletins
    links = pg.evaluate("[...document.querySelectorAll('main a')].map((a) => a.href)")
    assert url + "#insumos" in links and url + "boletim/" in links
    ctx.close()
